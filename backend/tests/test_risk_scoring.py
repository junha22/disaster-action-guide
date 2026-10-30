import pytest
import yaml
from shapely.geometry import LineString

from app import config as config_module
from app.config import ConfigError, get_config, parse_config, rain_level
from app.risk.geo import to_metric
from app.risk.scoring import score_route

from routing_fixtures import DESTINATION, LAT, ORIGIN, corridor_layer, make_zone, square

WEIGHTS = {"underpass": 3.0, "flood_history": 2.0, "riverside": 1.0}


def metric_overlap(coords, zone):
    return to_metric(LineString(coords)).intersection(zone.metric).length


def test_score_is_weighted_length_inside_original_zones():
    layer = corridor_layer()
    route = [ORIGIN, DESTINATION]
    exposure = score_route(route, layer, WEIGHTS)
    lengths = {z.type: metric_overlap(route, z) for z in layer.zones}
    assert all(150 < v < 250 for v in lengths.values())  # ~200 m through each 200 m square
    assert exposure.by_type_m == pytest.approx(lengths)
    assert exposure.score == pytest.approx(sum(lengths[t] * w for t, w in WEIGHTS.items()))
    assert exposure.zone_ids() == {"z-underpass", "z-flood_history", "z-riverside"}
    assert exposure.zone_ids(["underpass"]) == {"z-underpass"}


def test_buffer_is_not_part_of_the_score_and_inactive_zones_are_ignored():
    # 20 m north of the zone edge: inside a 30 m avoidance buffer, outside the zone itself.
    offset = (100 + 20) / 111_000
    near = [(126.81, LAT + offset), (126.83, LAT + offset)]
    inactive = make_zone("z-off", "underpass", square(126.86, LAT, 100), active=False)
    layer = corridor_layer(extra=[inactive])
    assert score_route(near, layer, WEIGHTS).score == 0
    # Crosses the active flood zone (126.85) and the inactive zone (126.86).
    assert score_route([(126.845, LAT), (126.865, LAT)], layer, WEIGHTS).zone_ids() == {"z-flood_history"}


def test_avoid_polygons_add_buffer_and_detect_contained_points():
    layer = corridor_layer()
    buffers = {"underpass": 30, "flood_history": 20, "riverside": 50}
    polygons = layer.avoid_polygons(["underpass"], buffers)
    assert [p.zone.id for p in polygons] == ["z-underpass"]
    ring = polygons[0].rings[0]
    assert ring[0] == ring[-1]
    assert polygons[0].metric.area > layer.zones[2].metric.area  # grown by the buffer
    inside_buffer = (126.82, LAT + (100 + 20) / 111_000)
    assert [z.id for z in layer.containing(inside_buffer, polygons)] == ["z-underpass"]
    assert layer.containing(ORIGIN, polygons) == []


@pytest.mark.parametrize("rn1, alert, expected", [
    (0, "none", 0), (29, "none", 0), (29.9, "none", 0), (30, "none", 1), (49, "none", 1),
    (50, "none", 2), (69, "none", 2), (70, "none", 3), (100, "none", 3),
    (0, "advisory", 1), (0, "warning", 2), (55, "advisory", 2), (75, "warning", 3),
])
def test_rain_level_thresholds_and_alert_minimum(rn1, alert, expected):
    assert rain_level(rn1, alert, (30, 50, 70), {"advisory": 1, "warning": 2}) == expected


def test_shipped_config_is_valid():
    cfg = get_config()
    assert cfg.rain_levels.thresholds_mm == (30, 50, 70)
    assert cfg.default_strategy == "tiered_rain"
    assert cfg.zone_types["underpass"].weight == 3


