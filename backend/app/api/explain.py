"""POST /api/route/explain (requirement 8).

Called by the screen after the route result is shown, so the route never waits for the LLM.
The body carries finished facts only: status, rain level, durations and zone ids with lengths.
No coordinates. Zone names and sources are looked up in the server's risk layer.
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..config import ZONE_GROUPS, ZONE_TYPES, AppConfig, group_tier, group_type
from ..risk.layer import RiskLayer
from ..route_explainer import ExplainInput, UnknownZone, ZoneLength, explain
from .deps import config_dep, layer_dep

router = APIRouter(prefix="/api", tags=["route"])
UNKNOWN_ZONE = "알 수 없는 위험 구역이 포함되어 있습니다"


class ZoneBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    length_m: float = Field(ge=0, le=200_000)


class RouteSide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration_s: float = Field(ge=0, le=172_800)
    zones: list[ZoneBody] = Field(default_factory=list, max_length=1000)


class ExplainBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["baseline", "no_avoid_level", "nothing_on_route", "avoided", "partially_avoided",
                    "avoid_failed", "ranked"]
    level: int = Field(ge=0, le=3)
    alert: Literal["none", "advisory", "warning"] = "none"
    route: RouteSide
    baseline: RouteSide
    fallback_engine: bool = False


def _zones(side: RouteSide) -> tuple[ZoneLength, ...]:
    return tuple(ZoneLength(z.id, z.length_m) for z in side.zones)


def zone_labels(config: AppConfig) -> tuple[dict[str, str], dict[str, str]]:
    """(type -> label, avoidance group -> flood tier label)."""
    return ({t: config.zone_types[t].label for t in ZONE_TYPES},
            {g: config.zone_types[group_type(g)].tiers[group_tier(g)].label for g in ZONE_GROUPS if group_tier(g)})


@router.post("/route/explain")
def explain_route(body: ExplainBody,
                  config: Annotated[AppConfig, Depends(config_dep)],
                  layer: Annotated[RiskLayer, Depends(layer_dep)]):
    data = ExplainInput(status=body.status, level=body.level, alert=body.alert,
                        route_duration_s=body.route.duration_s, baseline_duration_s=body.baseline.duration_s,
                        route_zones=_zones(body.route), baseline_zones=_zones(body.baseline),
                        fallback_engine=body.fallback_engine)
    labels, tier_labels = zone_labels(config)
    try:
        return explain(data, {z.id: z for z in layer.zones}, labels, tier_labels).as_dict()
    except UnknownZone:
        raise HTTPException(422, UNKNOWN_ZONE) from None
