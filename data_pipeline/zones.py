"""Point/line -> polygon conversion and output formatting for risk_zones.geojson.

Geometry and validation come from the backend package so both sides use one definition.
"""
import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

import shapely  # noqa: E402
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape  # noqa: E402
from shapely.geometry.polygon import orient  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from app.risk.geo import to_metric, to_wgs84  # noqa: E402
from app.risk.validation import TERRAIN_KEYS, validate_zone_collection  # noqa: E402

PROPERTY_KEYS = ("id", "name", "type", "active", "source_name", "source_url", "checked_at",
                 "is_dummy", "note")
# flood_history only: TERRAIN_KEYS (repeat count, DEM elevation) from the source, then the tier.
TIER_RULE_KEYS = ("repeat_count", "high_below_low_pct", "raised_from_low_pct")
ELEV_OK = "정상"
DIGITS = 6
# OSM maps each carriageway of a tunnel as its own way; ways this close belong to one tunnel.
TUNNEL_JOIN_M = 20.0


class PipelineError(RuntimeError):
    pass


def to_polygon(record: dict, default_radius_m: dict[str, dict[str, float]]):
    """Return a WGS84 Polygon/MultiPolygon for one record."""
    geom = shape(record["geometry"])
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    radius = record.get("radius_m") or default_radius_m.get(record.get("type"), {}).get(geom.geom_type)
    if not radius or radius <= 0:
        raise PipelineError(f"{record.get('id')}: no radius for {record.get('type')} {geom.geom_type}")
    return to_wgs84(to_metric(geom).buffer(float(radius)))


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, DIGITS)
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


def _clean(geom):
    geom = shapely.set_precision(geom, 10 ** -DIGITS)
    if isinstance(geom, MultiPolygon):
        geom = MultiPolygon([orient(p, 1.0) for p in geom.geoms])
    elif isinstance(geom, Polygon):
        geom = orient(geom, 1.0)
    out = mapping(geom)
    return {"type": out["type"], "coordinates": _round(out["coordinates"])}


def flood_tier(record: dict, rules: dict) -> tuple[str, str]:
    """(risk_tier, tier_reason) of a flood_history zone (design.md 5.8).

    Repeat count first, relative elevation (low_pct) second. Missing or partial elevation is
    treated like low ground, so unknown zones are avoided earlier, not later.
    """
    reasons = []
    count, low, status = record.get("flood_count"), record.get("low_pct"), record.get("elev_status")
    if isinstance(count, int) and count >= rules["repeat_count"]:
        reasons.append(f"{count}회 침수")
    if status != ELEV_OK or low is None:
        reasons.append("고도 자료 일부 없음" if status == "일부 범위 밖" else "고도 자료 없음")
    elif low < rules["high_below_low_pct"]:
        reasons.append("주변보다 낮은 땅")
    if reasons:
        return "high", "·".join(reasons)
    if low >= rules["raised_from_low_pct"]:
        return "raised", "주변보다 높은 편"
    return "normal", "주변과 비슷한 높이"


def match_underpasses(points: list[dict], tunnels: list[dict], radius_m: float) -> tuple[list[dict], list[str]]:
    """Tie each listed underpass ({name, lon, lat}) to its OSM tunnel (design.md 4.5).

    Returns underpass records and the names with no tunnel within radius_m. Ids follow the list
    order, so they stay the same when the list grows at the end.
    """
    ways = [(t, to_metric(shape(t["geometry"]))) for t in tunnels]
    joined = unary_union([metric.buffer(TUNNEL_JOIN_M) for _, metric in ways])
    groups = [[w for w in ways if w[1].intersects(blob)] for blob in getattr(joined, "geoms", [joined])]
    records: list[dict] = []
    unmatched: list[str] = []
    taken: dict[int, str] = {}
    for index, point in enumerate(points, 1):
        target = to_metric(Point(point["lon"], point["lat"]))
        gaps = [min(metric.distance(target) for _, metric in group) for group in groups]
        nearest = min(range(len(groups)), key=gaps.__getitem__)
        if gaps[nearest] > radius_m:
            unmatched.append(point["name"])
            continue
        if nearest in taken:
            raise PipelineError(f"{point['name']} and {taken[nearest]} match the same tunnel")
        taken[nearest] = point["name"]
        group = [t for t, _ in groups[nearest]]
        records.append({
            "id": f"UND-{index:03d}", "name": point["name"], "type": "underpass",
            "geometry": {"type": "MultiLineString", "coordinates": [t["geometry"]["coordinates"] for t in group]},
            "block_points": [t["properties"]["block_point"] for t in group],
            "note": f"목록 좌표에서 {gaps[nearest]:.0f}m 떨어진 OSM 터널 구간에 맞춤"})
    return records, unmatched


def build_collection(records: Iterable[dict], default_radius_m: dict, flood_tiers: dict | None = None) -> dict:
    features = []
    for record in sorted(records, key=lambda r: str(r.get("id"))):
        props = {k: record.get(k) for k in PROPERTY_KEYS}
        props["active"] = bool(record.get("active", True))
        props["is_dummy"] = bool(record.get("is_dummy", False))
        props["note"] = record.get("note") or ""
        if record.get("type") == "flood_history":
            missing = [k for k in TIER_RULE_KEYS if k not in (flood_tiers or {})]
            if missing:
                raise PipelineError(f"pipeline.yaml flood_tiers is missing {missing}")
            props.update({k: record.get(k) for k in TERRAIN_KEYS})
            props["risk_tier"], props["tier_reason"] = flood_tier(record, flood_tiers)
        if record.get("block_points"):
            line = record["geometry"]
            props["centerline"] = {"type": line["type"], "coordinates": _round(line["coordinates"])}
            props["block_points"] = _round(record["block_points"])
        features.append({"type": "Feature", "properties": props,
                         "geometry": _clean(to_polygon(record, default_radius_m))})
    return {"type": "FeatureCollection", "features": features}


def check(collection: dict) -> None:
    errors = validate_zone_collection(collection)
    if errors:
        raise PipelineError("validation failed:\n  " + "\n  ".join(errors))


def dumps(collection: dict) -> str:
    """One feature per line: stable and readable in diffs."""
    lines = [json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in collection["features"]]
    return '{"type":"FeatureCollection","features":[\n' + ",\n".join(lines) + "\n]}\n"
