"""Movement models shared by both backends.

Every model exposes ``step(dt) -> (lat, lng)`` where ``dt`` is the seconds
since the previous call. Coordinates are WGS-84 decimal degrees.
"""

import math
import random

EARTH_R = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def destination(lat, lon, brg, dist_m):
    d = dist_m / EARTH_R
    b = math.radians(brg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2)
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


class Fixed:
    """Stay parked on one point."""

    def __init__(self, lat, lng):
        self.lat, self.lng = float(lat), float(lng)

    def step(self, dt):
        return self.lat, self.lng


class Jitter:
    """Walk between random points inside a radius around the centre.

    Makes the device look alive instead of a frozen pin, which is what
    movement-aware consumers (Snap Map, location histories) expect.
    """

    def __init__(self, lat, lng, radius_m=120.0, speed_kmh=4.5):
        self.clat, self.clng = float(lat), float(lng)
        self.radius = max(15.0, float(radius_m))
        self.speed_mps = max(0.5, float(speed_kmh)) * 1000.0 / 3600.0
        self.lat, self.lng = self.clat, self.clng
        self.tlat, self.tlng = self._new_target()

    def _new_target(self):
        brg = random.uniform(0, 360)
        dist = self.radius * random.uniform(0.2, 1.0)
        return destination(self.clat, self.clng, brg, dist)

    def step(self, dt):
        d = haversine_m(self.lat, self.lng, self.tlat, self.tlng)
        if d < self.speed_mps * max(dt, 0.001) * 0.5:
            self.tlat, self.tlng = self._new_target()
            return self.lat, self.lng
        brg = bearing_deg(self.lat, self.lng, self.tlat, self.tlng)
        self.lat, self.lng = destination(
            self.lat, self.lng, brg, min(self.speed_mps * max(dt, 0.001), d)
        )
        return self.lat, self.lng


class Route:
    """Travel along a polyline of waypoints at a fixed speed.

    Loops back to the first waypoint (or ping-pongs when ``loop=False``).
    """

    def __init__(self, waypoints, speed_kmh=12.0, loop=True):
        self.wps = [(float(a), float(b)) for a, b in waypoints]
        if len(self.wps) < 2:
            raise ValueError("a route needs at least 2 waypoints")
        segs = []
        total = 0.0
        for (a, b), (c, d) in zip(self.wps, self.wps[1:]):
            n = haversine_m(a, b, c, d)
            segs.append((a, b, c, d, n))
            total += n
        if total <= 0:
            raise ValueError("route waypoints are all on the same spot")
        self.segs = segs
        self.total = total
        self.loop = loop
        self.dir = 1
        self.pos = 0.0
        self.speed_mps = max(0.5, float(speed_kmh)) * 1000.0 / 3600.0

    def _point_at(self, pos):
        acc = 0.0
        for a, b, c, d, n in self.segs:
            if pos <= acc + n or n == 0:
                t = 0.0 if n == 0 else min(1.0, max(0.0, (pos - acc) / n))
                return a + (c - a) * t, b + (d - b) * t
            acc += n
        return self.wps[-1]

    def step(self, dt):
        if self.loop:
            self.pos += self.speed_mps * max(dt, 0.001)
            if self.pos >= self.total:
                self.pos -= self.total
        else:
            # one-way trip: travel to the end, then stay parked there
            if self.pos < self.total:
                self.pos += self.speed_mps * max(dt, 0.001)
                self.pos = min(self.pos, self.total)
        return self._point_at(self.pos)

    @property
    def progress(self):
        return round((self.pos / self.total) * 100, 1) if self.total > 0 else 100.0

    @property
    def remaining_m(self):
        return max(0, int(round(self.total - self.pos)))

    @property
    def speed_kmh(self):
        return round(self.speed_mps * 3.6, 1)

    @property
    def completed(self):
        return (not self.loop) and (self.pos >= self.total)


class TimedRoute:
    """Travel a polyline where every segment has its own real travel time.

    This is what makes a trip behave like a real drive: segments that took
    the router 90 s (highway) are covered fast, segments that took 30 s
    (city street) slowly.  ``speed_factor`` scales the whole timeline.
    One-way only: after the total time the position stays parked at the end.
    """

    def __init__(self, waypoints, seg_seconds, speed_factor=1.0):
        self.wps = [(float(a), float(b)) for a, b in waypoints]
        if len(self.wps) < 2:
            raise ValueError("a route needs at least 2 waypoints")
        if len(seg_seconds) != len(self.wps) - 1:
            raise ValueError("seg_seconds must have one entry per segment")
        self.seg_t = [max(0.001, float(s)) / max(0.1, float(speed_factor))
                      for s in seg_seconds]
        # cumulative time at the start of each segment
        self.cum = [0.0]
        for t in self.seg_t:
            self.cum.append(self.cum[-1] + t)
        self.total_t = self.cum[-1]
        self.seg_d = [haversine_m(a, b, c, d)
                      for (a, b), (c, d) in zip(self.wps, self.wps[1:])]
        self.time = 0.0

    @property
    def progress(self):
        return round((self.time / self.total_t) * 100, 1) if self.total_t > 0 else 100.0

    @property
    def remaining_s(self):
        return max(0, int(round(self.total_t - self.time)))

    @property
    def speed_kmh(self):
        return round(self.speed_mps * 3.6, 1)

    @property
    def completed(self):
        return self.time >= self.total_t

    @property
    def speed_mps(self):
        i = min(self._edge_index(self.time), len(self.seg_d) - 1)
        return self.seg_d[i] / self.seg_t[i] if self.seg_t[i] > 0 else 0.0

    def _edge_index(self, t):
        lo, hi = 0, len(self.seg_t) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.cum[mid + 1] <= t:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def step(self, dt):
        self.time = min(self.time + max(dt, 0.0), self.total_t)
        i = self._edge_index(self.time)
        seg_t = self.seg_t[i]
        frac = 0.0 if seg_t <= 0 else min(1.0, (self.time - self.cum[i]) / seg_t)
        a, b = self.wps[i]
        c, d = self.wps[i + 1]
        return a + (c - a) * frac, b + (d - b) * frac


def build_motion(cfg):
    mode = cfg.get("mode", "fixed")
    if mode == "route" and cfg.get("seg_seconds"):
        return TimedRoute(
            cfg["waypoints"],
            cfg["seg_seconds"],
            speed_factor=cfg.get("speed_factor", 1.0),
        )
    if mode == "jitter":
        return Jitter(
            cfg["lat"], cfg["lng"],
            radius_m=cfg.get("radius_m", 120.0),
            speed_kmh=cfg.get("speed_kmh", 4.5),
        )
    if mode == "route":
        return Route(
            cfg["waypoints"],
            speed_kmh=cfg.get("speed_kmh", 12.0),
            loop=bool(cfg.get("loop", True)),
        )
    return Fixed(cfg["lat"], cfg["lng"])
