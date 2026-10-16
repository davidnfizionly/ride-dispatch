"""Minimal OSRM HTTP client (standard library only, keeps the Lambda package small)."""
import json
import urllib.request


class OsrmClient:
    def __init__(self, base_url, timeout_s=2.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    def route(self, from_latlng, to_latlng, geometry=False):
        """Returns {distance_m, duration_s[, coordinates]} for the driving route."""
        (lat1, lng1), (lat2, lng2) = from_latlng, to_latlng
        overview = "full&geometries=geojson" if geometry else "false"
        url = (f"{self._base}/route/v1/driving/"
               f"{lng1:.6f},{lat1:.6f};{lng2:.6f},{lat2:.6f}?overview={overview}")
        with urllib.request.urlopen(url, timeout=self._timeout) as resp:
            body = json.load(resp)
        if body.get("code") != "Ok" or not body.get("routes"):
            raise RuntimeError(f"OSRM route failed: {body.get('code')}")
        r = body["routes"][0]
        out = {"distance_m": r["distance"], "duration_s": r["duration"]}
        if geometry:
            # OSRM returns [lng, lat]; callers work in (lat, lng).
            out["coordinates"] = [(c[1], c[0]) for c in r["geometry"]["coordinates"]]
        return out
