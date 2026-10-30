"""Weather at a chosen place or the current location, within Gwangju and Jeonnam."""
import logging
import threading

from fastapi.testclient import TestClient
import httpx
import pytest

from app.api.deps import layer_dep
from app.context import weather_kma
from app.context.weather_kma import (BUSY, HUB_ALERT_URL, KmaWeatherService, WeatherSnapshot, get_weather_service,
                                     parse_hub_alert)
from app.context.weather_regions import GWANGJU_AREA_CODES, REGIONS, grid_of, in_weather_area, region_for
from app.engines import get_engine
from app.engines.fake import FakeCandidate, FakeEngine
from app.main import app

from routing_fixtures import CANDIDATES, DESTINATION, ORIGIN, corridor_layer

HUB_KEY = "a" * 22
YEOSU = next(r for r in REGIONS if r.id == "yeosu")
NAJU = next(r for r in REGIONS if r.id == "naju")


def ncst(rn1="12"):
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [
        {"category": "RN1", "obsrValue": rn1}]}}}}


def service(alerts=(), rain=lambda nx, ny: "12"):
    calls = []

    def handler(request):
        calls.append(request.url)
        if str(request.url).startswith(HUB_ALERT_URL):
            return httpx.Response(200, json=list(alerts))
        return httpx.Response(200, json=ncst(rain(request.url.params["nx"], request.url.params["ny"])))

    return KmaWeatherService(key=lambda: HUB_KEY, transport=httpx.MockTransport(handler)), calls


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def alert(code, level="경보", cmd="발표", up="L1050000"):
    return {"REG_UP": up, "REG_ID": code, "WRN": "호우", "LVL": level, "CMD": cmd}


@pytest.mark.parametrize("lon, lat, expected", [
    (126.978, 37.5665, (60, 127)),   # 서울 종로, the grid value KMA publishes
    (126.8514, 35.1600, (58, 74)),   # 광주광역시청
])
def test_grid_formula(lon, lat, expected):
    assert grid_of(lon, lat) == expected


def test_regions_are_complete_and_have_codes():
    names = {r.name for r in REGIONS}
    assert {"광주 광산구", "목포시", "여수시", "순천시", "나주시", "광양시", "신안군", "진도군"} <= names
    assert sum(r.group == "전남" for r in REGIONS) == 24  # 22 cities and counties, 2 island zones
    assert all(r.alert_codes for r in REGIONS)
    assert all(code.startswith("L105") for r in REGIONS if r.group == "전남" for code in r.alert_codes)
    assert all(in_weather_area(r.lon, r.lat) for r in REGIONS)


@pytest.mark.parametrize("lon, lat, name", [
    (127.67, 34.75, "여수시"), (126.79, 35.14, "광주 광산구"), (125.45, 34.70, "흑산도·홍도"), (126.40, 34.80, "목포시"),
])
def test_nearest_region(lon, lat, name):
    assert region_for(lon, lat).name == name


def test_each_place_reads_its_own_grid_and_is_cached_separately():
    svc, calls = service(rain=lambda nx, ny: "40" if (nx, ny) == (str(grid_of(YEOSU.lon, YEOSU.lat)[0]),
                                                                  str(grid_of(YEOSU.lon, YEOSU.lat)[1])) else "1")
    home, yeosu = svc.get(), svc.get((YEOSU.lon, YEOSU.lat))
    assert (home.rn1_mm, home.region, home.grid) == (1.0, "광주광역시", (58, 74))
    assert (yeosu.rn1_mm, yeosu.region, yeosu.grid) == (40.0, "여수시", grid_of(YEOSU.lon, YEOSU.lat))
    count = svc.fetch_count
    svc.get(), svc.get((YEOSU.lon, YEOSU.lat))
    assert svc.fetch_count == count
    assert sum(str(u).startswith(HUB_ALERT_URL) for u in calls) == 1  # one alert list serves every place


def test_only_gwangju_readings_can_drive_the_route_rules():
    svc, _ = service()
    assert svc.get().routable and svc.get((126.79, 35.14)).routable
    assert not svc.get((YEOSU.lon, YEOSU.lat)).routable


def counting_service(clock, handler=None):
    calls = []

    def respond(request):
        calls.append(request.url)
        if str(request.url).startswith(HUB_ALERT_URL):
            return httpx.Response(200, json=[])
        return handler(request) if handler else httpx.Response(200, json=ncst("3"))

    return KmaWeatherService(key=lambda: HUB_KEY, transport=httpx.MockTransport(respond), clock=clock), calls


def test_a_slow_place_does_not_hold_up_another():
    release, second_done = threading.Event(), threading.Event()
    slow_nx = str(grid_of(YEOSU.lon, YEOSU.lat)[0])

    def handler(request):
        if request.url.params["nx"] == slow_nx:
            release.wait(5)  # stays here until the other place has finished
        return httpx.Response(200, json=ncst("3"))

    svc, _ = counting_service(Clock(), handler)
    svc.get((126.39, 34.81))  # the shared alert list is fetched here, outside the slow call
    slow = threading.Thread(target=svc.get, args=((YEOSU.lon, YEOSU.lat),))
    slow.start()

    def other():
        svc.get((NAJU.lon, NAJU.lat))
        second_done.set()

    threading.Thread(target=other).start()
    assert second_done.wait(3), "another place waited for the slow one"
    release.set()
    slow.join(5)


