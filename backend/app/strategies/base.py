"""Strategy interface, route plan and the shared avoid-or-fall-back procedure (requirement 4)."""
from dataclasses import dataclass, field
import time
from typing import Any, ClassVar, Iterable, Protocol, Sequence

from pydantic import BaseModel

from ..config import ZONE_TYPES
from ..engines.base import (ExcludeLimitExceeded, LocationNotRoutable, LonLat, NoRouteFound,
                            OsrmRoute, RoutingEngine)
from ..risk.layer import RiskLayer
from ..risk.scoring import Exposure, score_route


class RouteNotFound(Exception):
    """Even the baseline route does not exist. API answers 422."""


@dataclass(frozen=True)
class RouteRequest:
    origin: LonLat
    destination: LonLat


@dataclass(frozen=True)
class WeatherContext:
    source: str              # "kma" | "demo" | "unavailable"
    rn1_mm: float
    alert: str               # "none" | "advisory" | "warning"
    level: int
    observed_at: str | None
    real_weather_applied: bool
    alert_status: str = "ok"  # "ok" | "failed" | "not_requested"

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "rn1_mm": self.rn1_mm, "alert": self.alert, "level": self.level,
                "observed_at": self.observed_at, "real_weather_applied": self.real_weather_applied,
                "alert_status": self.alert_status}


@dataclass(frozen=True)
class ResolvedParams:
    avoid_buffer_m: dict[str, float]
    weights: dict[str, float]
    thresholds_mm: tuple[float, ...]
    alert_min_level: dict[str, int]
    avoid_by_level: dict[int, tuple[str, ...]]
    labels: dict[str, str]
    lambda_: float


@dataclass
class StrategyContext:
    weather: WeatherContext
    layer: RiskLayer
    engine: RoutingEngine
    params: ResolvedParams
    deadline: float  # time.monotonic() value

    def remaining(self) -> float:
        return self.deadline - time.monotonic()


@dataclass(frozen=True)
class ScoredRoute:
    osrm: OsrmRoute
    exposure: Exposure
    label: str

    def metrics(self) -> dict[str, Any]:
        return {"label": self.label, "duration_s": round(self.osrm["duration"], 1),
                "distance_m": round(self.osrm["distance"], 1),
                "exposure_score": round(self.exposure.score, 1),
                "exposure_by_type_m": {t: round(v, 1) for t, v in self.exposure.by_type_m.items()}}


@dataclass(frozen=True)
class Explanation:
    status: str  # baseline | no_avoid_level | nothing_on_route | avoided | avoid_failed | ranked
    level: int
    avoid_types: tuple[str, ...]
    avoided_zones: list[dict]
    passed_zones: list[dict]
    added_duration_s: float
    added_distance_m: float
    message: str
    warning: str | None = None
    failure_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "level": self.level, "avoid_types": list(self.avoid_types),
                "avoided_zones": self.avoided_zones, "passed_zones": self.passed_zones,
                "added_duration_s": self.added_duration_s, "added_distance_m": self.added_distance_m,
                "message": self.message, "warning": self.warning, "failure_reason": self.failure_reason}


@dataclass(frozen=True)
class RoutePlan:
    route: ScoredRoute
    baseline: ScoredRoute
    alternatives: tuple[ScoredRoute, ...]
    explanation: Explanation

    def metrics(self) -> dict[str, Any]:
        return {"route": self.route.metrics(), "baseline": self.baseline.metrics(),
                "alternatives": [a.metrics() for a in self.alternatives]}

    def to_dict(self) -> dict[str, Any]:
        """Same shape for every strategy (requirement 4.2)."""
        return {"route": self.route.osrm, "alternatives": [a.osrm for a in self.alternatives],
                "baseline": self.baseline.osrm, "explanation": self.explanation.as_dict(),
                "metrics": self.metrics()}


class Strategy(Protocol):
    name: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str]
    params_model: ClassVar[type[BaseModel]]

    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan: ...


# ---- shared helpers -------------------------------------------------------------------------

MESSAGES = {
    "baseline": "회피 없이 최단 시간으로 찾은 경로입니다.",
    "no_avoid_level": "현재 강수 단계에서는 피하는 구역이 없습니다.",
    "nothing_on_route": "이 경로에는 지금 피해야 할 구역이 없습니다.",
    "ranked": "소요시간과 위험 노출 점수의 합이 가장 작은 경로입니다.",
}
AVOID_FAILED = "위험 구역을 피하는 경로를 찾지 못했습니다."
REASON_NO_PATH = "위험 구역을 제외하면 도착할 수 있는 경로가 없습니다."
REASON_LIMIT = "피할 구역이 너무 많거나 커서 경로 엔진이 처리하지 못했습니다."
REASON_NEAR_ROAD = "출발지나 목적지 근처 도로가 모두 피해야 할 구역에 걸립니다."
REASON_LEFTOVER = "경로 엔진이 일부 위험 구역을 피하지 못했습니다."


