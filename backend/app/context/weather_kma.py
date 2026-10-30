"""KMA weather for Gwangju (requirement 2, design.md 3.2-3.4).

- 1-hour rainfall (RN1) from the ultra-short-term observation API at grid (58, 74).
- Heavy-rain alert from the warning-code API, filtered by Gwangju alert-area codes.
- One shared result cached in memory for 10 minutes (failures for 1 minute).
- No user location is sent. The service key never appears in responses, messages or logs.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import logging
import os
import threading
import time
from typing import Any, Callable
from urllib.parse import unquote

import httpx

KST = timezone(timedelta(hours=9))
NCST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
WARNING_URL = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnCd"
GRID = (58, 74)  # 초안: Gwangju City Hall via the KMA LCC grid formula
# 광주광역시, 광주광역시(2026-05-31~), 광주서부, 광주동부. L1013400 is 경기 광주시: excluded on purpose.
GWANGJU_AREA_CODES = frozenset({"L1130000", "L1130100", "L1130110", "L1130120"})
HEAVY_RAIN = 2
ACTIVE_COMMANDS = {1, 3, 6, 7}  # 발표, 연장, 정정, 변경발표 (2 해제, 8 변경해제)
ALERT_DAYS = 3
TIMEOUT_S = 5.0
TTL_S = 600.0
FAIL_TTL_S = 60.0
UNAVAILABLE = "기상 정보를 가져오지 못했습니다"
ALERT_LABELS = {"none": "없음", "advisory": "호우주의보", "warning": "호우경보"}


class KmaError(Exception):
    """Fixed-message failure. Never carries URLs, keys or response bodies."""


@dataclass(frozen=True)
class WeatherSnapshot:
    available: bool
    rn1_mm: float | None
    alert: str
    alert_label: str
    alert_status: str  # "ok" | "failed"
    observed_at: str | None
    message: str | None


def unavailable_snapshot() -> WeatherSnapshot:
    return WeatherSnapshot(False, None, "none", ALERT_LABELS["none"], "failed", None, UNAVAILABLE)


def observation_time(now: datetime) -> datetime:
    """Hourly observation to request: the current hour from :40 on, otherwise the previous hour."""
    now = now.astimezone(KST)
    hour = now.replace(minute=0, second=0, microsecond=0)
    return hour if now.minute >= 40 else hour - timedelta(hours=1)


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


def parse_alert(payload: Any) -> tuple[str, str]:
    """Current Gwangju heavy-rain alert from getPwnCd items (design.md 3.3)."""
    _, items = _items(payload)
    latest: dict[tuple[str, int], dict] = {}
    for item in items:
        try:
            area = str(item.get("areaCode", ""))
            if area not in GWANGJU_AREA_CODES or int(item.get("warnVar", -1)) != HEAVY_RAIN:
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


class KmaWeatherService:
    def __init__(self, *, key: Callable[[], str | None] = lambda: os.environ.get("KMA_SERVICE_KEY"),
                 transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(KST)):
        self._key, self._transport, self._clock, self._now = key, transport, clock, now
        self._lock = threading.Lock()
        self._cached: WeatherSnapshot | None = None
        self._expires = 0.0
        self.fetch_count = 0
        # httpx logs request URLs (including serviceKey) at INFO.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    def get(self) -> WeatherSnapshot:
        with self._lock:
            if self._cached is not None and self._clock() < self._expires:
                return self._cached
            snapshot = self._fetch()
            self._cached = snapshot
            self._expires = self._clock() + (TTL_S if snapshot.available else FAIL_TTL_S)
            return snapshot

    def _get_json(self, client: httpx.Client, url: str, params: dict[str, Any]) -> Any:
        try:
            response = client.get(url, params=params)
            if response.status_code != 200:
                raise KmaError()
            return response.json()  # data.go.kr may answer XML on key errors -> ValueError
        except (httpx.HTTPError, ValueError):
            raise KmaError() from None

    def _fetch(self) -> WeatherSnapshot:
        raw = (self._key() or "").strip()
        if not raw:
            return unavailable_snapshot()
        key = unquote(raw) if "%" in raw else raw  # accept the portal's encoded or decoded key
        self.fetch_count += 1
        observed = observation_time(self._now())
        with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
            try:
                rn1 = parse_rn1(self._get_json(client, NCST_URL, {
                    "serviceKey": key, "pageNo": 1, "numOfRows": 20, "dataType": "JSON",
                    "base_date": observed.strftime("%Y%m%d"), "base_time": observed.strftime("%H00"),
                    "nx": GRID[0], "ny": GRID[1]}))
            except KmaError:
                return unavailable_snapshot()
            snapshot = WeatherSnapshot(True, rn1, "none", ALERT_LABELS["none"], "ok", observed.isoformat(), None)
            today = self._now().astimezone(KST).date()
            try:
                alert, label = parse_alert(self._get_json(client, WARNING_URL, {
                    "serviceKey": key, "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
                    "fromTmFc": (today - timedelta(days=ALERT_DAYS - 1)).strftime("%Y%m%d"),
                    "toTmFc": today.strftime("%Y%m%d"), "warningType": HEAVY_RAIN}))
            except KmaError:
                return replace(snapshot, alert_status="failed", alert_label="특보 확인 실패")
            return replace(snapshot, alert=alert, alert_label=label)


@lru_cache(maxsize=1)
def get_weather_service() -> KmaWeatherService:
    return KmaWeatherService()
