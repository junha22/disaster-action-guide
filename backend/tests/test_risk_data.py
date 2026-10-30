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
        assert zone.is_dummy and "더미" in zone.source_name and "더미" in zone.name


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