def ordered_types(types: Iterable[str]) -> tuple[str, ...]:
    wanted = set(types)
    return tuple(t for t in ZONE_TYPES if t in wanted)


def scored(ctx: StrategyContext, route: OsrmRoute, label: str) -> ScoredRoute:
    exposure = score_route(route["geometry"]["coordinates"], ctx.layer, ctx.params.weights)
    return ScoredRoute(osrm=route, exposure=exposure, label=label)


def baseline_routes(ctx: StrategyContext, request: RouteRequest, alternates: int = 0) -> list[ScoredRoute]:
    try:
        routes = ctx.engine.route(request.origin, request.destination, alternates=alternates,
                                  timeout_s=ctx.remaining())
    except (NoRouteFound, LocationNotRoutable):
        raise RouteNotFound() from None
    labels = ["기본 경로"] + [f"엔진 대안 {i}" for i in range(1, len(routes))]
    return [scored(ctx, r, label) for r, label in zip(routes, labels)]


def make_plan(ctx: StrategyContext, *, route: ScoredRoute, baseline: ScoredRoute, status: str,
              alternatives: Sequence[ScoredRoute] = (), avoid_types: Sequence[str] = (),
              message: str | None = None, warning: str | None = None,
              failure_reason: str | None = None) -> RoutePlan:
    # Zones the baseline passes but the chosen route does not. Restricted to the avoided types
    # when there are any, so the list explains the choice instead of listing side effects.
    scope = avoid_types or None
    route_ids = route.exposure.zone_ids()
    avoided = [p.zone.ref() for p in baseline.exposure.passes
               if p.zone.id not in route_ids and (scope is None or p.zone.type in scope)]
    explanation = Explanation(
        status=status, level=ctx.weather.level, avoid_types=ordered_types(avoid_types),
        avoided_zones=avoided, passed_zones=[p.as_dict() for p in route.exposure.passes],
        added_duration_s=round(route.osrm["duration"] - baseline.osrm["duration"], 1),
        added_distance_m=round(route.osrm["distance"] - baseline.osrm["distance"], 1),
        message=message or MESSAGES.get(status, ""), warning=warning, failure_reason=failure_reason)
    return RoutePlan(route=route, baseline=baseline, alternatives=tuple(alternatives), explanation=explanation)


def type_phrase(ctx: StrategyContext, types: Sequence[str]) -> str:
    return "·".join(ctx.params.labels[t] for t in types)


def avoid_plan(ctx: StrategyContext, request: RouteRequest, types: Iterable[str],
               empty_status: str = "no_avoid_level") -> RoutePlan:
    """Exclude active zones of `types`; fall back to the baseline with a warning (requirement 4.9)."""
    types = ordered_types(types)
    baseline = baseline_routes(ctx, request)[0]
    if not types:
        return make_plan(ctx, route=baseline, baseline=baseline, status=empty_status)
    if not baseline.exposure.zone_ids(types):
        return make_plan(ctx, route=baseline, baseline=baseline, status="nothing_on_route", avoid_types=types)

    def failed(reason: str) -> RoutePlan:
        return make_plan(ctx, route=baseline, baseline=baseline, status="avoid_failed", avoid_types=types,
                         message=AVOID_FAILED, warning=AVOID_FAILED, failure_reason=reason)

    polygons = ctx.layer.avoid_polygons(types, ctx.params.avoid_buffer_m)
    for role, point in (("출발지", request.origin), ("목적지", request.destination)):
        inside = ctx.layer.containing(point, polygons)
        if inside:
            return failed(f"{role}가 '{inside[0].name}' 구역 안에 있습니다.")
    limits = ctx.engine.exclude_limits()
    if (sum(p.perimeter_m for p in polygons) > limits.max_perimeter_m
            or sum(p.vertices for p in polygons) > limits.max_vertices):
        return failed(REASON_LIMIT)
    rings = [ring for p in polygons for ring in p.rings]
    try:
        routes = ctx.engine.route(request.origin, request.destination, exclude_polygons=rings,
                                  alternates=2, timeout_s=ctx.remaining())
    except NoRouteFound:
        return failed(REASON_NO_PATH)
    except ExcludeLimitExceeded:
        return failed(REASON_LIMIT)
    except LocationNotRoutable:
        return failed(REASON_NEAR_ROAD)
    phrase = type_phrase(ctx, types)
    candidates = [scored(ctx, r, f"{phrase} 회피" if i == 0 else f"{phrase} 회피 대안 {i}")
                  for i, r in enumerate(routes)]
    chosen = candidates[0]
    if chosen.exposure.zone_ids(types):
        return failed(REASON_LEFTOVER)
    return make_plan(ctx, route=chosen, baseline=baseline, status="avoided", avoid_types=types,
                     alternatives=candidates[1:], message=f"{phrase} 구역을 피한 경로입니다.")
