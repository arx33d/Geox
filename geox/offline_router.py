"""Offline Road Graph Router — highway corridors and road-following offline navigation.

Matches requested origin and destination coordinates against local vector road packs
and pre-seeded highway corridors (e.g. Autoroute 20 -> Highway 401 for Montreal -> Toronto),
slicing real turn-by-turn road curves and computing realistic highway speeds.
"""

from __future__ import annotations

import json
import math
import os
import threading
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFLINE_DIR = os.path.join(BASE_DIR, "offline")
ROUTING_DIR = os.path.join(OFFLINE_DIR, "routing")

_LOCK = threading.Lock()
_CORRIDORS_CACHE: list[dict[str, Any]] | None = None
_CACHE_MTIME: float = 0.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in kilometers between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def get_routing_dir() -> str:
    """Ensure and return the offline routing directory."""
    os.makedirs(ROUTING_DIR, exist_ok=True)
    return ROUTING_DIR


def load_corridors() -> list[dict[str, Any]]:
    """Load all available road corridors from local routing packs."""
    global _CORRIDORS_CACHE, _CACHE_MTIME

    r_dir = get_routing_dir()
    latest_mtime = 0.0
    try:
        for f in os.listdir(r_dir):
            if f.endswith(".json"):
                m = os.path.getmtime(os.path.join(r_dir, f))
                if m > latest_mtime:
                    latest_mtime = m
    except Exception:
        pass

    with _LOCK:
        if _CORRIDORS_CACHE is not None and latest_mtime <= _CACHE_MTIME:
            return _CORRIDORS_CACHE

        corridors: list[dict[str, Any]] = []
        try:
            for fname in os.listdir(r_dir):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(r_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and "waypoints" in item and len(item["waypoints"]) >= 2:
                                    corridors.append(item)
                        elif isinstance(data, dict) and "waypoints" in data and len(data["waypoints"]) >= 2:
                            corridors.append(data)
                except Exception:
                    continue
        except Exception:
            pass

        _CORRIDORS_CACHE = corridors
        _CACHE_MTIME = latest_mtime
        return corridors


def save_cached_route(route: dict[str, Any], from_ll: tuple[float, float], to_ll: tuple[float, float], summary: str = "") -> None:
    """Auto-cache an online planned route into the offline road library."""
    wps = route.get("waypoints")
    if not wps or len(wps) < 5:
        return

    cached_file = os.path.join(get_routing_dir(), "cached_routes.json")
    with _LOCK:
        entries: list[dict[str, Any]] = []
        if os.path.exists(cached_file):
            try:
                with open(cached_file, "r", encoding="utf-8") as fh:
                    entries = json.load(fh)
            except Exception:
                entries = []

        # Avoid duplicate routes if already recorded within 500m
        for e in entries:
            ewps = e.get("waypoints", [])
            if ewps:
                d1 = haversine_km(from_ll[0], from_ll[1], ewps[0][0], ewps[0][1])
                d2 = haversine_km(to_ll[0], to_ll[1], ewps[-1][0], ewps[-1][1])
                if d1 < 0.5 and d2 < 0.5:
                    return

        dist_km = route.get("distance_km", 0)
        dur_min = route.get("duration_min", 1)
        speed = round(dist_km / (dur_min / 60.0), 1) if dur_min > 0 else 60.0

        new_entry = {
            "corridor": summary or f"Route {from_ll[0]:.2f},{from_ll[1]:.2f} to {to_ll[0]:.2f},{to_ll[1]:.2f}",
            "summary": summary or route.get("summary") or "Saved Route",
            "distance_km": dist_km,
            "duration_min": dur_min,
            "speed_kmh": speed,
            "from_ll": [from_ll[0], from_ll[1]],
            "to_ll": [to_ll[0], to_ll[1]],
            "waypoints": wps,
            "roads": [],
        }
        entries.append(new_entry)
        if len(entries) > 100:
            entries.pop(0)

        try:
            with open(cached_file, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            pass


def _find_nearest_index(waypoints: list[list[float]], lat: float, lng: float) -> tuple[int, float]:
    """Find the index and distance in km of the nearest point in a waypoint list."""
    best_i = 0
    best_d = 999999.0
    for i, pt in enumerate(waypoints):
        d = haversine_km(lat, lng, pt[0], pt[1])
        if d < best_d:
            best_d = d
            best_i = i
    return best_i, best_d


def _build_route_result(
    waypoints: list[list[float]],
    summary: str,
    profile: str,
    road_routed: bool,
    avg_speed_kmh: float = 95.0,
) -> dict[str, Any]:
    """Construct standard GeoX route dictionary from waypoints and speed."""
    # Calculate distance along waypoints
    total_km = 0.0
    seg_seconds: list[float] = []

    for k in range(len(waypoints) - 1):
        d_km = haversine_km(waypoints[k][0], waypoints[k][1], waypoints[k + 1][0], waypoints[k + 1][1])
        total_km += d_km
        # Connectors (< 500m) at 45 km/h, highways at avg_speed_kmh
        seg_speed = 45.0 if k == 0 or k == len(waypoints) - 2 else avg_speed_kmh
        dur_s = max(0.5, (d_km / (seg_speed / 3600.0)))
        seg_seconds.append(round(dur_s, 2))

    total_duration_min = max(1, round(sum(seg_seconds) / 60.0))
    overall_speed = round(total_km / (total_duration_min / 60.0), 1) if total_duration_min > 0 else avg_speed_kmh

    primary = {
        "id": 0,
        "summary": summary,
        "waypoints": waypoints,
        "seg_seconds": seg_seconds,
        "distance_km": round(total_km, 2),
        "duration_min": total_duration_min,
        "speed_kmh": overall_speed,
        "profile": profile,
        "is_fastest": True,
        "offline": True,
        "road_routed": road_routed,
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
        "road_routed": road_routed,
    }


def find_offline_road_route(
    from_ll: tuple[float, float],
    to_ll: tuple[float, float],
    profile: str = "car",
) -> dict[str, Any]:
    """Find a route using offline highway corridors and road packs."""
    corridors = load_corridors()
    direct_dist_km = haversine_km(from_ll[0], from_ll[1], to_ll[0], to_ll[1])

    # 1. Look for a single matching corridor
    best_single = None
    min_combined = 999999.0

    for r in corridors:
        wps = r["waypoints"]
        i_from, d_from = _find_nearest_index(wps, from_ll[0], from_ll[1])
        i_to, d_to = _find_nearest_index(wps, to_ll[0], to_ll[1])

        # Highway access tolerance (within 45 km of highway)
        max_access = min(50.0, max(15.0, direct_dist_km * 0.45))
        if d_from < max_access and d_to < max_access and abs(i_from - i_to) >= 2:
            combined = d_from + d_to
            if combined < min_combined:
                min_combined = combined
                best_single = (r, i_from, i_to)

    if best_single:
        r, i_from, i_to = best_single
        wps = r["waypoints"]
        if i_from <= i_to:
            sub = [list(pt) for pt in wps[i_from : i_to + 1]]
        else:
            sub = [list(pt) for pt in reversed(wps[i_to : i_from + 1])]

        full_wps = [[round(from_ll[0], 6), round(from_ll[1], 6)]] + sub + [[round(to_ll[0], 6), round(to_ll[1], 6)]]
        road_names = r.get("roads", [])
        via_label = f"via {', '.join(road_names[:2])} (Offline Road Graph)" if road_names else f"via {r.get('summary', 'Highway Corridor')} (Offline Road Graph)"
        speed = r.get("speed_kmh", 95.0)
        return _build_route_result(full_wps, via_label, profile, road_routed=True, avg_speed_kmh=speed)

    # 2. Look for two intersecting corridors (e.g. Quebec -> Montreal -> Toronto)
    if direct_dist_km > 50.0 and len(corridors) >= 2:
        from_matches = []
        to_matches = []
        for idx, r in enumerate(corridors):
            wps = r["waypoints"]
            i_f, d_f = _find_nearest_index(wps, from_ll[0], from_ll[1])
            if d_f < 45.0:
                from_matches.append((idx, r, i_f))
            i_t, d_t = _find_nearest_index(wps, to_ll[0], to_ll[1])
            if d_t < 45.0:
                to_matches.append((idx, r, i_t))

        for idx1, r1, i1 in from_matches:
            wps1 = r1["waypoints"]
            for idx2, r2, i2 in to_matches:
                if idx1 == idx2:
                    continue
                wps2 = r2["waypoints"]
                # Search for an intersection point between r1 and r2
                step_sample = max(1, len(wps1) // 40)
                for p_idx in range(0, len(wps1), step_sample):
                    p1 = wps1[p_idx]
                    j_idx, d_j = _find_nearest_index(wps2, p1[0], p1[1])
                    if d_j < 6.0:  # Junction within 6 km
                        # Build segment 1
                        s1 = wps1[i1 : p_idx + 1] if i1 <= p_idx else list(reversed(wps1[p_idx : i1 + 1]))
                        # Build segment 2
                        s2 = wps2[j_idx : i2 + 1] if j_idx <= i2 else list(reversed(wps2[i2 : j_idx + 1]))
                        joined = (
                            [[round(from_ll[0], 6), round(from_ll[1], 6)]]
                            + [list(p) for p in s1]
                            + [list(p) for p in s2]
                            + [[round(to_ll[0], 6), round(to_ll[1], 6)]]
                        )
                        via_roads = list(dict.fromkeys(r1.get("roads", [])[:2] + r2.get("roads", [])[:2]))
                        via_label = f"via {', '.join(via_roads[:2])} (Offline Road Graph)" if via_roads else f"via {r1.get('corridor')} / {r2.get('corridor')} (Offline)"
                        return _build_route_result(joined, via_label, profile, road_routed=True, avg_speed_kmh=90.0)

    # 3. Direct beeline fallback when no road graph covers the origin/destination
    dist_m = direct_dist_km * 1000.0
    speeds = {"car": 50.0, "bike": 15.0, "walk": 4.5, "transit": 22.0}
    speed_kmh = speeds.get(profile, 50.0)
    n_points = max(5, min(80, int(dist_m / 350.0)))
    waypoints = []
    for i in range(n_points):
        frac = i / (n_points - 1)
        lat = from_ll[0] + (to_ll[0] - from_ll[0]) * frac
        lng = from_ll[1] + (to_ll[1] - from_ll[1]) * frac
        waypoints.append([round(lat, 6), round(lng, 6)])

    return _build_route_result(
        waypoints,
        f"Offline direct route ({profile}) · No road pack",
        profile,
        road_routed=False,
        avg_speed_kmh=speed_kmh,
    )
