"""Parked car check (requirement 10): the place's flood records, and how close the rain is to past flood days.

The zones and the rain rule were made from Buk-gu flood records of 2021-2023 and the Gwangju station
(ASOS 156). The rule says the rain has reached the level of past flood days. It does not say a car
floods, and it was tuned and checked on the same 17 days.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Sequence

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

DATA_PATH = Path(__file__).resolve().parent / "data" / "parking_zones_buk.geojson"
BASE_3H = 30.0
WET_24H = 90.0
WET_3H = 20.0
FREQUENT = "상습"
FREQUENT_FACTOR = 0.8
STEP_MIN = 10
# The rain the sample in the data notes uses. Shown only as a labelled demo.
DEMO_PAST = (0.0,) * 18 + (10.0, 20.0, 18.0, 4.0, 6.0, 8.0)
DEMO_FORECAST = (12.0, 20.0, 15.0, 5.0, 0.0, 0.0)


@dataclass(frozen=True)
class ParkingZone:
    zone_id: int
    grade: str
    records: int
    main_dong: str
    flood_dates: tuple[str, ...]
    geometry: BaseGeometry

    def as_dict(self) -> dict[str, Any]:
        return {"kind": "buk_records", "name": f"{self.main_dong} 일대", "grade": self.grade, "records": self.records,
                "flood_dates": list(self.flood_dates)}


@lru_cache(maxsize=1)
def load_zones() -> tuple[ParkingZone, ...]:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return tuple(ParkingZone(f["properties"]["zone_id"], f["properties"]["grade"], f["properties"]["records"],
                             f["properties"]["main_dong"], tuple(f["properties"]["flood_dates"].split(", ")), shape(f["geometry"]))
                 for f in data["features"])


def find_zone(lon: float, lat: float) -> ParkingZone | None:
    point = Point(lon, lat)
    return next((z for z in load_zones() if z.geometry.covers(point)), None)


def factor_of(grade: str | None) -> float:
    return FREQUENT_FACTOR if grade == FREQUENT else 1.0


def is_danger(sum_3h: float, sum_24h: float, factor: float) -> bool:
    return sum_3h >= BASE_3H * factor or (sum_24h >= WET_24H * factor and sum_3h >= WET_3H * factor)


def countdown_minutes(past_24h: Sequence[float], forecast: Sequence[float], factor: float) -> int | None:
    """Minutes until the rule is met: 0 now, None not within the forecast. Hourly rain is spread evenly."""
    per_hour = 60 // STEP_MIN
    series = [r / per_hour for r in (*past_24h, *forecast) for _ in range(per_hour)]
    now = len(past_24h) * per_hour
    for i in range(now, len(series) + 1):
        # Rounded: the evenly split parts must add back up to the exact threshold.
        sum_3h = round(sum(series[max(0, i - 3 * per_hour):i]), 6)
        sum_24h = round(sum(series[max(0, i - 24 * per_hour):i]), 6)
        if is_danger(sum_3h, sum_24h, factor):
            return (i - now) * STEP_MIN
    return None


def check_rain(past_24h: Sequence[float], forecast: Sequence[float] | None, grade: str | None) -> dict[str, Any]:
    factor = factor_of(grade)
    return {"minutes": countdown_minutes(past_24h, forecast or (), factor),
            "sum_3h": round(sum(past_24h[-3:]), 1), "sum_24h": round(sum(past_24h), 1),
            "need_3h": round(BASE_3H * factor, 1), "wet_24h": round(WET_24H * factor, 1), "wet_3h": round(WET_3H * factor, 1),
            "forecast_hours": len(forecast or ()), "forecast_peak_mm": max(forecast) if forecast else None}
