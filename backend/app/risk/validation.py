"""Checks shared by the data pipeline and the tests (requirement 3.8)."""
from datetime import date
from typing import Any

from shapely.geometry import shape

from ..config import ZONE_TYPES
from .geo import SERVICE_BBOX

REQUIRED = ("id", "name", "type", "active", "source_name", "source_url", "checked_at")


def validate_zone_collection(data: Any, bbox=SERVICE_BBOX) -> list[str]:
    """Return a list of problems; empty means valid."""
    errors: list[str] = []
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        return ["root must be a GeoJSON FeatureCollection"]
    features = data.get("features")
    if not isinstance(features, list) or not features:
        return ["features must be a non-empty list"]
    seen: set[str] = set()
    for index, feature in enumerate(features):
        props = feature.get("properties") or {}
        label = f"feature[{index}] {props.get('id', '?')}"
        for key in REQUIRED:
            value = props.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"{label}: missing {key}")
        zone_id = props.get("id")
        if zone_id in seen:
            errors.append(f"{label}: duplicate id")
        seen.add(zone_id)
        if props.get("type") not in ZONE_TYPES:
            errors.append(f"{label}: type must be one of {list(ZONE_TYPES)}")
        if not isinstance(props.get("active"), bool):
            errors.append(f"{label}: active must be true or false")
        url = props.get("source_url")
        if isinstance(url, str) and not url.startswith(("https://", "http://")):
            errors.append(f"{label}: source_url must be an http(s) URL")
        checked = props.get("checked_at")
        if isinstance(checked, str):
            try:
                date.fromisoformat(checked)
            except ValueError:
                errors.append(f"{label}: checked_at must be YYYY-MM-DD")
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            errors.append(f"{label}: geometry must be Polygon or MultiPolygon")
            continue
        try:
            geom = shape(geometry)
        except (ValueError, TypeError, AttributeError, IndexError):
            errors.append(f"{label}: geometry cannot be parsed")
            continue
        if geom.is_empty or not geom.is_valid:
            errors.append(f"{label}: geometry is not a valid polygon")
        minx, miny, maxx, maxy = geom.bounds
        if minx < bbox[0] or miny < bbox[1] or maxx > bbox[2] or maxy > bbox[3]:
            errors.append(f"{label}: coordinates outside the Gwangju service area")
    return errors
