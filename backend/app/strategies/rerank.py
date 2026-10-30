"""Pick the candidate with the smallest duration(s) + lambda x exposure score (requirement 4.6)."""
from .base import (RoutePlan, RouteRequest, ScoredRoute, StrategyContext, baseline_routes, collect_candidates,
                   geometry_key, make_plan)
from .params import RerankParams
from .registry import register

EXCLUSION_SETS = (("underpass",), ("underpass", "flood_history"), ("underpass", "flood_history", "riverside"))


@register("rerank")
class RerankStrategy:
    label = "시간·위험 균형"
    description = "후보 경로 여러 개 중 소요시간(초) + λ × 위험 노출 점수가 가장 작은 경로를 고릅니다."
    params_model = RerankParams

    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan:
        candidates = baseline_routes(ctx, request, alternates=2)
        baseline = candidates[0]
        for types in EXCLUSION_SETS:
            passed = baseline.exposure.zone_ids(types)
            if not passed:  # excluding zones the baseline does not touch gives the baseline again
                continue
            polygons = ctx.layer.avoid_polygons(types, ctx.params.avoid_buffer_m)
            if any(ctx.layer.containing(p, polygons) for p in (request.origin, request.destination)):
                continue
            # Every round's route is a candidate, not only the last one (design.md 5.7).
            candidates.extend(collect_candidates(ctx, request, types, polygons, passed, alternates=0).routes)
        unique: list[ScoredRoute] = []
        seen = set()
        for candidate in candidates:
            key = geometry_key(candidate)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)

        def score(route: ScoredRoute) -> float:
            return route.osrm["duration"] + ctx.params.lambda_ * route.exposure.score

        ranked = sorted(unique, key=score)  # stable: ties keep candidate order
        return make_plan(ctx, route=ranked[0], baseline=baseline, alternatives=ranked[1:], status="ranked")
