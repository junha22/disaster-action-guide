"""Strategy interface, route plan and the shared candidate search / selection (requirement 4)."""
from dataclasses import dataclass
import time
from typing import Any, ClassVar, Iterable, Protocol, Sequence

from pydantic import BaseModel

from ..config import ZONE_TYPES
from ..engines.base import (ExcludeLimitExceeded, LocationNotRoutable, LonLat, NoRouteFound,
                            OsrmRoute, RoutingEngine)
from ..risk.layer import AvoidPolygon, RiskLayer
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
    avoid_by_level: dict[int, tuple[str, ...]]  # hard + soft, for display
    hard_by_level: dict[int, tuple[str, ...]]
    soft_by_level: dict[int, tuple[str, ...]]
    entry_penalty_s: dict[str, float]
    per_m_penalty_s: dict[str, float]
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
    # baseline | no_avoid_level | nothing_on_route | avoided | partially_avoided | avoid_failed | ranked
    status: str
    level: int
    avoid_types: tuple[str, ...]
    avoided_zones: list[dict]
    passed_zones: list[dict]
    added_duration_s: float
    added_distance_m: float
    message: str
    warning: str | None = None
    failure_reason: str | None = None
    hard_types: tuple[str, ...] = ()
    soft_types: tuple[str, ...] = ()
    clear_option: dict[str, float] | None = None  # fastest candidate avoiding every avoided type

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "level": self.level, "avoid_types": list(self.avoid_types),
                "hard_types": list(self.hard_types), "soft_types": list(self.soft_types),
                "avoided_zones": self.avoided_zones, "passed_zones": self.passed_zones,
                "added_duration_s": self.added_duration_s, "added_distance_m": self.added_distance_m,
                "message": self.message, "warning": self.warning, "failure_reason": self.failure_reason,
                "clear_option": self.clear_option}


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
PARTIAL_WARNING = "일부 위험 구역을 지나는 경로입니다."
REASON_NO_PATH = "위험 구역을 제외하면 도착할 수 있는 경로가 없습니다."
REASON_LIMIT = "피할 구역이 너무 많거나 커서 경로 엔진이 처리하지 못했습니다."
REASON_NEAR_ROAD = "출발지나 목적지 근처 도로가 모두 피해야 할 구역에 걸립니다."
REASON_LEFTOVER = "경로 엔진이 일부 위험 구역을 피하지 못했습니다."
REASON_TIME = "제한 시간 안에 우회 경로 계산을 끝내지 못했습니다. 다시 시도해 주세요."
STOP_REASONS = {"no_path": REASON_NO_PATH, "limit": REASON_LIMIT, "near_road": REASON_NEAR_ROAD,
                "time": REASON_TIME}

# Rounds of "exclude the zones the route passes, route again" (design.md 5.7).
MAX_EXCLUDE_ROUNDS = 8
MAX_ALTERNATIVES = 3
# Do not start another engine call with less time than this left in the request's budget.
MIN_ROUND_TIME_S = 1.0
# Engine alternates make a round slower; below this budget only the main route is asked for.
ALTERNATES_MIN_TIME_S = 3.0


def ordered_types(types: Iterable[str]) -> tuple[str, ...]:
    wanted = set(types)
    return tuple(t for t in ZONE_TYPES if t in wanted)


def scored(ctx: StrategyContext, route: OsrmRoute, label: str) -> ScoredRoute:
    exposure = score_route(route["geometry"]["coordinates"], ctx.layer, ctx.params.weights)
    return ScoredRoute(osrm=route, exposure=exposure, label=label)


def geometry_key(route: ScoredRoute) -> tuple:
    return tuple(tuple(round(c, 6) for c in p) for p in route.osrm["geometry"]["coordinates"])


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
              failure_reason: str | None = None, hard_types: Sequence[str] = (),
              soft_types: Sequence[str] = (), clear_option: dict[str, float] | None = None) -> RoutePlan:
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
        message=message or MESSAGES.get(status, ""), warning=warning, failure_reason=failure_reason,
        hard_types=ordered_types(hard_types), soft_types=ordered_types(soft_types), clear_option=clear_option)
    return RoutePlan(route=route, baseline=baseline, alternatives=tuple(alternatives), explanation=explanation)


