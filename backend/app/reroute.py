"""Re-check of the remaining route when the rain gets worse during a drive.

The strategy plans a route from the car's position. This module compares it with what is left of
the route being driven, using the rules of the new rain level, and decides what to ask the driver.
"""
from typing import Sequence

from shapely.geometry import LineString

from .engines.base import osrm_route
from .risk.geo import to_metric
from .strategies.base import ScoredRoute, StrategyContext, scored, soft_penalty

RECOMMEND = "recommend"  # a better route exists: ask the driver
KEEP = "keep"            # nothing the new level avoids is left on the route
NO_BETTER = "no_better"  # zones are left, but no route found does better


def remaining_route(ctx: StrategyContext, coordinates, duration_s: float) -> ScoredRoute:
    distance = to_metric(LineString(coordinates)).length
    return scored(ctx, osrm_route(coordinates, distance, duration_s), "현재 경로")


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
