"""Driver positions, availability, zone supply and zone demand in Redis.

Keys:
  drivers:available       GEO set of available, unclaimed drivers
  driver:<id>             hash: lat, lng, status, zone, ts (ms)
  claim:<id>              ride id holding the driver; short TTL until the
                          simulator reports the driver as en_route
  zone:<h3>:available     set of available driver ids in a zone
  zone:<h3>:requests      sorted set of ride ids scored by request time (ms)
"""
import time

AVAILABLE = "drivers:available"
STATUS_AVAILABLE = "available"
STALE_AFTER_MS = 30_000
CLAIM_TTL_S = 30
DEMAND_WINDOW_MS = 10 * 60 * 1000


def _driver_key(driver_id):
    return f"driver:{driver_id}"


def _claim_key(driver_id):
    return f"claim:{driver_id}"


def _zone_available_key(zone):
    return f"zone:{zone}:available"


def _zone_requests_key(zone):
    return f"zone:{zone}:requests"


def _s(value):
    return value.decode() if isinstance(value, bytes) else value


class DriverIndex:
    def __init__(self, redis_client, zone_of, clock_ms=None):
        self._r = redis_client
        self._zone_of = zone_of
        self._now = clock_ms or (lambda: int(time.time() * 1000))

    def apply_positions(self, positions):
        """Applies a batch of position messages. Returns the number applied."""
        latest = {}
        for p in positions:
            cur = latest.get(p["driver_id"])
            if cur is None or p["ts"] >= cur["ts"]:
                latest[p["driver_id"]] = p
        if not latest:
            return 0

        ids = list(latest)
        read = self._r.pipeline(transaction=False)
        for driver_id in ids:
            read.hmget(_driver_key(driver_id), "zone", "ts")
            read.exists(_claim_key(driver_id))
        replies = read.execute()

        write = self._r.pipeline(transaction=False)
        applied = 0
        for i, driver_id in enumerate(ids):
            p = latest[driver_id]
            old_zone, old_ts = (_s(v) for v in replies[2 * i])
            claimed = bool(replies[2 * i + 1])
            if old_ts is not None and int(old_ts) > p["ts"]:
                continue  # out-of-order message
            zone = self._zone_of(p["lat"], p["lng"])
            write.hset(_driver_key(driver_id), mapping={
                "lat": p["lat"], "lng": p["lng"], "status": p["status"],
                "zone": zone, "ts": p["ts"],
            })
            if old_zone and old_zone != zone:
                write.srem(_zone_available_key(old_zone), driver_id)
            if p["status"] == STATUS_AVAILABLE and not claimed:
                write.geoadd(AVAILABLE, (p["lng"], p["lat"], driver_id))
                write.sadd(_zone_available_key(zone), driver_id)
            else:
                write.zrem(AVAILABLE, driver_id)
                write.srem(_zone_available_key(zone), driver_id)
            applied += 1
        write.execute()
        return applied

    def nearest_available(self, lat, lng, radius_m=6000, count=5):
        """Nearest fresh, unclaimed available drivers as (driver_id, distance_m)."""
        hits = self._r.geosearch(
            AVAILABLE, longitude=lng, latitude=lat, radius=radius_m, unit="m",
            sort="ASC", count=count * 2, withdist=True,
        )
        if not hits:
            return []
        ids = [_s(h[0]) for h in hits]
        pipe = self._r.pipeline(transaction=False)
        for driver_id in ids:
            pipe.hget(_driver_key(driver_id), "ts")
            pipe.exists(_claim_key(driver_id))
        replies = pipe.execute()
        cutoff = self._now() - STALE_AFTER_MS
        out = []
        for i, (driver_id, hit) in enumerate(zip(ids, hits)):
            ts, claimed = replies[2 * i], replies[2 * i + 1]
            if ts is not None and int(_s(ts)) >= cutoff and not claimed:
                out.append((driver_id, float(hit[1])))
            if len(out) == count:
                break
        return out

    def claim(self, driver_id, ride_id):
        """Atomically reserves a driver for a ride. True if this call won."""
        won = self._r.set(_claim_key(driver_id), ride_id, nx=True, ex=CLAIM_TTL_S)
        if won:
            pipe = self._r.pipeline(transaction=False)
            pipe.zrem(AVAILABLE, driver_id)
            zone = self._r.hget(_driver_key(driver_id), "zone")
            if zone:
                pipe.srem(_zone_available_key(_s(zone)), driver_id)
            pipe.execute()
        return bool(won)

    def position(self, driver_id):
        lat, lng = self._r.hmget(_driver_key(driver_id), "lat", "lng")
        if lat is None:
            return None
        return float(_s(lat)), float(_s(lng))

    def zone_supply(self, zone):
        """Fresh, unclaimed available drivers currently in the zone."""
        members = [_s(m) for m in self._r.smembers(_zone_available_key(zone))]
        if not members:
            return 0
        pipe = self._r.pipeline(transaction=False)
        for driver_id in members:
            pipe.hget(_driver_key(driver_id), "ts")
            pipe.exists(_claim_key(driver_id))
        replies = pipe.execute()
        cutoff = self._now() - STALE_AFTER_MS
        return sum(
            1 for i in range(len(members))
            if replies[2 * i] is not None
            and int(_s(replies[2 * i])) >= cutoff
            and not replies[2 * i + 1]
        )

    def record_request(self, zone, ride_id):
        self._r.zadd(_zone_requests_key(zone), {ride_id: self._now()})

    def recent_demand(self, zone):
        key = _zone_requests_key(zone)
        self._r.zremrangebyscore(key, "-inf", self._now() - DEMAND_WINDOW_MS)
        return self._r.zcard(key)

    def snapshot(self):
        """All known drivers, for the Live Ops Map."""
        out = []
        for key in self._r.scan_iter(match="driver:*", count=200):
            d = {_s(k): _s(v) for k, v in self._r.hgetall(key).items()}
            if not d:
                continue
            out.append({
                "driver_id": _s(key).split(":", 1)[1],
                "lat": float(d["lat"]), "lng": float(d["lng"]),
                "status": d["status"], "zone": d["zone"], "ts": int(d["ts"]),
            })
        return sorted(out, key=lambda x: x["driver_id"])
