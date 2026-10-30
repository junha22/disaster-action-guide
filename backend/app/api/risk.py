from typing import Annotated

from fastapi import APIRouter, Depends

from ..risk.layer import RiskLayer
from .deps import layer_dep

router = APIRouter(prefix="/api", tags=["route"])


@router.get("/risk-zones")
def risk_zones(layer: Annotated[RiskLayer, Depends(layer_dep)]):
    """Active zones as GeoJSON for the map layer (requirement 3.5)."""
    return layer.to_geojson()
