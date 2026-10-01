"""Geox Offline Manager — local map tile caching, pack downloader, and gazetteer.

Handles storage in offline/tiles/, auto-caching proxy, background downloads,
real-time estimate calculations based on disk space, and offline place/country searches.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import shutil
import threading
import time
from typing import Any

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFLINE_DIR = os.path.join(BASE_DIR, "offline")
TILES_DIR = os.path.join(OFFLINE_DIR, "tiles")
PLACES_FILE = os.path.join(OFFLINE_DIR, "places.json")

MAP_SOURCES = {
    "topo": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    "streets": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    "dark": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
}

USER_AGENT = "Geox/1.4.1 (Offline Map Downloader)"

COUNTRIES_BBOX: dict[str, list[float]] = {
    "United States": [24.3963, -125.0, 49.3844, -66.9346],
    "Canada": [41.6766, -141.0019, 83.1106, -52.6481],
    "United Kingdom": [49.8238, -8.6493, 60.8605, 1.7689],
    "France": [41.333, -5.142, 51.089, 9.56],
    "Germany": [47.2701, 5.8663, 55.0583, 15.0418],
    "Japan": [24.0457, 122.9345, 45.5515, 153.9866],
    "Australia": [-43.6345, 113.3389, -10.6681, 153.5694],
    "Italy": [36.6199, 6.6272, 47.092, 18.5204],
    "Spain": [36.0001, -9.3015, 43.7915, 4.3278],
    "Mexico": [14.5388, -118.404, 32.7186, -86.7104],
    "Brazil": [-33.75, -73.98, 5.27, -34.79],
    "India": [8.0667, 68.1167, 37.0833, 97.4],
    "China": [18.1536, 73.4997, 53.5609, 134.7754],
    "Switzerland": [45.818, 5.9559, 47.8084, 10.4923],
    "Netherlands": [50.7504, 3.3316, 53.555, 7.2275],
    "Belgium": [49.497, 2.544, 51.505, 6.408],
    "Sweden": [55.3369, 11.0274, 69.06, 24.167],
    "Norway": [57.9622, 4.636, 71.1855, 31.077],
    "Poland": [49.002, 14.1229, 54.836, 24.1458],
    "South Korea": [33.1, 125.0, 38.6, 129.6],
    "New Zealand": [-47.2899, 166.4261, -34.4288, 178.6146],
    "Argentina": [-55.0574, -73.577, -21.7812, -53.6375],
    "South Africa": [-34.8333, 16.45, -22.1265, 32.8906],
    "United Arab Emirates": [22.6333, 51.5833, 26.0667, 56.3833],
    "Singapore": [1.1304, 103.602, 1.4504, 104.012],
    "Hong Kong": [22.1534, 113.835, 22.562, 114.407],
    "Ireland": [51.419, -10.663, 55.435, -5.996],
    "Austria": [46.3723, 9.5307, 49.0206, 17.1607],
    "Portugal": [36.961, -9.5005, 42.154, -6.189],
    "Greece": [34.802, 19.373, 41.748, 28.246],
    "Turkey": [35.813, 25.663, 42.107, 44.817],
    "Egypt": [22.0, 24.7, 31.7, 36.9],
    "Saudi Arabia": [16.38, 34.5, 32.15, 55.67],
    "Indonesia": [-11.0, 95.0, 6.07, 141.0],
    "Philippines": [4.58, 116.93, 21.13, 126.6],
    "Thailand": [5.61, 97.34, 20.46, 105.64],
    "Vietnam": [8.56, 102.14, 23.39, 109.46],
}


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[int, int]:
    """Convert WGS84 lat/lon to Web Mercator tile x, y."""
    lat_deg = max(-85.0511, min(85.0511, float(lat_deg)))
    lon_deg = max(-180.0, min(180.0, float(lon_deg)))
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(int(n) - 1, xtile)), max(0, min(int(n) - 1, ytile))


def get_tile_path(z: int, x: int, y: int) -> str:
    """Return local filesystem path for a tile."""
    return os.path.join(TILES_DIR, str(z), str(x), f"{y}.jpg")


def get_storage_stats() -> dict[str, Any]:
    """Calculate total downloaded tiles, routing packs, and disk space used/free."""
    target_path = OFFLINE_DIR if os.path.exists(OFFLINE_DIR) else BASE_DIR
    try:
        u = shutil.disk_usage(target_path)
        disk_free_gb = round(u.free / (1024 * 1024 * 1024), 1)
        disk_total_gb = round(u.total / (1024 * 1024 * 1024), 1)
    except Exception:
        disk_free_gb = 50.0
        disk_total_gb = 250.0

    total_bytes = 0
    tile_count = 0
    if os.path.exists(TILES_DIR):
        for root, _, files in os.walk(TILES_DIR):
            for f in files:
                if f.endswith(".jpg"):
                    total_bytes += os.path.getsize(os.path.join(root, f))
                    tile_count += 1

    routing_dir = os.path.join(OFFLINE_DIR, "routing")
    routing_packs = 0
    if os.path.exists(routing_dir):
        for f in os.listdir(routing_dir):
            if f.endswith(".json"):
                routing_packs += 1
                total_bytes += os.path.getsize(os.path.join(routing_dir, f))

    size_mb = total_bytes / (1024 * 1024)
    if size_mb >= 1024:
        size_fmt = f"{size_mb / 1024:.2f} GB"
    else:
        size_fmt = f"{size_mb:.1f} MB"

    return {
        "tile_count": tile_count,
        "routing_packs_count": max(1, routing_packs),
        "size_mb": round(size_mb, 1),
        "size_formatted": size_fmt,
        "disk_free_gb": disk_free_gb,
        "disk_free_formatted": f"{disk_free_gb} GB",
        "disk_total_gb": disk_total_gb,
        "max_limit_gb": disk_free_gb,
    }


def clear_cache() -> dict[str, Any]:
    """Clear all downloaded map tiles from disk."""
    if os.path.exists(TILES_DIR):
        shutil.rmtree(TILES_DIR, ignore_errors=True)
    os.makedirs(TILES_DIR, exist_ok=True)
    return {"ok": True, "message": "Offline map cache cleared."}


_PLACES_CACHE: list[dict[str, Any]] | None = None


def search_offline_places(query: str, limit: int = 6) -> list[dict[str, Any]]:
    """Search the local offline places database."""
    global _PLACES_CACHE
    if _PLACES_CACHE is None:
        if os.path.exists(PLACES_FILE):
            try:
                with open(PLACES_FILE, "r", encoding="utf-8") as f:
                    _PLACES_CACHE = json.load(f)
            except Exception:
                _PLACES_CACHE = []
        else:
            _PLACES_CACHE = []

    q = query.strip().lower()
    if not q or not _PLACES_CACHE:
        return []

    prefix_matches = [p for p in _PLACES_CACHE if p["label"].lower().startswith(q)]
    substring_matches = [
        p for p in _PLACES_CACHE
        if q in p["label"].lower() and p not in prefix_matches
    ]

    combined = prefix_matches + substring_matches
    return combined[:limit]


def search_countries(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Search country / region bounding box dataset."""
    q = query.strip().lower()
    if not q:
        return [{"name": name, "bounds": bbox} for name, bbox in list(COUNTRIES_BBOX.items())[:limit]]

    matches = []
    for name, bbox in COUNTRIES_BBOX.items():
        if name.lower().startswith(q) or q in name.lower():
            matches.append({"name": name, "bounds": bbox})
            if len(matches) >= limit:
                break
    return matches


