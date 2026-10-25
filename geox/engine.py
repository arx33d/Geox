"""Session manager: device discovery + one spoofing session per device."""

import os
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from . import android_backend, ios_backend

SCAN_THROTTLE = 1.5


import sys

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _apple_service_installed():
    import os

    if os.name != "nt":
        return True  # assume drivers exist on macOS/Linux
    for base in (
        r"C:\Program Files\Common Files\Apple\Mobile Device Support\AppleMobileDeviceService.exe",
        r"C:\Program Files (x86)\Common Files\Apple\Mobile Device Support\AppleMobileDeviceService.exe",
    ):
        if Path(base).exists():
            return True
    return False


import atexit


class Engine:
    def __init__(self):
        self._lock = threading.RLock()
        self.sessions = {}
        self.logs = deque(maxlen=400)
        self._devices_cache = []
        self._last_scan = 0.0
        self._scan_lock = threading.Lock()
        self.adb_install_running = False
        self._last_shown = {}
        self._reap_orphans()
        atexit.register(self._cleanup)
        self.log("[Geox] engine ready. Connect a phone with USB and hit refresh.", "good")

    def _cleanup(self):
        with self._lock:
            sessions = list(self.sessions.values())
        for s in sessions:
            try:
                s.stop()
            except Exception:
                pass

    def _reap_orphans(self):
        """Kill simulation processes orphaned by a previous crashed/restarted
        server: they keep asserting their old location forever, which shows up
        as the phone flapping between two places."""
        if os.name != "nt":
            return
        my_pid = os.getpid()
        killed = 0
        try:
            p = subprocess.run(
                ["taskkill", "/F", "/T", "/IM", "pymobiledevice3.exe"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=0x08000000,
            )
            killed += (p.stdout or "").upper().count("SUCCESS")
        except Exception:
            pass

        try:
            ps_cmd = (
                f"Get-CimInstance Win32_Process | Where-Object {{ "
                f"$_.ProcessId -ne {my_pid} -and $_.CommandLine -like '*pymobiledevice3*simulate-location*' "
                f"}} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force; Write-Output 'KILLED' }}"
            )
            p2 = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, creationflags=0x08000000,
            )
            killed += (p2.stdout or "").count("KILLED")
        except Exception:
            pass

        if killed:
            self.log(f"[Geox] reaped {killed} orphaned spoofing process(es) "
                     "left over from a previous run.", "warn")




