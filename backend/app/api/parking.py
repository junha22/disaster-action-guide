"""POST /api/parking/check (requirement 10). It reads the risk layer and changes nothing in the route service.

Coordinates stay in the body and are not stored or logged.
"""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from shapely.geometry import Point as ShapelyPoint

from ..context.parking_rain import ParkingRainService, get_parking_rain_service
from ..context.weather_regions import grid_of
from ..parking import DEMO_FORECAST, DEMO_PAST, check_rain, find_zone
from ..risk.geo import in_service_area, to_metric
from ..risk.layer import RiskLayer
from .deps import layer_dep
from .route import OUTSIDE, Point

router = APIRouter(prefix="/api/parking", tags=["route"])
FLOOD_RECORDS = "flood_history"


class CheckBody(Point):
    demo: bool = False


def _zone_at(lon: float, lat: float, layer: RiskLayer) -> dict[str, Any] | None:
    """The Buk-gu zones cover 2021-2023. Outside them, the service's own records (up to 2025) still count."""
    zone = find_zone(lon, lat)
    if zone:
        return zone.as_dict()
    target = to_metric(ShapelyPoint(lon, lat))
    record = next((z for z in layer.active([FLOOD_RECORDS]) if z.metric.covers(target)), None)
    if record is None:
        return None
    return {"kind": "service_records", "name": record.name, "grade": None, "records": None, "flood_dates": []}


@router.post("/check")
def check(body: CheckBody,
          layer: Annotated[RiskLayer, Depends(layer_dep)],
          rain: Annotated[ParkingRainService, Depends(get_parking_rain_service)]):
    if not in_service_area(body.lon, body.lat):
        raise HTTPException(422, OUTSIDE)
    zone = _zone_at(body.lon, body.lat, layer)
    grade = zone["grade"] if zone else None
    if body.demo:
        return {"demo": True, "zone": zone, "status": "known", "observed_at": None, "missing_hours": 0, "forecast_ok": True,
                "rain": check_rain(DEMO_PAST, DEMO_FORECAST, grade)}
    past = rain.past()
    if past is None:
        return {"demo": False, "zone": zone, "status": "unknown", "observed_at": None, "missing_hours": 0, "forecast_ok": False,
                "rain": None}
    forecast = rain.forecast(grid_of(body.lon, body.lat))
    return {"demo": False, "zone": zone, "status": "known", "observed_at": past.observed_at, "missing_hours": past.missing_hours,
            "forecast_ok": forecast is not None, "rain": check_rain(past.hours, forecast, grade)}
