"""Session manager: device discovery + one spoofing session per device."""

import threading
import time
from collections import deque
from pathlib import Path

from . import android_backend, ios_backend

SCAN_THROTTLE = 1.5


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
        self.log("[Geox] engine ready. Connect a phone with USB and hit refresh.", "good")

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
        print(f"[{level}] {msg}", flush=True)

    # --------------------------------------------------------------- devices
    def scan_devices(self):
        with self._scan_lock:
            now = time.time()
            if now - self._last_scan < SCAN_THROTTLE:
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
                for d in devices:
                    s = self.sessions.get(d["id"])
                    d["active"] = bool(s and s.state == "active")
                    d["session_state"] = s.state if s else None
            self._devices_cache = devices
            return devices

    # --------------------------------------------------------------- control
    def start(self, device_id, cfg):
        device = next((d for d in self.scan_devices() if d["id"] == device_id), None)
        if device is None:
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

        self.sessions[device_id] = session
        session.start()
        return session.snapshot()

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
        else:
            cfg["lat"], cfg["lng"] = check_ll(cfg.get("lat"), cfg.get("lng"), "Target")
        if mode == "jitter":
            cfg["radius_m"] = min(max(float(cfg.get("radius_m", 120)), 15), 2000)
        cfg["speed_kmh"] = min(max(float(cfg.get("speed_kmh", 10)), 0.5), 300)
        cfg["tick"] = min(max(float(cfg.get("tick", 3.0)), 1.0), 30)

    # --------------------------------------------------------------- status
    def capabilities(self):
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
