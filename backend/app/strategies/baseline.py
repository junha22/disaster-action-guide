from .base import RoutePlan, RouteRequest, StrategyContext, baseline_routes, make_plan
from .params import CommonParams
from .registry import register


@register("baseline")
class BaselineStrategy:
    label = "기본 경로 (회피 없음)"
    description = "회피 없이 최단 시간 경로를 찾습니다. 비교 기준입니다."
    params_model = CommonParams

    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan:
        routes = baseline_routes(ctx, request, alternates=2)
        return make_plan(ctx, route=routes[0], baseline=routes[0], alternatives=routes[1:], status="baseline")
