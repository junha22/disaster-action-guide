"""Requirement 3.2: points/lines become polygons, output is deterministic, invalid input is not written."""
import json
import math
from pathlib import Path
import sys

import pytest
from shapely.geometry import LineString, Point, shape

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data_pipeline"))

import build_risk_zones  # noqa: E402
import zones  # noqa: E402
from app.risk.geo import to_metric  # noqa: E402

RADIUS = {"underpass": {"Point": 50, "LineString": 12}, "riverside": {"LineString": 40}}


def record(**overrides):
    base = {"id": "z1", "name": "test", "type": "underpass", "source_name": "test",
            "source_url": "https://www.data.go.kr", "checked_at": "2026-10-30",
            "geometry": {"type": "Point", "coordinates": [126.85, 35.15]}}
    return {**base, **overrides}


def test_point_becomes_circle_with_default_radius():
    polygon = zones.to_polygon(record(), RADIUS)
    area = to_metric(polygon).area
    assert area == pytest.approx(math.pi * 50 ** 2, rel=0.02)
    assert polygon.contains(Point(126.85, 35.15))


def test_line_becomes_corridor_and_record_radius_overrides_default():
    line = {"type": "LineString", "coordinates": [[126.85, 35.15], [126.86, 35.15]]}
    default = to_metric(zones.to_polygon(record(type="riverside", geometry=line), RADIUS))
    custom = to_metric(zones.to_polygon(record(type="riverside", geometry=line, radius_m=10), RADIUS))
    length = to_metric(LineString(line["coordinates"])).length
    assert default.area == pytest.approx(length * 80 + math.pi * 40 ** 2, rel=0.03)
    assert custom.area < default.area


def test_polygon_input_is_kept_and_missing_radius_fails():
    square = {"type": "Polygon", "coordinates": [[[126.85, 35.15], [126.851, 35.15], [126.851, 35.151],
                                                  [126.85, 35.151], [126.85, 35.15]]]}
    assert zones.to_polygon(record(geometry=square), RADIUS).equals(shape(square))
    with pytest.raises(zones.PipelineError, match="no radius"):
        zones.to_polygon(record(type="flood_history"), RADIUS)


def test_same_input_gives_identical_output():
    records = [record(id="b"), record(id="a", geometry={"type": "LineString",
                                                        "coordinates": [[126.85, 35.15], [126.851, 35.151]]})]
    first = zones.dumps(zones.build_collection(records, RADIUS))
    second = zones.dumps(zones.build_collection(list(reversed(records)), RADIUS))
    assert first == second
    assert [f["properties"]["id"] for f in json.loads(first)["features"]] == ["a", "b"]


def write_config(tmp_path, records):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"records": records}), encoding="utf-8")
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        "output: out/risk_zones.geojson\n"
        "default_radius_m:\n  underpass: {Point: 50, LineString: 12}\n"
        "sources:\n  - {reader: seed_json, path: seed.json}\n", encoding="utf-8")
    return config


def test_invalid_records_are_not_written(tmp_path, capsys):
    config = write_config(tmp_path, [record(id="dup"), record(id="dup"),
                                     record(id="far", geometry={"type": "Point", "coordinates": [129.0, 35.1]})])
    assert build_risk_zones.main(["--config", str(config)]) == 1
    assert not (tmp_path / "out").exists()
    message = capsys.readouterr().err
    assert "duplicate id" in message and "outside" in message


def test_valid_records_are_written(tmp_path):
    config = write_config(tmp_path, [record()])
    assert build_risk_zones.main(["--config", str(config)]) == 0
    data = json.loads((tmp_path / "out" / "risk_zones.geojson").read_text(encoding="utf-8"))
    assert data["features"][0]["geometry"]["type"] == "Polygon"
    assert build_risk_zones.main(["--config", str(config), "--check"]) == 0


def test_committed_risk_zones_match_the_pipeline():
    assert build_risk_zones.main(["--check"]) == 0


