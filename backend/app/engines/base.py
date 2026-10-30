"""Engine adapter contract (requirement 5.1). Strategies call engines only through this."""
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

LonLat = tuple[float, float]
Ring = Sequence[Sequence[float]]  # closed [[lon, lat], ...]
OsrmRoute = dict[str, Any]


@dataclass(frozen=True)
class ExcludeLimits:
    max_perimeter_m: float
    max_vertices: int


class EngineError(Exception):
    """Base class. Messages are fixed strings; engine details are never passed through."""


class EngineUnavailable(EngineError):
    """Engine cannot be loaded (no tiles, bad config) or timed out. API answers 503."""


class NoRouteFound(EngineError):
    """No drivable route for this request (e.g. every way is excluded)."""


class ExcludeLimitExceeded(EngineError):
    """Exclusion polygons exceed the engine's limits."""


class LocationNotRoutable(EngineError):
    """No road near the origin or destination."""


class RoutingEngine(Protocol):
    name: str

    def exclude_limits(self) -> ExcludeLimits: ...

    def route(self, origin: LonLat, destination: LonLat, *, exclude_polygons: Sequence[Ring] = (),
              alternates: int = 0, timeout_s: float = 10.0) -> list[OsrmRoute]:
        """Return OSRM-format routes, best first, at most 1 + alternates."""
        ...


def osrm_route(coordinates: Sequence[Sequence[float]], distance: float, duration: float,
               weight: float | None = None, weight_name: str = "auto") -> OsrmRoute:
    weight = duration if weight is None else weight
    return {
        "geometry": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in coordinates]},
        "distance": float(distance),
        "duration": float(duration),
        "weight": float(weight),
        "weight_name": weight_name,
        "legs": [{"distance": float(distance), "duration": float(duration), "weight": float(weight),
                  "summary": "", "steps": []}],
    }
