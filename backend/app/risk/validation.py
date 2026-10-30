"""Checks shared by the data pipeline and the tests (requirement 3.8)."""
from datetime import date
from typing import Any

from shapely.geometry import shape

from ..config import ZONE_TIERS, ZONE_TYPES
from .geo import SERVICE_BBOX

REQUIRED = ("id", "name", "type", "active", "source_name", "source_url", "checked_at")
# Optional flood_history facts (design.md 4.1, 5.8). Missing means unknown.
TERRAIN_KEYS = ("flood_count", "elev_m", "low_pct", "above_local_min_m", "elev_status")
ELEV_STATUSES = ("정상", "일부 범위 밖", "범위 밖")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _terrain_errors(props: dict, label: str) -> list[str]:
    errors = []
    tier = props.get("risk_tier")
    if tier is not None:
        allowed = ZONE_TIERS.get(props.get("type"), ())
        if tier not in allowed:
            errors.append(f"{label}: risk_tier must be one of {list(allowed)}")
    count = props.get("flood_count")
    if count is not None and not (isinstance(count, int) and not isinstance(count, bool) and count >= 1):
        errors.append(f"{label}: flood_count must be a positive integer")
    for key in ("elev_m", "low_pct", "above_local_min_m"):
        value = props.get(key)
        if value is not None and not _is_number(value):
            errors.append(f"{label}: {key} must be a number or null")
    low = props.get("low_pct")
    if _is_number(low) and not 0 <= low <= 100:
        errors.append(f"{label}: low_pct must be between 0 and 100")
    status = props.get("elev_status")
    if status is not None and status not in ELEV_STATUSES:
        errors.append(f"{label}: elev_status must be one of {list(ELEV_STATUSES)}")
    return errors


def _underpass_errors(props: dict, label: str) -> list[str]:
    """centerline and block_points (design.md 4.5) come together, on underpasses only."""
    line, points = props.get("centerline"), props.get("block_points")
    if line is None and points is None:
        return []
    errors = []
    if props.get("type") != "underpass":
        errors.append(f"{label}: centerline is for underpass zones only")
    if not isinstance(line, dict) or line.get("type") != "MultiLineString" or not line.get("coordinates"):
        errors.append(f"{label}: centerline must be a MultiLineString")
    if not (isinstance(points, list) and points
            and all(isinstance(p, list) and len(p) == 2 and all(_is_number(v) for v in p) for p in points)):
        errors.append(f"{label}: block_points must be a list of [lon, lat]")
    return errors


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
        errors.extend(_terrain_errors(props, label))
        errors.extend(_underpass_errors(props, label))
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