# ---- flood_history terrain tiers (design.md 5.8) ---------------------------------------------

TIERS = {"repeat_count": 2, "high_below_low_pct": 20, "raised_from_low_pct": 50}
SQUARE = {"type": "Polygon", "coordinates": [[[126.85, 35.15], [126.851, 35.15], [126.851, 35.151],
                                              [126.85, 35.151], [126.85, 35.15]]]}


@pytest.mark.parametrize("terrain, tier, reason", [
    ({"flood_count": 2, "low_pct": 60, "elev_status": "정상"}, "high", "2회 침수"),
    ({"flood_count": 1, "low_pct": 19.9, "elev_status": "정상"}, "high", "주변보다 낮은 땅"),
    ({"flood_count": 2, "low_pct": 5, "elev_status": "정상"}, "high", "2회 침수·주변보다 낮은 땅"),
    ({"flood_count": 1, "low_pct": None, "elev_status": "범위 밖"}, "high", "고도 자료 없음"),
    ({"flood_count": 1, "low_pct": 70, "elev_status": "일부 범위 밖"}, "high", "고도 자료 일부 없음"),
    ({}, "high", "고도 자료 없음"),
    ({"flood_count": 1, "low_pct": 20, "elev_status": "정상"}, "normal", "주변과 비슷한 높이"),
    ({"flood_count": 1, "low_pct": 49.9, "elev_status": "정상"}, "normal", "주변과 비슷한 높이"),
    ({"flood_count": 1, "low_pct": 50, "elev_status": "정상"}, "raised", "주변보다 높은 편"),
])
def test_flood_tier_from_repeat_count_and_relative_elevation(terrain, tier, reason):
    assert zones.flood_tier(terrain, TIERS) == (tier, reason)


def test_only_flood_records_get_terrain_and_tier():
    flood = record(id="f", type="flood_history", geometry=SQUARE, flood_count=1, elev_m=30.0, low_pct=55.0,
                   above_local_min_m=6.0, elev_status="정상")
    data = zones.build_collection([flood, record(id="u")], RADIUS, TIERS)
    props = {f["properties"]["id"]: f["properties"] for f in data["features"]}
    assert props["f"]["risk_tier"] == "raised" and props["f"]["tier_reason"] == "주변보다 높은 편"
    assert (props["f"]["low_pct"], props["f"]["elev_m"], props["f"]["flood_count"]) == (55.0, 30.0, 1)
    assert "risk_tier" not in props["u"] and "low_pct" not in props["u"]
    zones.check(data)
    with pytest.raises(zones.PipelineError, match="flood_tiers"):
        zones.build_collection([flood], RADIUS)


def tunnel_way(osm_id, coordinates, block):
    return {"type": "Feature", "properties": {"osm_id": osm_id, "highway": "primary", "name": None,
                                              "block_point": block},
            "geometry": {"type": "LineString", "coordinates": coordinates}}


# Two carriageways of one tunnel, 11 m apart, and another tunnel far to the east.
WAYS = [tunnel_way("w1", [[126.85, 35.15], [126.851, 35.15]], [126.8502, 35.15]),
        tunnel_way("w2", [[126.85, 35.1501], [126.851, 35.1501]], [126.8508, 35.1501]),
        tunnel_way("w3", [[126.90, 35.15], [126.901, 35.15]], [126.9005, 35.15])]


def test_underpass_point_takes_every_way_of_its_tunnel_and_misses_are_reported():
    points = [{"name": "가지하차도", "lon": 126.8505, "lat": 35.15},
              {"name": "없는지하차도", "lon": 126.87, "lat": 35.15},
              {"name": "나지하차도", "lon": 126.9005, "lat": 35.1503}]
    records, unmatched = zones.match_underpasses(points, WAYS, 60)
    assert unmatched == ["없는지하차도"]
    assert [r["id"] for r in records] == ["UND-001", "UND-003"]  # ids follow the list order
    assert records[0]["block_points"] == [[126.8502, 35.15], [126.8508, 35.1501]]
    assert records[0]["geometry"] == {"type": "MultiLineString", "coordinates": [WAYS[0]["geometry"]["coordinates"],
                                                                                 WAYS[1]["geometry"]["coordinates"]]}
    assert len(records[1]["block_points"]) == 1


