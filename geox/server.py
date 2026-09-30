"""Geox web server + JSON API.

Run:  python -m geox.server          → http://127.0.0.1:7876
"""

import argparse
import threading
import time
import webbrowser

import os
import requests
from flask import Flask, jsonify, request, send_file, send_from_directory

from .android_backend import AndroidError, install_adb, setup_bridge
from .engine import get_engine
from .offline import (
    COUNTRIES_BBOX,
    MAP_SOURCES,
    USER_AGENT,
    calculate_estimate,
    clear_cache,
    get_downloader,
    get_tile_path,
    search_countries,
    search_offline_places,
)

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


_GEOCODE_CACHE = {}
_REVERSE_CACHE = {}


@app.post("/api/geocode")
def api_geocode():
    q = (request.get_json(force=True, silent=True) or {}).get("q", "").strip()
    if len(q) < 2:
        return jsonify(results=[])
    norm_q = q.lower()
    now = time.time()
    if norm_q in _GEOCODE_CACHE and now - _GEOCODE_CACHE[norm_q][0] < 3600:
        return jsonify(results=_GEOCODE_CACHE[norm_q][1])

    results = []
    try:
        r = requests.get(
            f"{NOMINATIM}/search",
            params={"format": "jsonv2", "q": q, "limit": 6, "addressdetails": 0},
            headers=HEADERS,
            timeout=8,
        )
        r.raise_for_status()
        results = [
            {"label": item.get("display_name", ""), "lat": float(item["lat"]), "lng": float(item["lon"])}
            for item in r.json()
        ]
    except Exception:
        pass

    if not results:
        results = search_offline_places(q, limit=6)

    _GEOCODE_CACHE[norm_q] = (now, results)
    if len(_GEOCODE_CACHE) > 200:
        _GEOCODE_CACHE.pop(next(iter(_GEOCODE_CACHE)))
    return jsonify(results=results)


@app.get("/api/reverse")
def api_reverse():
    lat, lng = request.args.get("lat"), request.args.get("lng")
    if not lat or not lng:
        return jsonify(label="")
    try:
        key = f"{round(float(lat), 4)},{round(float(lng), 4)}"
    except (ValueError, TypeError):
        key = f"{lat},{lng}"
    now = time.time()
    if key in _REVERSE_CACHE and now - _REVERSE_CACHE[key][0] < 3600:
        return jsonify(label=_REVERSE_CACHE[key][1])
    try:
        r = requests.get(
            f"{NOMINATIM}/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 12},
            headers=HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        label = r.json().get("display_name", "")
        _REVERSE_CACHE[key] = (now, label)
        if len(_REVERSE_CACHE) > 300:
            _REVERSE_CACHE.pop(next(iter(_REVERSE_CACHE)))
        return jsonify(label=label)
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
        for r in result.get("routes", []):
            r["dest_label"] = label
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


@app.get("/api/offline/tiles/<int:z>/<int:x>/<int:y>.jpg")
@app.get("/api/offline/tiles/<int:z>/<int:x>/<int:y>")
def api_offline_tile(z, x, y):
    tile_file = get_tile_path(z, x, y)
    if os.path.exists(tile_file) and os.path.getsize(tile_file) > 100:
        return send_file(tile_file, mimetype="image/jpeg")

    style = request.args.get("style", "topo")
    source_url = MAP_SOURCES.get(style, MAP_SOURCES["topo"]).format(z=z, x=x, y=y)
    try:
        r = requests.get(source_url, headers={"User-Agent": USER_AGENT}, timeout=4)
        if r.status_code == 200 and len(r.content) > 100:
            os.makedirs(os.path.dirname(tile_file), exist_ok=True)
            with open(tile_file, "wb") as f:
                f.write(r.content)
            return send_file(tile_file, mimetype="image/jpeg")
    except Exception:
        pass

    return ("", 404)


@app.get("/api/offline/status")
def api_offline_status():
    return jsonify(get_downloader().status())


@app.get("/api/offline/estimate")
@app.post("/api/offline/estimate")
def api_offline_estimate():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
    else:
        data = request.args.to_dict()
    region_type = data.get("region_type", "world")
    weight = data.get("weight", "moderate")
    bounds = data.get("bounds")
    if isinstance(bounds, str):
        try:
            bounds = [float(x.strip()) for x in bounds.split(",")]
        except Exception:
            bounds = None
    country = data.get("country")
    if country and country in COUNTRIES_BBOX:
        bounds = COUNTRIES_BBOX[country]
        region_type = "country"

    return jsonify(calculate_estimate(region_type=region_type, weight=weight, bounds=bounds))


@app.get("/api/offline/regions")
def api_offline_regions():
    q = request.args.get("q", "")
    return jsonify(results=search_countries(q))


@app.post("/api/offline/download")
def api_offline_download():
    data = request.get_json(force=True, silent=True) or {}
    package = data.get("package", "world")
    style = data.get("style", "topo")
    bounds = data.get("bounds")
    max_zoom = data.get("max_zoom")
    if max_zoom is not None:
        try:
            max_zoom = int(max_zoom)
        except Exception:
            max_zoom = None
    weight = data.get("weight", "moderate")
    country = data.get("country")
    if country and country in COUNTRIES_BBOX:
        bounds = COUNTRIES_BBOX[country]
        package = "country"

    res = get_downloader().start_download(
        package=package,
        style=style,
        bounds=bounds,
        max_zoom=max_zoom,
        weight=weight,
    )
    if "error" in res:
        return jsonify(res), 400
    return jsonify(res)


@app.post("/api/offline/cancel")
def api_offline_cancel():
    return jsonify(get_downloader().cancel())


@app.post("/api/offline/clear")
def api_offline_clear():
    return jsonify(clear_cache())


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
        try:
            from waitress import serve
            serve(app, host=args.host, port=args.port, threads=8)
        except ImportError:
            # waitress not installed — fall back to Flask's built-in server
            app.run(host=args.host, port=args.port, threaded=True, debug=False)
    except KeyboardInterrupt:
        pass
    finally:
        for sid in list(engine.sessions.keys()):
            try:
                engine.stop(sid)
            except Exception:
                pass


if __name__ == "__main__":
    main()
