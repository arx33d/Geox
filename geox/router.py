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


def geocode_name(name):
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"format": "jsonv2", "q": name, "limit": 1},
        headers=HEADERS,
        timeout=12,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"Could not find “{name}” — try a clearer place name.")
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", name)


def _coords_from_text(text):
    """Best-effort extraction of [lat, lng] pairs from any Google Maps URL."""
    pairs = []
    # !3dLAT!4dLNG (place pins inside /dir/ URLs)
    for m in re.finditer(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", text):
        pairs.append((float(m.group(1)), float(m.group(2))))
    # @lat,lng (map view)
    if not pairs:
        m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", text)
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


def _param(text, key):
    m = re.search(rf"[?&]{key}=([^&]+)", text)
    return m.group(1) if m else None


def parse_trip_input(payload):
    """Return ((lat, lng), label, profile) from /api/route request fields."""
    profile = payload.get("profile", "car")
    if profile not in OSRM:
        raise ValueError(f"Unknown profile {profile!r}")

    gmaps_url = (payload.get("gmaps_url") or "").strip()
    origin = payload.get("from")  # {lat, lng} or None
    dest = payload.get("to")      # {lat, lng} or {name} or None

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

    if isinstance(dest, dict) and "name" in dest and "lat" not in dest:
        lat, lng, label = geocode_name(dest["name"])
        dest = {"lat": lat, "lng": lng}
    else:
        label = f"{float(dest['lat']):.5f}, {float(dest['lng']):.5f}"

    return origin, dest, label, profile


def plan_route(from_ll, to_ll, profile):
    """Fetch a real itinerary with per-segment travel times.

    Returns downsampled waypoints plus ``seg_seconds``: the real time each
    segment takes, so the spoofed location speeds up on highways and slows
    down in city streets instead of moving at one flat average.
    """
    url = (
        f"{OSRM[profile]}/{from_ll[1]:.6f},{from_ll[0]:.6f};"
        f"{to_ll[1]:.6f},{to_ll[0]:.6f}"
    )
    r = requests.get(url, params={
        "geometries": "geojson", "overview": "full", "annotations": "true",
    }, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"Router could not find a {profile} itinerary ({data.get('code')}).")
    route = data["routes"][0]

    coords = [(p[1], p[0]) for p in route["geometry"]["coordinates"]]  # lon,lat → lat,lng
    durs = []
    for leg in route["legs"]:
        durs += [float(x) for x in (leg.get("annotation") or {}).get("duration", [])]
    distance_m = float(route["distance"])
    real_duration_s = float(route["duration"])

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
    return {
        "waypoints": [[round(a, 6), round(b, 6)] for a, b in waypoints],
        "seg_seconds": seg_seconds,
        "distance_km": round(distance_m / 1000.0, 2),
        "duration_min": round(real_duration_s / 60.0),
        "speed_kmh": round(speed_kmh, 1),
        "profile": profile,
    }