def test_two_points_on_one_tunnel_stop_the_build():
    points = [{"name": "가", "lon": 126.8505, "lat": 35.15}, {"name": "나", "lon": 126.8506, "lat": 35.15}]
    with pytest.raises(zones.PipelineError, match="same tunnel"):
        zones.match_underpasses(points, WAYS, 60)


def test_underpass_reader_and_collection_keep_tunnel_lines(tmp_path, capsys):
    from readers import read_underpass_csv

    source = tmp_path / "underpasses.csv"
    source.write_text("시설물명,위도,경도\n가지하차도,35.15,126.8505\n없는지하차도,35.15,126.87\n", encoding="utf-8-sig")
    (tmp_path / "tunnels.geojson").write_text(json.dumps({"features": WAYS}), encoding="utf-8")
    [rec] = read_underpass_csv(source, "tunnels.geojson", 60, source_name="목록",
                               source_url="https://www.openstreetmap.org/copyright", checked_at="2026-10-31")
    assert capsys.readouterr().err.strip() == "UNDERPASS_UNMATCHED: 없는지하차도"
    assert rec["source_name"] == "목록" and rec["name"] == "가지하차도"
    data = zones.build_collection([rec], {"underpass": {"MultiLineString": 12}})
    zones.check(data)
    [feature] = data["features"]
    assert feature["geometry"]["type"] == "Polygon"  # both carriageways in one corridor
    assert feature["properties"]["centerline"]["type"] == "MultiLineString"
    assert len(feature["properties"]["block_points"]) == 2


def test_block_point_stays_away_from_the_road_over_the_tunnel():
    from extract_osm_tunnels import tunnel_features

    def way(osm_id, coordinates, **tags):
        return {"type": "Feature", "id": osm_id, "properties": tags,
                "geometry": {"type": "LineString", "coordinates": coordinates}}

    crossing = [[126.8505, 35.145], [126.8505, 35.155]]
    features = [way("w9", [[126.85, 35.15], [126.851, 35.15]], highway="primary", tunnel="yes", name="터널"),
                way("w8", crossing, highway="secondary"),
                way("w7", [[126.84, 35.15], [126.841, 35.15]], highway="footway", tunnel="yes"),
                way("w6", [[126.86, 35.15], [126.861, 35.15]], highway="motorway", tunnel="yes")]
    [tunnel] = tunnel_features(features)
    props = tunnel["properties"]
    assert (props["osm_id"], props["name"]) == ("w9", "터널")
    road = to_metric(LineString(crossing))
    assert to_metric(Point(props["block_point"])).distance(road) == pytest.approx(props["block_clearance_m"], abs=0.1)
    assert props["block_clearance_m"] > 30  # the middle would be on the road
    assert to_metric(LineString(tunnel["geometry"]["coordinates"])).distance(
        to_metric(Point(props["block_point"]))) < 1


def test_flood_reader_passes_elevation_through(tmp_path):
    from readers import read_flood_zone_geojson

    source = tmp_path / "flood.geojson"
    source.write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": SQUARE,
        "properties": {"id": "FLD-T-1", "name": "t", "type": "침수 이력", "active": True, "source_name": "s",
                       "source_url": "https://www.data.go.kr/a", "verified_date": "2026-10-30",
                       "flood_count": 2, "elev_m": 31.5, "elev_min_m": 30.0, "low_pct": 12.0,
                       "above_local_min_m": 1.0, "elev_status": "정상"}}]}), encoding="utf-8")
    [rec] = read_flood_zone_geojson(source)
    assert rec["type"] == "flood_history" and rec["flood_count"] == 2 and rec["low_pct"] == 12.0
    assert "elev_min_m" not in rec  # only the keys the app uses
