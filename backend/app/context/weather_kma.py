"""KMA weather for a place in Gwangju or Jeonnam (requirement 2, design.md 3.2-3.4).

- Rainfall of the last 60 minutes from the nearest per-minute AWS station when KMA_AWS_KEY is set
  (weather_aws.py), otherwise or on failure the hourly RN1 of the ultra-short-term observation API
  at the place's grid cell.
- Heavy-rain alert filtered by the region's alert-area codes: the warning-code API on data.go.kr, or
  the current-alert list (wrn_now_data) on KMA API Hub.
- Results cached in memory per grid cell and region for 10 minutes (failures for 1 minute).
- Only one request at a time reads a place; other places do not wait for it.
- New readings have a budget, since any client can name any place. Over it: the last reading, or
  unavailable. The default place is exempt, so the budget cannot take the main screen down.
- KMA receives the 5 km grid cell only, never coordinates. The service key never appears in
  responses, messages or logs.
- Accepts a data.go.kr service key or a KMA API Hub auth key.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
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

from .weather_aws import AwsFormatError, Station, StationRain, nearest_rain, parse_minute_table, parse_stations
from .weather_regions import DEFAULT_REGION, GWANGJU_AREA_CODES, LonLat, grid_of, region_for

KST = timezone(timedelta(hours=9))
NCST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
WARNING_URL = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnCd"
HUB_NCST_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtNcst"
HUB_ALERT_URL = "https://apihub.kma.go.kr/api/typ01/url/wrn_now_data.php"
AWS_MINUTE_URL = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-aws2_min"
AWS_STATIONS_URL = "https://apihub.kma.go.kr/api/typ01/url/stn_inf.php"
# API Hub keys are 22 URL-safe characters. Portal keys are longer, or contain %, + or =.
HUB_KEY = re.compile(r"[A-Za-z0-9_-]{22}")
GRID = grid_of(DEFAULT_REGION.lon, DEFAULT_REGION.lat)  # (58, 74)
# More than the grid cells of the weather area, so a scan of places cannot evict the ones in use.
CACHE_SIZE = 4096
READINGS_PER_MINUTE = 60
READINGS_PER_DAY = 5000
HUB_HEAVY_RAIN = "호우"
# Values seen in real responses. 예비 is a preliminary notice, not an alert in effect yet.
HUB_LEVELS = {"주의": "advisory", "경보": "warning"}
HEAVY_RAIN = 2
ACTIVE_COMMANDS = {1, 3, 6, 7}  # 발표, 연장, 정정, 변경발표 (2 해제, 8 변경해제)
ALERT_DAYS = 3
TIMEOUT_S = 5.0
TTL_S = 600.0
# The stations renew every minute: a shorter wait is what lets a sudden downpour be noticed.
AWS_TTL_S = 120.0
AWS_STATIONS_TTL_S = 86400.0
FAIL_TTL_S = 60.0
UNAVAILABLE = "기상 정보를 가져오지 못했습니다"
BUSY = "기상 정보 요청이 많아 가져오지 못했습니다"
ALERT_LABELS = {"none": "없음", "advisory": "호우주의보", "warning": "호우경보"}


class KmaError(Exception):
    """Fixed-message failure. Never carries URLs, keys or response bodies."""


class KmaNoData(KmaError):
    """The requested observation hour has not been published yet."""


@dataclass(frozen=True)
class WeatherSnapshot:
    available: bool
    rn1_mm: float | None
    alert: str
    alert_label: str
    alert_status: str  # "ok" | "failed"
    observed_at: str | None
    message: str | None
    region: str = DEFAULT_REGION.name
    grid: tuple[int, int] = GRID
    routable: bool = True  # routes and risk zones cover Gwangju only
    station: str | None = None  # the AWS station read, when the rain came from one


def unavailable_snapshot() -> WeatherSnapshot:
    return WeatherSnapshot(False, None, "none", ALERT_LABELS["none"], "failed", None, UNAVAILABLE)


def observation_hours(now: datetime) -> tuple[datetime, datetime]:
    """Hourly observations to try, newest first. Publication time varies, so ask rather than guess."""
    hour = now.astimezone(KST).replace(minute=0, second=0, microsecond=0)
    return hour, hour - timedelta(hours=1)


def _items(payload: Any) -> tuple[str, list[dict]]:
    if not isinstance(payload, dict) or "response" not in payload:
        raise KmaError()
    response = payload["response"]
    code = str(response.get("header", {}).get("resultCode", ""))
    if code in ("03",):  # NODATA_ERROR
        return "nodata", []
    if code not in ("00", "0"):
        raise KmaError()
    items = (response.get("body") or {}).get("items") or {}
    item = items.get("item", []) if isinstance(items, dict) else []
    return "ok", item if isinstance(item, list) else [item]


def parse_rn1(payload: Any) -> float:
    status, items = _items(payload)
    if status == "nodata":
        raise KmaNoData()
    for item in items:
        if item.get("category") == "RN1":
            try:
                value = float(item.get("obsrValue"))
            except (TypeError, ValueError):
                raise KmaError() from None
            if value < 0:
                raise KmaError()
            return value
    raise KmaError()


def parse_alert(payload: Any, codes: frozenset[str] = GWANGJU_AREA_CODES) -> tuple[str, str]:
    """Current heavy-rain alert of the area codes from getPwnCd items (design.md 3.3)."""
    _, items = _items(payload)
    latest: dict[tuple[str, int], dict] = {}
    for item in items:
        try:
            area = str(item.get("areaCode", ""))
            if area not in codes or int(item.get("warnVar", -1)) != HEAVY_RAIN:
                continue
            if int(item.get("cancel", 0) or 0) == 1:
                continue
            stress = int(item.get("warnStress", 0))
            order = (str(item.get("tmFc", "")), int(item.get("tmSeq", 0) or 0))
        except (TypeError, ValueError):
            raise KmaError() from None
        key = (area, stress)
        if key not in latest or order >= latest[key]["_order"]:
            latest[key] = {**item, "_order": order}
    active = [stress for (_, stress), item in latest.items() if int(item.get("command", 0)) in ACTIVE_COMMANDS]
    if not active:
        return "none", ALERT_LABELS["none"]
    top = max(active)
    if top == 0:
        return "advisory", ALERT_LABELS["advisory"]
    return "warning", ALERT_LABELS["warning"] + (" (중대)" if top >= 2 else "")


def _text(item: dict, key: str) -> str:
    return str(item.get(key, "")).strip()  # the API pads fields with spaces


def parse_hub_alert(items: Any, codes: frozenset[str] = GWANGJU_AREA_CODES) -> tuple[str, str]:
    """Current heavy-rain alert of the area codes from API Hub's list of alerts in effect."""
    if not isinstance(items, list):
        raise KmaError()
    active = set()
    for item in items:
        if not isinstance(item, dict):
            raise KmaError()
        in_area = _text(item, "REG_ID") in codes or _text(item, "REG_UP") in codes
        if in_area and _text(item, "WRN") == HUB_HEAVY_RAIN and _text(item, "CMD") != "해제":
            alert = HUB_LEVELS.get(_text(item, "LVL"))
            if alert:
                active.add(alert)
    alert = "warning" if "warning" in active else "advisory" if "advisory" in active else "none"
    return alert, ALERT_LABELS[alert]