def type_phrase(ctx: StrategyContext, types: Sequence[str]) -> str:
    return "·".join(ctx.params.labels[t] for t in types)


@dataclass(frozen=True)
class SearchResult:
    routes: list[ScoredRoute]  # every route seen, in discovery order, no duplicate geometry
    stop_reason: str | None    # None (clear) | no_path | limit | near_road | leftover | rounds | time


def collect_candidates(ctx: StrategyContext, request: RouteRequest, types: Sequence[str],
                       polygons: Sequence[AvoidPolygon], start_ids: Iterable[str], *,
                       seed: Sequence[ScoredRoute] = (), alternates: int = 2) -> SearchResult:
    """Exclude only the zones a route actually passes, adding more each round, and keep every
    route the engine returns along the way (design.md 5.7).

    Real data has hundreds of zones; sending all of them at once exceeds the engine's
    exclude_polygons limits (risk_zones_guide.md 6-3). Each round adds the `types` zones the
    round's best route still passes. Earlier rounds and engine alternatives often contain better
    routes than the last round, so nothing is thrown away here; the caller chooses.
    EngineUnavailable (timeout, no tiles) propagates.
    """
    by_id = {p.zone.id: p for p in polygons}
    chosen = sorted(i for i in set(start_ids) if i in by_id)
    found: list[ScoredRoute] = list(seed)
    seen = {geometry_key(r) for r in found}
    limits = ctx.engine.exclude_limits()
    stop: str | None = "rounds"
    for round_no in range(1, MAX_EXCLUDE_ROUNDS + 1):
        if not chosen:
            stop = None
            break
        if round_no > 1 and ctx.remaining() < MIN_ROUND_TIME_S:
            stop = "time"
            break
        selected = [by_id[i] for i in chosen]
        if (sum(p.perimeter_m for p in selected) > limits.max_perimeter_m
                or sum(p.vertices for p in selected) > limits.max_vertices):
            stop = "limit"
            break
        try:
            # Alternates of every round are kept as candidates (they found the best routes in
            # scenario A); they cost little (~0.07 s over 8 rounds locally) but are dropped when
            # the remaining budget is short.
            ask = alternates if ctx.remaining() >= ALTERNATES_MIN_TIME_S else 0
            routes = ctx.engine.route(request.origin, request.destination,
                                      exclude_polygons=[r for p in selected for r in p.rings],
                                      alternates=ask, timeout_s=ctx.remaining())
        except NoRouteFound:
            stop = "no_path"
            break
        except ExcludeLimitExceeded:
            stop = "limit"
            break
        except LocationNotRoutable:
            stop = "near_road"
            break
        main = None
        for k, raw in enumerate(routes):
            route = scored(ctx, raw, f"탐색 {round_no}회차" + (f" 대안 {k}" if k else ""))
            main = main or route
            key = geometry_key(route)
            if key not in seen:
                seen.add(key)
                found.append(route)
        passed = main.exposure.zone_ids(types) if main else set()
        new = sorted(i for i in passed if i in by_id and i not in chosen)
        if not new:
            stop = "leftover" if passed else None
            break
        chosen.extend(new)
    return SearchResult(routes=found, stop_reason=stop)


def soft_penalty(ctx: StrategyContext, route: ScoredRoute, soft: Sequence[str]) -> float:
    """Detour seconds charged for passing 'soft' zones (entry penalty + per-metre penalty)."""
    p = ctx.params
    return sum(p.entry_penalty_s[z.zone.type] + p.per_m_penalty_s[z.zone.type] * z.length_m
               for z in route.exposure.passes if z.zone.type in soft)


