"""WGS84 <-> EPSG:5179 (Korea 2000 unified CS, metres). Transformers are created on first use."""
from functools import lru_cache

import numpy as np
from pyproj import Transformer
import shapely
from shapely.geometry.base import BaseGeometry

# Gwangju Metropolitan City approximated by a box (design.md 7). Used for request validation.
SERVICE_BBOX: tuple[float, float, float, float] = (126.63, 35.04, 127.03, 35.27)


@lru_cache(maxsize=1)
def _forward() -> Transformer:
    return Transformer.from_crs(4326, 5179, always_xy=True)


@lru_cache(maxsize=1)
def _inverse() -> Transformer:
    return Transformer.from_crs(5179, 4326, always_xy=True)


def _apply(transformer: Transformer, geom: BaseGeometry) -> BaseGeometry:
    def project(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])
    return shapely.transform(geom, project)


def to_metric(geom: BaseGeometry) -> BaseGeometry:
    return _apply(_forward(), geom)


def to_wgs84(geom: BaseGeometry) -> BaseGeometry:
    return _apply(_inverse(), geom)


def in_service_area(lon: float, lat: float, bbox=SERVICE_BBOX) -> bool:
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]
