"""Android GPS spoofing backend.

Uses the standard Android *mock location provider* mechanism:

1. the Geox Bridge companion app (see ``android-bridge/``) is installed on
   the phone and granted mock-location capability (``appops set … allow``);
2. Geox on the PC repeatedly broadcasts target coordinates to the bridge
   over ADB; the bridge feeds them into the OS as GPS fixes.

Every app — Google Maps, Snap Map, Find My Device, … — then reads the
mocked fix from the OS location stack.
"""

import json
import os
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .motion import build_motion

ADB_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
BRIDGE_PKG = "com.geox.bridge"
APK_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "android-bridge" / "bin" / "GeoxBridge.apk",
    Path(__file__).resolve().parent.parent / "android-bridge" / "app" / "build"
    / "outputs" / "apk" / "debug" / "app-debug.apk",
]
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class AndroidError(Exception):
    """User-actionable Android failure."""


_ADB_PATH: str | None = None
_ADB_RESOLVED = False
_ANDROID_DETAILS: dict = {}
_ANDROID_DETAILS_TTL = 10.0


def resolve_adb():
    global _ADB_PATH, _ADB_RESOLVED
    if _ADB_RESOLVED:
        return _ADB_PATH or None
    _ADB_RESOLVED = True
    bundled = TOOLS_DIR / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    if bundled.exists():
        _ADB_PATH = str(bundled)
        return _ADB_PATH
    for candidate in ("adb", "adb.exe"):
        found = subprocess.run(
            ["where", candidate] if os.name == "nt" else ["which", candidate],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if found.returncode == 0 and found.stdout.strip():
            _ADB_PATH = found.stdout.strip().splitlines()[0]
            return _ADB_PATH
    return None


def adb_available():
    return resolve_adb() is not None


def install_adb(engine):
    """Download Google's platform-tools into tools/ (background thread)."""
    def work():
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = TOOLS_DIR / "platform-tools.zip"
        engine.log("[Android] downloading Google platform-tools (~13 MB)…")
        try:
            urllib.request.urlretrieve(ADB_URL, zip_path)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(TOOLS_DIR)
            zip_path.unlink(missing_ok=True)
            global _ADB_PATH, _ADB_RESOLVED
            _ADB_PATH, _ADB_RESOLVED = None, False
            engine.log("[Android] platform-tools installed — ADB ready.", "good")
        except Exception as e:
            engine.log(f"[Android] ADB download failed: {e}", "error")
        engine.adb_install_running = False

    engine.adb_install_running = True
    threading.Thread(target=work, daemon=True).start()


def _run(engine, args, timeout=15):
    adb = resolve_adb()
    if not adb:
        raise AndroidError(
            "ADB is not installed. Click 'Install ADB automatically' (downloads "
            "Google's official platform-tools) or install Android platform-tools "
            "and put adb on your PATH."
        )
    proc = subprocess.run(
        [adb, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )
    return proc


def _shell(engine, device_id, cmd, timeout=15):
    return _run(engine, ["-s", device_id, "shell", *cmd], timeout=timeout)


def _bridge_state(engine, device_id):
    state = {"installed": False, "mock_allowed": False}
    p = _shell(engine, device_id, ["pm", "list", "packages", BRIDGE_PKG])
    if f"package:{BRIDGE_PKG}" in (p.stdout or ""):
        state["installed"] = True
    p = _shell(engine, device_id, ["appops", "get", BRIDGE_PKG, "android:mock_location"])
    out = (p.stdout or "").lower()
    if "allow" in out:
        state["mock_allowed"] = True
    return state


def list_devices(engine):
    if not adb_available():
        return []
    p = _run(engine, ["devices", "-l"])
    devices = []
    for line in (p.stdout or "").splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        device_id, status = parts[0], parts[1]
        if status not in ("device", "unauthorized", "offline"):
            continue
        info = {
            "id": device_id,
            "platform": "android",
            "connection": "USB",
            "name": None,
            "os_version": None,
            "adb_status": status,
            "bridge": None,
            "notes": [],
        }
        for field in parts[2:]:
            if field.startswith("model:"):
                info["name"] = field.split(":", 1)[1]
        if status == "unauthorized":
            info["notes"].append(
                "Unlock the phone and allow the USB-debugging prompt to authorise this PC"
            )
            devices.append(info)
            continue
        if status == "offline":
            info["notes"].append("Device shows offline — replug the cable")
            devices.append(info)
            continue
        # adb shell round-trips are slow; reuse details for a few scans
        cached = _ANDROID_DETAILS.get(device_id)
        if cached and time.time() - cached[0] < _ANDROID_DETAILS_TTL:
            info.update(cached[1])
            devices.append(info)
            continue
        try:
            model = _shell(engine, device_id, ["getprop", "ro.product.model"], timeout=10)
            ver = _shell(engine, device_id, ["getprop", "ro.build.version.release"], timeout=10)
            info["name"] = info["name"] or (model.stdout or "").strip() or device_id
            info["os_version"] = (ver.stdout or "").strip() or None
        except Exception:
            pass
        try:
            info["bridge"] = _bridge_state(engine, device_id)
            b = info["bridge"]
            if not b["installed"]:
                info["notes"].append("Geox Bridge app not installed on the phone yet")
            elif not b["mock_allowed"]:
                info["notes"].append("Click 'Setup bridge' to grant mock-location permission")
            else:
                info["notes"].append("Ready")
        except Exception as e:
            info["notes"].append(f"Bridge check failed: {e}")
        _ANDROID_DETAILS[device_id] = (
            time.time(),
            {k: info[k] for k in ("name", "os_version", "bridge")},
        )
        devices.append(info)
    return devices


def setup_bridge(engine, device_id):
    """Install the bridge APK if available, then grant permissions."""
    apk = next((a for a in APK_CANDIDATES if a.exists()), None)
    if apk is None:
        raise AndroidError(
            "No bridge APK found. Build it once from the android-bridge/ folder "
            "(see EXPLANATION.md → Android setup), then copy it to "
            "android-bridge/bin/GeoxBridge.apk and click again."
        )
    engine.log(f"[Android] installing {apk.name} on {device_id}…")
    p = _run(engine, ["-s", device_id, "install", "-r", "-t", str(apk)], timeout=120)
    if "success" not in (p.stdout or "").lower():
        raise AndroidError(f"APK install failed: {(p.stdout or p.stderr or '').strip()}")
    for perm in (
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
    ):
        _shell(engine, device_id, ["pm", "grant", BRIDGE_PKG, perm])
    p = _shell(engine, device_id, ["appops", "set", BRIDGE_PKG, "android:mock_location", "allow"])
    if p.returncode != 0:
        raise AndroidError(
            "Could not grant mock-location permission. On the phone enable "
            "Developer Options, then let Geox retry ('Setup bridge')."
        )
    engine.log("[Android] bridge installed and mock-location granted.", "good")
    return _bridge_state(engine, device_id)


class AndroidSession:
    """Broadcasts fresh coordinates to the bridge every tick."""

    def __init__(self, engine, device, cfg):
        self.engine = engine
        self.device = device
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.state = "connecting"
        start_pt = (
            (float(cfg["lat"]), float(cfg["lng"]))
            if "lat" in cfg and "lng" in cfg
            else (float(cfg["waypoints"][0][0]), float(cfg["waypoints"][0][1]))
            if cfg.get("waypoints")
            else (0.0, 0.0)
        )
        self.last = start_pt
        self.started_at = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def update(self, cfg):
        """Update Android mock location in-flight with zero delay or downtime."""
        self.cfg = cfg
        self.motion = build_motion(cfg)
        if "lat" in cfg and "lng" in cfg:
            self.last = (float(cfg["lat"]), float(cfg["lng"]))
        elif cfg.get("waypoints"):
            self.last = (float(cfg["waypoints"][0][0]), float(cfg["waypoints"][0][1]))
        self.engine.log(
            f"[Android] AUTO SWAP -> {self.cfg.get('place') or ''} "
            f"{self.last[0]:.5f}, {self.last[1]:.5f} (seamless transition)",
            "good",
        )
        try:
            self._send(*self.last, speed_mps=getattr(self.motion, "speed_mps", None))
        except Exception as e:
            self.engine.log(f"[Android] swap broadcast notice: {e}", "warn")

    def stop(self):
        self.stop_event.set()

    def snapshot(self):
        telemetry = None
        motion_obj = getattr(self, "motion", None)
        if self.state == "active" and self.cfg.get("mode") == "route" and motion_obj:
            telemetry = {
                "progress": getattr(motion_obj, "progress", 0.0),
                "speed_kmh": getattr(motion_obj, "speed_kmh", 0.0),
                "remaining_s": getattr(motion_obj, "remaining_s", None),
                "completed": getattr(motion_obj, "completed", False),
            }
        return {
            "device_id": self.device["id"],
            "device_name": self.device.get("name") or "Android",
            "platform": "android",
            "engine": "mock-provider",
            "mode": self.cfg.get("mode"),
            "place": self.cfg.get("place") or "",
            "state": self.state,
            "error": self.error,
            "started_at": self.started_at,
            "last": list(self.last),
            "telemetry": telemetry,
        }

    def _send(self, lat, lng, speed_mps=None):
        cmd = [
            "am", "broadcast", "-a", f"{BRIDGE_PKG}.SET_LOCATION", "-p", BRIDGE_PKG,
            "--ed", "lat", f"{lat:.7f}", "--ed", "lng", f"{lng:.7f}",
            "--ed", "acc", "5.0", "--ed", "alt", "10.0",
        ]
        if speed_mps is not None:
            cmd += ["--ed", "speed", f"{speed_mps:.2f}"]
        p = _shell(self.engine, self.device["id"], cmd, timeout=15)
        out = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0 or "exception" in out.lower():
            raise AndroidError(f"Could not reach the Geox Bridge app: {out.strip()[:300]}")

    def _run(self):
        tick = float(self.cfg.get("tick", 2.0))
        try:
            self.motion = build_motion(self.cfg)
            self._send(*self.last)
            self.state = "active"
            self.engine.log(
                f"[Android] spoofing ON → {self.cfg.get('place') or ''}"
                f"{self.last[0]:.5f}, {self.last[1]:.5f}"
            )
            prev = time.time()
            while not self.stop_event.is_set():
                time.sleep(0.2)
                now = time.time()
                if now - prev >= tick:
                    # self.motion is read each tick so AutoSwap takes effect live
                    lat, lng = self.motion.step(now - prev)
                    try:
                        self._send(lat, lng, speed_mps=getattr(self.motion, "speed_mps", None))
                    except AndroidError as e:
                        self.error = str(e)
                        self.state = "failed"
                        self.engine.log(f"[Android] {e}", "error")
                        return
                    self.last = (lat, lng)
                    prev = now
            try:
                _shell(
                    self.engine, self.device["id"],
                    ["am", "broadcast", "-a", f"{BRIDGE_PKG}.CLEAR", "-p", BRIDGE_PKG],
                    timeout=10,
                )
            except Exception:
                pass
            self.state = "stopped"
            self.engine.log("[Android] spoofing OFF — bridge cleared, real GPS restored")
        except AndroidError as e:
            self.error = str(e)
            self.state = "failed"
            self.engine.log(f"[Android] {e}", "error")
        except Exception as e:
            self.error = f"Android error: {e}"
            self.state = "failed"
            self.engine.log(f"[Android] unexpected failure: {e}", "error")
