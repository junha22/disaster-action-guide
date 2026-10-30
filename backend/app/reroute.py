"""Re-check of the remaining route when the rain gets worse during a drive.

The strategy plans a route from the car's position. This module compares it with what is left of
the route being driven, using the rules of the new rain level, and decides what to ask the driver.
"""
from typing import Sequence

from shapely.geometry import LineString

from .engines.base import EngineUnavailable, osrm_route
from .risk.geo import to_metric
from .strategies.base import (RoutePlan, RouteRequest, ScoredRoute, StrategyContext, common_candidates, make_plan,
                              scored, soft_penalty)

RECOMMEND = "recommend"  # a better route exists: ask the driver
KEEP = "keep"            # nothing the new level avoids is left on the route
NO_BETTER = "no_better"  # zones are left, but no route found does better


def remaining_route(ctx: StrategyContext, coordinates, duration_s: float) -> ScoredRoute:
    distance = to_metric(LineString(coordinates)).length
    return scored(ctx, osrm_route(coordinates, distance, duration_s), "현재 경로")


def best_effort_plan(ctx: StrategyContext, request: RouteRequest, failed: RoutePlan) -> RoutePlan:
    """A moving car can sit between zones, or inside one, so that no route avoids them all. It then
    still needs the route passing the fewest hard zones, not the plain fastest one. Soft zones and
    time break ties the way the strategy weighs them."""
    e = failed.explanation
    try:
        pool = common_candidates(ctx, request)
    except EngineUnavailable:
        return failed  # out of time: the failed plan is still a valid answer
    chosen = min(pool.routes, key=lambda r: (len(r.exposure.zone_ids(e.hard_groups)),
                                             r.osrm["duration"] + soft_penalty(ctx, r, e.soft_groups)))
    return make_plan(ctx, route=chosen, baseline=pool.baseline, status=e.status, message=e.message, warning=e.warning,
                     failure_reason=e.failure_reason, avoid_groups=e.avoid_groups, hard_groups=e.hard_groups,
                     soft_groups=e.soft_groups)


def decide(ctx: StrategyContext, candidate: ScoredRoute, current: ScoredRoute,
           hard: Sequence[str], soft: Sequence[str]) -> str:
    """Hard zones count first. With the same hard zones, fewer soft zones win only when the detour
    costs less than their penalty, the same trade-off the strategy makes between candidates."""
    now_hard, now_soft = (len(current.exposure.zone_ids(g)) for g in (hard, soft))
    new_hard, new_soft = (len(candidate.exposure.zone_ids(g)) for g in (hard, soft))
    if now_hard + now_soft == 0:
        return KEEP
    if new_hard < now_hard:
        return RECOMMEND
    if new_hard == now_hard and new_soft < now_soft:
        now_cost = current.osrm["duration"] + soft_penalty(ctx, current, soft)
        new_cost = candidate.osrm["duration"] + soft_penalty(ctx, candidate, soft)
        if new_cost < now_cost:
            return RECOMMEND
    return NO_BETTER
