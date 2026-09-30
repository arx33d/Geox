"""Geox web server + JSON API.

Run:  python -m geox.server          → http://127.0.0.1:7876
"""

import argparse
import threading
import time
import webbrowser

import math
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


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    return r * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


@app.route("/api/geocode", methods=["GET", "POST"])
def api_geocode():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
    else:
        data = request.args.to_dict()
    q = (data.get("q") or "").strip()
    if len(q) < 2:
        return jsonify(results=[])

    user_lat = data.get("lat")
    user_lng = data.get("lng")
    has_coords = False
    try:
        if user_lat is not None and user_lng is not None:
            user_lat = float(user_lat)
            user_lng = float(user_lng)
            if -90 <= user_lat <= 90 and -180 <= user_lng <= 180:
                has_coords = True
    except (ValueError, TypeError):
        has_coords = False

    norm_q = q.lower()
    cache_key = (norm_q, round(user_lat, 2) if has_coords else None, round(user_lng, 2) if has_coords else None)
    now = time.time()
    if cache_key in _GEOCODE_CACHE and now - _GEOCODE_CACHE[cache_key][0] < 3600:
        return jsonify(results=_GEOCODE_CACHE[cache_key][1])
    if norm_q in _GEOCODE_CACHE and now - _GEOCODE_CACHE[norm_q][0] < 3600:
        return jsonify(results=_GEOCODE_CACHE[norm_q][1])

    results = []
    params = {"format": "jsonv2", "q": q, "limit": 10, "addressdetails": 1}
    if has_coords:
        # Bias viewbox around user's location (approx +/- 3.0 degrees ~ 300km)
        min_lng = max(-180.0, user_lng - 3.0)
        max_lng = min(180.0, user_lng + 3.0)
        min_lat = max(-85.0511, user_lat - 3.0)
        max_lat = min(85.0511, user_lat + 3.0)
        params["viewbox"] = f"{min_lng},{max_lat},{max_lng},{min_lat}"
        params["bounded"] = 0

    try:
        r = requests.get(
            f"{NOMINATIM}/search",
            params=params,
            headers=HEADERS,
            timeout=8,
        )
        r.raise_for_status()
        raw_items = r.json()
        for item in raw_items:
            try:
                ilat = float(item["lat"])
                ilng = float(item["lon"])
            except (KeyError, ValueError, TypeError):
                continue

            address = item.get("address") or {}
            city = (
                address.get("city")
                or address.get("town")
                or address.get("village")
                or address.get("municipality")
                or address.get("hamlet")
                or address.get("suburb")
                or ""
            )
            state_prov = address.get("state") or address.get("province") or address.get("region") or ""
            country = address.get("country") or ""
            display_name = item.get("display_name", "")
            first_part = display_name.split(",")[0].strip() if display_name else ""
            title = item.get("name") or first_part or city or "Location"

            dist_km = None
            dist_str = ""
            if has_coords:
                dist_km = haversine_km(user_lat, user_lng, ilat, ilng)
                if dist_km < 10:
                    dist_str = f"{dist_km:.1f} km away"
                elif dist_km < 1000:
                    dist_str = f"{round(dist_km)} km away"
                else:
                    dist_str = f"{round(dist_km):,} km away"

            sub_parts = []
            if city and city.lower() != title.lower():
                sub_parts.append(city)
            if state_prov:
                sub_parts.append(state_prov)
            if country:
                sub_parts.append(country)
            if dist_str:
                sub_parts.append(dist_str)

            subtitle = " · ".join(sub_parts) if sub_parts else display_name

            results.append({
                "label": display_name,
                "title": title,
                "subtitle": subtitle,
                "city": city,
                "state": state_prov,
                "country": country,
                "dist_km": round(dist_km, 1) if dist_km is not None else None,
                "lat": ilat,
                "lng": ilng,
            })
    except Exception:
        pass

    # If proximity is known, prioritize nearby results (< 300km) and sort by distance
    if has_coords and results:
        def sort_key(x):
            d = x.get("dist_km")
            if d is None:
                return (3, 0)
            if d < 300:
                return (0, d)
            if d < 2500:
                return (1, d)
            return (2, d)

        results.sort(key=sort_key)
        results = results[:7]

    if not results:
        offline_matches = search_offline_places(q, limit=8)
        for om in offline_matches:
            olat = float(om["lat"])
            olng = float(om["lng"])
            dist_km = haversine_km(user_lat, user_lng, olat, olng) if has_coords else None
            dist_str = f"{round(dist_km)} km away" if dist_km is not None else ""
            label = om.get("label", "")
            parts = [p.strip() for p in label.split(",") if p.strip()]
            title = parts[0] if parts else label
            sub_parts = parts[1:]
            if dist_str:
                sub_parts.append(dist_str)
            results.append({
                "label": label,
                "title": title,
                "subtitle": " · ".join(sub_parts) if sub_parts else label,
                "city": parts[0] if parts else "",
                "state": parts[1] if len(parts) > 1 else "",
                "country": parts[-1] if len(parts) > 2 else "",
                "dist_km": round(dist_km, 1) if dist_km is not None else None,
                "lat": olat,
                "lng": olng,
            })
        if has_coords and results:
            results.sort(key=lambda x: x.get("dist_km") or 999999)

    _GEOCODE_CACHE[cache_key] = (now, results)
    if len(_GEOCODE_CACHE) > 250:
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


@app.route("/api/offline/status", methods=["GET", "POST"])
def api_offline_status():
    return jsonify(get_downloader().status())


@app.route("/api/offline/estimate", methods=["GET", "POST"])
def api_offline_estimate():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
    else:
        data = request.args.to_dict()
    region_type = data.get("region_type") or data.get("package") or data.get("region") or "world"
    weight = data.get("weight", "moderate")
    bounds = data.get("bounds")
    if isinstance(bounds, str):
        try:
            bounds = [float(x.strip()) for x in bounds.split(",")]
        except Exception:
            bounds = None
    elif isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        try:
            bounds = [float(x) for x in bounds]
        except Exception:
            bounds = None
    country = data.get("country")
    if country and country in COUNTRIES_BBOX:
        bounds = COUNTRIES_BBOX[country]
        region_type = "country"

    return jsonify(calculate_estimate(region_type=region_type, weight=weight, bounds=bounds))


@app.route("/api/offline/regions", methods=["GET", "POST"])
def api_offline_regions():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        q = data.get("q", "")
    else:
        q = request.args.get("q", "")
    return jsonify(results=search_countries(q))


@app.route("/api/offline/download", methods=["GET", "POST"])
def api_offline_download():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
    else:
        data = request.args.to_dict()
    package = data.get("package", "world")
    style = data.get("style", "topo")
    bounds = data.get("bounds")
    if isinstance(bounds, str):
        try:
            bounds = [float(x.strip()) for x in bounds.split(",")]
        except Exception:
            bounds = None
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


@app.route("/api/offline/cancel", methods=["GET", "POST"])
def api_offline_cancel():
    return jsonify(get_downloader().cancel())


@app.route("/api/offline/clear", methods=["GET", "POST"])
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
