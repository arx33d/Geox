"""iOS GPS spoofing backend.

Drives Apple's own Instruments location-simulation channel (the exact
mechanism Xcode uses when you tick "Simulate Location").  The simulated fix
replaces the GPS fix at OS level, so every app that reads Core Location —
Find My, Snap Map, Weather, banking apps, … — sees the fake coordinates for
as long as the session stays open.

* iOS <= 16: done in-process over usbmux (``DvtProvider`` +
  ``LocationSimulation``).
* iOS >= 17: DVT moved behind a RemoteXPC tunnel.  Session prep is automated
  here (Apple USB service start, developer-image mount) and the spoof runs
  through the bundled ``pymobiledevice3`` CLI, which establishes its own
  tunnel.  Continuous movement is replayed from a generated GPX file.
"""

import asyncio
import datetime as _dt
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .motion import build_motion

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
GPX_DIR = Path(__file__).resolve().parent.parent / "var" / "gpx"
PLAYBACK_HOURS = 8  # one GPX file keeps the CLI spoof alive this long
USBMUX_PORT = 27015

_last_service_check = 0.0
_last_usb_probe = 0.0
_last_usb_probe_result = False


class IosError(Exception):
    """User-actionable iOS failure."""


def pmd3_command():
    here = Path(sys.executable).parent
    for candidate in (here / "pymobiledevice3.exe", here / "Scripts" / "pymobiledevice3.exe"):
        if candidate.exists():
            return [str(candidate)]
    return [sys.executable, "-m", "pymobiledevice3"]


def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except ValueError:
        return (0,)


def _usbmux_up():
    try:
        s = socket.create_connection(("127.0.0.1", USBMUX_PORT), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def _apple_usb_device_present():
    """Does Windows see an Apple USB device (iPhone/iPad, vendor 0x05AC)?"""
    global _last_usb_probe
    if os.name != "nt":
        return True
    now = time.time()
    if now - _last_usb_probe < 60:
        return _last_usb_probe_result
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "@(Get-PnpDevice -PresentOnly | Where-Object "
             "{$_.InstanceId -like '*VID_05AC*'}).Count"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        nums = re.findall(r"\d+", (out.stdout or "").strip().splitlines()[-1] if (out.stdout or "").strip() else "")
        count = int(nums[0]) if nums else 0
    except Exception:
        count = 0
    _last_usb_probe = now
    _last_usb_probe_result = count > 0
    return _last_usb_probe_result


def ensure_apple_service(engine):
    """On Windows, bring the Apple USB service (usbmuxd) up if it isn't.

    The modern “Apple Devices” app hosts usbmuxd but only runs it when the
    app is started or a device trigger fires — so when an Apple USB device is
    present but port 27015 is closed, we launch the app and wait for it.
    """
    global _last_service_check
    if os.name != "nt" or _usbmux_up():
        return
    if time.time() - _last_service_check < 60:
        return
    _last_service_check = time.time()
    if not _apple_usb_device_present():
        return
    try:
        ps = ("$p = Get-AppxPackage AppleInc.AppleDevices; "
              "$id = (Get-AppxPackageManifest $p).Package.Applications.Application.Id | "
              "Select-Object -First 1; "
              "Write-Output \"$($p.PackageFamilyName)!$id\"")
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW,
        )
        target = (out.stdout or "").strip().splitlines()
        target = target[-1].strip() if target else ""
    except Exception:
        target = ""
    if not target:
        return
    engine.log("[iOS] starting the Apple Devices app to bring the USB service up…")
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"])
    except Exception:
        return
    for _ in range(25):
        time.sleep(1)
        if _usbmux_up():
            engine.log("[iOS] Apple USB service is up.", "good")
            return
    engine.log("[iOS] Apple USB service did not come up — open the Apple Devices "
               "app once manually, then press Refresh.", "warn")


