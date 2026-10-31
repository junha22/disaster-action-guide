"""Rain for the parked car check: the last 24 hours at the Gwangju station, the next hours at the car's grid cell.

KMA receives the 5 km grid cell only, never coordinates. Keys never appear in responses or logs.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import logging
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import unquote

import httpx

from .weather_aws import MAX_AGE, MISSING_BELOW, AwsFormatError, parse_station_rows
from .weather_kma import AWS_MINUTE_URL, HUB_KEY, KmaError, KmaNoData, _items

KST = timezone(timedelta(hours=9))
STATION = 156  # the rule was made from this station's rain
HOURS = 24
FORECAST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst"
HUB_FORECAST_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtFcst"
# A day of minutes is about 190 KB.
TIMEOUT_S = 15.0
PAST_TTL_S = 300.0
FORECAST_TTL_S = 600.0
FAIL_TTL_S = 60.0
# A missing hour counts as dry, so too many of them would hide rain.
MAX_MISSING_HOURS = 3
NEAR_MINUTES = 5
NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class PastRain:
    hours: tuple[float, ...]  # oldest first
    observed_at: str
    missing_hours: int


def hourly_rain(rows: list[tuple[datetime, float]], now: datetime, hours: int = HOURS) -> PastRain | None:
    """Rain of each hour counted back from the newest reading. None: too old or too much missing."""
    valid = {at: mm for at, mm in rows if mm > MISSING_BELOW and mm >= 0}
    if not valid:
        return None
    newest = max(valid)
    if now - newest > MAX_AGE:
        return None
    values, missing = [], 0
    for back in range(hours - 1, -1, -1):
        at = newest - timedelta(hours=back)
        near = (at + timedelta(minutes=m) for m in sorted(range(-NEAR_MINUTES, NEAR_MINUTES + 1), key=abs))
        value = next((valid[t] for t in near if t in valid), None)
        missing += value is None
        values.append(value or 0.0)
    return None if missing > MAX_MISSING_HOURS else PastRain(tuple(values), newest.isoformat(), missing)


def forecast_mm(value: Any) -> float:
    """"강수없음", "1mm 미만", "30.0~50.0mm", "50.0mm 이상": a range or a limit counts as its top number."""
    text = str(value).strip()
    if text in ("강수없음", "0", "0.0"):
        return 0.0
    numbers = NUMBER.findall(text)
    if not numbers:
        raise KmaError()
    return max(float(n) for n in numbers)


def parse_forecast(payload: Any, now: datetime) -> list[float]:
    status, items = _items(payload)
    if status == "nodata":
        raise KmaNoData()
    hours = []
    for item in items:
        if item.get("category") == "RN1":
            try:
                at = datetime.strptime(f"{item.get('fcstDate')}{item.get('fcstTime')}", "%Y%m%d%H%M").replace(tzinfo=KST)
            except ValueError:
                raise KmaError() from None
            if at > now:
                hours.append((at, forecast_mm(item.get("fcstValue"))))
    if not hours:
        raise KmaError()
    return [mm for _, mm in sorted(hours)]


class ParkingRainService:
    def __init__(self, *, key: Callable[[], str | None] = lambda: os.environ.get("KMA_SERVICE_KEY"),
                 aws_key: Callable[[], str | None] = lambda: os.environ.get("KMA_AWS_KEY"),
                 transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(KST)):
        self._key, self._aws_key, self._transport, self._clock, self._now = key, aws_key, transport, clock, now
        self._past_lock = threading.Lock()
        self._past: tuple[PastRain | None, float] | None = None
        self._forecast_lock = threading.Lock()
        self._forecasts: dict[tuple[int, int], tuple[list[float] | None, float]] = {}  # the service area has few cells
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    def past(self) -> PastRain | None:
        with self._past_lock:
            if self._past is None or self._clock() >= self._past[1]:
                value = self._read_past()
                self._past = (value, self._clock() + (PAST_TTL_S if value else FAIL_TTL_S))
            return self._past[0]

    def _read_past(self) -> PastRain | None:
        key = (self._aws_key() or "").strip()
        if not key:
            return None
        now = self._now().astimezone(KST)
        # The newest minutes have not arrived yet and read as missing.
        end = now - timedelta(minutes=5)
        start = end - timedelta(hours=HOURS) + timedelta(minutes=1)
        try:
            with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
                response = client.get(AWS_MINUTE_URL, params={
                    "tm1": start.strftime("%Y%m%d%H%M"), "tm2": end.strftime("%Y%m%d%H%M"),
                    "stn": STATION, "disp": 0, "help": 0, "authKey": key})
            if response.status_code != 200:
                return None
            rows = parse_station_rows(response.content.decode("euc-kr", errors="replace"), str(STATION))
        except (httpx.HTTPError, AwsFormatError):
            return None
        return hourly_rain(rows, now)

    def forecast(self, grid: tuple[int, int]) -> list[float] | None:
        with self._forecast_lock:
            hit = self._forecasts.get(grid)
            if hit is None or self._clock() >= hit[1]:
                value = self._read_forecast(grid)
                hit = (value, self._clock() + (FORECAST_TTL_S if value else FAIL_TTL_S))
                self._forecasts[grid] = hit
            return hit[0]

    def _read_forecast(self, grid: tuple[int, int]) -> list[float] | None:
        raw = (self._key() or "").strip()
        if not raw:
            return None
        key = unquote(raw) if "%" in raw else raw
        url, key_param = (HUB_FORECAST_URL, "authKey") if HUB_KEY.fullmatch(key) else (FORECAST_URL, "serviceKey")
        now = self._now().astimezone(KST)
        # Published at HH30 and available from about HH45.
        latest = (now - timedelta(minutes=45)).replace(minute=30, second=0, microsecond=0)
        try:
            with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
                for base in (latest, latest - timedelta(hours=1)):
                    response = client.get(url, params={
                        key_param: key, "pageNo": 1, "numOfRows": 60, "dataType": "JSON",
                        "base_date": base.strftime("%Y%m%d"), "base_time": base.strftime("%H%M"),
                        "nx": grid[0], "ny": grid[1]})
                    if response.status_code != 200:
                        return None
                    try:
                        return parse_forecast(response.json(), now)
                    except KmaNoData:
                        continue
        except (httpx.HTTPError, ValueError, KmaError):
            return None
        return None


@lru_cache(maxsize=1)
def get_parking_rain_service() -> ParkingRainService:
    return ParkingRainService()
