from typing import Annotated

from fastapi import APIRouter, Depends

from ..config import ZONE_GROUPS, ZONE_TYPES, AppConfig, group_tier, group_type
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
    labels = config.group_labels()
    levels = config.rain_levels.avoid_by_level

    def tier_label(group: str) -> str | None:
        tier = group_tier(group)
        return config.zone_types[group_type(group)].tiers[tier].label if tier else None

    return {
        "search_mode": "kakao" if search.has_key() else "demo",
        "service_area_bbox": list(SERVICE_BBOX),
        "zone_types": {t: {"label": config.zone_types[t].label, "color": config.zone_types[t].color,
                           "weight": config.zone_types[t].weight} for t in ZONE_TYPES},
        # Avoidance groups (design.md 5.8): a type, or "type.tier" for flood_history tiers.
        "zone_groups": {g: {"type": group_type(g), "tier": group_tier(g), "label": labels[g],
                            "tier_label": tier_label(g)} for g in ZONE_GROUPS},
        "level_rules": {"thresholds_mm": list(config.rain_levels.thresholds_mm),
                        # Group keys. hard + soft, kept for map highlighting; the split is in the two lists below.
                        "avoid_by_level": {str(k): list(v.all_groups) for k, v in levels.items()},
                        "hard_by_level": {str(k): list(v.hard_groups) for k, v in levels.items()},
                        "soft_by_level": {str(k): list(v.soft_groups) for k, v in levels.items()},
                        "alert_min_level": config.alert_min_level.model_dump()},
        "default_strategy": config.default_strategy,
    }


@router.get("/demo-points")
def demo_points():
    return [p.as_dict() for p in load_demo_points()]