def enable_developer_mode(engine):
    """Enable Developer Mode on the iPhone.

    Passcode-free phones: automated (`amfi enable-developer-mode`, reboots).
    Passcode-protected phones: Apple refuses automation, so we reveal the
    Settings toggle and tell the user to flip it (one confirmation + reboot).
    """
    ensure_apple_service(engine)
    try:
        subprocess.run(
            pmd3_command() + ["amfi", "reveal-developer-mode"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=CREATE_NO_WINDOW,
        )
        p = subprocess.run(
            pmd3_command() + ["amfi", "enable-developer-mode"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=90, creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        raise IosError(f"Could not reach the iPhone: {e}")
    out = _strip_ansi((p.stdout or "") + (p.stderr or ""))
    if p.returncode == 0:
        engine.log("[iOS] Developer Mode enabled — the iPhone is rebooting. "
                   "Unlock it when it's back up and press START again.", "good")
        return {"ok": True, "note": "enabled"}
    low = out.lower()
    if "not connected" in low or "nodeviceconnected" in low:
        raise IosError(
            "No iPhone is connected over USB. Plug it in, unlock it, tap "
            "'Trust' if asked, then try again."
        )
    if "passcode is set" in low:
        engine.log("[iOS] The toggle is now visible on the phone: Settings → "
                   "Privacy & Security → Developer Mode → ON (passcode + reboot).",
                   "good")
        return {
            "ok": True,
            "manual": True,
            "note": "On the iPhone open Settings → Privacy & Security → "
                    "Developer Mode and turn it ON (enter passcode; the phone "
                    "reboots). Then press Refresh and START again.",
        }
    if "passcode" in low:
        raise IosError("Unlock the iPhone (enter the passcode) and try again.")
    if "trust" in low or "pair" in low:
        raise IosError("The iPhone doesn't trust this PC yet: unlock it, tap "
                       "'Trust', then try again.")
    raise IosError(f"Could not enable Developer Mode: {out.strip()[:300]}")


def humanize_error(e):
    name = type(e).__name__
    text = str(e)
    if "DeveloperMode" in name:
        raise IosError(
            "Developer Mode is OFF on the iPhone. On the phone: Settings → "
            "Privacy & Security → Developer Mode → ON (the phone reboots) — "
            "or use the 'Enable Developer Mode' button in Geox."
        )
    if "PairingDialogResponsePending" in name or "pairing" in text.lower():
        raise IosError(
            "The iPhone is waiting for you to trust this computer: unlock the "
            "phone, tap 'Trust' and enter the passcode, then try again."
        )
    if "PasswordRequired" in name:
        raise IosError("Your iOS backup password is needed to finish the pairing.")
    if "NoDeviceConnected" in name:
        raise IosError(
            "The iPhone disappeared from USB. Keep it plugged in and unlocked, "
            "then press START again."
        )
    if "ConnectionFailed" in name or "usbmux" in text.lower() or "refused" in text.lower():
        raise IosError(
            "Cannot reach the Apple USB service (usbmuxd). Install iTunes "
            "(or the 'Apple Devices' app from the Microsoft Store), let its "
            "drivers install, then replug the cable."
        )
    raise IosError(f"iOS error: {text or name}")


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text or "")


def _cli_failure_message(text):
    """Map pymobiledevice3 CLI output to a user-actionable message."""
    low = _strip_ansi(text).lower()
    if "enable-developer-mode" in low or "developer mode" in low:
        return (
            "Developer Mode is OFF on the iPhone. Use the 'Enable Developer "
            "Mode' button (the phone reboots once), then press START again."
        )
    if "nodeviceconnected" in low or "no device" in low:
        return (
            "The iPhone disappeared from USB. Keep it plugged in and unlocked, "
            "then press START again."
        )
    if "trust" in low or "pairing" in low:
        return ("The iPhone is waiting for you to trust this computer: unlock "
                "it, tap 'Trust' and enter the passcode, then try again.")
    if "password" in low:
        return "Your iOS backup password is needed to finish the pairing."
    if "usbmux" in low or "connection" in low and "refused" in low:
        return ("Cannot reach the Apple USB service. Open the Apple Devices "
                "app (or iTunes) once, replug the cable and retry.")
    return None


def _run_cli(args, timeout=180):
    return subprocess.run(
        pmd3_command() + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=CREATE_NO_WINDOW,
    )


def _prepare_developer_image(engine):
    """iOS 17+: make sure the personalized developer image is mounted."""
    engine.log("[iOS] preparing the developer image (auto-mount, first time "
               "can take a minute)…")
    try:
        p = _run_cli(["mounter", "auto-mount"], timeout=240)
    except Exception as e:
        engine.log(f"[iOS] auto-mount could not run: {e}", "warn")
        return
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        engine.log("[iOS] developer image mounted.", "good")
    else:
        engine.log(f"[iOS] auto-mount skipped: {_cli_failure_message(out) or out.strip()[-200:]}", "warn")


async def _scan(engine):
    from pymobiledevice3.exceptions import NoDeviceConnectedError
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.usbmux import list_devices

    ensure_apple_service(engine)
    devices = []
    for mux in await list_devices():
        info = {
            "id": mux.serial,
            "platform": "ios",
            "connection": mux.connection_type or "USB",
            "name": None,
            "os_version": None,
            "paired": False,
            "developer_mode": None,
            "tunnel_mode": False,
            "notes": [],
        }
        try:
            lockdown = await create_using_usbmux(serial=mux.serial, autopair=False)
        except NoDeviceConnectedError:
            continue
        except Exception:
            info["notes"].append("Tap 'Trust' on the phone to pair it with this PC")
            devices.append(info)
            continue
        try:
            short = lockdown.short_info
            info["name"] = short.get("DeviceName")
            info["os_version"] = short.get("ProductVersion")
            info["paired"] = True
            try:
                info["developer_mode"] = bool(
                    await asyncio.wait_for(
                        lockdown.get_value(key="DeveloperModeStatus"), timeout=5
                    )
                )
            except Exception:
                info["developer_mode"] = None
        except Exception:
            pass
        if _version_tuple(info["os_version"] or "0") >= (17,):
            info["tunnel_mode"] = True
        devices.append(info)
    return devices


def list_devices(engine):
    try:
        return asyncio.run(_scan(engine))
    except IosError:
        raise
    except Exception as e:
        name = type(e).__name__
        if "Usbmuxd" in name or "ConnectionFailed" in name:
            engine.log(
                "[iOS] Apple USB service not running — install iTunes (or the "
                "'Apple Devices' app from the Microsoft Store) so iPhones show up.",
                "warn",
            )
        else:
            engine.log(f"[iOS] device scan failed: {type(e).__name__} {e}", "warn")
        return []


class IosSession:
    """In-process DVT location simulation (iOS 16 and older)."""

    def __init__(self, engine, device, cfg):
        self.engine = engine
        self.device = device
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.state = "connecting"
        self.error = None
        self.last = (float(cfg["lat"]), float(cfg["lng"]))
        self.started_at = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def snapshot(self):
        return {
            "device_id": self.device["id"],
            "device_name": self.device.get("name") or "iPhone",
            "platform": "ios",
            "engine": "dvt-inprocess",
            "mode": self.cfg.get("mode"),
            "place": self.cfg.get("place") or "",
            "state": self.state,
            "error": self.error,
            "started_at": self.started_at,
            "last": list(self.last),
        }

    def _fail(self, e):
        try:
            humanize_error(e)
        except IosError as hum:
            self.error = str(hum)
        else:
            self.error = f"iOS error: {e}"
        self.state = "failed"
        self.engine.log(f"[iOS] {self.error}", "error")

    def _run(self):
        try:
            asyncio.run(self._main())
        except IosError as e:
            self.error = str(e)
            self.state = "failed"
            self.engine.log(f"[iOS] {e}", "error")
        except Exception as e:
            self._fail(e)

    async def _main(self):
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import (
            LocationSimulation,
        )

        self.engine.log(
            f"[iOS] opening developer session with {self.device.get('name') or self.device['id']}…"
        )
        lockdown = await create_using_usbmux(
            serial=self.device["id"], autopair=True, pair_timeout=90
        )
        async with DvtProvider(lockdown) as dvt, LocationSimulation(dvt) as sim:
            motion = build_motion(self.cfg)
            tick = float(self.cfg.get("tick", 3.0))
            self.state = "active"
            self.engine.log(
                f"[iOS] spoofing ON → {self.cfg.get('place') or ''}"
                f"{self.last[0]:.5f}, {self.last[1]:.5f}"
            )
            prev = time.time()
            while not self.stop_event.is_set():
                await asyncio.sleep(0.25)
                now = time.time()
                if now - prev >= tick:
                    lat, lng = motion.step(now - prev)
                    await sim.set(lat, lng)
                    self.last = (lat, lng)
                    prev = now
            await sim.clear()
            self.state = "stopped"
            self.engine.log("[iOS] spoofing OFF — real GPS restored")


class IosCliSession:
    """iOS 17+ session driven through the pymobiledevice3 CLI.

    ``simulate-location set`` blocks and holds the tunnel open — perfect for
    a fixed point.  Movement is replayed from a generated GPX file at 1 Hz;
    when the file is consumed the process is relaunched with a fresh one.
    """

    def __init__(self, engine, device, cfg):
        self.engine = engine
        self.device = device
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.state = "connecting"
        self.error = None
        self.last = (
            float(cfg.get("lat", 0)),
            float(cfg.get("lng", 0)),
        )
        self.started_at = time.time()
        self.proc = None
        self._out = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def snapshot(self):
        return {
            "device_id": self.device["id"],
            "device_name": self.device.get("name") or "iPhone",
            "platform": "ios",
            "engine": "dvt-tunnel-cli",
            "mode": self.cfg.get("mode"),
            "place": self.cfg.get("place") or "",
            "state": self.state,
            "error": self.error,
            "started_at": self.started_at,
            "last": list(self.last),
        }

    def _pump(self, proc):
        for line in proc.stdout:
            line = line.strip()
            if line:
                self._out.append(line)
                if "error" in line.lower() or "warning" in line.lower():
                    self.engine.log(f"[iOS17] {line[:220]}", "debug")

    def _fail_from_output(self, text):
        clean = _strip_ansi(text)
        msg = _cli_failure_message(clean)
        if not msg:
            err_lines = [l for l in clean.splitlines() if "ERROR" in l or "error" in l]
            if err_lines:
                msg = err_lines[-1].split("] ", 1)[-1].strip()
            else:
                msg = "The tunnel session ended unexpectedly — press START to retry."
        self.error = msg[:400]
        self.state = "failed"
        self.engine.log(f"[iOS17] {self.error}", "error")

    def _gpx_path(self, name):
        GPX_DIR.mkdir(parents=True, exist_ok=True)
        return GPX_DIR / name

    def _write_gpx(self, path):
        motion = build_motion(self.cfg)
        t0 = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<gpx version="1.1" creator="Geox" xmlns="http://www.topografix.com/GPX/1/1">\n'
                "<trk><trkseg>\n"
            )
            for i in range(PLAYBACK_HOURS * 3600):
                lat, lng = motion.step(1.0)
                ts = (t0 + _dt.timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
                f.write(
                    f'<trkpt lat="{lat:.7f}" lon="{lng:.7f}"><time>{ts}</time></trkpt>\n'
                )
            f.write("</trkseg></trk>\n</gpx>\n")
        self.last = motion.step(0)

    def _launch(self, gpx=None, point=None):
        cmd = pmd3_command() + ["developer", "dvt", "simulate-location"]
        if point is not None:
            cmd += ["set", "--", f"{point[0]:.6f}", f"{point[1]:.6f}"]
        else:
            cmd += ["play", str(gpx)]
        # stdin stays open so the CLI's "Press ENTER to exit" wait blocks
        # instead of reading EOF and aborting the session
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )

    def _run(self):
        try:
            ensure_apple_service(self.engine)
            if not _usbmux_up():
                raise IosError(
                    "The Apple USB service isn't running and no iPhone was seen "
                    "on USB. Replug the cable, open the Apple Devices app once, "
                    "then press START again."
                )
            self._prepare_developer_image()
            if self.cfg.get("mode") == "fixed":
                self._run_point()
            else:
                self._run_gpx()
        except IosError as e:
            self.error = str(e)
            self.state = "failed"
            self.engine.log(f"[iOS17] {e}", "error")
        except Exception as e:
            try:
                humanize_error(e)
            except IosError as hum:
                self.error = str(hum)
                self.state = "failed"
                self.engine.log(f"[iOS17] {hum}", "error")
                return
            self.error = f"iOS error: {e}"
            self.state = "failed"
            self.engine.log(f"[iOS17] unexpected failure: {e}", "error")
        finally:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()

    def _prepare_developer_image(self):
        self.engine.log("[iOS17] establishing tunnel & preparing developer image…")
        _prepare_developer_image(self.engine)

    def _run_point(self):
        self.proc = self._launch(point=(float(self.cfg["lat"]), float(self.cfg["lng"])))
        self.last = (float(self.cfg["lat"]), float(self.cfg["lng"]))
        pump = threading.Thread(target=self._pump, args=(self.proc,), daemon=True)
        pump.start()
        # the first tunnel establishment can take ~20 s; wait for either the
        # process to die (failure) or the session to settle in
        for _ in range(40):
            if self.proc.poll() is not None:
                break
            time.sleep(0.5)
        if self.proc.poll() is not None:
            self._fail_from_output("\n".join(self._out))
            return
        self.state = "active"
        self.engine.log(
            f"[iOS17] spoofing ON → {self.cfg.get('place') or ''}"
            f"{self.last[0]:.5f}, {self.last[1]:.5f}"
        )
        while not self.stop_event.is_set() and self.proc.poll() is None:
            time.sleep(0.5)
        if not self.stop_event.is_set():
            self._fail_from_output("\n".join(self._out))
            return
        self.state = "stopped"
        self.engine.log("[iOS17] spoofing OFF — real GPS restored")

    def _run_gpx(self):
        path = self._gpx_path(f"route-{int(time.time())}.gpx")
        self._write_gpx(path)
        self.engine.log(f"[iOS17] generated movement track: {path.name}")
        while not self.stop_event.is_set():
            self._out = []
            self.proc = self._launch(gpx=path)
            pump = threading.Thread(target=self._pump, args=(self.proc,), daemon=True)
            pump.start()
            self.state = "active"
            started = time.time()
            while not self.stop_event.is_set() and self.proc.poll() is None:
                time.sleep(0.5)
            if self.stop_event.is_set():
                break
            output = "\n".join(self._out)
            if self.proc.returncode != 0 or "ERROR" in output or time.time() - started < 10:
                self._fail_from_output(output)
                return
            self.engine.log("[iOS17] track finished — regenerating and reconnecting…")
            try:
                self._write_gpx(path)
            except Exception as e:
                self.engine.log(f"[iOS17] could not regenerate track: {e}", "error")
                break
        self.state = "stopped"
        self.engine.log("[iOS17] spoofing OFF — real GPS restored")


def start_session(engine, device, cfg):
    if device.get("tunnel_mode"):
        return IosCliSession(engine, device, cfg)
    return IosSession(engine, device, cfg)
