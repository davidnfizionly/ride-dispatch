"""H3 zones and distance helpers.

Zones are H3 resolution 7 cells (about 5 km2 each). They are the unit for
supply, demand and surge. Nearest-driver search itself runs in Redis GEOSEARCH.
"""
import math

import h3

from shared.events import DEMO_AREA

ZONE_RES = 7


def demo_zones():
    """Zones covering the area where simulated drivers circulate."""
    south, west, north, east = DEMO_AREA
    shape = h3.LatLngPoly([(south, west), (south, east), (north, east), (north, west)])
    return sorted(h3.h3shape_to_cells(shape, ZONE_RES))


def zone_of(lat, lng):
    return h3.latlng_to_cell(lat, lng, ZONE_RES)


def zone_center(zone):
    return h3.cell_to_latlng(zone)


def zone_boundary(zone):
    return h3.cell_to_boundary(zone)


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
