"""Place search: Kakao Local (keyword, then address), demo points as fallback (requirement 1).

Only the query and the Gwangju search box are sent to Kakao; never the user's location.
The query is not logged or stored.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

import httpx

from ..risk.geo import SERVICE_BBOX, in_service_area

KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
RECT = ",".join(str(v) for v in SERVICE_BBOX)
SIZE = 10
TIMEOUT_S = 5.0
DEMO_PATH = Path(__file__).resolve().parents[1] / "data" / "demo_points.json"
OUTSIDE = "데모 지역 밖"
NOTICE_NO_KEY = "카카오 API 키가 설정되지 않아 데모 지점 목록을 보여줍니다."
NOTICE_FAILED = "장소 검색(카카오)에 연결하지 못해 데모 지점 목록을 보여줍니다."


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    address: str
    lon: float
    lat: float
    selectable: bool
    reason: str | None
    source: str  # "kakao" | "demo"

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@lru_cache(maxsize=1)
def load_demo_points() -> tuple[Place, ...]:
    data = json.loads(DEMO_PATH.read_text(encoding="utf-8"))
    return tuple(Place(p["id"], p["name"], p["address"], float(p["lon"]), float(p["lat"]), True, None, "demo")
                 for p in data["points"])


def _normalize(text: str) -> str:
    return "".join(text.split()).lower()


def demo_results(query: str) -> list[Place]:
    q = _normalize(query)
    points = list(load_demo_points())
    matches = [p for p in points if q and (q in _normalize(p.name) or _normalize(p.name) in q)]
    return matches + [p for p in points if p not in matches]


def _is_gwangju(region_1depth: str | None, address: str | None, lon: float, lat: float) -> bool:
    first = region_1depth or (address.split()[0] if address and address.split() else "")
    # Kakao may return the short name (광주), the former full name
    # (광주광역시), or the current full administrative name. Coordinates
    # still provide the strict boundary check that excludes 경기 광주시.
    return "광주" in first and in_service_area(lon, lat)


def _place(pid: str, name: str, address: str, x: Any, y: Any, region: str | None) -> Place | None:
    try:
        lon, lat = float(x), float(y)
    except (TypeError, ValueError):
        return None
    ok = _is_gwangju(region, address, lon, lat)
    return Place(pid, name, address, lon, lat, ok, None if ok else OUTSIDE, "kakao")


def parse_keyword(payload: Any) -> list[Place]:
    places = []
    for d in (payload or {}).get("documents", [])[:SIZE]:
        address = d.get("road_address_name") or d.get("address_name") or ""
        # address_name is the lot address and always starts with the province ("광주 북구 ...").
        p = _place(f"kakao-{d.get('id', len(places))}", d.get("place_name", ""), address, d.get("x"), d.get("y"),
                   (d.get("address_name") or "").split()[0] if d.get("address_name") else None)
        if p:
            places.append(p)
    return places


def parse_address(payload: Any) -> list[Place]:
    places = []
    for i, d in enumerate((payload or {}).get("documents", [])[:SIZE]):
        region = (d.get("address") or {}).get("region_1depth_name") or (d.get("road_address") or {}).get(
            "region_1depth_name")
        name = d.get("address_name", "")
        p = _place(f"kakao-address-{i}", name, name, d.get("x"), d.get("y"), region)
        if p:
            places.append(p)
    return places


class KakaoSearch:
    def __init__(self, *, key: Callable[[], str | None] = lambda: os.environ.get("KAKAO_REST_API_KEY"),
                 transport: httpx.BaseTransport | None = None):
        self._key, self._transport = key, transport
        logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs contain the query
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    def has_key(self) -> bool:
        return bool((self._key() or "").strip())

    def _get(self, client: httpx.Client, url: str, params: dict[str, Any]) -> Any:
        response = client.get(url, params=params)
        if response.status_code != 200:
            raise httpx.HTTPStatusError("kakao", request=response.request, response=response)
        return response.json()

    def search(self, query: str) -> dict[str, Any]:
        key = (self._key() or "").strip()
        if not key:
            return self._demo(query, NOTICE_NO_KEY)
        headers = {"Authorization": f"KakaoAK {key}"}
        try:
            with httpx.Client(timeout=TIMEOUT_S, transport=self._transport, headers=headers) as client:
                places = parse_keyword(self._get(client, KEYWORD_URL, {"query": query, "rect": RECT, "size": SIZE}))
                if not places:
                    places = parse_address(self._get(client, ADDRESS_URL, {"query": query, "size": SIZE}))
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            return self._demo(query, NOTICE_FAILED)
        return {"mode": "kakao", "notice": None if places else "검색 결과가 없습니다.",
                "items": [p.as_dict() for p in places]}

    @staticmethod
    def _demo(query: str, notice: str) -> dict[str, Any]:
        return {"mode": "demo", "notice": notice, "items": [p.as_dict() for p in demo_results(query)]}


@lru_cache(maxsize=1)
def get_search_service() -> KakaoSearch:
    return KakaoSearch()