# ------------------------------------------------------------------ logs
    def log(self, msg, level="info"):
        now = time.time()
        key = (msg, level)
        with self._lock:
            # repeated scans shouldn't spam the console/UI with the same line
            if now - self._last_shown.get(key, 0.0) < 120:
                return
            self._last_shown[key] = now
            self.logs.append({"t": now, "level": level, "msg": msg})
        try:
            print(f"[{level}] {msg}", flush=True)
        except Exception:
            try:
                safe_msg = str(msg).encode("ascii", errors="replace").decode("ascii")
                print(f"[{level}] {safe_msg}", flush=True)
            except Exception:
                pass

    # --------------------------------------------------------------- devices
    def scan_devices(self, force=False):
        with self._scan_lock:
            now = time.time()
            if not force and now - self._last_scan < SCAN_THROTTLE:
                return self._devices_cache
            self._last_scan = now
            devices = []
            try:
                devices += ios_backend.list_devices(self)
            except Exception as e:
                self.log(f"[iOS] scan error: {e}", "error")
            try:
                devices += android_backend.list_devices(self)
            except Exception as e:
                self.log(f"[Android] scan error: {e}", "error")
            with self._lock:
                deduped = []
                seen_ids = set()
                seen_keys = set()
                for d in devices:
                    did = d.get("id")
                    norm = re.sub(r'[\s\(\)\-_.]', '', (d.get("name") or "").replace(".local", "")).lower()
                    key = (d.get("platform"), norm) if norm else None

                    s = self.sessions.get(did)
                    d["active"] = bool(s and s.state == "active")
                    d["session_state"] = s.state if s else None

                    if did in seen_ids:
                        continue

                    if key and key in seen_keys:
                        # Duplicate device detected on same platform with matching name
                        existing_idx = next((i for i, x in enumerate(deduped) if (x.get("platform"), re.sub(r'[\s\(\)\-_.]', '', (x.get("name") or "").replace(".local", "")).lower()) == key), None)
                        if existing_idx is not None:
                            existing = deduped[existing_idx]
                            should_replace = (
                                not existing.get("active") and d.get("active")
                            ) or (
                                existing.get("connection") != "USB" and d.get("connection") == "USB"
                            ) or (
                                not existing.get("os_version") and d.get("os_version")
                            )
                            if should_replace:
                                deduped[existing_idx] = d
                        continue

                    seen_ids.add(did)
                    if key:
                        seen_keys.add(key)
                    deduped.append(d)
                devices = deduped
            self._devices_cache = devices
            return devices

    def _find_device(self, device_id):
        current_devices = self.scan_devices()
        dev = next((d for d in current_devices if d["id"] == device_id), None)
        if dev is not None:
            return dev, current_devices

        current_devices = self.scan_devices(force=True)
        dev = next((d for d in current_devices if d["id"] == device_id), None)
        if dev is not None:
            return dev, current_devices

        old_s = self.sessions.get(device_id)
        if old_s and hasattr(old_s, "device"):
            old_name = old_s.device.get("name")
            norm_old = re.sub(r'[\s\(\)\-_.]', '', (old_name or "").replace(".local", "")).lower()
            if norm_old:
                dev = next(
                    (d for d in current_devices if re.sub(r'[\s\(\)\-_.]', '', (d.get("name") or "").replace(".local", "")).lower() == norm_old),
                    None
                )
                if dev is not None:
                    return dev, current_devices

        return None, current_devices

    # --------------------------------------------------------------- control
    def start(self, device_id, cfg):
        device, current = self._find_device(device_id)
        if device is None:
            old_s = self.sessions.get(device_id)
            if old_s and hasattr(old_s, "device") and old_s.device.get("connection") == "USB":
                raise ValueError(
                    "iPhone was disconnected from USB. If switching to cable-free Wi-Fi, "
                    "ensure your phone is unlocked and on the same Wi-Fi network, then click Refresh."
                )
            raise ValueError("That device is not connected (or not authorised) any more.")
        self._validate_cfg(cfg)

        old = self.sessions.pop(device_id, None)
        if old:
            self.log(f"[Geox] stopping previous session on {device_id}…")
            old.stop()
            old.thread.join(timeout=15)

        if device["platform"] == "ios":
            session = ios_backend.start_session(self, device, cfg)
        elif device["platform"] == "android":
            bridge = device.get("bridge") or {}
            if not bridge.get("installed"):
                raise ValueError(
                    "The Geox Bridge app is not installed on this phone. Click "
                    "'Setup bridge' (after building the APK once — see "
                    "EXPLANATION.md)."
                )
            if not bridge.get("mock_allowed"):
                raise ValueError(
                    "Mock-location permission is missing. Click 'Setup bridge' "
                    "to grant it automatically."
                )
            session = android_backend.AndroidSession(self, device, cfg)
        else:
            raise ValueError(f"Unknown platform {device['platform']!r}")

        self.sessions[device["id"]] = session
        if device["id"] != device_id:
            self.sessions[device_id] = session
        session.start()
        return session.snapshot()

    def update(self, device_id, cfg):
        """Seamlessly hot-swap location and motion settings without stopping the session or exposing real GPS."""
        self._validate_cfg(cfg)

        session = self.sessions.get(device_id)
        if session and hasattr(session, "update") and getattr(session, "state", None) in ("active", "connecting", "locked_unplugged"):
            session.update(cfg)
            return session.snapshot()

        device, _ = self._find_device(device_id)
        if device is None:
            old_s = self.sessions.get(device_id)
            if old_s and hasattr(old_s, "device") and old_s.device.get("connection") == "USB":
                raise ValueError(
                    "iPhone was disconnected from USB. If switching to cable-free Wi-Fi, "
                    "ensure your phone is unlocked and on the same Wi-Fi network, then click Refresh."
                )
            raise ValueError("That device is not connected (or not authorised) any more.")

        return self.start(device["id"], cfg)

    def stop(self, device_id):
        session = self.sessions.pop(device_id, None)
        if not session:
            raise ValueError("No spoofing session is running for that device.")
        session.stop()
        session.thread.join(timeout=20)
        return session.snapshot()

    def _validate_cfg(self, cfg):
        mode = cfg.get("mode", "fixed")

        def check_ll(lat, lng, what):
            try:
                lat, lng = float(lat), float(lng)
            except (TypeError, ValueError):
                raise ValueError(f"{what}: lat/lng must be numbers")
            if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                raise ValueError(f"{what}: coordinates out of range")
            return lat, lng

        if mode == "route":
            wps = cfg.get("waypoints") or []
            if len(wps) < 2:
                raise ValueError("A route needs at least 2 waypoints.")
            cfg["waypoints"] = [check_ll(a, b, f"waypoint {i+1}") for i, (a, b) in enumerate(wps)]
            if cfg.get("seg_seconds") is not None:
                segs = cfg["seg_seconds"]
                if not isinstance(segs, list) or len(segs) != len(cfg["waypoints"]) - 1:
                    raise ValueError("The route timing is malformed. Plan the trip again.")
                cfg["seg_seconds"] = [min(max(float(s), 0.01), 86400.0) for s in segs]
                if sum(cfg["seg_seconds"]) > 14 * 86400:
                    raise ValueError("That trip would take over 2 weeks at this speed.")
                cfg["speed_factor"] = min(max(float(cfg.get("speed_factor", 1.0)), 0.1), 20.0)
        else:
            cfg["lat"], cfg["lng"] = check_ll(cfg.get("lat"), cfg.get("lng"), "Target")
        if mode == "jitter":
            cfg["radius_m"] = min(max(float(cfg.get("radius_m", 120)), 15), 2000)
        cfg["speed_kmh"] = min(max(float(cfg.get("speed_kmh", 10)), 0.5), 300)
        cfg["tick"] = min(max(float(cfg.get("tick", 3.0)), 1.0), 30)

    def enable_wireless(self, device_id):
        device = next((d for d in self.scan_devices() if d["id"] == device_id), None)
        if device is None:
            raise ValueError("Device not found or not connected.")
        if device.get("platform") == "android":
            res = android_backend.enable_wireless_adb(self, device_id)
        elif device.get("platform") == "ios":
            res = ios_backend.enable_wifi_sync(self, device_id)
        else:
            raise ValueError(f"Unsupported platform: {device.get('platform')}")
        self._last_scan = 0
        return res

    def connect_wireless(self, host_port, platform="android", pairing_code=None):
        if platform == "android":
            if pairing_code:
                android_backend.pair_wireless_adb(self, host_port, pairing_code)
            res = android_backend.connect_wireless_adb(self, host_port)
        elif platform == "ios":
            res = {"ok": True, "message": "iOS Wi-Fi devices are auto-discovered on the local network."}
        else:
            raise ValueError(f"Unsupported platform: {platform}")
        self._last_scan = 0
        return res

    # --------------------------------------------------------------- status
    def capabilities(self):
        now = time.time()
        if getattr(self, "_caps_cache", None) and now - self._caps_cache[0] < 5:
            caps = dict(self._caps_cache[1])
            caps["adb_install_running"] = self.adb_install_running
            return caps
        caps = self._compute_capabilities()
        self._caps_cache = (now, caps)
        return caps

    def _compute_capabilities(self):
        adb = android_backend.resolve_adb()
        from .ios_backend import _usbmux_up

        return {
            "ios_lib": True,  # import failure would have killed the process by now
            "apple_service": _usbmux_up() or _apple_service_installed(),
            "adb": ("bundled" if (Path("tools") / "platform-tools").exists() and adb else
                    "path" if adb else None),
            "adb_install_running": self.adb_install_running,
        }

    def status(self):
        with self._lock:
            sessions = [s.snapshot() for s in self.sessions.values()]
            logs = list(self.logs)[-60:]
        return {
            "devices": self.scan_devices(),
            "sessions": sessions,
            "logs": logs,
            "capabilities": self.capabilities(),
        }


_SINGLETON = None


def get_engine():
    """One shared Engine per process: the Web UI and the CLI must not keep
    separate session states."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Engine()
    return _SINGLETON
