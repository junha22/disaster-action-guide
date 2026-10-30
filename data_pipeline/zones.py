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
from shapely.geometry import MultiPolygon, Polygon, mapping, shape  # noqa: E402
from shapely.geometry.polygon import orient  # noqa: E402

from app.risk.geo import to_metric, to_wgs84  # noqa: E402
from app.risk.validation import validate_zone_collection  # noqa: E402

PROPERTY_KEYS = ("id", "name", "type", "active", "source_name", "source_url", "checked_at",
                 "is_dummy", "note")
DIGITS = 6


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


def build_collection(records: Iterable[dict], default_radius_m: dict) -> dict:
    features = []
    for record in sorted(records, key=lambda r: str(r.get("id"))):
        props = {k: record.get(k) for k in PROPERTY_KEYS}
        props["active"] = bool(record.get("active", True))
        props["is_dummy"] = bool(record.get("is_dummy", False))
        props["note"] = record.get("note") or ""
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