@pytest.mark.parametrize("mutate", [
    lambda d: d["rain_levels"].__setitem__("thresholds_mm", [50, 30, 70]),
    lambda d: d["zone_types"]["underpass"].__setitem__("weight", -1),
    lambda d: d["zone_types"].__setitem__("bridge", {"label": "x", "weight": 1, "avoid_buffer_m": 1,
                                                     "color": "#000000"}),
    lambda d: d["rain_levels"]["avoid_by_level"].__setitem__(2, ["riverside"]),
    lambda d: d["alert_min_level"].__setitem__("advisory", 3),
    lambda d: d["rain_levels"]["avoid_by_level"].__setitem__(2, {"hard": ["underpass"], "soft": ["underpass"]}),
    lambda d: d["rain_levels"]["avoid_by_level"].__setitem__(
        3, {"hard": [], "soft": ["underpass", "flood_history", "riverside"]}),
    lambda d: d["zone_types"]["flood_history"].__setitem__("entry_penalty_s", -1),
])
def test_invalid_config_is_rejected_with_reason(mutate):
    data = yaml.safe_load(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
    mutate(data)
    with pytest.raises(ConfigError, match="strategies.yaml"):
        parse_config(data)


FLOOD_GROUPS = ("flood_history.high", "flood_history.normal", "flood_history.raised")


def test_level_rules_hard_soft_and_legacy_list_format():
    cfg = get_config().rain_levels.avoid_by_level
    assert (cfg[1].hard_groups, cfg[1].soft_groups) == (("underpass",), ("flood_history.high",))
    assert (cfg[2].hard_groups, cfg[2].soft_groups) == (("underpass", "flood_history.high"),
                                                        ("flood_history.normal", "flood_history.raised"))
    assert cfg[3].hard_groups == ("underpass", *FLOOD_GROUPS, "riverside")
    assert cfg[2].all == ("underpass", "flood_history")
    data = yaml.safe_load(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
    data["rain_levels"]["avoid_by_level"] = {0: [], 1: ["underpass"], 2: ["underpass", "flood_history"],
                                             3: ["underpass", "flood_history", "riverside"]}
    legacy = parse_config(data).rain_levels.avoid_by_level
    assert legacy[2].hard_groups == ("underpass", *FLOOD_GROUPS) and legacy[2].soft_groups == ()


def test_group_helpers_expand_types_and_default_unknown_tiers():
    assert config_module.expand_groups(["riverside", "flood_history"]) == (*FLOOD_GROUPS, "riverside")
    assert config_module.expand_groups(["flood_history.raised", "underpass"]) == ("underpass", "flood_history.raised")
    assert config_module.zone_group("flood_history", "raised") == "flood_history.raised"
    assert config_module.zone_group("flood_history", None) == "flood_history.high"   # most cautious
    assert config_module.zone_group("flood_history", "bogus") == "flood_history.high"
    assert config_module.zone_group("underpass", "high") == "underpass"               # no tiers
    labels = get_config().group_labels()
    assert labels["flood_history.raised"] == "침수 이력(주변보다 높은 편)" and labels["underpass"] == "지하차도"
    assert get_config().penalty_scales() == {"underpass": 1.0, "flood_history.high": 1.5,
                                             "flood_history.normal": 1.0, "flood_history.raised": 0.5,
                                             "riverside": 1.0}


@pytest.mark.parametrize("mutate", [
    lambda d: d["rain_levels"]["avoid_by_level"].__setitem__(1, {"hard": ["flood_history.low"], "soft": []}),
    # the type name covers every tier, so this overlaps
    lambda d: d["rain_levels"]["avoid_by_level"].__setitem__(
        2, {"hard": ["underpass", "flood_history"], "soft": ["flood_history.raised"]}),
    # level 2 must keep level 1's hard and soft groups
    lambda d: d["rain_levels"]["avoid_by_level"].__setitem__(2, {"hard": ["underpass"], "soft": []}),
    lambda d: d["zone_types"]["flood_history"]["tiers"].pop("raised"),
    lambda d: d["zone_types"]["underpass"].__setitem__("tiers", {"high": {"label": "x"}}),
    lambda d: d["zone_types"]["flood_history"]["tiers"]["high"].__setitem__("penalty_scale", -1),
])
def test_invalid_tier_config_is_rejected(mutate):
    data = yaml.safe_load(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
    mutate(data)
    with pytest.raises(ConfigError, match="strategies.yaml"):
        parse_config(data)


def test_zone_ids_and_avoid_polygons_accept_group_keys():
    high = make_zone("z-high", "flood_history", square(126.86, LAT, 50), tier="high")
    layer = corridor_layer(extra=[high])  # corridor flood zone is "normal"
    exposure = score_route([ORIGIN, DESTINATION], layer, WEIGHTS)
    assert exposure.zone_ids(["flood_history.high"]) == {"z-high"}
    assert exposure.zone_ids(["flood_history"]) == {"z-high", "z-flood_history"}
    buffers = {"underpass": 30, "flood_history": 20, "riverside": 50}
    assert [p.zone.id for p in layer.avoid_polygons(["flood_history.normal"], buffers)] == ["z-flood_history"]