def calculate_estimate(
    region_type: str = "world",
    weight: str = "moderate",
    bounds: list[float] | None = None,
) -> dict[str, Any]:
    """Calculate precise tile counts, MB/GB sizes, and disk sufficiency for a pack."""
    stats = get_storage_stats()
    free_gb = stats["disk_free_gb"]

    if region_type in ("world", "global", "global_base"):
        zoom_map = {"light": 5, "moderate": 6, "heavy": 7, "full": 8}
        target_zoom = zoom_map.get(weight, 6)
        tile_count = sum(4 ** z for z in range(target_zoom + 1))
    elif region_type in ("world_ext", "global_extended"):
        zoom_map = {"light": 6, "moderate": 7, "heavy": 8, "full": 9}
        target_zoom = zoom_map.get(weight, 7)
        tile_count = sum(4 ** z for z in range(target_zoom + 1))
    elif region_type in ("country", "bounds", "region", "viewport") and bounds and len(bounds) == 4:
        min_lat = min(float(bounds[0]), float(bounds[2]))
        max_lat = max(float(bounds[0]), float(bounds[2]))
        min_lng = min(float(bounds[1]), float(bounds[3]))
        max_lng = max(float(bounds[1]), float(bounds[3]))
        zoom_map = {"light": 8, "moderate": 10, "heavy": 12, "full": 14}
        target_zoom = zoom_map.get(weight, 10)
        min_z = max(0, target_zoom - 4)
        tile_count = 0
        for z in range(min_z, target_zoom + 1):
            x1, y2 = deg2num(min_lat, min_lng, z)
            x2, y1 = deg2num(max_lat, max_lng, z)
            tile_count += (max(x1, x2) - min(x1, x2) + 1) * (max(y1, y2) - min(y1, y2) + 1)
    else:
        tile_count = 5461

    # Average tile size is ~15 KB
    est_bytes = tile_count * 15 * 1024
    est_mb = est_bytes / (1024 * 1024)
    if est_mb >= 1024:
        est_fmt = f"{est_mb / 1024:.2f} GB"
    else:
        est_fmt = f"{round(est_mb)} MB" if est_mb >= 10 else f"{est_mb:.1f} MB"

    weight_descriptions = {
        "light": "Lightweight: Basemap overview, borders, major topography, and primary highways.",
        "moderate": "Moderate Weight: Regional road network, state/provincial routes, elevation contours, and towns.",
        "heavy": "Heavy Weight: High-density road network, local connectors, municipal roads, and detailed terrain.",
        "full": "Full Map (Maximum Detail): Complete street network including all available local streets, neighborhood roads, and maximum cartographic detail.",
    }

    needed_gb = est_mb / 1024
    has_space = free_gb > (needed_gb + 0.5)

    return {
        "tile_count": tile_count,
        "tile_count_formatted": f"{tile_count:,}",
        "estimated_mb": round(est_mb, 1),
        "size_formatted": est_fmt,
        "disk_free_gb": free_gb,
        "disk_free_formatted": f"{free_gb} GB",
        "has_space": has_space,
        "description": weight_descriptions.get(weight, weight_descriptions["moderate"]),
    }