def test_requests_for_one_place_share_one_reading():
    gate = threading.Event()

    def handler(request):
        gate.wait(0.3)
        return httpx.Response(200, json=ncst("3"))

    svc, _ = counting_service(Clock(), handler)
    threads = [threading.Thread(target=svc.get, args=((YEOSU.lon, YEOSU.lat),)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert svc.fetch_count == 1


def far_apart(n):
    return [(125.1 + i * 0.1, 34.0 + (i % 15) * 0.1) for i in range(n)]


def test_new_readings_stop_at_the_budget_and_recover(monkeypatch):
    monkeypatch.setattr(weather_kma, "READINGS_PER_MINUTE", 3)
    clock = Clock()
    svc, _ = counting_service(clock)
    points = far_apart(5)
    results = [svc.get(p) for p in points]
    assert [r.available for r in results] == [True, True, True, False, False]
    assert results[3].message == BUSY and svc.fetch_count == 3
    assert results[3].region and results[3].grid == grid_of(*points[3])  # still says which place
    assert svc.get(points[0]).available and svc.fetch_count == 3  # what was read is still served
    clock.t += 61
    assert svc.get(points[3]).available and svc.fetch_count == 4


def test_over_budget_serves_the_last_reading_and_the_default_place(monkeypatch):
    monkeypatch.setattr(weather_kma, "READINGS_PER_MINUTE", 1)
    clock = Clock()
    svc, _ = counting_service(clock)
    point = (YEOSU.lon, YEOSU.lat)
    assert svc.get(point).available
    clock.t += 601  # the reading expired
    svc.get(far_apart(1)[0])  # takes this minute's budget
    assert svc.get(point).available and svc.fetch_count == 2
    assert svc.get().available and svc.fetch_count == 3  # the main screen never hits the budget


def test_daily_budget(monkeypatch):
    monkeypatch.setattr(weather_kma, "READINGS_PER_DAY", 2)
    clock = Clock()
    svc, _ = counting_service(clock)
    points = far_apart(4)
    assert svc.get(points[0]).available
    clock.t += 3600
    assert svc.get(points[1]).available
    clock.t += 3600
    assert not svc.get(points[2]).available
    clock.t += 86400
    assert svc.get(points[3]).available


def test_kma_never_receives_coordinates():
    svc, calls = service()
    svc.get((YEOSU.lon, YEOSU.lat))
    assert not any("127.66" in str(u) or "34.76" in str(u) for u in calls)
    assert all(not {"lon", "lat"} & set(u.params) for u in calls)


def test_alerts_follow_the_region():
    items = [alert("L1051000")]
    assert parse_hub_alert(items, YEOSU.alert_codes)[0] == "warning"
    assert parse_hub_alert(items, NAJU.alert_codes)[0] == "none"
    assert parse_hub_alert(items, GWANGJU_AREA_CODES)[0] == "none"
    # A split county counts either part. The province as a parent code does not reach every county.
    assert parse_hub_alert([alert("L1052820", "주의")], NAJU.alert_codes)[0] == "advisory"
    assert parse_hub_alert([alert("L1052820", "주의")], YEOSU.alert_codes)[0] == "none"


@pytest.fixture
def client():
    state = {}

    class Stub:
        def get(self, point=None):
            state["point"] = point
            return WeatherSnapshot(True, 55.0, "none", "없음", "ok", "2026-10-30T18:00:00+09:00", None, "광주 서구", (58, 74))

    app.dependency_overrides[get_weather_service] = lambda: Stub()
    app.dependency_overrides[layer_dep] = corridor_layer
    app.dependency_overrides[get_engine] = lambda: FakeEngine([FakeCandidate(c["coords"], c["duration"]) for c in CANDIDATES])
    with TestClient(app) as value:
        value.state_seen = state
        yield value
    app.dependency_overrides.clear()


def test_api_reads_weather_at_a_point_from_the_body(client, caplog):
    caplog.set_level(logging.DEBUG)
    response = client.post("/api/weather", json={"lon": YEOSU.lon, "lat": YEOSU.lat})
    assert response.status_code == 200 and response.json()["region"] == "광주 서구" and response.json()["level"] == 2
    assert client.state_seen["point"] == (YEOSU.lon, YEOSU.lat)
    assert str(YEOSU.lon) not in caplog.text and str(YEOSU.lat) not in caplog.text


@pytest.mark.parametrize("point", [{"lon": 126.978, "lat": 37.5665}, {"lon": 129.0, "lat": 35.1}])
def test_outside_gwangju_and_jeonnam_is_refused(client, point):
    response = client.post("/api/weather", json=point)
    assert response.status_code == 422 and "광주·전남" in response.json()["detail"]
    assert "point" not in client.state_seen


def test_get_keeps_the_default_place(client):
    assert client.get("/api/weather").status_code == 200
    assert client.state_seen["point"] is None


def test_regions_list_has_no_alert_codes(client):
    data = client.get("/api/weather/regions").json()
    assert data[0]["name"] == "광주광역시" and set(data[0]) == {"id", "name", "group", "lon", "lat"}


def test_route_uses_the_weather_at_its_start(client):
    data = client.post("/api/route", json={"origin": {"lon": ORIGIN[0], "lat": ORIGIN[1]},
                                           "destination": {"lon": DESTINATION[0], "lat": DESTINATION[1]},
                                           "strategy": "tiered_rain"}).json()
    assert client.state_seen["point"] == ORIGIN
    assert data["weather"]["region"] == "광주 서구" and data["weather"]["level"] == 2


def test_reroute_uses_the_weather_at_the_car(client):
    client.post("/api/route/reroute", json={
        "position": {"lon": 126.82, "lat": 35.15}, "destination": {"lon": DESTINATION[0], "lat": DESTINATION[1]},
        "remaining": [[126.82, 35.15], list(DESTINATION)], "remaining_duration_s": 300,
        "previous": {"rn1_mm": 0, "alert": "none"}})
    assert client.state_seen["point"] == (126.82, 35.15)
