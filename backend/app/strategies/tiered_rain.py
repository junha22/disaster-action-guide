from .base import RoutePlan, RouteRequest, StrategyContext, avoid_plan
from .params import TieredParams
from .registry import register


@register("tiered_rain")
class TieredRainStrategy:
    label = "강수 단계 회피"
    description = "강수 단계가 오를수록 지하차도 → 침수 이력 → 하천변 순서로 피하는 구역을 늘립니다."
    params_model = TieredParams

    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan:
        types = ctx.params.avoid_by_level[ctx.weather.level]
        return avoid_plan(ctx, request, types, empty_status="no_avoid_level")
