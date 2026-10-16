"""Fare and surge rules. All amounts are illustrative values in KES."""

BASE_FARE = 100
PER_KM = 40
PER_MIN = 4
MIN_FARE = 200

# A zone is considered fully supplied with this many available drivers plus
# one per recent request in the same zone.
BASELINE_SUPPLY = 1
SURGE_STEP = 0.25
MAX_SURGE = 3.0


def surge_multiplier(available, recent_requests):
    """Each missing driver against the zone's need adds SURGE_STEP, capped."""
    required = BASELINE_SUPPLY + max(0, recent_requests)
    shortage = max(0, required - max(0, available))
    return min(MAX_SURGE, 1.0 + SURGE_STEP * shortage)


def fare(distance_m, duration_s, surge):
    raw = BASE_FARE + PER_KM * distance_m / 1000 + PER_MIN * duration_s / 60
    amount = max(MIN_FARE, raw) * surge
    return int(round(amount / 10.0)) * 10
