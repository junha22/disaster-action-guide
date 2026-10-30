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

from routing_fixtures import CANDIDATES, DESTINATION, LAT, ORIGIN, corridor_layer, make_zone, square

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
    assert set(data["explanation"]) == {"status", "level", "avoid_types", "avoided_zones", "passed_zones",
                                        "added_duration_s", "added_distance_m", "message", "warning",
                                        "failure_reason"}
    assert set(data["metrics"]) == {"route", "baseline", "alternatives"}
    reference, _ = run("baseline", rn1=75)
    assert shape_of(data["route"]) == shape_of(reference.to_dict()["route"])
    assert shape_of(data["metrics"]["route"]) == shape_of(reference.to_dict()["metrics"]["route"])


@pytest.mark.parametrize("rn1, level, avoided, route_label", [
    (0, 0, [], "straight"), (29, 0, [], "straight"),
    (30, 1, ["underpass"], "avoid-u"), (49, 1, ["underpass"], "avoid-u"),
    (50, 2, ["underpass", "flood_history"], "avoid-uf"), (69, 2, ["underpass", "flood_history"], "avoid-uf"),
    (70, 3, ["underpass", "flood_history", "riverside"], "avoid-all"),
])
def test_tiered_rain_boundaries(rn1, level, avoided, route_label):
    plan, fake = run("tiered_rain", rn1=rn1)
    e = plan.explanation
    assert e.level == level and list(e.avoid_types) == avoided
    assert label_of(plan) == route_label
    if level == 0:
        assert e.status == "no_avoid_level" and e.message.startswith("현재 강수 단계에서는 피하는 구역이 없습니다")
        assert len(fake.calls) == 1 and plan.route is plan.baseline
    else:
        # baseline, the avoiding route, then the same exclusions once more for alternates
        assert e.status == "avoided" and len(fake.calls) == 3
        assert len(fake.calls[1]["exclude_polygons"]) == len(avoided)
        assert fake.calls[1]["alternates"] == 0 and fake.calls[2]["alternates"] == 2
        assert fake.calls[2]["exclude_polygons"] == fake.calls[1]["exclude_polygons"]
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
    assert len(fake.calls) == 1


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
    assert len(fake.calls) == 4
    assert len(fake.calls[1]["exclude_polygons"]) == 2  # z-underpass, z-flood_history
    assert len(fake.calls[2]["exclude_polygons"]) == 3  # + second
    assert [c["alternates"] for c in fake.calls[1:]] == [0, 0, 2]  # only the final set asks for them
    assert label_of(plan) == "avoid-all"


def test_running_out_of_time_is_reported_as_a_timeout():
    # 'second' forces another round, but the budget is gone by then.
    second = make_zone("second", "flood_history", square(126.86, LAT + 0.005, 100))

    def slow(call):
        time.sleep(0.15)

    fake = engine(error=slow)
    resolved = resolve(get_config(), registry.get_strategy("tiered_rain").params_model, {})
    ctx = StrategyContext(weather=demo_weather(55, "none", resolved), layer=corridor_layer([second]),
                          engine=fake, params=resolved, deadline=time.monotonic() + 1.2)
    e = registry.get_strategy("tiered_rain").plan(REQUEST, ctx).explanation
    assert e.status == "avoid_failed"
    assert "제한 시간" in e.failure_reason


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
