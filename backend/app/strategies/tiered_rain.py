from .base import RoutePlan, RouteRequest, StrategyContext, avoid_plan
from .params import TieredParams
from .registry import register


@register("tiered_rain")
class TieredRainStrategy:
    label = "강수 단계 회피"
    description = ("강수 단계가 오를수록 지하차도 → 침수 이력(반복 침수·저지대 먼저) → 하천변 순서로 피하는 구역을 "
                   "늘립니다. '되도록 피함' 구역은 우회 시간과 벌점을 비교해 고릅니다.")
    params_model = TieredParams

    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan:
        level = ctx.weather.level
        return avoid_plan(ctx, request, ctx.params.hard_by_level[level], ctx.params.soft_by_level[level],
                          empty_status="no_avoid_level")
