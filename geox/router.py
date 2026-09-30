"""Itinerary planning against free OpenStreetMap routers (no API keys).

* car  → FOSSGIS OSRM demo  (real road network, real speeds)
* bike / walk → FOSSGIS OSRM bike / foot instances
* transit → free routers don't expose real bus/metro schedules, so we follow
  the road network and hold a transit-like average speed. Honest
  approximation, clearly labelled in the UI.

Also parses pasted Google Maps links (share URLs, /dir/ URLs, api=1 URLs,
@lat,lng views, !3d..!4d.. pins) into origin/destination pairs.
"""

import re

import requests

HEADERS = {"User-Agent": "Geox/1.0 (personal GPS-spoofing desktop app)"}

OSRM = {
    "car": "https://routing.openstreetmap.de/routed-car/route/v1/driving",
    "bike": "https://routing.openstreetmap.de/routed-bike/route/v1/driving",
    "walk": "https://routing.openstreetmap.de/routed-foot/route/v1/driving",
    "transit": "https://routing.openstreetmap.de/routed-car/route/v1/driving",
}
TRANSIT_AVG_KMH = 22.0  # urban bus/metro door-to-door average


def geocode_name(name, proximity=None):
    params = {"format": "jsonv2", "q": name, "limit": 6, "addressdetails": 1}
    has_prox = False
    if proximity and len(proximity) == 2:
        try:
            plat, plng = float(proximity[0]), float(proximity[1])
            min_lng = max(-180.0, plng - 3.0)
            max_lng = min(180.0, plng + 3.0)
            min_lat = max(-85.0511, plat - 3.0)
            max_lat = min(85.0511, plat + 3.0)
            params["viewbox"] = f"{min_lng},{max_lat},{max_lng},{min_lat}"
            params["bounded"] = 0
            has_prox = True
        except Exception:
            has_prox = False

    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=HEADERS,
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            if has_prox and len(data) > 1:
                import math

                def _dist(item):
                    try:
                        dlat = math.radians(float(item["lat"]) - float(proximity[0]))
                        dlon = math.radians(float(item["lon"]) - float(proximity[1]))
                        a = (
                            math.sin(dlat / 2.0) ** 2
                            + math.cos(math.radians(float(proximity[0])))
                            * math.cos(math.radians(float(item["lat"])))
                            * math.sin(dlon / 2.0) ** 2
                        )
                        return 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
                    except Exception:
                        return 999.0

                data.sort(key=_dist)
            best = data[0]
            return float(best["lat"]), float(best["lon"]), best.get("display_name", name)
    except Exception:
        pass

    from .offline import search_offline_places

    matches = search_offline_places(name, limit=6)
    if matches:
        if has_prox and len(matches) > 1:
            import math

            def _off_dist(item):
                try:
                    dlat = math.radians(float(item["lat"]) - float(proximity[0]))
                    dlon = math.radians(float(item["lng"]) - float(proximity[1]))
                    a = (
                        math.sin(dlat / 2.0) ** 2
                        + math.cos(math.radians(float(proximity[0])))
                        * math.cos(math.radians(float(item["lat"])))
                        * math.sin(dlon / 2.0) ** 2
                    )
                    return 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
                except Exception:
                    return 999.0

            matches.sort(key=_off_dist)
        return float(matches[0]["lat"]), float(matches[0]["lng"]), matches[0]["label"]

    raise ValueError(f"Could not find “{name}” — try a clearer place name or search offline places.")


PRESETS = {
    "mcmurdo": (-77.8419, 166.6863, "McMurdo Station, Antarctica"),
    "southpole": (-89.9975, 0.0, "South Pole Station"),
    "vancouver": (49.2827, -123.1207, "Vancouver, Canada"),
    "toronto": (43.6532, -79.3832, "Toronto, Canada"),
    "newyork": (40.7128, -74.0060, "New York, USA"),
    "nyc": (40.7128, -74.0060, "New York, USA"),
    "paris": (48.8566, 2.3522, "Paris, France"),
    "tokyo": (35.6762, 139.6503, "Tokyo, Japan"),
    "london": (51.5072, -0.1276, "London, UK"),
    "dubai": (25.2048, 55.2708, "Dubai, UAE"),
    "sydney": (-33.8688, 151.2093, "Sydney, Australia"),
    "honolulu": (21.3069, -157.8583, "Honolulu, Hawaii"),
    "lasvegas": (36.1699, -115.1398, "Las Vegas, USA"),
    "losangeles": (34.0522, -118.2437, "Los Angeles, USA"),
    "la": (34.0522, -118.2437, "Los Angeles, USA"),
    "sanfrancisco": (37.7749, -122.4194, "San Francisco, USA"),
    "sf": (37.7749, -122.4194, "San Francisco, USA"),
    "seattle": (47.6062, -122.3321, "Seattle, USA"),
    "miami": (25.7617, -80.1918, "Miami, USA"),
    "chicago": (41.8781, -87.6298, "Chicago, USA"),
}


