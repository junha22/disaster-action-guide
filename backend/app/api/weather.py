from typing import Annotated

from fastapi import APIRouter, Depends

from ..config import AppConfig, rain_level
from ..context.weather_kma import GRID, KmaWeatherService, get_weather_service
from .deps import config_dep

router = APIRouter(prefix="/api", tags=["route"])


@router.get("/weather")
def weather(config: Annotated[AppConfig, Depends(config_dep)],
            service: Annotated[KmaWeatherService, Depends(get_weather_service)]):
    s = service.get()
    level = (rain_level(s.rn1_mm, s.alert, config.rain_levels.thresholds_mm, config.alert_min_level.model_dump())
             if s.available and s.rn1_mm is not None else None)
    return {"available": s.available, "source": "kma" if s.available else "unavailable",
            "rn1_mm": s.rn1_mm, "alert": s.alert, "alert_label": s.alert_label, "alert_status": s.alert_status,
            "level": level, "observed_at": s.observed_at, "grid": {"nx": GRID[0], "ny": GRID[1]},
            "message": s.message}
