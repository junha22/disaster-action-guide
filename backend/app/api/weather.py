import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

from ..config import AppConfig, rain_level
from ..context.weather_kma import KmaWeatherService, WeatherSnapshot, get_weather_service
from ..context.weather_regions import REGIONS, in_weather_area
from .deps import config_dep

router = APIRouter(prefix="/api", tags=["route"])
OUTSIDE = "광주·전남 밖의 위치입니다"


class WeatherPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lon: float
    lat: float

    @field_validator("lon", "lat")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value


def _answer(s: WeatherSnapshot, config: AppConfig) -> dict:
    level = (rain_level(s.rn1_mm, s.alert, config.rain_levels.thresholds_mm, config.alert_min_level.model_dump())
             if s.available and s.rn1_mm is not None else None)
    return {"available": s.available, "source": "kma" if s.available else "unavailable",
            "rn1_mm": s.rn1_mm, "alert": s.alert, "alert_label": s.alert_label, "alert_status": s.alert_status,
            "level": level, "observed_at": s.observed_at, "grid": {"nx": s.grid[0], "ny": s.grid[1]},
            "region": s.region, "routable": s.routable, "station": s.station, "message": s.message}


@router.get("/weather")
def weather(config: Annotated[AppConfig, Depends(config_dep)],
            service: Annotated[KmaWeatherService, Depends(get_weather_service)]):
    return _answer(service.get(), config)


@router.post("/weather")
def weather_at(body: WeatherPoint,
               config: Annotated[AppConfig, Depends(config_dep)],
               service: Annotated[KmaWeatherService, Depends(get_weather_service)]):
    """Coordinates stay in the body and are not stored or logged. KMA gets the grid cell only."""
    if not in_weather_area(body.lon, body.lat):
        raise HTTPException(422, OUTSIDE)
    return _answer(service.get((body.lon, body.lat)), config)


@router.get("/weather/regions")
def weather_regions():
    return [r.as_dict() for r in REGIONS]
