"""Requirement 4.11 (and 4.2, 4.3, 4.6, 4.9, 4.10) with the fake engine adapter."""
import sys
import time

import pytest

from app import strategies as strategies_package
from app.config import get_config
from app.context.weather_mock import demo_weather
from app.engines.base import ExcludeLimitExceeded, ExcludeLimits, LocationNotRoutable, NoRouteFound
from app.engines.fake import FakeCandidate, FakeEngine
from app.strategies import registry
from app.strategies.base import RouteNotFound, RouteRequest, StrategyContext
from app.strategies.params import ParamsError, resolve

from routing_fixtures import (CANDIDATES, DESTINATION, LAT, ORIGIN, corridor_layer, make_underpass, make_zone,
                              square)

NAMES = ["baseline", "hard_exclude", "tiered_rain", "rerank"]
REQUEST = RouteRequest(ORIGIN, DESTINATION)


def engine(candidates=None, **kwargs):
    rows = CANDIDATES if candidates is None else candidates
    return FakeEngine([FakeCandidate(c["coords"], c["duration"], label=c["label"]) for c in rows], **kwargs)


def run(name, rn1=0.0, alert="none", params=None, fake=None, layer=None, request=REQUEST):
    strategy = registry.get_strategy(name)
    resolved = resolve(get_config(), strategy.params_model, params)
    fake = fake or engine()
    ctx = StrategyContext(weather=demo_weather(rn1, alert, resolved), layer=layer or corridor_layer(),
                          engine=fake, params=resolved, deadline=time.monotonic() + 10)
    return strategy.plan(request, ctx), fake


def label_of(plan):
    coords = [tuple(p) for p in plan.route.osrm["geometry"]["coordinates"]]
    return next(c["label"] for c in CANDIDATES if [tuple(p) for p in c["coords"]] == coords)


