"""Geox web server + JSON API.

Run:  python -m geox.server          → http://127.0.0.1:7876
"""

import argparse
import threading
import time
import webbrowser

import requests
from flask import Flask, jsonify, request, send_from_directory

from .android_backend import AndroidError, install_adb, setup_bridge
from .engine import get_engine

app = Flask(__name__, static_folder="../web", static_url_path="")
engine = get_engine()

NOMINATIM = "https://nominatim.openstreetmap.org"
HEADERS = {"User-Agent": "Geox/1.0 (personal GPS-spoofing desktop app)"}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/<path:path>")
def assets(path):
    return send_from_directory(app.static_folder, path)


@app.get("/api/status")
def api_status():
    return jsonify(engine.status())


@app.post("/api/start")
def api_start():
    data = request.get_json(force=True, silent=True) or {}
    device_id = data.get("device_id")
    if not device_id:
        return jsonify(error="Pick a device first."), 400
    try:
        snap = engine.start(device_id, data)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001 — surface anything else to the UI
        return jsonify(error=f"Could not start: {e}"), 500
    return jsonify(snapshot=snap)


@app.post("/api/swap")
@app.post("/api/update")
def api_swap():
    data = request.get_json(force=True, silent=True) or {}
    device_id = data.get("device_id")
    if not device_id:
        return jsonify(error="Pick a device first."), 400
    try:
        snap = engine.update(device_id, data)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Could not swap location: {e}"), 500
    return jsonify(snapshot=snap)


@app.post("/api/stop")
def api_stop():
    data = request.get_json(force=True, silent=True) or {}
    try:
        snap = engine.stop(data.get("device_id"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(snapshot=snap)


@app.post("/api/geocode")
def api_geocode():
    q = (request.get_json(force=True, silent=True) or {}).get("q", "").strip()
    if len(q) < 2:
        return jsonify(results=[])
    try:
        r = requests.get(
            f"{NOMINATIM}/search",
            params={"format": "jsonv2", "q": q, "limit": 6, "addressdetails": 0},
            headers=HEADERS,
            timeout=12,
        )
        r.raise_for_status()
        results = [
            {"label": item.get("display_name", ""), "lat": float(item["lat"]), "lng": float(item["lon"])}
            for item in r.json()
        ]
    except Exception as e:  # noqa: BLE001
        return jsonify(results=[], error=f"Search failed: {e}"), 502
    return jsonify(results=results)


@app.get("/api/reverse")
def api_reverse():
    lat, lng = request.args.get("lat"), request.args.get("lng")
    try:
        r = requests.get(
            f"{NOMINATIM}/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 12},
            headers=HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        return jsonify(label=r.json().get("display_name", ""))
    except Exception:
        return jsonify(label="")


@app.post("/api/route")
def api_route():
    from .router import geocode_name, parse_trip_input, plan_route

    payload = request.get_json(force=True, silent=True) or {}
    try:
        origin, dest, label, profile = parse_trip_input(payload)
        if origin is None:
            # fall back to the map marker / current target as the start point
            origin = payload.get("start") or None
        if origin is None:
            return jsonify(
                error="Choose a start point: move the map marker to where the "
                      "phone really is, or paste a Google Maps link that "
                      "contains both ends."
            ), 400
        result = plan_route(
            (float(origin["lat"]), float(origin["lng"])),
            (float(dest["lat"]), float(dest["lng"])),
            profile,
        )
        result["dest_label"] = label
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Route planning failed: {e}"), 502
    return jsonify(result)


@app.post("/api/ios/enable-devmode")
def api_enable_devmode():
    from .ios_backend import IosError, enable_developer_mode

    try:
        result = enable_developer_mode(engine)
    except IosError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Could not enable Developer Mode: {e}"), 500
    return jsonify(result)


@app.post("/api/android/install-adb")
def api_install_adb():
    if engine.adb_install_running:
        return jsonify(started=True, note="already downloading")
    install_adb(engine)
    return jsonify(started=True)


@app.post("/api/android/setup-bridge")
def api_setup_bridge():
    device_id = (request.get_json(force=True, silent=True) or {}).get("device_id")
    if not device_id:
        return jsonify(error="Pick a device first."), 400
    try:
        state = setup_bridge(engine, device_id)
    except AndroidError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Bridge setup failed: {e}"), 500
    return jsonify(bridge=state)


def main():
    parser = argparse.ArgumentParser(description="Geox — GPS spoofer for connected phones")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7876)
    parser.add_argument("--no-open", action="store_true", help="don't open the browser")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print("=" * 60)
    print(f"  Geox running → {url}")
    print("  Keep this window open while spoofing.")
    print("=" * 60)
    if not args.no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host=args.host, port=args.port, threads=8)
    except ImportError:
        # waitress not installed — fall back to Flask's built-in server
        app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
