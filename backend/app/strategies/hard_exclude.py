from ..config import ZONE_TYPES
from .base import RoutePlan, RouteRequest, StrategyContext, avoid_plan
from .params import CommonParams
from .registry import register


@register("hard_exclude")
class HardExcludeStrategy:
    label = "모든 위험 구역 회피"
    description = "강수량과 관계없이 사용 중인 위험 구역을 모두 제외합니다."
    params_model = CommonParams

    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan:
        return avoid_plan(ctx, request, ZONE_TYPES)
