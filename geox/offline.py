"""Geox Offline Manager — local map tile caching, pack downloader, and gazetteer.

Handles storage in offline/tiles/, auto-caching proxy, background downloads,
and offline place searches.
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

USER_AGENT = "Geox/1.3.0 (Offline Map Downloader)"


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[int, int]:
    """Convert WGS84 lat/lon to Web Mercator tile x, y."""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(int(n) - 1, xtile)), max(0, min(int(n) - 1, ytile))


def get_tile_path(z: int, x: int, y: int) -> str:
    """Return local filesystem path for a tile."""
    return os.path.join(TILES_DIR, str(z), str(x), f"{y}.jpg")


def get_storage_stats() -> dict[str, Any]:
    """Calculate total downloaded tiles and disk space used."""
    if not os.path.exists(TILES_DIR):
        return {"tile_count": 0, "size_mb": 0.0, "size_formatted": "0 MB", "max_limit_gb": 25}

    total_bytes = 0
    tile_count = 0
    for root, _, files in os.walk(TILES_DIR):
        for f in files:
            if f.endswith(".jpg"):
                total_bytes += os.path.getsize(os.path.join(root, f))
                tile_count += 1

    size_mb = total_bytes / (1024 * 1024)
    if size_mb >= 1024:
        size_fmt = f"{size_mb / 1024:.2f} GB"
    else:
        size_fmt = f"{size_mb:.1f} MB"

    return {
        "tile_count": tile_count,
        "size_mb": round(size_mb, 1),
        "size_formatted": size_fmt,
        "max_limit_gb": 25,
    }


def clear_cache() -> dict[str, Any]:
    """Clear all downloaded map tiles from disk."""
    if os.path.exists(TILES_DIR):
        shutil.rmtree(TILES_DIR)
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

    # Priority 1: Label starts with query
    prefix_matches = [p for p in _PLACES_CACHE if p["label"].lower().startswith(q)]
    # Priority 2: Label contains query word boundary or substring
    substring_matches = [
        p for p in _PLACES_CACHE
        if q in p["label"].lower() and p not in prefix_matches
    ]

    combined = prefix_matches + substring_matches
    return combined[:limit]


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
                "size_formatted": stats["size_formatted"],
                "max_limit_gb": stats.get("max_limit_gb", 25),
            }

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            if self.downloading:
                self.cancelled = True
                self.message = "Cancelling download…"
        return {"ok": True}

    def start_download(
        self,
        package: str = "global",
        style: str = "topo",
        bounds: list[float] | None = None,
        max_zoom: int = 6,
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
            args=(package, style, bounds, max_zoom),
            daemon=True,
        )
        self._thread.start()
        return {"ok": True, "message": "Download started."}

    def _generate_tile_list(
        self, package: str, bounds: list[float] | None, max_zoom: int
    ) -> list[tuple[int, int, int]]:
        tiles: list[tuple[int, int, int]] = []

        if package in ("global", "global_base"):
            # Global overview tiles up to zoom 6 (5,461 tiles, ~60 MB)
            target_zoom = min(max_zoom, 6)
            for z in range(target_zoom + 1):
                n = 2 ** z
                for x in range(n):
                    for y in range(n):
                        tiles.append((z, x, y))

        elif package == "global_extended":
            # Global extended tiles up to zoom 7 (21,845 tiles, ~250 MB)
            target_zoom = min(max_zoom, 7)
            for z in range(target_zoom + 1):
                n = 2 ** z
                for x in range(n):
                    for y in range(n):
                        tiles.append((z, x, y))

        elif package in ("bounds", "region") and bounds and len(bounds) == 4:
            min_lat, min_lng, max_lat, max_lng = bounds
            min_z = max(0, max_zoom - 3)
            for z in range(min_z, max_zoom + 1):
                x1, y2 = deg2num(min_lat, min_lng, z)
                x2, y1 = deg2num(max_lat, max_lng, z)
                xmin, xmax = min(x1, x2), max(x1, x2)
                ymin, ymax = min(y1, y2), max(y1, y2)
                for x in range(xmin, xmax + 1):
                    for y in range(ymin, ymax + 1):
                        tiles.append((z, x, y))
        else:
            # Default world base (zoom 0 to 5)
            for z in range(5):
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
        self, package: str, style: str, bounds: list[float] | None, max_zoom: int
    ) -> None:
        source_template = MAP_SOURCES.get(style, MAP_SOURCES["topo"])
        tile_list = self._generate_tile_list(package, bounds, max_zoom)

        with self.lock:
            self.total = len(tile_list)
            self.message = f"Downloading {self.total} tiles…"

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        max_bytes = 25 * 1024 * 1024 * 1024  # 25 GB limit
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
                    stats = get_storage_stats()
                    if stats.get("size_mb", 0) * 1024 * 1024 >= max_bytes:
                        with self.lock:
                            self.cancelled = True
                            self.message = "Stopped: 25 GB offline storage limit reached."
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

        with self.lock:
            self.downloading = False
            if self.cancelled:
                if "limit reached" in self.message:
                    pass
                else:
                    self.message = f"Cancelled ({self.completed}/{self.total} saved)."
            else:
                self.message = f"Complete: {self.completed} tiles ready offline."


_downloader = TileDownloader()


def get_downloader() -> TileDownloader:
    return _downloader
