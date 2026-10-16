"""Position interpolation along an OSRM route geometry."""
import bisect
import math


def _haversine_m(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class RoutePath:
    """A polyline of (lat, lng) points walked at a constant speed."""

    def __init__(self, coords, duration_s):
        if len(coords) < 2:
            coords = [coords[0], coords[0]] if coords else [(0.0, 0.0), (0.0, 0.0)]
        self.coords = coords
        self.cum = [0.0]
        for a, b in zip(coords, coords[1:]):
            self.cum.append(self.cum[-1] + _haversine_m(a, b))
        self.length_m = self.cum[-1]
        self.speed_mps = self.length_m / duration_s if duration_s > 0 else 8.0
        self.travelled_m = 0.0

    @property
    def done(self):
        return self.travelled_m >= self.length_m

    @property
    def remaining_s(self):
        if self.speed_mps <= 0:
            return 0.0
        return max(0.0, self.length_m - self.travelled_m) / self.speed_mps

    def advance(self, seconds):
        self.travelled_m = min(self.length_m, self.travelled_m + self.speed_mps * seconds)
        return self.position()

    def position(self):
        d = self.travelled_m
        if d <= 0:
            return self.coords[0]
        if d >= self.length_m:
            return self.coords[-1]
        i = bisect.bisect_right(self.cum, d) - 1
        seg = self.cum[i + 1] - self.cum[i]
        t = 0.0 if seg == 0 else (d - self.cum[i]) / seg
        (lat1, lng1), (lat2, lng2) = self.coords[i], self.coords[i + 1]
        return (lat1 + (lat2 - lat1) * t, lng1 + (lng2 - lng1) * t)
