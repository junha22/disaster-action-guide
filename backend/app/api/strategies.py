from typing import Annotated

from fastapi import APIRouter, Depends

from ..config import AppConfig, ZONE_TYPES
from ..context.kakao import KakaoSearch, get_search_service, load_demo_points
from ..risk.geo import SERVICE_BBOX
from ..strategies.registry import list_strategies
from .deps import config_dep

router = APIRouter(prefix="/api", tags=["route"])
ConfigDep = Annotated[AppConfig, Depends(config_dep)]


@router.get("/strategies")
def strategies(config: ConfigDep):
    return list_strategies(config.default_strategy)


@router.get("/app-config")
def app_config(config: ConfigDep, search: Annotated[KakaoSearch, Depends(get_search_service)]):
    return {
        "search_mode": "kakao" if search.has_key() else "demo",
        "service_area_bbox": list(SERVICE_BBOX),
        "zone_types": {t: {"label": config.zone_types[t].label, "color": config.zone_types[t].color,
                           "weight": config.zone_types[t].weight} for t in ZONE_TYPES},
        "level_rules": {"thresholds_mm": list(config.rain_levels.thresholds_mm),
                        # hard + soft, kept for map highlighting; the split is in the two lists below.
                        "avoid_by_level": {str(k): list(v.all) for k, v in config.rain_levels.avoid_by_level.items()},
                        "hard_by_level": {str(k): list(v.hard) for k, v in config.rain_levels.avoid_by_level.items()},
                        "soft_by_level": {str(k): list(v.soft) for k, v in config.rain_levels.avoid_by_level.items()},
                        "alert_min_level": config.alert_min_level.model_dump()},
        "default_strategy": config.default_strategy,
    }


@router.get("/demo-points")
def demo_points():
    return [p.as_dict() for p in load_demo_points()]
