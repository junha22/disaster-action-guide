"""Risk exposure score (design.md 5.3).

score = sum(length of the route inside the original zone polygon [m] x type weight).
The avoidance buffer is not used here.
"""
from dataclasses import dataclass
from typing import Iterable, Sequence

from shapely.geometry import LineString

from ..config import ZONE_TYPES
from .geo import to_metric
from .layer import RiskLayer, RiskZone

# Overlaps shorter than this (crossing a corner, touching an edge) are not counted as passing.
MIN_PASS_M = 1.0


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


def score_route(coordinates: Sequence[Sequence[float]], layer: RiskLayer,
                weights: dict[str, float]) -> Exposure:
    by_type = {t: 0.0 for t in ZONE_TYPES}
    passes: list[ZonePass] = []
    if len(coordinates) >= 2:
        line = to_metric(LineString([(float(x), float(y)) for x, y in coordinates]))
        for zone in layer.active():
            if not line.intersects(zone.metric):
                continue
            length = line.intersection(zone.metric).length
            if length >= MIN_PASS_M:
                passes.append(ZonePass(zone, length))
                by_type[zone.type] += length
    score = sum(by_type[t] * weights[t] for t in ZONE_TYPES)
    return Exposure(score=score, by_type_m=by_type, passes=tuple(passes))
