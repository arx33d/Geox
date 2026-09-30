"""Geox Command Line Interface (CLI).

Run anywhere via:
    geox --location <url|name|coords> --movement <stay|roam [radius] [speed]>
or:
    python -m geox.cli --help
"""

import argparse
import os
import re
import signal
import sys
import threading
import time

from .engine import get_engine
from .router import PRESETS, geocode_name, parse_trip_input, plan_route, resolve_location_input


def _format_time(seconds):
    mins, secs = divmod(int(seconds), 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _parse_movement_args(movement_tokens, explicit_radius=None, explicit_speed=None):
    """Parse movement arguments supporting both combined and separated arguments.

    Examples supported:
        ['stay']
        ['roam']
        ['roam', '120', '4.5']
        ['roam', '120,4.5']
        ['roam', '-120,', '4.5']
        ['trip']
    """
    if not movement_tokens:
        mode = "fixed"
        numbers = []
    else:
        first = movement_tokens[0].lower().strip().rstrip(",")
        if first in ("stay", "fixed", "park", "stop_move"):
            mode = "fixed"
        elif first in ("roam", "jitter", "drift", "walk"):
            mode = "jitter"
        elif first in ("trip", "route", "drive", "itinerary"):
            mode = "route"
        else:
            mode = "fixed"

        # extract any numbers in the remaining tokens or in the first token
        joined = " ".join(movement_tokens)
        # find all positive numbers (even if user prefixed with - or comma)
        found_nums = re.findall(r"[-+]?(\d+(?:\.\d+)?)", joined)
        numbers = [float(x) for x in found_nums]

    radius = explicit_radius
    speed = explicit_speed

    if mode == "jitter":
        if radius is None:
            if len(numbers) >= 1:
                radius = abs(numbers[0])
            else:
                radius = 120.0
        if speed is None:
            if len(numbers) >= 2:
                speed = abs(numbers[1])
            else:
                speed = 4.5

    return mode, radius, speed


def list_devices_cmd(engine):
    print("\nScanning for connected devices...\n")
    devices = engine.scan_devices()
    if not devices:
        print("No iOS or Android devices detected over USB.")
        print("Tip: Make sure the phone is plugged in, unlocked, and 'Trust' is accepted.")
        print("     For Android: ensure USB Debugging is enabled.")
        print("     For iOS: ensure Apple USB drivers / Apple Devices app are present.\n")
        return

    print(f"Found {len(devices)} device(s):")
    print("-" * 65)
    for i, d in enumerate(devices, 1):
        name = d.get("name") or "Unknown Device"
        platform = (d.get("platform") or "").upper()
        dev_id = d.get("id", "N/A")
        ver = d.get("os_version") or "unknown OS"
        active = "[ACTIVE SPOOFING]" if d.get("active") else "[IDLE]"

        print(f"  {i}. {name} ({platform} {ver}) - {active}")
        print(f"     ID: {dev_id}")
        if d.get("platform") == "ios":
            dev_mode = "ON" if d.get("developer_mode") else ("OFF" if d.get("developer_mode") is False else "Unknown")
            print(f"     Developer Mode: {dev_mode} | Tunnel Mode: {d.get('tunnel_mode', False)}")
        elif d.get("platform") == "android":
            bridge = d.get("bridge") or {}
            print(f"     Bridge Installed: {bridge.get('installed', False)} | Mock Allowed: {bridge.get('mock_allowed', False)}")
    print("-" * 65 + "\n")


def list_presets_cmd():
    print("\nAvailable Location Presets:")
    print("-" * 65)
    for name, (lat, lng, label) in sorted(PRESETS.items()):
        print(f"  --preset {name:<14} -> {label:<32} ({lat:.4f}, {lng:.4f})")
    print("-" * 65 + "\n")


def pick_target_device(engine, requested_id=None):
    devices = engine.scan_devices()
    if not devices:
        raise ValueError("No devices detected on USB. Plug in an iPhone or Android device and unlock it.")

    if requested_id:
        req_low = requested_id.lower()
        matched = [d for d in devices if req_low == d["id"].lower() or req_low in (d.get("name") or "").lower()]
        if not matched:
            raise ValueError(f"Device matching '{requested_id}' not found. Run 'geox --devices' to list connected devices.")
        return matched[0]

    if len(devices) == 1:
        return devices[0]

    # Multiple devices: pick active or first
    active = [d for d in devices if d.get("active")]
    if active:
        return active[0]

    print(f"\nMultiple devices found ({len(devices)}). Defaulting to first device:")
    print(f"-> {devices[0].get('name') or devices[0]['id']} ({devices[0]['platform'].upper()})")
    print("Tip: Use --device <id or name> to select a specific device.\n")
    return devices[0]


def run_spoof(engine, device, cfg):
    device_id = device["id"]
    device_name = device.get("name") or device_id
    platform = device.get("platform", "ios").upper()

    print("\n" + "=" * 65)
    print("  GEOX - GPS SPOOFER")
    print("=" * 65)
    print(f" Device:    {device_name} ({platform})")
    print(f" Target:    {cfg.get('place', 'Custom')}")
    if cfg.get("mode") == "fixed":
        print(f" Mode:      STAY (Fixed at {cfg['lat']:.5f}, {cfg['lng']:.5f})")
    elif cfg.get("mode") == "jitter":
        print(f" Mode:      ROAM (Radius: {cfg.get('radius_m', 120)}m, Speed: {cfg.get('speed_kmh', 4.5)} km/h)")
        print(f" Center:    {cfg['lat']:.5f}, {cfg['lng']:.5f}")
    elif cfg.get("mode") == "route":
        wps = cfg.get("waypoints", [])
        print(f" Mode:      TRIP ({len(wps)} waypoints, Speed Factor: {cfg.get('speed_factor', 1.0)}x)")
    print("-" * 65)
    print(" [Press Ctrl+C at any time to STOP spoofing and restore real GPS]")
    print("=" * 65 + "\n")

    try:
        snap = engine.start(device_id, cfg)
    except Exception as e:
        print(f"\n[ERROR] Failed to start spoofing session: {e}\n")
        return 1

    start_time = time.time()
    session = engine.sessions.get(device_id)

    def sigint_handler(sig, frame):
        print("\n\n[Geox] Stopping spoofing and restoring real GPS...")
        try:
            engine.stop(device_id)
            print("[Geox] Real GPS successfully restored.")
        except Exception as stop_err:
            print(f"[Geox] Stop completed ({stop_err}).")
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, sigint_handler)

    try:
        while True:
            time.sleep(1.0)
            if not session:
                break
            snap = session.snapshot()
            state = snap.get("state")
            if state == "failed":
                print(f"\n[ERROR] Session failed: {snap.get('error')}")
                break
            if state == "stopped":
                print("\n[Geox] Session stopped.")
                break

            last = snap.get("last") or [cfg.get("lat", 0), cfg.get("lng", 0)]
            uptime = _format_time(time.time() - start_time)
            mode_label = cfg.get("mode", "fixed").upper()
            if mode_label == "JITTER":
                mode_label = "ROAM"

            # Print single-line live update ticker
            sys.stdout.write(
                f"\r[LIVE] Status: {state.upper():<10} | Coords: {last[0]:.5f}, {last[1]:.5f} | "
                f"Mode: {mode_label} | Elapsed: {uptime}   "
            )
            sys.stdout.flush()

    except KeyboardInterrupt:
        sigint_handler(None, None)

    return 0


