"""Risk-zone layer (requirement 3). Loaded from app/data/risk_zones.geojson on first use."""
from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import threading
from typing import Any, Iterable, Sequence

from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

from ..config import ZONE_TIERS, group_tier, zone_group
from .geo import to_metric, to_wgs84
from .validation import TERRAIN_KEYS, validate_zone_collection

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "risk_zones.geojson"
SIMPLIFY_M = 2.0

LonLat = tuple[float, float]
Ring = list[list[float]]


class RiskDataError(RuntimeError):
    """risk_zones.geojson is missing or invalid."""


@dataclass(frozen=True)
class RiskZone:
    id: str
    name: str
    type: str
    active: bool
    source_name: str
    source_url: str
    checked_at: str
    is_dummy: bool
    note: str
    geometry: BaseGeometry  # WGS84, original zone without the avoidance buffer
    metric: BaseGeometry    # same geometry in EPSG:5179
    # Terrain tier from the data (design.md 5.8). Tiered types without a known tier use the most
    # cautious one, see `group`.
    tier: str | None = None
    tier_reason: str | None = None
    # flood_count and DEM elevation facts for the map popup; not used for routing.
    terrain: dict[str, Any] | None = field(default=None, compare=False)

    @property
    def group(self) -> str:
        """Avoidance group: the type, or "type.tier" for tiered types (config.zone_group)."""
        return zone_group(self.type, self.tier)

    def ref(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "type": self.type}

    def properties(self) -> dict[str, Any]:
        props = {"id": self.id, "name": self.name, "type": self.type, "active": self.active,
                 "source_name": self.source_name, "source_url": self.source_url,
                 "checked_at": self.checked_at, "is_dummy": self.is_dummy, "note": self.note,
                 "group": self.group, "risk_tier": group_tier(self.group), "tier_reason": None}
        if self.type in ZONE_TIERS:
            props["tier_reason"] = self.tier_reason if group_tier(self.group) == self.tier else "등급 자료 없음"
            props.update({k: (self.terrain or {}).get(k) for k in TERRAIN_KEYS})
        return props


@dataclass(frozen=True)
class AvoidPolygon:
    zone: RiskZone
    rings: tuple[Ring, ...]  # closed lon/lat rings for exclude_polygons
    metric: BaseGeometry     # buffered polygon in EPSG:5179
    perimeter_m: float
    vertices: int


class RiskLayer:
    def __init__(self, zones: Iterable[RiskZone]):
        self.zones: tuple[RiskZone, ...] = tuple(sorted(zones, key=lambda z: z.id))

    @classmethod
    def from_geojson(cls, data: Any) -> "RiskLayer":
        errors = validate_zone_collection(data)
        if errors:
            raise RiskDataError("risk_zones.geojson 검증 실패: " + "; ".join(errors[:5]))
        zones = []
        for feature in data["features"]:
            p = feature["properties"]
            geometry = shape(feature["geometry"])
            terrain = {k: p[k] for k in TERRAIN_KEYS if k in p}
            zones.append(RiskZone(
                id=p["id"], name=p["name"], type=p["type"], active=p["active"],
                source_name=p["source_name"], source_url=p["source_url"],
                checked_at=p["checked_at"], is_dummy=bool(p.get("is_dummy", False)),
                note=p.get("note", ""), geometry=geometry, metric=to_metric(geometry),
                tier=p.get("risk_tier"), tier_reason=p.get("tier_reason"), terrain=terrain or None))
        return cls(zones)

    def active(self, types: Iterable[str] | None = None) -> list[RiskZone]:
        """Active zones. `types` may mix type names and group keys ("flood_history.high")."""
        wanted = None if types is None else set(types)
        return [z for z in self.zones
                if z.active and (wanted is None or z.type in wanted or z.group in wanted)]

    def avoid_polygons(self, types: Iterable[str], buffers: dict[str, float]) -> list[AvoidPolygon]:
        """Original zones grown by the per-type buffer, simplified, as lon/lat rings."""
        result = []
        for zone in self.active(types):
            grown = zone.metric.buffer(buffers[zone.type]).simplify(SIMPLIFY_M)
            parts = list(grown.geoms) if isinstance(grown, MultiPolygon) else [grown]
            rings: list[Ring] = []
            perimeter = 0.0
            vertices = 0
            for part in parts:
                if not isinstance(part, Polygon) or part.is_empty:
                    continue
                exterior = to_wgs84(Polygon(part.exterior))
                ring = [[round(x, 6), round(y, 6)] for x, y in exterior.exterior.coords]
                rings.append(ring)
                perimeter += part.exterior.length
                vertices += len(ring)
            if rings:
                result.append(AvoidPolygon(zone, tuple(rings), grown, perimeter, vertices))
        return result

    @staticmethod
    def containing(point: LonLat, polygons: Sequence[AvoidPolygon]) -> list[RiskZone]:
        target = to_metric(Point(point))
        return [p.zone for p in polygons if p.metric.covers(target)]

    def data_checked_at(self) -> str | None:
        dates = [z.checked_at for z in self.active()]
        return max(dates) if dates else None

    def to_geojson(self) -> dict[str, Any]:
        active = self.active()
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": z.properties(), "geometry": mapping(z.geometry)}
                         for z in active],
            "metadata": {"has_dummy": any(z.is_dummy for z in active),
                         "data_checked_at": self.data_checked_at(), "count": len(active)},
        }


_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load(path: Path) -> RiskLayer:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RiskDataError(f"risk_zones.geojson을 읽지 못했습니다: {type(exc).__name__}") from None
    return RiskLayer.from_geojson(data)


def get_risk_layer() -> RiskLayer:
    with _lock:
        return _load(DATA_PATH)
