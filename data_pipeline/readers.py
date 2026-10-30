"""Source readers. Each returns records: dicts with id, name, type, geometry (GeoJSON),
source_name, source_url, checked_at and optional active, is_dummy, note, radius_m.

The seed, processed flood-zone GeoJSON and underpass list readers work. The other raw formats are
not fixed yet (requirements: 팀 확정 필요).
"""
import csv
import json
from pathlib import Path
import sys

from zones import match_underpasses

# Korean type names used by the processed flood-zone file (risk_zones_guide.md) -> app type ids.
KOREAN_TYPES = {"침수 이력": "flood_history", "지하차도": "underpass", "하천변": "riverside"}
# Optional per-zone facts passed through unchanged (design.md 4.1, 5.8).
TERRAIN_KEYS = ("flood_count", "elev_m", "low_pct", "above_local_min_m", "elev_status")


def read_seed_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    return [{**defaults, **record} for record in data["records"]]


def _split(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def read_flood_zone_geojson(path: Path) -> list[dict]:
    """구청 침수 피해 자료를 가공한 다각형 GeoJSON (risk_zones_guide.md 형식).

    - type: 한글 유형 -> 앱 유형 ID, verified_date -> checked_at
    - source_url: 지도 팝업 링크가 깨지지 않게 첫 번째 URL만 쓰고, 전체 목록은 note에 남긴다.
    - flood_count와 DEM 고도 속성(있으면)은 그대로 넘긴다. 등급은 zones.py가 정한다.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for feature in data["features"]:
        p = feature["properties"]
        zone_type = KOREAN_TYPES.get(p.get("type"), p.get("type"))
        urls = _split(p.get("source_url"))
        years = "·".join(str(y) for y in p.get("flood_years") or [])
        note_parts = [p.get("origin") or ""]
        if years:
            note_parts.append(f"침수 연도 {years}")
        if p.get("record_count") is not None:
            note_parts.append(f"원본 기록 {p['record_count']}건")
        if p.get("location_accuracy"):
            note_parts.append(f"위치 정확도 {p['location_accuracy']}")
        if len(urls) > 1:
            note_parts.append("출처 전체: " + " ; ".join(urls))
        # Repeat count and DEM elevation (risk_zones_guide(DEM).md 3-3); zones.py derives risk_tier.
        terrain = {k: p[k] for k in TERRAIN_KEYS if k in p}
        records.append({
            **terrain,
            "id": p.get("id") or feature.get("id"),
            "name": p.get("name"),
            "type": zone_type,
            "active": p.get("active", True),
            "source_name": p.get("source_name"),
            "source_url": urls[0] if urls else None,
            "checked_at": p.get("verified_date") or p.get("checked_at"),
            "is_dummy": False,
            "note": ". ".join(part for part in note_parts if part),
            "geometry": feature["geometry"],
        })
    return records


def read_underpass_csv(path: Path, tunnels: str, match_radius_m: float, **source: str) -> list[dict]:
    """지하차도 위치 목록(시설물명, 위도, 경도)을 OSM 터널 구간에 맞춘다 (design.md 4.5).

    `tunnels`는 목록과 같은 폴더의 extract_osm_tunnels.py 결과다. `source`는 출처 속성이다.
    맞는 터널이 없는 좌표는 빼고 알린다.
    """
    with path.open(encoding="utf-8-sig", newline="") as file:
        points = [{"name": row["시설물명"], "lon": float(row["경도"]), "lat": float(row["위도"])}
                  for row in csv.DictReader(file)]
    ways = json.loads(path.with_name(tunnels).read_text(encoding="utf-8"))["features"]
    records, unmatched = match_underpasses(points, ways, match_radius_m)
    if unmatched:
        print(f"UNDERPASS_UNMATCHED: {', '.join(unmatched)}", file=sys.stderr)
    return [{**source, **record} for record in records]


def read_flood_trace_shp(path: Path) -> list[dict]:
    """침수흔적도·침수피해지(다각형). Shapefile reading needs a reviewed library choice."""
    raise NotImplementedError("침수흔적도 원본 형식이 정해지면 구현한다")


def read_river_centerline(path: Path) -> list[dict]:
    """하천 중심선(선)."""
    raise NotImplementedError("하천 원본 형식이 정해지면 구현한다")


READERS = {
    "seed_json": read_seed_json,
    "flood_zone_geojson": read_flood_zone_geojson,
    "underpass_csv": read_underpass_csv,
    "flood_trace_shp": read_flood_trace_shp,
    "river_centerline": read_river_centerline,
}