def build_cli_parser():
    parser = argparse.ArgumentParser(
        prog="geox",
        description="Geox — GPS location spoofer for USB-connected iPhones and Android devices.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Spoof fixed location via Google Maps link:
  geox --location "https://www.google.com/maps/place/Toronto,+ON/@43.7164673,-79.6563003,59047m/data=..."

  # Spoof location with Roam (radius 120m, speed 4.5 km/h):
  geox --location "Toronto, ON" --movement roam 120 4.5

  # Spoof to a preset:
  geox --preset mcmurdo --movement roam 200 5

  # Drive / walk trip between two places:
  geox --from "Vancouver" --to "Seattle" --profile car --speed-factor 1.5

  # Manage devices and sessions:
  geox --devices
  geox --stop
  geox --status

  # Launch the web browser UI:
  geox server
        """,
    )

    # Subcommands or action flags
    parser.add_argument(
        "command",
        nargs="?",
        choices=["server", "devices", "stop", "status", "presets", "setup-bridge"],
        help="Optional command (or use flags below)",
    )

    # Location input
    parser.add_argument(
        "-l", "--location",
        dest="location",
        help="Target location: Google Maps URL, 'lat,lng', address name, or place search.",
    )
    parser.add_argument(
        "--preset",
        dest="preset",
        help="Target built-in preset (e.g. mcmurdo, southpole, vancouver, tokyo, nyc, paris, london, etc.)",
    )

    # Movement options
    parser.add_argument(
        "-m", "--movement",
        dest="movement",
        nargs="+",
        metavar="ARG",
        help="Movement mode: 'stay' or 'roam [radius_m] [speed_kmh]' (e.g. --movement roam 120 4.5)",
    )
    parser.add_argument(
        "-r", "--radius",
        dest="radius",
        type=float,
        help="Roam radius in meters (default: 120m)",
    )
    parser.add_argument(
        "-s", "--speed",
        dest="speed",
        type=float,
        help="Speed in km/h for roam mode (default: 4.5 km/h)",
    )

    # Trip mode options
    parser.add_argument(
        "--from",
        dest="trip_from",
        help="Origin location for Trip mode (address, URL, or coords).",
    )
    parser.add_argument(
        "--to",
        dest="trip_to",
        help="Destination location for Trip mode (address, URL, or coords).",
    )
    parser.add_argument(
        "-p", "--profile",
        dest="profile",
        choices=["car", "bike", "walk", "transit"],
        default="car",
        help="Routing travel profile for Trip mode (default: car).",
    )
    parser.add_argument(
        "--speed-factor",
        dest="speed_factor",
        type=float,
        default=1.0,
        help="Trip speed multiplier (default: 1.0 = real road speeds, 2.0 = 2x faster).",
    )

    # Device selection and control
    parser.add_argument(
        "-d", "--device",
        dest="device",
        help="Target device ID or name (default: auto-select connected phone).",
    )
    parser.add_argument(
        "--devices", "--list-devices",
        dest="list_devices",
        action="store_true",
        help="List connected devices and their pairing / bridge status.",
    )
    parser.add_argument(
        "--stop",
        dest="stop_spoof",
        action="store_true",
        help="Stop active spoofing session and restore real GPS.",
    )
    parser.add_argument(
        "--status",
        dest="show_status",
        action="store_true",
        help="Show status of connected devices and active sessions.",
    )
    parser.add_argument(
        "--presets",
        dest="list_presets",
        action="store_true",
        help="List all built-in location presets.",
    )

    # Server control
    parser.add_argument(
        "--server",
        dest="run_server",
        action="store_true",
        help="Launch the Geox Web UI server.",
    )
    parser.add_argument(
        "--port",
        dest="port",
        type=int,
        default=7876,
        help="Port for Web UI server (default: 7876).",
    )
    parser.add_argument(
        "--no-browser",
        dest="no_browser",
        action="store_true",
        help="Do not automatically open the web browser when starting server.",
    )

    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = build_cli_parser()
    args = parser.parse_args(argv)
    engine = get_engine()

    # Handle explicit commands or action flags
    cmd = args.command

    if cmd == "server" or args.run_server:
        from . import server
        print(f"\n[Geox] Starting Web UI on http://127.0.0.1:{args.port} ...")
        if not args.no_browser:
            import webbrowser
            threading_timer = threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}"))
            threading_timer.daemon = True
            threading_timer.start()
        try:
            from waitress import serve
            serve(server.app, host="127.0.0.1", port=args.port, threads=8)
        except ImportError:
            server.app.run(host="127.0.0.1", port=args.port, threaded=True, debug=False)
        return 0

    if cmd == "devices" or args.list_devices:
        list_devices_cmd(engine)
        return 0

    if cmd == "presets" or args.list_presets:
        list_presets_cmd()
        return 0

    if cmd == "status" or args.show_status:
        stat = engine.status()
        list_devices_cmd(engine)
        sessions = stat.get("sessions", [])
        if sessions:
            print("Active Spoofing Sessions:")
            print("-" * 65)
            for s in sessions:
                print(f"  Device: {s.get('device_name')} ({s.get('device_id')})")
                print(f"  State:  {s.get('state')} | Mode: {s.get('mode')}")
                print(f"  Coords: {s.get('last')} | Target: {s.get('place')}\n")
            print("-" * 65)
        else:
            print("No active spoofing sessions.\n")
        return 0

    if cmd == "stop" or args.stop_spoof:
        try:
            target_device = pick_target_device(engine, args.device)
            print(f"Stopping spoofing on {target_device.get('name') or target_device['id']}...")
            engine.stop(target_device["id"])
            print("[Geox] Real GPS restored.")
        except Exception as e:
            print(f"[Geox] Stop result: {e}")
        return 0

    if cmd == "setup-bridge":
        from .android_backend import setup_bridge
        try:
            target_device = pick_target_device(engine, args.device)
            if target_device.get("platform") != "android":
                print("Bridge setup is only for Android devices.")
                return 1
            print(f"Setting up Geox Bridge on {target_device.get('name') or target_device['id']}...")
            res = setup_bridge(engine, target_device["id"])
            print(f"Result: {res}")
        except Exception as e:
            print(f"[ERROR] Bridge setup failed: {e}")
        return 0

    # Determine location or trip route
    loc_input = args.location or args.preset

    # Trip mode via --from / --to
    if args.trip_from or args.trip_to or (args.movement and args.movement[0].lower() in ("trip", "route")):
        origin_text = args.trip_from
        dest_text = args.trip_to or loc_input

        if not origin_text or not dest_text:
            print("[ERROR] Trip mode requires both origin (--from) and destination (--to or --location).")
            print("Example: geox --from \"Vancouver\" --to \"Seattle\" --profile car")
            return 1

        print(f"Planning trip from '{origin_text}' to '{dest_text}' ({args.profile})...")
        from_lat, from_lng, from_label = resolve_location_input(origin_text)
        to_lat, to_lng, to_label = resolve_location_input(dest_text)

        route_data = plan_route((from_lat, from_lng), (to_lat, to_lng), args.profile)
        print(f"Trip planned: {route_data['distance_km']} km, ~{route_data['duration_min']} min at road speed.")

        cfg = {
            "mode": "route",
            "waypoints": route_data["waypoints"],
            "seg_seconds": route_data["seg_seconds"],
            "speed_factor": args.speed_factor,
            "place": f"{from_label} → {to_label}",
        }

        try:
            target_device = pick_target_device(engine, args.device)
        except Exception as e:
            print(f"\n[ERROR] {e}\n")
            return 1

        return run_spoof(engine, target_device, cfg)

    # Standard location spoofing
    if not loc_input:
        parser.print_help()
        print("\n[NOTE] Please specify a location (--location) or a command (server, devices, stop).")
        return 1

    try:
        print(f"Resolving location: '{loc_input}'...")
        lat, lng, label = resolve_location_input(loc_input)
    except Exception as e:
        print(f"[ERROR] Could not resolve location: {e}")
        return 1

    mode, radius, speed = _parse_movement_args(
        args.movement,
        explicit_radius=args.radius,
        explicit_speed=args.speed,
    )

    cfg = {
        "mode": mode,
        "lat": lat,
        "lng": lng,
        "place": label,
    }
    if mode == "jitter":
        cfg["radius_m"] = radius
        cfg["speed_kmh"] = speed

    try:
        target_device = pick_target_device(engine, args.device)
    except Exception as e:
        print(f"\n[ERROR] {e}\n")
        return 1

    return run_spoof(engine, target_device, cfg)


if __name__ == "__main__":
    import threading
    sys.exit(main())