def shape_of(value):
    if isinstance(value, dict):
        return {k: shape_of(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape_of(value[0])] if value else []
    return type(value).__name__


def test_all_default_strategies_are_registered():
    assert set(NAMES) <= {s["name"] for s in registry.list_strategies("tiered_rain")}
    assert registry.list_strategies("tiered_rain")[0]["name"] == "tiered_rain"


@pytest.mark.parametrize("name", NAMES)
def test_every_strategy_returns_the_same_osrm_plan_shape(name):
    plan, _ = run(name, rn1=75)
    data = plan.to_dict()
    assert set(data) == {"route", "alternatives", "baseline", "explanation", "metrics"}
    for route in [data["route"], data["baseline"], *data["alternatives"]]:
        assert route["geometry"]["type"] == "LineString"
        assert {"distance", "duration", "weight", "weight_name", "legs"} <= set(route)
    assert set(data["explanation"]) == {"status", "level", "avoid_types", "avoid_groups", "hard_groups",
                                        "soft_groups", "avoided_zones", "passed_zones", "baseline_passed_zones",
                                        "added_duration_s", "added_distance_m", "message", "warning",
                                        "failure_reason", "clear_option"}
    assert set(data["metrics"]) == {"route", "baseline", "alternatives"}
    reference, _ = run("baseline", rn1=75)
    assert shape_of(data["route"]) == shape_of(reference.to_dict()["route"])
    assert shape_of(data["metrics"]["route"]) == shape_of(reference.to_dict()["metrics"]["route"])


ALL_FLOOD = ["flood_history.high", "flood_history.normal", "flood_history.raised"]


# The corridor flood zone is "normal": level 1 avoids only "high" flood zones (design.md 5.8).
@pytest.mark.parametrize("rn1, level, groups, avoided, route_label", [
    (0, 0, [], [], "straight"), (29, 0, [], [], "straight"),
    (30, 1, ["underpass", "flood_history.high"], ["underpass"], "avoid-u"),
    (49, 1, ["underpass", "flood_history.high"], ["underpass"], "avoid-u"),
    (50, 2, ["underpass", *ALL_FLOOD], ["underpass", "flood_history"], "avoid-uf"),
    (69, 2, ["underpass", *ALL_FLOOD], ["underpass", "flood_history"], "avoid-uf"),
    (70, 3, ["underpass", *ALL_FLOOD, "riverside"], ["underpass", "flood_history", "riverside"], "avoid-all"),
])
def test_tiered_rain_boundaries(rn1, level, groups, avoided, route_label):
    plan, fake = run("tiered_rain", rn1=rn1)
    e = plan.explanation
    assert e.level == level and list(e.avoid_groups) == groups
    assert list(e.avoid_types) == sorted({g.split(".")[0] for g in groups}, key=["underpass", "flood_history",
                                                                                  "riverside"].index)
    assert label_of(plan) == route_label
    # Every level asks the same questions: the plain request, then one search per group set.
    # Every round asks for alternates (they are candidates).
    assert [len(c["exclude_polygons"]) for c in fake.calls] == [0, 1, 2, 3]
    assert [c["alternates"] for c in fake.calls] == [2, 2, 2, 2]
    if level == 0:
        assert e.status == "no_avoid_level" and e.message.startswith("현재 강수 단계에서는 피하는 구역이 없습니다")
        assert plan.route is plan.baseline
    else:
        assert e.status == "avoided"
        assert {z["type"] for z in e.avoided_zones} == set(avoided)
        assert e.added_duration_s > 0
        assert plan.metrics()["route"]["exposure_score"] < plan.metrics()["baseline"]["exposure_score"]


@pytest.mark.parametrize("rn1, alert, params, level", [
    (0, "advisory", None, 1), (0, "warning", None, 2), (55, "advisory", None, 2), (75, "warning", None, 3),
    (10, "advisory", {"alert_min_level": {"advisory": 2}}, 2),
    (35, "none", {"rain_thresholds_mm": [40, 60, 80]}, 0),
])
def test_alert_rule_and_threshold_overrides(rn1, alert, params, level):
    plan, _ = run("tiered_rain", rn1=rn1, alert=alert, params=params)
    assert plan.explanation.level == level


@pytest.mark.parametrize("name, params", [
    ("tiered_rain", {"lambda": 1}),
    ("baseline", {"rain_thresholds_mm": [30, 50, 70]}),
    ("rerank", {"lambda": 11}),
    ("rerank", {"lambda": -1}),
    ("hard_exclude", {"weights": {"bridge": 1}}),
    ("hard_exclude", {"avoid_buffer_m": {"underpass": 500}}),
    ("tiered_rain", {"rain_thresholds_mm": [50, 30, 70]}),
    ("tiered_rain", {"alert_min_level": {"advisory": 3}}),
    ("tiered_rain", {"unknown": True}),
])
def test_invalid_parameter_overrides_are_rejected(name, params):
    with pytest.raises(ParamsError, match="허용되지 않는 파라미터"):
        run(name, params=params)


def test_unknown_strategy_is_rejected():
    with pytest.raises(registry.UnknownStrategy):
        registry.get_strategy("no_such_strategy")


def assert_failed(plan, reason_part):
    e = plan.explanation
    assert e.status == "avoid_failed"
    assert e.warning == "위험 구역을 피하는 경로를 찾지 못했습니다."
    assert reason_part in e.failure_reason
    assert plan.route is plan.baseline
    assert {z["id"] for z in e.passed_zones} >= {"z-underpass"}  # zones the returned route passes


def test_destination_inside_zone_returns_baseline_with_warning():
    plan, fake = run("tiered_rain", rn1=35, request=RouteRequest(ORIGIN, (126.82, LAT)))
    assert_failed(plan, "목적지가 'z-underpass' 구역 안에 있습니다")
    assert max(len(c["exclude_polygons"]) for c in fake.calls) == 2  # flood + riverside, never the blocked zone


def test_no_route_after_exclusion_returns_baseline_with_warning():
    plan, _ = run("hard_exclude", fake=engine(CANDIDATES[:1]))
    assert_failed(plan, "도착할 수 있는 경로가 없습니다")


@pytest.mark.parametrize("fake", [
    engine(limits=ExcludeLimits(max_perimeter_m=1e9, max_vertices=3)),
    engine(error=lambda call: ExcludeLimitExceeded() if call["exclude_polygons"] else None),
])
def test_exclusion_limits_return_baseline_with_warning(fake):
    plan, _ = run("tiered_rain", rn1=75, fake=fake)
    assert_failed(plan, "경로 엔진이 처리하지 못했습니다")


def test_unroutable_location_after_exclusion_returns_baseline_with_warning():
    fake = engine(error=lambda call: LocationNotRoutable() if call["exclude_polygons"] else None)
    plan, _ = run("tiered_rain", rn1=75, fake=fake)
    assert_failed(plan, "근처 도로")


def test_missing_baseline_raises_route_not_found():
    with pytest.raises(RouteNotFound):
        run("tiered_rain", rn1=75, fake=engine(error=NoRouteFound()))


def test_only_zones_on_the_route_are_excluded_and_new_ones_are_added():
    # 'far' is never on a route: it must not be sent. 'second' lies only on the first detour,
    # so a second round adds it and the route moves to the next detour.
    far = make_zone("far", "flood_history", square(126.85, LAT + 0.05, 100))
    second = make_zone("second", "flood_history", square(126.86, LAT + 0.005, 100))
    plan, fake = run("tiered_rain", rn1=55, layer=corridor_layer([far, second]))
    assert plan.explanation.status == "avoided"
    # Each group set searches from the first route's zones, then from those of all three routes
    # ('second' is on the third). Level 2 from the first route: z-underpass and z-flood_history,
    # then 'second' is added. 'far' is never sent.
    assert [len(c["exclude_polygons"]) for c in fake.calls] == [0, 1, 2, 2, 3, 3, 3, 4]
    assert all(c["alternates"] == 2 for c in fake.calls[1:])  # enough budget: alternates every round
    assert label_of(plan) == "avoid-all"


def _slow_plan(rn1, extra_zones):
    def slow(call):
        time.sleep(0.3)

    fake = engine(error=slow)
    resolved = resolve(get_config(), registry.get_strategy("tiered_rain").params_model, {})
    ctx = StrategyContext(weather=demo_weather(rn1, "none", resolved), layer=corridor_layer(extra_zones),
                          engine=fake, params=resolved, deadline=time.monotonic() + 1.5)
    return registry.get_strategy("tiered_rain").plan(REQUEST, ctx), fake


def test_running_out_of_time_is_reported_as_a_timeout():
    # 75 mm: every type is hard. The budget is gone after the level 1 search, before anything
    # avoids the riverside zone. Later searches stop instead of failing with an engine timeout.
    plan, fake = _slow_plan(75, [])
    e = plan.explanation
    assert e.status == "avoid_failed"
    assert "제한 시간" in e.failure_reason
    assert fake.calls[1]["alternates"] == 0  # short budget: no alternates


def test_short_budget_still_returns_a_partial_route_when_one_exists():
    # 55 mm: normal flood zones are soft, so a candidate that only passes them is usable.
    second = make_zone("second", "flood_history", square(126.86, LAT + 0.005, 100), tier="normal")
    plan, _ = _slow_plan(55, [second])
    assert plan.explanation.status in ("partially_avoided", "avoided")
    assert not plan.route.exposure.zone_ids(["underpass"])


def test_nothing_on_route_skips_the_exclusion_call():
    far = make_zone("far", "underpass", square(126.85, LAT + 0.05, 100))
    plan, fake = run("hard_exclude", layer=corridor_layer_without_route(far))
    assert plan.explanation.status == "nothing_on_route"
    assert plan.explanation.message.startswith("이 경로에는 지금 피해야 할 구역이 없습니다")
    assert len(fake.calls) == 1


def corridor_layer_without_route(*zones):
    from app.risk.layer import RiskLayer
    return RiskLayer(zones)


@pytest.mark.parametrize("lam, expected", [(0, "straight"), (1, "avoid-all")])
def test_rerank_picks_the_smallest_score(lam, expected):
    plan, fake = run("rerank", params={"lambda": lam})
    assert label_of(plan) == expected and plan.explanation.status == "ranked"
    assert len(fake.calls) == 4
    scores = [r.osrm["duration"] + lam * r.exposure.score for r in (plan.route, *plan.alternatives)]
    assert scores == sorted(scores) and len(plan.alternatives) == 3  # duplicates removed


@pytest.mark.parametrize("name", NAMES)
def test_same_input_same_plan(name):
    assert run(name, rn1=55)[0].to_dict() == run(name, rn1=55)[0].to_dict()


def test_new_strategy_module_is_discovered(tmp_path):
    module = tmp_path / "tmp_shortest_plugin.py"
    module.write_text(
        "from app.strategies.base import baseline_routes, make_plan\n"
        "from app.strategies.params import CommonParams\n"
        "from app.strategies.registry import register\n"
        "@register('tmp_shortest')\n"
        "class TmpShortest:\n"
        "    label = 'tmp'\n    description = 'tmp'\n    params_model = CommonParams\n"
        "    def plan(self, request, ctx):\n"
        "        r = baseline_routes(ctx, request)[0]\n"
        "        return make_plan(ctx, route=r, baseline=r, status='baseline')\n", encoding="utf-8")
    strategies_package.__path__.append(str(tmp_path))
    registry.reset_discovery()
    try:
        assert "tmp_shortest" in {s["name"] for s in registry.list_strategies()}
        plan, _ = run("tmp_shortest")
        assert plan.explanation.status == "baseline"
    finally:
        strategies_package.__path__.remove(str(tmp_path))
        registry.unregister("tmp_shortest")
        sys.modules.pop("app.strategies.tmp_shortest_plugin", None)
        registry.reset_discovery()


# ---- B안: hard/soft avoidance and candidate pool (design.md 5.7) ------------------------------

SLOW_CLEAR = [  # avoiding every flood zone costs a long detour
    {"label": "straight", "coords": CANDIDATES[0]["coords"], "duration": 600.0},
    {"label": "avoid-u", "coords": CANDIDATES[1]["coords"], "duration": 700.0},
    {"label": "avoid-uf", "coords": CANDIDATES[2]["coords"], "duration": 2000.0},
    {"label": "avoid-all", "coords": CANDIDATES[3]["coords"], "duration": 2100.0},
]


def test_level_rules_split_hard_and_soft():
    plan, _ = run("tiered_rain", rn1=55)
    e = plan.explanation
    assert (e.hard_groups, e.soft_groups) == (("underpass", "flood_history.high"),
                                              ("flood_history.normal", "flood_history.raised"))
    assert e.avoid_types == ("underpass", "flood_history")
    plan, _ = run("tiered_rain", rn1=35)
    assert (plan.explanation.hard_groups, plan.explanation.soft_groups) == (("underpass",), ("flood_history.high",))
    plan, _ = run("tiered_rain", rn1=75)
    assert plan.explanation.hard_groups == ("underpass", *ALL_FLOOD, "riverside")


def test_soft_zone_is_passed_when_the_detour_costs_more_than_its_penalty():
    plan, fake = run("tiered_rain", rn1=55, fake=engine(SLOW_CLEAR))
    e = plan.explanation
    assert label_of(plan) == "avoid-u"  # underpass avoided, flood zone passed (cheaper than +1300 s)
    assert e.status == "partially_avoided" and e.warning == "일부 위험 구역을 지나는 경로입니다."
    assert e.message.startswith("지하차도·침수 이력(우선 회피) 구역은 모두 피했고, 침수 이력(일반) 구역 1곳(")
    assert {z["id"] for z in e.passed_zones} >= {"z-flood_history"}
    assert [z["id"] for z in e.avoided_zones] == ["z-underpass"]
    # fastest candidate avoiding both types is avoid-uf (2000 s)
    assert e.clear_option["added_duration_s"] == 1300.0 and isinstance(e.clear_option["added_distance_m"], float)
    assert all(not r.exposure.zone_ids(["underpass"]) for r in (plan.route, *plan.alternatives))


def test_higher_soft_penalty_prefers_the_clear_detour():
    plan, _ = run("tiered_rain", rn1=55, fake=engine(SLOW_CLEAR),
                  params={"entry_penalty_s": {"flood_history": 3600}})
    assert plan.route.osrm["duration"] == 2000.0 and plan.explanation.status == "avoided"
    assert plan.explanation.clear_option is None


def test_hard_zones_are_never_chosen_even_when_much_faster():
    plan, _ = run("tiered_rain", rn1=75, fake=engine(SLOW_CLEAR))
    assert plan.route.osrm["duration"] == 2100.0 and plan.explanation.status == "avoided"


def test_candidates_from_earlier_rounds_are_kept():
    # zone A lies on the 'north' detour. 'near' runs 15 m outside A: clear by the score but inside
    # A's 30 m avoidance buffer, so once A is excluded the engine stops returning it. The old code
    # kept only the last round ('far', 1500 s); 'near' (700 s) came back as a round-1 alternative.
    zone_u = make_zone("u", "underpass", square(126.82, LAT, 100))
    zone_a = make_zone("a", "underpass", square(126.85, LAT + 0.01, 100))
    near_lat = LAT + 0.01 + (100 + 15) / 111_000
    rows = [
        {"label": "straight", "coords": [ORIGIN, DESTINATION], "duration": 600.0},
        {"label": "north", "coords": detour_to(126.86, LAT + 0.01), "duration": 650.0},
        {"label": "straight2", "coords": [ORIGIN, (126.85, LAT - 0.0001), DESTINATION], "duration": 610.0},
        {"label": "near", "coords": detour_to(126.86, near_lat), "duration": 700.0},
        {"label": "far", "coords": detour_to(126.86, LAT + 0.03), "duration": 1500.0},
    ]
    plan, fake = run("hard_exclude", fake=engine(rows), layer=corridor_layer_without_route(zone_u, zone_a))
    assert plan.route.osrm["duration"] == 700.0 and plan.explanation.status == "avoided"
    assert plan.route.label == "탐색 1회차 대안 1"
    assert [len(c["exclude_polygons"]) for c in fake.calls] == [0, 1, 2, 2]


def detour_to(until_lon, lat):
    return [ORIGIN, (126.81, LAT), (126.81, lat), (until_lon, lat), (until_lon, LAT), DESTINATION]


def test_soft_zone_covering_the_destination_is_not_excluded():
    plan, fake = run("tiered_rain", rn1=55, request=RouteRequest(ORIGIN, (126.85, LAT)))
    assert plan.explanation.status != "avoid_failed"
    assert len(fake.calls[1]["exclude_polygons"]) == 1  # underpass only; the flood zone stays in the cost


@pytest.mark.parametrize("name, params", [
    ("tiered_rain", {"entry_penalty_s": {"flood_history": 4000}}),
    ("tiered_rain", {"per_m_penalty_s": {"bridge": 1}}),
    ("rerank", {"entry_penalty_s": {"flood_history": 10}}),
])
def test_invalid_penalty_overrides_are_rejected(name, params):
    with pytest.raises(ParamsError):
        run(name, params=params)


# ---- flood_history terrain tiers (design.md 5.8) ---------------------------------------------

# Avoiding the flood zone costs +250 s over avoid-u. Passing it (~200 m) costs
# (120 + 1 x 200) x scale: high 480 s, normal 320 s, raised 160 s.
TIER_DETOUR = [
    {"label": "straight", "coords": CANDIDATES[0]["coords"], "duration": 600.0},
    {"label": "avoid-u", "coords": CANDIDATES[1]["coords"], "duration": 700.0},
    {"label": "avoid-uf", "coords": CANDIDATES[2]["coords"], "duration": 950.0},
    {"label": "avoid-all", "coords": CANDIDATES[3]["coords"], "duration": 1050.0},
]


@pytest.mark.parametrize("rn1, tier, expected, status", [
    (35, "high", "avoid-uf", "avoided"),       # soft at level 1, 480 s > 250 s detour
    (35, None, "avoid-uf", "avoided"),         # unknown tier is treated as high
    (35, "normal", "avoid-u", "avoided"),      # not avoided at level 1
    (35, "raised", "avoid-u", "avoided"),
    (55, "normal", "avoid-uf", "avoided"),     # soft, 320 s > 250 s
    (55, "raised", "avoid-u", "partially_avoided"),  # soft, 160 s < 250 s: passed
    (75, "raised", "avoid-all", "avoided"),    # level 3: every tier is hard
])
def test_flood_tier_decides_how_strongly_a_zone_is_avoided(rn1, tier, expected, status):
    plan, _ = run("tiered_rain", rn1=rn1, fake=engine(TIER_DETOUR), layer=corridor_layer(flood_tier=tier))
    assert label_of(plan) == expected and plan.explanation.status == status


def test_high_tier_is_hard_at_level_2_even_when_much_slower():
    rows = [*TIER_DETOUR[:2], {**TIER_DETOUR[2], "duration": 5000.0}, {**TIER_DETOUR[3], "duration": 5100.0}]
    plan, _ = run("tiered_rain", rn1=55, fake=engine(rows), layer=corridor_layer(flood_tier="high"))
    assert label_of(plan) == "avoid-uf" and plan.explanation.status == "avoided"
    assert plan.explanation.message == "지하차도·침수 이력 구역을 피한 경로입니다."


def test_partial_message_names_the_tier_that_is_passed():
    plan, _ = run("tiered_rain", rn1=55, fake=engine(TIER_DETOUR), layer=corridor_layer(flood_tier="raised"))
    e = plan.explanation
    assert e.message.startswith("지하차도·침수 이력(우선 회피) 구역은 모두 피했고, 침수 이력(주변보다 높은 편) 구역 1곳(")
    assert e.clear_option["added_duration_s"] == 250.0
    assert [z["id"] for z in e.avoided_zones] == ["z-underpass"]


def test_penalty_scale_multiplies_the_type_penalty():
    from app.strategies.base import soft_penalty

    plan, _ = run("tiered_rain", rn1=55, fake=engine(TIER_DETOUR), layer=corridor_layer(flood_tier="raised"))
    resolved = resolve(get_config(), registry.get_strategy("tiered_rain").params_model, None)
    ctx = StrategyContext(weather=demo_weather(55, "none", resolved), layer=corridor_layer(flood_tier="raised"),
                          engine=engine(), params=resolved, deadline=time.monotonic() + 10)
    passed = next(z for z in plan.route.exposure.passes if z.zone.id == "z-flood_history")
    expected = (120 + 1 * passed.length_m) * 0.5
    assert soft_penalty(ctx, plan.route, ["flood_history.raised"]) == pytest.approx(expected)
    assert soft_penalty(ctx, plan.route, ["flood_history.normal"]) == 0  # other tiers are not charged


# ---- common candidates: every strategy and level chooses from the same routes (design.md 5.7) --

# The engine's first route is not the fastest, and the fastest only shows up in an exclusion round.
FAST_DETOUR = [
    {"label": "straight", "coords": CANDIDATES[0]["coords"], "duration": 900.0},
    {"label": "avoid-u", "coords": CANDIDATES[1]["coords"], "duration": 950.0},
    {"label": "avoid-uf", "coords": CANDIDATES[2]["coords"], "duration": 1000.0},
    {"label": "avoid-all", "coords": CANDIDATES[3]["coords"], "duration": 800.0},
]


def test_level_0_takes_the_fastest_candidate_not_the_engines_first_route():
    plan, _ = run("tiered_rain", rn1=0, fake=engine(FAST_DETOUR))
    assert label_of(plan) == "avoid-all" and plan.route is plan.baseline
    assert plan.explanation.status == "no_avoid_level" and plan.baseline.label == "기본 경로"


def test_the_fastest_route_is_the_baseline_of_every_strategy():
    baseline_plan, _ = run("baseline", fake=engine(FAST_DETOUR))
    assert baseline_plan.route is baseline_plan.baseline
    durations = [baseline_plan.route.osrm["duration"], *(a.osrm["duration"] for a in baseline_plan.alternatives)]
    assert durations == [800.0, 900.0, 950.0, 1000.0]
    for name in NAMES:
        plan, _ = run(name, rn1=55, fake=engine(FAST_DETOUR))
        assert plan.baseline.osrm["duration"] == 800.0 and plan.explanation.added_duration_s >= 0


@pytest.mark.parametrize("rows", [CANDIDATES, SLOW_CLEAR, TIER_DETOUR, FAST_DETOUR])
@pytest.mark.parametrize("tier", ["high", "normal", "raised"])
def test_eta_never_falls_as_the_level_rises(rows, tier):
    plans = [run("tiered_rain", rn1=rn1, fake=engine(rows), layer=corridor_layer(flood_tier=tier))[0]
             for rn1 in (0, 35, 55, 75)]
    durations = [p.route.osrm["duration"] for p in plans]
    assert durations == sorted(durations)
    assert all(p.explanation.added_duration_s >= 0 for p in plans)


# ---- underpasses: tunnel lines and block points (design.md 4.5) --------------------------------

TUNNEL = [(126.84, LAT), (126.841, LAT)]
TUNNEL_BLOCK = (126.8402, LAT)
BESIDE = 6 / 111_000  # a surface lane inside the 12 m map polygon
THROUGH_TUNNEL = {"label": "tunnel", "coords": [ORIGIN, *TUNNEL, DESTINATION], "duration": 600.0}
SURFACE = {"label": "surface", "duration": 640.0,
           "coords": [ORIGIN, (126.84, LAT + BESIDE), (126.841, LAT + BESIDE), DESTINATION]}


def tunnel_layer():
    far = make_underpass("far", [[(126.87, LAT + 0.05), (126.871, LAT + 0.05)]], [(126.8702, LAT + 0.05)])
    return corridor_layer_without_route(make_underpass("u", [TUNNEL], [TUNNEL_BLOCK]), far)


def test_underpass_is_refused_at_level_1_but_the_lane_beside_it_stays_usable():
    rows = [THROUGH_TUNNEL, SURFACE]
    plan, _ = run("tiered_rain", rn1=0, fake=engine(rows), layer=tunnel_layer())
    assert plan.route.osrm["duration"] == 600.0 and plan.explanation.status == "no_avoid_level"
    assert [z["id"] for z in plan.explanation.passed_zones] == ["u"]
    plan, _ = run("tiered_rain", rn1=35, fake=engine(rows), layer=tunnel_layer())
    e = plan.explanation
    assert plan.route.osrm["duration"] == 640.0 and e.status == "avoided"
    assert [z["id"] for z in e.avoided_zones] == ["u"] and e.passed_zones == []


def test_every_underpass_is_excluded_from_the_first_round_whatever_the_route_passes():
    fastest_surface = {**SURFACE, "duration": 590.0}
    plan, fake = run("tiered_rain", rn1=35, fake=engine([fastest_surface, THROUGH_TUNNEL]), layer=tunnel_layer())
    assert plan.explanation.status == "nothing_on_route"
    assert [len(c["exclude_polygons"]) for c in fake.calls] == [0, 2]  # one ring per block point


def test_underpass_with_no_way_around_is_a_failure():
    plan, _ = run("tiered_rain", rn1=35, fake=engine([THROUGH_TUNNEL]), layer=tunnel_layer())
    e = plan.explanation
    assert e.status == "avoid_failed" and "도착할 수 있는 경로가 없습니다" in e.failure_reason
    assert [z["id"] for z in e.passed_zones] == ["u"]


def test_group_sets_with_the_same_zones_are_searched_once():
    only_underpass = corridor_layer_without_route(make_zone("u", "underpass", square(126.82, LAT, 100)))
    plan, fake = run("hard_exclude", layer=only_underpass)
    assert plan.explanation.status == "avoided"
    assert [len(c["exclude_polygons"]) for c in fake.calls] == [0, 1]
