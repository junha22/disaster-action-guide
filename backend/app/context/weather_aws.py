"""Rainfall from KMA's per-minute AWS stations (API Hub).

Each station reports the rain of the last 60 minutes, renewed every minute, about three minutes
late. The rain levels are defined per hour, so this value replaces the hourly observation directly.
One table covers every station, so any number of places costs one request.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Iterable, Iterator

KST = timezone(timedelta(hours=9))
# A station further away than this says little about the place; the grid observation is used instead.
MAX_STATION_KM = 20.0
# Mountain top stations (무등산) do not describe the roads below them.
MAX_STATION_HEIGHT_M = 300.0
# KMA: -50 or below means no observation.
MISSING_BELOW = -50.0
MAX_AGE = timedelta(minutes=30)


class AwsFormatError(ValueError):
    """The response is not the expected table. Never carries the response body."""


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    lon: float
    lat: float
    height_m: float


@dataclass(frozen=True)
class StationRain:
    station: str
    distance_km: float
    rn60_mm: float
    observed_at: datetime


def parse_stations(text: str) -> dict[str, Station]:
    """stn_inf.php rows: STN LON LAT STN_SP HT HT_WD LAU STN_AD STN_KO ..."""
    stations = {}
    for line in text.splitlines():
        parts = line.split()
        if line.startswith("#") or len(parts) < 9:
            continue
        try:
            stations[parts[0]] = Station(parts[0], parts[8], float(parts[1]), float(parts[2]), float(parts[4]))
        except ValueError:
            continue
    if not stations:
        raise AwsFormatError()
    return stations


def _minute_rows(text: str) -> Iterator[tuple[str, datetime, float]]:
    """nph-aws2_min rows, located by the header's column names: (station id, observed, RN-60m)."""
    columns: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("#"):
            tokens = line[1:].split()
            if tokens[:2] == ["YYMMDDHHMI", "STN"]:
                columns = tokens
            continue
        parts = line.split()
        if not parts:
            continue
        if columns is None or "RN-60m" not in columns:
            raise AwsFormatError()
        index = columns.index("RN-60m")
        if len(parts) <= index:
            continue
        try:
            yield parts[1], datetime.strptime(parts[0], "%Y%m%d%H%M").replace(tzinfo=KST), float(parts[index])
        except ValueError:
            continue


def parse_minute_table(text: str) -> dict[str, tuple[datetime, float]]:
    """The last row of each station: {station id: (observed, RN-60m)}"""
    rows = {station: (observed, rn60) for station, observed, rn60 in _minute_rows(text)}
    if not rows:
        raise AwsFormatError()
    return rows


def parse_station_rows(text: str, station: str) -> list[tuple[datetime, float]]:
    """Every row of one station: [(observed, RN-60m)]"""
    rows = [(observed, rn60) for row_station, observed, rn60 in _minute_rows(text) if row_station == station]
    if not rows:
        raise AwsFormatError()
    return rows


def distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    mid = math.radians((lat1 + lat2) / 2)
    return math.hypot((lon1 - lon2) * 111.32 * math.cos(mid), (lat1 - lat2) * 110.57)


def nearest_rain(stations: Iterable[Station], table: dict[str, tuple[datetime, float]], lon: float, lat: float,
                 now: datetime) -> StationRain | None:
    """The closest usable station. A station with no reading is skipped, not read as dry."""
    best: StationRain | None = None
    for station in stations:
        row = table.get(station.id)
        if row is None or row[1] <= MISSING_BELOW or row[1] < 0 or station.height_m >= MAX_STATION_HEIGHT_M:
            continue
        if now - row[0] > MAX_AGE:
            continue
        distance = distance_km(lon, lat, station.lon, station.lat)
        if distance <= MAX_STATION_KM and (best is None or distance < best.distance_km):
            best = StationRain(station.name, distance, row[1], row[0])
    return best
