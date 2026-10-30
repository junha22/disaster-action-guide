"""Source readers. Each returns records: dicts with id, name, type, geometry (GeoJSON),
source_name, source_url, checked_at and optional active, is_dummy, note, radius_m.

Only the seed reader works now. The raw formats are not fixed yet (requirements: 팀 확정 필요).
"""
import json
from pathlib import Path


def read_seed_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    return [{**defaults, **record} for record in data["records"]]


def read_underpass_csv(path: Path) -> list[dict]:
    """공공데이터포털 지하차도 목록(점). Columns and coordinate system to be confirmed."""
    raise NotImplementedError("지하차도 원본 형식이 정해지면 구현한다")


def read_flood_trace_shp(path: Path) -> list[dict]:
    """침수흔적도·침수피해지(다각형). Shapefile reading needs a reviewed library choice."""
    raise NotImplementedError("침수흔적도 원본 형식이 정해지면 구현한다")


def read_river_centerline(path: Path) -> list[dict]:
    """하천 중심선(선)."""
    raise NotImplementedError("하천 원본 형식이 정해지면 구현한다")


READERS = {
    "seed_json": read_seed_json,
    "underpass_csv": read_underpass_csv,
    "flood_trace_shp": read_flood_trace_shp,
    "river_centerline": read_river_centerline,
}