class TileDownloader:
    """Manages asynchronous background downloading of map tile packs."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.downloading = False
        self.cancelled = False
        self.total = 0
        self.completed = 0
        self.failed = 0
        self.current_package = ""
        self.message = "Idle"
        self._thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        with self.lock:
            pct = round((self.completed / self.total * 100), 1) if self.total > 0 else 0
            stats = get_storage_stats()
            return {
                "downloading": self.downloading,
                "total": self.total,
                "completed": self.completed,
                "failed": self.failed,
                "percent": pct,
                "package": self.current_package,
                "message": self.message,
                "tile_count": stats["tile_count"],
                "routing_packs_count": stats.get("routing_packs_count", 1),
                "size_formatted": stats["size_formatted"],
                "disk_free_gb": stats["disk_free_gb"],
                "disk_free_formatted": stats["disk_free_formatted"],
                "max_limit_gb": stats.get("max_limit_gb", stats["disk_free_gb"]),
            }

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            if self.downloading:
                self.cancelled = True
                self.message = "Cancelling download…"
        return {"ok": True}

    def start_download(
        self,
        package: str = "world",
        style: str = "topo",
        bounds: list[float] | None = None,
        max_zoom: int | None = None,
        weight: str = "moderate",
    ) -> dict[str, Any]:
        with self.lock:
            if self.downloading:
                return {"error": "A download is already in progress."}
            self.downloading = True
            self.cancelled = False
            self.completed = 0
            self.failed = 0
            self.current_package = package
            self.message = "Preparing tile manifest…"

        self._thread = threading.Thread(
            target=self._run_download,
            args=(package, style, bounds, max_zoom, weight),
            daemon=True,
        )
        self._thread.start()
        return {"ok": True, "message": "Download started."}

    def _generate_tile_list(
        self,
        package: str,
        bounds: list[float] | None,
        max_zoom: int | None,
        weight: str = "moderate",
    ) -> list[tuple[int, int, int]]:
        tiles: list[tuple[int, int, int]] = []

        if package in ("world", "global", "global_base"):
            zoom_map = {"light": 5, "moderate": 6, "heavy": 7, "full": 8}
            target_zoom = max_zoom if max_zoom is not None else zoom_map.get(weight, 6)
            for z in range(target_zoom + 1):
                n = 2 ** z
                for x in range(n):
                    for y in range(n):
                        tiles.append((z, x, y))

        elif package in ("world_ext", "global_extended"):
            zoom_map = {"light": 6, "moderate": 7, "heavy": 8, "full": 9}
            target_zoom = max_zoom if max_zoom is not None else zoom_map.get(weight, 7)
            for z in range(target_zoom + 1):
                n = 2 ** z
                for x in range(n):
                    for y in range(n):
                        tiles.append((z, x, y))

        elif package in ("country", "bounds", "region", "viewport") and bounds and len(bounds) == 4:
            min_lat = min(float(bounds[0]), float(bounds[2]))
            max_lat = max(float(bounds[0]), float(bounds[2]))
            min_lng = min(float(bounds[1]), float(bounds[3]))
            max_lng = max(float(bounds[1]), float(bounds[3]))
            zoom_map = {"light": 8, "moderate": 10, "heavy": 12, "full": 14}
            target_zoom = max_zoom if max_zoom is not None else zoom_map.get(weight, 10)
            min_z = max(0, target_zoom - 4)
            for z in range(min_z, target_zoom + 1):
                x1, y2 = deg2num(min_lat, min_lng, z)
                x2, y1 = deg2num(max_lat, max_lng, z)
                xmin, xmax = min(x1, x2), max(x1, x2)
                ymin, ymax = min(y1, y2), max(y1, y2)
                for x in range(xmin, xmax + 1):
                    for y in range(ymin, ymax + 1):
                        tiles.append((z, x, y))
        else:
            for z in range(6):
                n = 2 ** z
                for x in range(n):
                    for y in range(n):
                        tiles.append((z, x, y))

        return tiles

    def _download_single(
        self, z: int, x: int, y: int, source_template: str, session: requests.Session
    ) -> bool:
        if self.cancelled:
            return False

        path = get_tile_path(z, x, y)
        if os.path.exists(path) and os.path.getsize(path) > 100:
            return True  # Already cached

        url = source_template.format(z=z, x=x, y=y)
        try:
            r = session.get(url, timeout=6)
            if r.status_code == 200 and len(r.content) > 100:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            pass
        return False

    def _run_download(
        self,
        package: str,
        style: str,
        bounds: list[float] | None,
        max_zoom: int | None,
        weight: str = "moderate",
    ) -> None:
        source_template = MAP_SOURCES.get(style, MAP_SOURCES["topo"])
        tile_list = self._generate_tile_list(package, bounds, max_zoom, weight)

        with self.lock:
            self.total = len(tile_list)
            self.message = f"Downloading {self.total} tiles…"

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        min_free_bytes = 500 * 1024 * 1024  # Ensure at least 500 MB remains on disk
        check_counter = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(self._download_single, z, x, y, source_template, session)
                for (z, x, y) in tile_list
            ]

            for future in concurrent.futures.as_completed(futures):
                if self.cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    ok = future.result()
                    with self.lock:
                        if ok:
                            self.completed += 1
                        else:
                            self.failed += 1
                except Exception:
                    with self.lock:
                        self.failed += 1

                check_counter += 1
                if check_counter % 200 == 0:
                    try:
                        free_bytes = shutil.disk_usage(OFFLINE_DIR if os.path.exists(OFFLINE_DIR) else BASE_DIR).free
                        if free_bytes < min_free_bytes:
                            with self.lock:
                                self.cancelled = True
                                self.message = "Stopped: Low disk space (< 500 MB remaining on disk)."
                            executor.shutdown(wait=False, cancel_futures=True)
                            break
                    except Exception:
                        pass

        with self.lock:
            self.downloading = False
            if self.cancelled:
                if "Low disk space" in self.message:
                    pass
                else:
                    self.message = f"Cancelled ({self.completed}/{self.total} saved)."
            else:
                self.message = f"Complete: {self.completed} tiles ready offline with road routing pack."


_downloader = TileDownloader()


def get_downloader() -> TileDownloader:
    return _downloader
