"""Automated test suite for Geox core engine, server API, and motion models."""

import os
import sys
import time
import unittest
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from geox.engine import Engine
from geox.motion import Fixed, Jitter, Route, TimedRoute, build_motion
from geox.router import parse_trip_input
import geox.server as server_module


class TestMotionModels(unittest.TestCase):
    def test_fixed(self):
        f = Fixed(40.7128, -74.0060)
        p1 = f.step(0.0)
        p2 = f.step(10.0)
        self.assertEqual(p1, (40.7128, -74.0060))
        self.assertEqual(p2, (40.7128, -74.0060))

    def test_jitter(self):
        j = Jitter(40.7128, -74.0060, radius_m=50, speed_kmh=5.0)
        p0 = (j.lat, j.lng)
        p1 = j.step(5.0)
        self.assertIsInstance(p1[0], float)
        self.assertIsInstance(p1[1], float)

    def test_route(self):
        wps = [[40.0, -74.0], [40.1, -74.0], [40.2, -74.0]]
        r = Route(wps, speed_kmh=60.0, loop=False)
        self.assertEqual(len(r.wps), 3)
        self.assertEqual(r.progress, 0.0)
        p0 = r.step(0.0)
        self.assertAlmostEqual(p0[0], 40.0, places=3)
        # Advance 1 hour
        p_end = r.step(3600.0)
        self.assertAlmostEqual(p_end[0], 40.2, places=3)
        self.assertEqual(r.progress, 100.0)
        self.assertTrue(r.completed)

    def test_timed_route(self):
        wps = [[40.0, -74.0], [40.05, -74.0], [40.1, -74.0]]
        seg_seconds = [60.0, 120.0]
        tr = TimedRoute(wps, seg_seconds, speed_factor=1.0)
        self.assertEqual(tr.total_t, 180.0)
        self.assertEqual(tr.progress, 0.0)
        self.assertEqual(tr.remaining_s, 180)
        p_start = tr.step(0.0)
        self.assertAlmostEqual(p_start[0], 40.0, places=3)
        # Halfway through first segment (30s out of 180s = 16.7%)
        p_mid = tr.step(30.0)
        self.assertTrue(40.0 < p_mid[0] < 40.05)
        self.assertAlmostEqual(tr.progress, 16.7, places=1)
        self.assertEqual(tr.remaining_s, 150)
        self.assertFalse(tr.completed)
        # End of route
        p_done = tr.step(200.0)
        self.assertAlmostEqual(p_done[0], 40.1, places=3)
        self.assertEqual(tr.progress, 100.0)
        self.assertEqual(tr.remaining_s, 0)
        self.assertTrue(tr.completed)


class TestRouter(unittest.TestCase):
    def test_parse_trip_input(self):
        payload = {
            "from": {"lat": 40.7128, "lng": -74.0060},
            "to": {"lat": 40.7829, "lng": -73.9654},
            "profile": "car",
        }
        origin, dest, label, profile = parse_trip_input(payload)
        self.assertEqual(origin["lat"], 40.7128)
        self.assertEqual(dest["lat"], 40.7829)
        self.assertEqual(profile, "car")


class TestServerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server_module.app.config["TESTING"] = True
        cls.client = server_module.app.test_client()

    def test_status_endpoint(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("devices", data)
        self.assertIn("capabilities", data)
        self.assertIn("sessions", data)
        self.assertIn("logs", data)

    def test_geocode_cache(self):
        # Seed cache
        now = time.time()
        server_module._GEOCODE_CACHE["test query"] = (
            now,
            [{"label": "Test City", "lat": 12.34, "lng": 56.78}],
        )
        res = self.client.post("/api/geocode", json={"q": "Test Query"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["label"], "Test City")

    def test_reverse_cache(self):
        # Seed cache
        now = time.time()
        server_module._REVERSE_CACHE["40.7128,-74.006"] = (now, "New York, NY")
        res = self.client.get("/api/reverse?lat=40.7128&lng=-74.0060")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["label"], "New York, NY")

    def test_validation_errors(self):
        # /api/start without device_id
        res = self.client.post("/api/start", json={})
        self.assertEqual(res.status_code, 400)
        # /api/swap without device_id
        res = self.client.post("/api/swap", json={})
        self.assertEqual(res.status_code, 400)


class TestGpxGeneration(unittest.TestCase):
    def test_dynamic_duration(self):
        import xml.etree.ElementTree as ET
        from geox.ios_backend import IosCliSession

        engine = Engine()
        device = {"id": "dummy-iphone-test", "name": "iPhone Test"}
        cfg = {
            "mode": "fixed",
            "lat": 40.7128,
            "lng": -74.0060,
            "playback_hours": 0.5,  # 30 minutes = 1800 seconds
        }
        session = IosCliSession(engine, device, cfg)
        gpx_file = ROOT / "var" / "test_output.gpx"
        try:
            session._write_gpx(gpx_file)
            self.assertTrue(gpx_file.exists())
            tree = ET.parse(gpx_file)
            root = tree.getroot()
            ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
            points = root.findall(".//gpx:trkpt", ns)
            self.assertEqual(len(points), 1800)
        finally:
            if gpx_file.exists():
                gpx_file.unlink()


class TestOfflineCapabilities(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server_module.app.config["TESTING"] = True
        cls.client = server_module.app.test_client()

    def test_offline_places_search(self):
        from geox.offline import search_offline_places
        results = search_offline_places("tokyo")
        self.assertTrue(len(results) > 0)
        self.assertIn("Tokyo", results[0]["label"])

        vanc = search_offline_places("Vancouver")
        self.assertTrue(len(vanc) > 0)
        self.assertAlmostEqual(vanc[0]["lat"], 49.2827, places=2)

    def test_offline_direct_routing(self):
        from geox.router import _offline_plan_route
        route = _offline_plan_route((40.7128, -74.0060), (40.7829, -73.9654), "car")
        self.assertTrue(route.get("offline"))
        self.assertTrue(len(route["waypoints"]) >= 5)
        self.assertEqual(len(route["seg_seconds"]), len(route["waypoints"]) - 1)
        self.assertTrue(route["distance_km"] > 0)
        self.assertTrue(route["duration_min"] > 0)

    def test_offline_status_api(self):
        res = self.client.get("/api/offline/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("downloading", data)
        self.assertIn("tile_count", data)
        self.assertIn("size_formatted", data)
        self.assertIn("disk_free_gb", data)
        self.assertTrue(data.get("disk_free_gb", 0) > 0)

        res2 = self.client.post("/api/offline/status")
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.get_json().get("disk_free_gb", 0) > 0)

    def test_offline_estimate_api(self):
        res = self.client.get("/api/offline/estimate?region_type=world&weight=moderate")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("tile_count"), 5461)
        self.assertIn("size_formatted", data)
        self.assertIn("has_space", data)

        res_post = self.client.post("/api/offline/estimate", json={"region_type": "world", "weight": "full"})
        self.assertEqual(res_post.status_code, 200)
        data_post = res_post.get_json()
        self.assertEqual(data_post.get("tile_count"), 87381)

        res2 = self.client.get("/api/offline/estimate?region_type=country&weight=heavy&country=France")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2.get("tile_count") > 0)
        self.assertIn("size_formatted", data2)

        # Test bounds normalization with reversed min/max
        res_bounds = self.client.post(
            "/api/offline/estimate",
            json={"region_type": "viewport", "weight": "moderate", "bounds": [50.0, 10.0, 40.0, -5.0]},
        )
        self.assertEqual(res_bounds.status_code, 200)
        self.assertTrue(res_bounds.get_json().get("tile_count") > 0)

    def test_offline_regions_api(self):
        res = self.client.get("/api/offline/regions?q=United")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        names = [x["name"] for x in data.get("results", [])]
        self.assertIn("United States", names)
        self.assertIn("United Kingdom", names)

        res_post = self.client.post("/api/offline/regions", json={"q": "France"})
        self.assertEqual(res_post.status_code, 200)
        names_post = [x["name"] for x in res_post.get_json().get("results", [])]
        self.assertIn("France", names_post)

    def test_offline_clear_api(self):
        res1 = self.client.post("/api/offline/clear")
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.get_json().get("ok"))

        res2 = self.client.get("/api/offline/clear")
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.get_json().get("ok"))

    def test_offline_cancel_api(self):
        res1 = self.client.post("/api/offline/cancel")
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.get_json().get("ok"))

        res2 = self.client.get("/api/offline/cancel")
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.get_json().get("ok"))


if __name__ == "__main__":
    unittest.main()
