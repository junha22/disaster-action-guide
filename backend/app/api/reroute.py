"""POST /api/route/reroute and /api/route/reroute/explain: rain got worse during a drive.

The first call decides from the car's position and the rest of the route. Coordinates are not
stored or logged. The second carries finished facts only, like /api/route/explain, so the change
request is on screen before the LLM answers.
"""
import math
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import ZONE_GROUPS, AppConfig, rain_level
from ..context.weather_kma import KmaWeatherService, get_weather_service
from ..engines import get_engine
from ..engines.base import EngineUnavailable, RoutingEngine
from ..reroute import best_effort_plan, decide, remaining_route
from ..risk.geo import in_service_area
from ..risk.layer import RiskLayer
from ..route_explainer import (RerouteInput, UnknownZone, ZoneLength, explain_reroute, reroute_facts,
                               reroute_template)
from ..strategies.base import RouteNotFound, RouteRequest, ScoredRoute, StrategyContext
from ..strategies.params import ParamsError, resolve
from ..strategies.registry import UnknownStrategy, get_strategy
from .deps import config_dep, layer_dep
from .explain import UNKNOWN_ZONE, RouteSide, _zones, zone_labels
from .route import ENGINE_DOWN, MAX_GUIDANCE_POINTS, NO_ROUTE, OUTSIDE, Point, WeatherOverride, timeout_s, weather_context

router = APIRouter(prefix="/api/route", tags=["route"])


class RerouteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: Point
    destination: Point
    heading: float | None = Field(default=None, ge=-360, le=360)
    remaining: list[tuple[float, float]] = Field(min_length=2, max_length=MAX_GUIDANCE_POINTS)
    remaining_duration_s: float = Field(ge=0, le=172_800)
    previous: WeatherOverride  # the rain the current route was last checked against
    strategy: str | None = Field(default=None, max_length=64)
    weather_override: WeatherOverride | None = None

    @field_validator("remaining")
    @classmethod
    def _finite(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if not all(math.isfinite(n) for point in value for n in point):
            raise ValueError("must be finite")
        return value


def _side(route: ScoredRoute, hard: tuple[str, ...], soft: tuple[str, ...]) -> dict[str, Any]:
    return {"duration_s": round(route.osrm["duration"], 1), "distance_m": round(route.osrm["distance"], 1),
            "zones": [p.as_dict() for p in route.exposure.passes],
            "hard_zone_ids": sorted(route.exposure.zone_ids(hard)),
            "soft_zone_ids": sorted(route.exposure.zone_ids(soft))}


def _lengths(route: ScoredRoute) -> tuple[ZoneLength, ...]:
    return tuple(ZoneLength(p.zone.id, p.length_m) for p in route.exposure.passes)


@router.post("/reroute")
def reroute(body: RerouteBody,
            config: Annotated[AppConfig, Depends(config_dep)],
            layer: Annotated[RiskLayer, Depends(layer_dep)],
            engine: Annotated[RoutingEngine, Depends(get_engine)],
            weather_service: Annotated[KmaWeatherService, Depends(get_weather_service)]):
    origin = (body.position.lon, body.position.lat)
    destination = (body.destination.lon, body.destination.lat)
    if not (in_service_area(*origin) and in_service_area(*destination)):
        raise HTTPException(422, OUTSIDE)
    name = body.strategy or config.default_strategy
    try:
        strategy = get_strategy(name)
    except UnknownStrategy:
        raise HTTPException(422, "등록되지 않은 알고리즘입니다") from None
    try:
        params = resolve(config, strategy.params_model, {})
    except ParamsError as exc:
        raise HTTPException(422, str(exc)) from None
    started = time.monotonic()
    weather = weather_context(body.weather_override, weather_service, params)
    ctx = StrategyContext(weather=weather, layer=layer, engine=engine, params=params,
                          deadline=started + timeout_s(config))
    request = RouteRequest(origin, destination, body.heading)
    try:
        plan = strategy.plan(request, ctx)
        hard, soft = plan.explanation.hard_groups, plan.explanation.soft_groups
        if plan.explanation.status == "avoid_failed":
            plan = best_effort_plan(ctx, request, plan)
    except EngineUnavailable:
        raise HTTPException(503, ENGINE_DOWN) from None
    except RouteNotFound:
        raise HTTPException(422, NO_ROUTE) from None
    current = remaining_route(ctx, body.remaining, body.remaining_duration_s)
    action = decide(ctx, plan.route, current, hard, soft)
    previous_level = rain_level(body.previous.rn1_mm, body.previous.alert, params.thresholds_mm, params.alert_min_level)
    labels, tier_labels = zone_labels(config)
    facts = reroute_facts(
        RerouteInput(action=action, previous_rn1_mm=body.previous.rn1_mm, previous_alert=body.previous.alert,
                     previous_level=previous_level, rn1_mm=weather.rn1_mm, alert=weather.alert, level=weather.level,
                     current_duration_s=current.osrm["duration"], candidate_duration_s=plan.route.osrm["duration"],
                     current_zones=_lengths(current), candidate_zones=_lengths(plan.route), hard_groups=hard, soft_groups=soft),
        {z.id: z for z in layer.zones}, labels, tier_labels)
    candidate_ids = plan.route.exposure.zone_ids()
    return {"action": action, "status": plan.explanation.status, "hard_groups": list(hard), "soft_groups": list(soft),
            "previous_level": previous_level, "weather": weather.as_dict(), "route": plan.route.osrm,
            "current": _side(current, hard, soft), "candidate": _side(plan.route, hard, soft),
            "avoided_zone_ids": sorted(current.exposure.zone_ids((*hard, *soft)) - candidate_ids),
            "text": reroute_template(facts)}


class RainBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rn1_mm: float = Field(ge=0, le=300)
    alert: Literal["none", "advisory", "warning"] = "none"


class RerouteExplainBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["recommend", "keep", "no_better"]
    previous: RainBody
    now: RainBody
    current: RouteSide
    candidate: RouteSide
    hard_groups: list[str] = Field(default_factory=list, max_length=len(ZONE_GROUPS))
    soft_groups: list[str] = Field(default_factory=list, max_length=len(ZONE_GROUPS))

    @field_validator("hard_groups", "soft_groups")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        if any(g not in ZONE_GROUPS for g in value):
            raise ValueError("unknown group")
        return value


@router.post("/reroute/explain")
def reroute_explain(body: RerouteExplainBody,
                    config: Annotated[AppConfig, Depends(config_dep)],
                    layer: Annotated[RiskLayer, Depends(layer_dep)]):
    rules = config.rain_levels.thresholds_mm, config.alert_min_level.model_dump()
    data = RerouteInput(action=body.action, previous_rn1_mm=body.previous.rn1_mm, previous_alert=body.previous.alert,
                        previous_level=rain_level(body.previous.rn1_mm, body.previous.alert, *rules),
                        rn1_mm=body.now.rn1_mm, alert=body.now.alert, level=rain_level(body.now.rn1_mm, body.now.alert, *rules),
                        current_duration_s=body.current.duration_s, candidate_duration_s=body.candidate.duration_s,
                        current_zones=_zones(body.current), candidate_zones=_zones(body.candidate),
                        hard_groups=tuple(body.hard_groups), soft_groups=tuple(body.soft_groups))
    labels, tier_labels = zone_labels(config)
    try:
        return explain_reroute(data, {z.id: z for z in layer.zones}, labels, tier_labels).as_dict()
    except UnknownZone:
        raise HTTPException(422, UNKNOWN_ZONE) from None