def expand_gmaps_url(url):
    """Follow redirects if the URL is a shortened Google Maps link."""
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return url
    if any(short in url.lower() for short in ("goo.gl", "maps.app.goo.gl", "page.link", "bit.ly")):
        try:
            r = requests.head(url, allow_redirects=True, timeout=10, headers=HEADERS)
            return r.url
        except Exception:
            try:
                r = requests.get(url, allow_redirects=True, timeout=10, headers=HEADERS)
                return r.url
            except Exception:
                pass
    return url


def _coords_from_text(text):
    """Best-effort extraction of [lat, lng] pairs from any Google Maps URL."""
    text = expand_gmaps_url(text)
    pairs = []
    # !3dLAT!4dLNG (place pins inside /dir/ URLs or search URLs)
    for m in re.finditer(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", text):
        pairs.append((float(m.group(1)), float(m.group(2))))
    # @lat,lng (map view)
    if not pairs:
        m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", text)
        if m:
            pairs.append((float(m.group(1)), float(m.group(2))))
    # /search/LAT,LNG or /place/LAT,LNG
    if not pairs:
        m = re.search(r"/(?:search|place)/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", text)
        if m:
            pairs.append((float(m.group(1)), float(m.group(2))))
    # origin= / destination= params — names or "lat,lng"
    if not pairs:
        origin = _param(text, "origin")
        dest = _param(text, "destination")
        for value in (origin, dest):
            if value:
                m = re.match(r"(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", value)
                if m:
                    pairs.append((float(m.group(1)), float(m.group(2))))
                else:
                    lat, lng, _ = geocode_name(value)
                    pairs.append((lat, lng))
    # /dir/A/B/ path segments (URL-encoded names)
    if not pairs:
        m = re.search(r"/dir/([^/@]+?)/([^/@]+?)(?:/|@|$)", text)
        if m:
            for name in (m.group(1), m.group(2)):
                name = requests.utils.unquote(name)
                if name and name not in ("-", "now"):
                    lat, lng, _ = geocode_name(name)
                    pairs.append((lat, lng))
    return pairs


def resolve_location_input(raw):
    """Resolve a raw location input (Google Maps URL, preset, coords, or search text).

    Returns:
        (lat: float, lng: float, label: str)
    """
    if not raw or not str(raw).strip():
        raise ValueError("Location cannot be empty.")
    text = str(raw).strip()

    # 1. Preset lookup (normalized)
    norm = re.sub(r"[^a-zA-Z0-9]", "", text).lower()
    if norm in PRESETS:
        lat, lng, label = PRESETS[norm]
        return lat, lng, label

    # 2. Check if it's a URL or contains Google Maps pattern
    if "http" in text.lower() or "maps" in text.lower() or "!3d" in text or "@" in text:
        pairs = _coords_from_text(text)
        if pairs:
            lat, lng = pairs[-1]
            # Try to extract a clean label from the place name in URL if present
            label = f"{lat:.5f}, {lng:.5f}"
            place_match = re.search(r"/place/([^/@]+)", text)
            if place_match:
                cleaned = requests.utils.unquote(place_match.group(1)).replace("+", " ")
                label = f"{cleaned} ({lat:.5f}, {lng:.5f})"
            return lat, lng, label

    # 3. Direct numeric coordinates: "43.6548, -79.3884" or "43.6548 -79.3884"
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*[,;\s]\s*([+-]?\d+(?:\.\d+)?)$", text)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise ValueError(f"Coordinates out of bounds: lat={lat}, lng={lng}")
        return lat, lng, f"{lat:.5f}, {lng:.5f}"

    # 4. Search via Nominatim geocoding
    return geocode_name(text)


def _param(text, key):
    m = re.search(rf"[?&]{key}=([^&]+)", text)
    return m.group(1) if m else None


def parse_trip_input(payload):
    """Return ((lat, lng), label, profile) from /api/route request fields."""
    profile = payload.get("profile", "car")
    if profile not in OSRM:
        raise ValueError(f"Unknown profile {profile!r}")

    gmaps_url = (payload.get("gmaps_url") or "").strip()
    origin = payload.get("from") or payload.get("start")  # {lat, lng} or None
    dest = payload.get("to")      # {lat, lng} or {name} or str or None

    if isinstance(dest, str):
        m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*[,;\s]\s*([+-]?\d+(?:\.\d+)?)$", dest.strip())
        if m:
            dest = {"lat": float(m.group(1)), "lng": float(m.group(2))}
        else:
            dest = {"name": dest.strip()}

    if gmaps_url:
        pairs = _coords_from_text(gmaps_url)
        if not pairs:
            raise ValueError(
                "Could not read coordinates from that Google Maps link. "
                "Search the destination below instead."
            )
        if len(pairs) >= 2 and origin is None:
            origin = {"lat": pairs[0][0], "lng": pairs[0][1]}
            pairs = pairs[1:]
        if not dest and pairs:
            dest = {"lat": pairs[-1][0], "lng": pairs[-1][1]}

    if not dest:
        raise ValueError("Pick a destination (search, map click, or Google Maps link).")

    if isinstance(dest, dict) and "name" in dest and ("lat" not in dest or dest.get("lat") is None):
        origin_coords = None
        if origin and isinstance(origin, dict) and "lat" in origin and "lng" in origin:
            try:
                origin_coords = (float(origin["lat"]), float(origin["lng"]))
            except Exception:
                pass
        lat, lng, label = geocode_name(dest["name"], proximity=origin_coords)
        dest = {"lat": lat, "lng": lng}
    elif isinstance(dest, dict) and "lat" in dest and "lng" in dest:
        lat = float(dest["lat"])
        lng = float(dest["lng"])
        label = dest.get("name") or dest.get("label") or f"{lat:.5f}, {lng:.5f}"
        dest = {"lat": lat, "lng": lng}
    else:
        label = f"{float(dest['lat']):.5f}, {float(dest['lng']):.5f}"

    return origin, dest, label, profile


def _extract_summary(route, route_id):
    road_names = []
    steps = []
    for leg in route.get("legs", []):
        for s in leg.get("steps", []):
            name = (s.get("name") or "").strip()
            ref = (s.get("ref") or "").strip()
            label = f"{name} ({ref})" if name and ref and name != ref else (ref or name)
            dist = float(s.get("distance", 0))
            if label and dist > 50:
                steps.append((dist, label))
    steps.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    for _, name in steps:
        if name not in seen:
            seen.add(name)
            road_names.append(name)
            if len(road_names) >= 2:
                break
    if road_names:
        return f"via {', '.join(road_names)}"
    return f"Option {route_id + 1}"


def _process_osrm_route(route, profile, route_id=0):
    coords = [(p[1], p[0]) for p in route["geometry"]["coordinates"]]  # lon,lat → lat,lng
    durs = []
    for leg in route.get("legs", []):
        durs += [float(x) for x in (leg.get("annotation") or {}).get("duration", [])]
    distance_m = float(route.get("distance", 0))
    real_duration_s = float(route.get("duration", 0))

    if len(durs) != len(coords) - 1 or not durs:
        # router gave no per-edge annotation: fall back to one flat speed
        durs = []
        if distance_m > 0 and real_duration_s > 0:
            step_m = distance_m / max(1, len(coords) - 1)
            n = max(1, len(coords) - 1)
            durs = [real_duration_s / n] * n

    if profile == "transit":
        # no free transit timetables: hold a transit-like average speed
        speed_mps = TRANSIT_AVG_KMH * 1000.0 / 3600.0
        real_duration_s = distance_m / speed_mps
        durs = []
        if distance_m > 0:
            n = max(1, len(coords) - 1)
            durs = [real_duration_s / n] * n

    # downsample: merge edges so the engine gets ~400 segments with the
    # summed real travel time of everything merged away
    n_edges = len(coords) - 1
    step = max(1, n_edges // 400)
    waypoints, seg_seconds = [coords[0]], []
    acc = 0.0
    for i in range(n_edges):
        acc += durs[i]
        if (i + 1) % step == 0 or i == n_edges - 1:
            waypoints.append(coords[i + 1])
            seg_seconds.append(round(acc, 3))
            acc = 0.0
    if waypoints[-1] != coords[-1]:
        waypoints.append(coords[-1])
        seg_seconds.append(0.001)

    speed_kmh = (distance_m / 1000.0) / (real_duration_s / 3600.0) if real_duration_s > 0 else 20.0
    summary = _extract_summary(route, route_id)

    return {
        "id": route_id,
        "summary": summary,
        "waypoints": [[round(a, 6), round(b, 6)] for a, b in waypoints],
        "seg_seconds": seg_seconds,
        "distance_km": round(distance_m / 1000.0, 2),
        "duration_min": max(1, round(real_duration_s / 60.0)),
        "speed_kmh": round(speed_kmh, 1),
        "profile": profile,
    }


def _offline_plan_route(from_ll, to_ll, profile):
    from .motion import haversine_m

    dist_m = haversine_m(from_ll[0], from_ll[1], to_ll[0], to_ll[1])
    speeds = {
        "car": 65.0,
        "transit": 25.0,
        "bike": 18.0,
        "walk": 4.5,
    }
    speed_kmh = speeds.get(profile, 50.0)
    real_duration_s = max(5.0, (dist_m / 1000.0) / (speed_kmh / 3600.0))

    # Generate smooth waypoints along the direct vector
    n_points = max(5, min(80, int(dist_m / 350)))
    waypoints = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        lat = from_ll[0] + (to_ll[0] - from_ll[0]) * frac
        lng = from_ll[1] + (to_ll[1] - from_ll[1]) * frac
        waypoints.append([round(lat, 6), round(lng, 6)])

    seg_dur = round(real_duration_s / (n_points - 1), 3)
    seg_seconds = [seg_dur] * (n_points - 1)

    primary = {
        "id": 0,
        "summary": f"Offline direct route ({profile})",
        "waypoints": waypoints,
        "seg_seconds": seg_seconds,
        "distance_km": round(dist_m / 1000.0, 2),
        "duration_min": max(1, round(real_duration_s / 60.0)),
        "speed_kmh": round(speed_kmh, 1),
        "profile": profile,
        "is_fastest": True,
        "offline": True,
    }
    return {
        "waypoints": primary["waypoints"],
        "seg_seconds": primary["seg_seconds"],
        "distance_km": primary["distance_km"],
        "duration_min": primary["duration_min"],
        "speed_kmh": primary["speed_kmh"],
        "profile": profile,
        "summary": primary["summary"],
        "routes": [primary],
        "offline": True,
    }


def plan_route(from_ll, to_ll, profile):
    """Fetch a real itinerary with per-segment travel times.

    Supports alternative routes (up to 3 candidate itineraries).
    Falls back to offline direct route generation if network or OSRM is unreachable.
    """
    try:
        url = (
            f"{OSRM[profile]}/{from_ll[1]:.6f},{from_ll[0]:.6f};"
            f"{to_ll[1]:.6f},{to_ll[0]:.6f}"
        )
        r = requests.get(url, params={
            "geometries": "geojson", "overview": "full", "annotations": "true",
            "alternatives": "3", "steps": "true",
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError(f"Router could not find a {profile} itinerary ({data.get('code')}).")

        parsed_routes = []
        for idx, raw_route in enumerate(data["routes"]):
            parsed_routes.append(_process_osrm_route(raw_route, profile, idx))

        min_dur = min(r["duration_min"] for r in parsed_routes)
        for r in parsed_routes:
            r["is_fastest"] = (r["duration_min"] == min_dur)

        primary = parsed_routes[0]
        return {
            "waypoints": primary["waypoints"],
            "seg_seconds": primary["seg_seconds"],
            "distance_km": primary["distance_km"],
            "duration_min": primary["duration_min"],
            "speed_kmh": primary["speed_kmh"],
            "profile": profile,
            "summary": primary["summary"],
            "routes": parsed_routes,
            "offline": False,
        }
    except Exception:
        return _offline_plan_route(from_ll, to_ll, profile)
