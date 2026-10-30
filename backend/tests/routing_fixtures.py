"""Synthetic zones and candidate routes for tests. No real engine, network or data files."""
from shapely.geometry import box

from app.risk.layer import RiskLayer, RiskZone
from app.risk.geo import to_metric

LAT = 35.15
ORIGIN = (126.80, LAT)
DESTINATION = (126.90, LAT)
DEG_LAT_M = 111_000.0
DEG_LON_M = 91_000.0  # roughly, at 35 degrees north

ZONE_CENTRES = {"underpass": 126.82, "flood_history": 126.85, "riverside": 126.88}


def square(lon: float, lat: float, half_m: float):
    dx, dy = half_m / DEG_LON_M, half_m / DEG_LAT_M
    return box(lon - dx, lat - dy, lon + dx, lat + dy)


def make_zone(zone_id: str, zone_type: str, geometry, active: bool = True, name: str | None = None,
              tier: str | None = None):
    """tier: flood_history terrain tier; None means unknown, which routing treats as "high"."""
    return RiskZone(id=zone_id, name=name or zone_id, type=zone_type, active=active,
                    source_name="test", source_url="https://www.data.go.kr", checked_at="2026-10-30",
                    is_dummy=True, note="", geometry=geometry, metric=to_metric(geometry), tier=tier)


def corridor_layer(extra=(), flood_tier: str = "normal") -> RiskLayer:
    """One zone per type on the straight route. The flood zone is "normal": not avoided at level 1,
    soft at level 2, hard at level 3 (design.md 5.8)."""
    zones = [make_zone(f"z-{t}", t, square(lon, LAT, 100), tier=flood_tier if t == "flood_history" else None)
             for t, lon in ZONE_CENTRES.items()]
    return RiskLayer([*zones, *extra])


def detour(until_lon: float, north: float = 0.01):
    """Straight east-west route that bends north between 126.81 and until_lon."""
    return [ORIGIN, (126.81, LAT), (126.81, LAT + north), (until_lon, LAT + north),
            (until_lon, LAT), DESTINATION]


# Ordered fastest first: baseline passes all three zones, each detour avoids one more type.
CANDIDATES = [
    {"label": "straight", "coords": [ORIGIN, DESTINATION], "duration": 600.0},
    {"label": "avoid-u", "coords": detour(126.83), "duration": 700.0},
    {"label": "avoid-uf", "coords": detour(126.86), "duration": 800.0},
    {"label": "avoid-all", "coords": detour(126.89), "duration": 900.0},
]
