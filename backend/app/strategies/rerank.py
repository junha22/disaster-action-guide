"""Pick the candidate with the smallest duration(s) + lambda x exposure score (requirement 4.6)."""
from .base import RoutePlan, RouteRequest, ScoredRoute, StrategyContext, common_candidates, make_plan
from .params import RerankParams
from .registry import register


@register("rerank")
class RerankStrategy:
    label = "시간·위험 균형"
    description = "후보 경로 여러 개 중 소요시간(초) + λ × 위험 노출 점수가 가장 작은 경로를 고릅니다."
    params_model = RerankParams

    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan:
        pool = common_candidates(ctx, request)

        def score(route: ScoredRoute) -> float:
            return route.osrm["duration"] + ctx.params.lambda_ * route.exposure.score

        ranked = sorted(pool.routes, key=score)  # stable: ties keep candidate order
        return make_plan(ctx, route=ranked[0], baseline=pool.baseline, alternatives=ranked[1:], status="ranked")
