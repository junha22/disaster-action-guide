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
