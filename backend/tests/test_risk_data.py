"""Requirement 3.8 (and 3.1, 3.4, 1.7): the shipped data files are valid."""
import copy
import json
from pathlib import Path

import pytest
from shapely.geometry import shape

from app.config import ZONE_TYPES
from app.risk.geo import SERVICE_BBOX, in_service_area
from app.risk.layer import DATA_PATH, RiskLayer
from app.risk.validation import validate_zone_collection

DATA = json.loads(DATA_PATH.read_text(encoding="utf-8"))
DEMO = json.loads((Path(DATA_PATH).parent / "demo_points.json").read_text(encoding="utf-8"))


def test_shipped_zones_pass_validation():
    assert validate_zone_collection(DATA) == []


def test_ids_unique_types_allowed_and_sources_present():
    props = [f["properties"] for f in DATA["features"]]
    ids = [p["id"] for p in props]
    assert len(ids) == len(set(ids))
    assert {p["type"] for p in props} <= set(ZONE_TYPES)
    for p in props:
        assert p["source_name"].strip() and p["source_url"].startswith("https://")
        assert p["checked_at"] == "2026-10-30"


def test_geometries_are_valid_polygons_inside_gwangju():
    for feature in DATA["features"]:
        geom = shape(feature["geometry"])
        assert geom.geom_type in ("Polygon", "MultiPolygon")
        assert geom.is_valid and not geom.is_empty
        minx, miny, maxx, maxy = geom.bounds
        assert SERVICE_BBOX[0] <= minx and maxx <= SERVICE_BBOX[2]
        assert SERVICE_BBOX[1] <= miny and maxy <= SERVICE_BBOX[3]


def test_every_type_has_an_active_zone_and_dummies_are_marked():
    layer = RiskLayer.from_geojson(DATA)
    assert {z.type for z in layer.active()} == set(ZONE_TYPES)
    for zone in layer.zones:
        if zone.is_dummy:
            assert "더미" in zone.source_name and "더미" in zone.name
        else:  # real public data (data_pipeline/sources/gwangju_flood_zones.geojson)
            assert "더미" not in zone.source_name and "더미" not in zone.name
            assert zone.source_url.startswith("https://www.data.go.kr/")


def test_real_flood_history_zones_are_included():
    real = [z for z in RiskLayer.from_geojson(DATA).active(["flood_history"]) if not z.is_dummy]
    assert len(real) == 657
    assert all(z.id.startswith("FLD-") for z in real)


def test_real_flood_zones_have_terrain_tiers():
    """design.md 5.8: tiers come from data_pipeline (pipeline.yaml flood_tiers)."""
    layer = RiskLayer.from_geojson(DATA)
    real = [z for z in layer.active(["flood_history"]) if not z.is_dummy]
    counts = {t: sum(z.tier == t for z in real) for t in ("high", "normal", "raised")}
    assert counts == {"high": 182, "normal": 360, "raised": 115}
    assert all(z.tier_reason for z in real)
    assert all(z.group == f"flood_history.{z.tier}" for z in real)
    # zones without elevation are never put in a lower tier
    assert all(z.tier == "high" for z in real if (z.terrain or {}).get("elev_status") != "정상")
    for zone in layer.active(["underpass", "riverside"]):
        assert zone.tier is None and zone.group == zone.type
        assert zone.properties()["risk_tier"] is None and "low_pct" not in zone.properties()


def first_flood(data):
    return next(f for f in data["features"] if f["properties"]["type"] == "flood_history")


@pytest.mark.parametrize("mutate, expected", [
    (lambda p: p.__setitem__("risk_tier", "bogus"), "risk_tier must be one of"),
    (lambda p: p.__setitem__("type", "underpass"), "risk_tier must be one of []"),
    (lambda p: p.__setitem__("low_pct", 150), "low_pct must be between"),
    (lambda p: p.__setitem__("elev_m", "high"), "elev_m must be a number"),
    (lambda p: p.__setitem__("flood_count", 0), "flood_count must be a positive integer"),
    (lambda p: p.__setitem__("elev_status", "unknown"), "elev_status must be one of"),
])
def test_validator_rejects_bad_terrain_properties(mutate, expected):
    data = copy.deepcopy(DATA)
    mutate(first_flood(data)["properties"])
    assert any(expected in e for e in validate_zone_collection(data))


def bowtie(feature):
    feature["geometry"] = {"type": "Polygon", "coordinates": [[[126.85, 35.15], [126.86, 35.16], [126.86, 35.15],
                                                               [126.85, 35.16], [126.85, 35.15]]]}


@pytest.mark.parametrize("mutate, expected", [
    (lambda f: f["properties"].__setitem__("id", DATA["features"][1]["properties"]["id"]), "duplicate id"),
    (bowtie, "not a valid polygon"),
    (lambda f: f.__setitem__("geometry", {"type": "Point", "coordinates": [126.85, 35.15]}), "Polygon"),
    (lambda f: f["properties"].__setitem__("type", "bridge"), "type must be"),
    (lambda f: f["properties"].__setitem__("source_url", ""), "missing source_url"),
    (lambda f: f["properties"].pop("checked_at"), "missing checked_at"),
    (lambda f: f["geometry"]["coordinates"][0].__setitem__(0, [129.0, 35.1]), "outside"),
])
def test_validator_rejects_bad_zones(mutate, expected):
    data = copy.deepcopy(DATA)
    mutate(data["features"][0])
    assert any(expected in e for e in validate_zone_collection(data))


def test_demo_points_are_unique_and_inside_gwangju():
    points = DEMO["points"]
    assert 5 <= len(points) <= 8
    assert len({p["id"] for p in points}) == len(points)
    assert all(in_service_area(p["lon"], p["lat"]) and p["name"] and p["address"] for p in points)