class KmaWeatherService:
    def __init__(self, *, key: Callable[[], str | None] = lambda: os.environ.get("KMA_SERVICE_KEY"),
                 aws_key: Callable[[], str | None] = lambda: os.environ.get("KMA_AWS_KEY"),
                 transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(KST)):
        self._key, self._aws_key, self._transport, self._clock, self._now = key, aws_key, transport, clock, now
        self._lock = threading.Lock()  # guards the fields below, and is never held across the network
        self._cached: OrderedDict[tuple, tuple[WeatherSnapshot, float]] = OrderedDict()
        self._place_locks: dict[tuple, threading.Lock] = {}
        self._readings: deque[float] = deque()
        self._aws_lock = threading.Lock()
        self._aws_stations: tuple[list[Station], float] | None = None
        self._aws_table: tuple[dict[str, tuple[datetime, float]] | None, float] | None = None
        self.aws_fetch_count = 0
        self._alert_lock = threading.Lock()
        self._alert_payload: tuple[Any, float] | None = None  # one list serves every region
        self.fetch_count = 0
        # httpx logs request URLs (including serviceKey) at INFO.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    def get(self, point: LonLat | None = None) -> WeatherSnapshot:
        """Weather at `point`, or at the default place in Gwangju."""
        region = region_for(*point) if point else DEFAULT_REGION
        grid = grid_of(*point) if point else GRID
        key = (grid, region.id)
        place = {"region": region.name, "grid": grid, "routable": region.group == "광주"}
        with self._lock:
            fresh = self._fresh(key)
            if fresh is not None:
                return fresh
            place_lock = self._place_locks.setdefault(key, threading.Lock())
        with place_lock:
            with self._lock:
                fresh = self._fresh(key)  # another request may just have read this place
                if fresh is not None:
                    return fresh
            lon, lat = point or (DEFAULT_REGION.lon, DEFAULT_REGION.lat)
            rain = self._aws_rain(lon, lat)  # one shared table: no budget needed
            if rain is not None:
                snapshot = replace(self._from_station(rain, region.alert_codes), **place)
                ttl = AWS_TTL_S
            else:
                with self._lock:
                    if point is not None and not self._take_reading():
                        hit = self._cached.get(key)
                        if hit is not None and hit[0].available:
                            return hit[0]
                        return replace(unavailable_snapshot(), message=BUSY, **place)
                snapshot = replace(self._fetch(grid, region.alert_codes), **place)
                ttl = TTL_S if snapshot.available else FAIL_TTL_S
            with self._lock:
                self._cached[key] = (snapshot, self._clock() + ttl)
                self._cached.move_to_end(key)
                while len(self._cached) > CACHE_SIZE:
                    self._place_locks.pop(self._cached.popitem(last=False)[0], None)
            return snapshot

    def _aws_rain(self, lon: float, lat: float) -> StationRain | None:
        """None sends the caller to the hourly observation: no key, no answer, or no station nearby."""
        key = (self._aws_key() or "").strip()
        if not key:
            return None
        with self._aws_lock:
            now = self._clock()
            if self._aws_table is None or now >= self._aws_table[1]:
                try:
                    self._aws_table = (self._read_aws(key, now), now + AWS_TTL_S)
                except (KmaError, AwsFormatError):
                    self._aws_table = (None, now + FAIL_TTL_S)
            table = self._aws_table[0]
            stations = self._aws_stations[0] if self._aws_stations else []
        return nearest_rain(stations, table, lon, lat, self._now()) if table else None

    def _read_aws(self, key: str, now: float) -> dict[str, tuple[datetime, float]]:
        with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
            if self._aws_stations is None or now >= self._aws_stations[1]:
                text = self._get_text(client, AWS_STATIONS_URL, {
                    "inf": "AWS", "tm": self._now().astimezone(KST).strftime("%Y%m%d%H%M"), "help": 0, "authKey": key})
                self._aws_stations = (list(parse_stations(text).values()), now + AWS_STATIONS_TTL_S)
            self.aws_fetch_count += 1
            # No time asked for: the newest minutes have not arrived yet and read as missing everywhere.
            return parse_minute_table(self._get_text(client, AWS_MINUTE_URL, {"stn": 0, "disp": 0, "help": 0, "authKey": key}))

    def _get_text(self, client: httpx.Client, url: str, params: dict[str, Any]) -> str:
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError:
            raise KmaError() from None
        if response.status_code != 200:
            raise KmaError()
        return response.content.decode("euc-kr", errors="replace")

    def _from_station(self, rain: StationRain, codes: frozenset[str]) -> WeatherSnapshot:
        snapshot = WeatherSnapshot(True, rain.rn60_mm, "none", ALERT_LABELS["none"], "ok", rain.observed_at.isoformat(), None,
                                   station=rain.station)
        failed = replace(snapshot, alert_status="failed", alert_label="특보 확인 실패")
        raw = (self._key() or "").strip()
        if not raw:
            return failed
        key = unquote(raw) if "%" in raw else raw
        with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
            try:
                alert, label = self._fetch_alert(client, key, bool(HUB_KEY.fullmatch(key)), codes)
            except KmaError:
                return failed
        return replace(snapshot, alert=alert, alert_label=label)

    def _fresh(self, key: tuple) -> WeatherSnapshot | None:
        hit = self._cached.get(key)
        if hit is None or self._clock() >= hit[1]:
            return None
        self._cached.move_to_end(key)
        return hit[0]

    def _take_reading(self) -> bool:
        now = self._clock()
        while self._readings and now - self._readings[0] >= 86400:
            self._readings.popleft()
        last_minute = sum(1 for t in reversed(self._readings) if now - t < 60) if self._readings else 0
        if len(self._readings) >= READINGS_PER_DAY or last_minute >= READINGS_PER_MINUTE:
            return False
        self._readings.append(now)
        return True

    def _get_json(self, client: httpx.Client, url: str, params: dict[str, Any]) -> Any:
        try:
            response = client.get(url, params=params)
            if response.status_code != 200:
                raise KmaError()
            return response.json()  # data.go.kr may answer XML on key errors -> ValueError
        except (httpx.HTTPError, ValueError):
            raise KmaError() from None

    def _alert_list(self, client: httpx.Client, key: str, is_hub: bool) -> Any:
        with self._alert_lock:
            if self._alert_payload is not None and self._clock() < self._alert_payload[1]:
                return self._alert_payload[0]
            if is_hub:
                payload = self._get_json(client, HUB_ALERT_URL, {
                    "fe": "f", "tm": self._now().astimezone(KST).strftime("%Y%m%d%H%M"),
                    "disp": 1, "help": 0, "authKey": key})
            else:
                today = self._now().astimezone(KST).date()
                payload = self._get_json(client, WARNING_URL, {
                    "serviceKey": key, "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
                    "fromTmFc": (today - timedelta(days=ALERT_DAYS - 1)).strftime("%Y%m%d"),
                    "toTmFc": today.strftime("%Y%m%d"), "warningType": HEAVY_RAIN})
            # Alerts keep up with the rain when the rain is read every couple of minutes.
            ttl = AWS_TTL_S if (self._aws_key() or "").strip() else TTL_S
            self._alert_payload = (payload, self._clock() + ttl)
            return payload

    def _fetch_alert(self, client: httpx.Client, key: str, is_hub: bool, codes: frozenset[str]) -> tuple[str, str]:
        parse = parse_hub_alert if is_hub else parse_alert
        return parse(self._alert_list(client, key, is_hub), codes)

    def _fetch(self, grid: tuple[int, int], codes: frozenset[str]) -> WeatherSnapshot:
        raw = (self._key() or "").strip()
        if not raw:
            return unavailable_snapshot()
        key = unquote(raw) if "%" in raw else raw  # accept the portal's encoded or decoded key
        is_hub = bool(HUB_KEY.fullmatch(key))
        ncst_url, key_param = (HUB_NCST_URL, "authKey") if is_hub else (NCST_URL, "serviceKey")
        with self._lock:
            self.fetch_count += 1
        with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
            rn1, observed = None, None
            for hour in observation_hours(self._now()):
                try:
                    rn1 = parse_rn1(self._get_json(client, ncst_url, {
                        key_param: key, "pageNo": 1, "numOfRows": 20, "dataType": "JSON",
                        "base_date": hour.strftime("%Y%m%d"), "base_time": hour.strftime("%H00"),
                        "nx": grid[0], "ny": grid[1]}))
                    observed = hour
                    break
                except KmaNoData:
                    continue
                except KmaError:
                    return unavailable_snapshot()
            if rn1 is None or observed is None:
                return unavailable_snapshot()
            snapshot = WeatherSnapshot(True, rn1, "none", ALERT_LABELS["none"], "ok", observed.isoformat(), None)
            try:
                alert, label = self._fetch_alert(client, key, is_hub, codes)
            except KmaError:
                return replace(snapshot, alert_status="failed", alert_label="특보 확인 실패")
            return replace(snapshot, alert=alert, alert_label=label)


@lru_cache(maxsize=1)
def get_weather_service() -> KmaWeatherService:
    return KmaWeatherService()
