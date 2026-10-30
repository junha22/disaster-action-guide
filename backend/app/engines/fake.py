"""Fake engine for tests (requirement 5.7). Returns preset candidates that avoid the exclusions."""
from dataclasses import dataclass, field
from typing import Callable, Sequence

from shapely.geometry import LineString, Polygon

from ..risk.geo import to_metric
from .base import (EngineError, ExcludeLimits, LonLat, NoRouteFound, OsrmRoute, Ring,
                   osrm_route)


@dataclass
class FakeCandidate:
    coordinates: list[LonLat]
    duration: float
    distance: float | None = None
    label: str = ""


@dataclass
class FakeEngine:
    candidates: list[FakeCandidate]
    limits: ExcludeLimits = ExcludeLimits(max_perimeter_m=1e9, max_vertices=10 ** 9)
    # An exception to raise, or a function of the call record returning one (or None).
    error: EngineError | Callable[[dict], EngineError | None] | None = None
    calls: list[dict] = field(default_factory=list)
    name: str = "fake"

    def exclude_limits(self) -> ExcludeLimits:
        return self.limits

    def route(self, origin: LonLat, destination: LonLat, *, exclude_polygons: Sequence[Ring] = (),
              alternates: int = 0, timeout_s: float = 10.0) -> list[OsrmRoute]:
        call = {"origin": origin, "destination": destination, "alternates": alternates,
                "exclude_polygons": [[tuple(p) for p in ring] for ring in exclude_polygons],
                "timeout_s": timeout_s}
        self.calls.append(call)
        error = self.error(call) if callable(self.error) else self.error
        if error is not None:
            raise error
        polygons = [Polygon(ring) for ring in exclude_polygons]
        usable = [c for c in self.candidates
                  if not any(LineString(c.coordinates).intersects(p) for p in polygons)]
        if not usable:
            raise NoRouteFound()
        routes = []
        for c in usable[: alternates + 1]:
            distance = c.distance if c.distance is not None else to_metric(LineString(c.coordinates)).length
            routes.append(osrm_route(c.coordinates, distance, c.duration))
        return routes
