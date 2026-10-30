"""Risk exposure score (design.md 5.3).

score = sum(length of the route inside the original zone polygon [m] x type weight).
Underpasses count the length driven along the tunnel instead (design.md 4.5).
The avoidance buffer is not used here.
"""
from dataclasses import dataclass
from typing import Iterable, Sequence

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from ..config import ZONE_TYPES
from .geo import to_metric
from .layer import RiskLayer, RiskZone

# Overlaps shorter than this (crossing a corner, touching an edge) are not counted as passing.
MIN_PASS_M = 1.0
# Routes and tunnel lines share OSM vertices, so a route in the tunnel lies within this band of it.
TUNNEL_BAND_M = 1.0
# A route is in the tunnel when it follows the way this far, or half of it when the way is shorter.
# A road crossing over the tunnel shares only the width of the band.
TUNNEL_FOLLOW_M = 15.0
TUNNEL_FOLLOW_SHARE = 0.5


@dataclass(frozen=True)
class ZonePass:
    zone: RiskZone
    length_m: float

    def as_dict(self) -> dict:
        return {**self.zone.ref(), "length_m": round(self.length_m, 1)}


@dataclass(frozen=True)
class Exposure:
    score: float
    by_type_m: dict[str, float]
    passes: tuple[ZonePass, ...]

    def zone_ids(self, types: Iterable[str] | None = None) -> set[str]:
        """Ids of passed zones. `types` may mix type names and group keys ("flood_history.high")."""
        wanted = None if types is None else set(types)
        return {p.zone.id for p in self.passes
                if wanted is None or p.zone.type in wanted or p.zone.group in wanted}


def tunnel_length(line: BaseGeometry, zone: RiskZone) -> float:
    """Metres of `line` (EPSG:5179) driven along the tunnel ways of `zone`."""
    band = line.buffer(TUNNEL_BAND_M)
    shared = (way.intersection(band).length for way in zone.centerline)
    return sum(s for s, way in zip(shared, zone.centerline)
               if s >= min(TUNNEL_FOLLOW_M, way.length * TUNNEL_FOLLOW_SHARE))


def score_route(coordinates: Sequence[Sequence[float]], layer: RiskLayer,
                weights: dict[str, float]) -> Exposure:
    by_type = {t: 0.0 for t in ZONE_TYPES}
    passes: list[ZonePass] = []
    if len(coordinates) >= 2:
        line = to_metric(LineString([(float(x), float(y)) for x, y in coordinates]))
        for zone in layer.active():
            if not line.intersects(zone.metric):
                continue
            length = tunnel_length(line, zone) if zone.centerline else line.intersection(zone.metric).length
            if length >= MIN_PASS_M:
                passes.append(ZonePass(zone, length))
                by_type[zone.type] += length
    score = sum(by_type[t] * weights[t] for t in ZONE_TYPES)
    return Exposure(score=score, by_type_m=by_type, passes=tuple(passes))