def _partial_message(ctx: StrategyContext, route: ScoredRoute, hard: Sequence[str],
                     soft: Sequence[str]) -> str:
    parts = []
    for t in soft:
        passes = [z for z in route.exposure.passes if z.zone.type == t]
        if passes:
            parts.append(f"{ctx.params.labels[t]} 구역 {len(passes)}곳({round(sum(z.length_m for z in passes))}m)")
    tail = ", ".join(parts) + "은 지납니다."
    return (f"{type_phrase(ctx, hard)} 구역은 모두 피했고, " + tail) if hard else tail


def avoid_plan(ctx: StrategyContext, request: RouteRequest, hard: Iterable[str], soft: Iterable[str] = (),
               empty_status: str = "no_avoid_level") -> RoutePlan:
    """Never pass `hard` zones; pass `soft` zones only when the detour costs more than their penalty.

    Falls back to the baseline with a warning when no candidate avoids every hard zone
    (requirement 4.9). Candidates come from collect_candidates (design.md 5.7).
    """
    hard = ordered_types(hard)
    soft = ordered_types(t for t in soft if t not in hard)
    types = ordered_types((*hard, *soft))
    base_routes = baseline_routes(ctx, request, alternates=2)
    baseline = base_routes[0]
    common = {"avoid_types": types, "hard_types": hard, "soft_types": soft}
    if not types:
        return make_plan(ctx, route=baseline, baseline=baseline, status=empty_status)
    if not baseline.exposure.zone_ids(types):
        return make_plan(ctx, route=baseline, baseline=baseline, status="nothing_on_route", **common)

    def failed(reason: str) -> RoutePlan:
        return make_plan(ctx, route=baseline, baseline=baseline, status="avoid_failed", message=AVOID_FAILED,
                         warning=AVOID_FAILED, failure_reason=reason, **common)

    buffers = ctx.params.avoid_buffer_m
    hard_polygons = ctx.layer.avoid_polygons(hard, buffers) if hard else []
    for role, point in (("출발지", request.origin), ("목적지", request.destination)):
        inside = ctx.layer.containing(point, hard_polygons)
        if inside:
            return failed(f"{role}가 '{inside[0].name}' 구역 안에 있습니다.")
    soft_polygons = ctx.layer.avoid_polygons(soft, buffers) if soft else []
    # Soft zones covering the origin/destination cannot be excluded (no route at all); they stay
    # in the cost only.
    blocked = {z.id for point in (request.origin, request.destination)
               for z in ctx.layer.containing(point, soft_polygons)}
    polygons = hard_polygons + [p for p in soft_polygons if p.zone.id not in blocked]
    search = collect_candidates(ctx, request, types, polygons, baseline.exposure.zone_ids(types),
                                seed=base_routes)
    valid = [r for r in search.routes if not r.exposure.zone_ids(hard)]
    if not valid:
        reason = STOP_REASONS.get(search.stop_reason or "", REASON_LEFTOVER)
        if reason == REASON_LEFTOVER and ctx.remaining() < MIN_ROUND_TIME_S:
            reason = REASON_TIME
        return failed(reason)
    ranked = sorted(valid, key=lambda r: r.osrm["duration"] + soft_penalty(ctx, r, soft))  # stable
    chosen = ranked[0]
    alternatives = ranked[1:1 + MAX_ALTERNATIVES]
    phrase = type_phrase(ctx, types)
    if not chosen.exposure.zone_ids(soft):
        return make_plan(ctx, route=chosen, baseline=baseline, status="avoided", alternatives=alternatives,
                         message=f"{phrase} 구역을 피한 경로입니다.", **common)
    clear = sorted((r for r in valid if not r.exposure.zone_ids(types)), key=lambda r: r.osrm["duration"])
    clear_option = None
    if clear:
        clear_option = {"added_duration_s": round(clear[0].osrm["duration"] - chosen.osrm["duration"], 1),
                        "added_distance_m": round(clear[0].osrm["distance"] - chosen.osrm["distance"], 1)}
    return make_plan(ctx, route=chosen, baseline=baseline, status="partially_avoided", alternatives=alternatives,
                     message=_partial_message(ctx, chosen, hard, soft), warning=PARTIAL_WARNING,
                     clear_option=clear_option, **common)
