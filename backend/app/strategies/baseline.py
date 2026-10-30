from .base import MAX_ALTERNATIVES, RoutePlan, RouteRequest, StrategyContext, common_candidates, make_plan
from .params import CommonParams
from .registry import register


@register("baseline")
class BaselineStrategy:
    label = "기본 경로 (회피 없음)"
    description = "회피 없이 최단 시간 경로를 찾습니다. 비교 기준입니다."
    params_model = CommonParams

    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan:
        pool = common_candidates(ctx, request)
        ranked = sorted(pool.routes, key=lambda r: r.osrm["duration"])  # stable: ranked[0] is pool.baseline
        return make_plan(ctx, route=ranked[0], baseline=pool.baseline, status="baseline",
                         alternatives=ranked[1:1 + MAX_ALTERNATIVES])
