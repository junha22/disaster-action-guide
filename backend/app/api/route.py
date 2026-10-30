"""POST /api/route (requirements 2.7, 4, 5.4, 7.3, 7.4)."""
import math
import os
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import AppConfig, rain_level
from ..context.weather_kma import KmaWeatherService, get_weather_service
from ..context.weather_mock import demo_weather, unavailable_weather
from ..engines import get_engine
from ..engines.base import EngineUnavailable, RoutingEngine
from ..risk.geo import in_service_area
from ..risk.layer import RiskLayer
from ..strategies.base import ResolvedParams, RouteNotFound, RouteRequest, StrategyContext, WeatherContext
from ..strategies.params import ParamsError, resolve
from ..strategies.registry import UnknownStrategy, get_strategy
from .deps import config_dep, layer_dep

router = APIRouter(prefix="/api", tags=["route"])
ENGINE_DOWN = "경로 엔진에 연결할 수 없습니다"
NO_ROUTE = "두 지점 사이 자동차 경로를 찾지 못했습니다"
OUTSIDE = "광주광역시 범위 밖의 좌표입니다"


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lon: float
    lat: float

    @field_validator("lon", "lat")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value


class WeatherOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rn1_mm: float = Field(ge=0, le=300)
    alert: Literal["none", "advisory", "warning"] = "none"


class RouteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: Point
    destination: Point
    strategy: str | None = Field(default=None, max_length=64)
    weather_override: WeatherOverride | None = None
    params: dict[str, Any] = Field(default_factory=dict)


def weather_context(override: WeatherOverride | None, service: KmaWeatherService,
                    params: ResolvedParams) -> WeatherContext:
    if override is not None:
        return demo_weather(override.rn1_mm, override.alert, params)
    snapshot = service.get()
    if not snapshot.available or snapshot.rn1_mm is None:
        return unavailable_weather()
    alert = snapshot.alert if snapshot.alert_status == "ok" else "none"
    return WeatherContext(source="kma", rn1_mm=snapshot.rn1_mm, alert=alert,
                          level=rain_level(snapshot.rn1_mm, alert, params.thresholds_mm, params.alert_min_level),
                          observed_at=snapshot.observed_at, real_weather_applied=True,
                          alert_status=snapshot.alert_status)


def timeout_s(config: AppConfig) -> float:
    raw = os.environ.get("ROUTING_TIMEOUT_S")
    try:
        value = float(raw) if raw else config.engine.timeout_s
    except ValueError:
        value = config.engine.timeout_s
    return value if value > 0 else config.engine.timeout_s


@router.post("/route")
def find_route(body: RouteBody,
               config: Annotated[AppConfig, Depends(config_dep)],
               layer: Annotated[RiskLayer, Depends(layer_dep)],
               engine: Annotated[RoutingEngine, Depends(get_engine)],
               weather_service: Annotated[KmaWeatherService, Depends(get_weather_service)]):
    origin = (body.origin.lon, body.origin.lat)
    destination = (body.destination.lon, body.destination.lat)
    if not (in_service_area(*origin) and in_service_area(*destination)):
        raise HTTPException(422, OUTSIDE)
    name = body.strategy or config.default_strategy
    try:
        strategy = get_strategy(name)
    except UnknownStrategy:
        raise HTTPException(422, "등록되지 않은 알고리즘입니다") from None
    try:
        params = resolve(config, strategy.params_model, body.params)
    except ParamsError as exc:
        raise HTTPException(422, str(exc)) from None
    started = time.monotonic()
    weather = weather_context(body.weather_override, weather_service, params)
    ctx = StrategyContext(weather=weather, layer=layer, engine=engine, params=params,
                          deadline=started + timeout_s(config))
    try:
        plan = strategy.plan(RouteRequest(origin, destination), ctx)
    except EngineUnavailable:
        raise HTTPException(503, ENGINE_DOWN) from None
    except RouteNotFound:
        raise HTTPException(422, NO_ROUTE) from None
    return {"strategy": {"name": strategy.name, "label": strategy.label}, **plan.to_dict(),
            "weather": weather.as_dict()}
