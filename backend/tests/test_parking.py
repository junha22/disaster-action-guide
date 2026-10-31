"""Parked car check: the rule, the rain readings and the answer the card shows."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import httpx
import pytest

from app.api.deps import layer_dep
from app.context.parking_rain import PastRain, ParkingRainService, forecast_mm, get_parking_rain_service, hourly_rain, parse_forecast
from app.context.weather_aws import parse_station_rows
from app.context.weather_kma import KmaError
from app.main import app
from app.parking import DEMO_FORECAST, DEMO_PAST, check_rain, countdown_minutes, factor_of, find_zone, is_danger, load_zones

from routing_fixtures import LAT, ORIGIN, corridor_layer, make_zone, square

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 31, 9, 20, tzinfo=KST)
MANGWOL = (126.9558918, 35.2047702)


def test_zone_file_matches_its_notes():
    zones = load_zones()
    assert len(zones) == 55
    assert all(z.geometry.is_valid for z in zones)
    assert [sum(z.grade == g for z in zones) for g in ("상습", "보통", "단발")] == [6, 25, 24]
    assert find_zone(*MANGWOL).main_dong == "망월동"
    assert find_zone(126.8, 35.1) is None


def test_rule_at_its_boundaries():
    assert is_danger(30.0, 0.0, 1.0)
    assert not is_danger(29.9, 0.0, 1.0)
    assert is_danger(29.9, 200.0, 1.0)  # wet ground: 3h 20 is enough
    assert not is_danger(19.9, 200.0, 1.0)
    assert is_danger(20.0, 90.0, 1.0)
    assert not is_danger(20.0, 89.9, 1.0)
    assert is_danger(24.0, 0.0, factor_of("상습"))
    assert not is_danger(24.0, 0.0, factor_of("단발"))


def test_countdown_of_the_sample_in_the_notes():
    assert countdown_minutes(DEMO_PAST, DEMO_FORECAST, factor_of("상습")) == 30
    assert countdown_minutes(DEMO_PAST, DEMO_FORECAST, factor_of("단발")) == 80


def test_countdown_now_and_never():
    assert countdown_minutes((0.0,) * 21 + (10.0, 10.0, 10.0), (0.0,) * 6, 1.0) == 0
    assert countdown_minutes((0.0,) * 24, (0.0,) * 6, 1.0) is None
    assert countdown_minutes((0.0,) * 24, (), 1.0) is None


def test_check_reports_the_thresholds_of_the_grade():
    rain = check_rain(DEMO_PAST, DEMO_FORECAST, "상습")
    assert (rain["minutes"], rain["need_3h"], rain["wet_24h"], rain["wet_3h"]) == (30, 24.0, 72.0, 16.0)
    assert (rain["sum_3h"], rain["sum_24h"], rain["forecast_peak_mm"]) == (18.0, 66.0, 20.0)
    assert check_rain(DEMO_PAST, None, None)["forecast_hours"] == 0


@pytest.mark.parametrize("value, mm", [("강수없음", 0), ("1mm 미만", 1), ("3.0mm", 3), ("30.0~50.0mm", 50), ("50.0mm 이상", 50), ("2", 2)])
def test_forecast_values_use_the_top_of_a_range(value, mm):
    assert forecast_mm(value) == mm


def test_unknown_forecast_value_is_not_read_as_dry():
    with pytest.raises(KmaError):
        forecast_mm("모름")


def minutes(values_by_hours_ago, *, newest=datetime(2026, 10, 31, 9, 15, tzinfo=KST)):
    return [(newest - timedelta(hours=h), mm) for h, mm in values_by_hours_ago.items()]


def test_hourly_rain_counts_back_from_the_newest_reading():
    rows = minutes({h: float(h) for h in range(24)})
    past = hourly_rain(rows, NOW)
    assert past.hours == tuple(float(h) for h in range(23, -1, -1))
    assert past.missing_hours == 0
    assert past.observed_at == "2026-10-31T09:15:00+09:00"


def test_hourly_rain_takes_a_nearby_minute_and_counts_gaps():
    rows = minutes({h: 1.0 for h in range(24) if h not in (3, 4)}) + [(datetime(2026, 10, 31, 6, 13, tzinfo=KST), 7.0)]
    past = hourly_rain(rows, NOW)
    assert past.hours[-4] == 7.0  # two minutes from the hour it stands for
    assert past.missing_hours == 1


def test_hourly_rain_refuses_old_or_gappy_data():
    assert hourly_rain(minutes({0: 1.0}), NOW + timedelta(hours=2)) is None
    assert hourly_rain(minutes({0: 1.0}), NOW) is None  # 23 hours missing
    assert hourly_rain([(NOW, -99.9)], NOW) is None
    assert hourly_rain([], NOW) is None


def test_missing_readings_do_not_count_as_newest():
    rows = minutes({h: 1.0 for h in range(24)}) + [(datetime(2026, 10, 31, 9, 18, tzinfo=KST), -99.9)]
    assert hourly_rain(rows, NOW).observed_at == "2026-10-31T09:15:00+09:00"


FORECAST = {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [
    {"category": "T1H", "fcstDate": "20261031", "fcstTime": "1000", "fcstValue": "14"},
    {"category": "RN1", "fcstDate": "20261031", "fcstTime": "1100", "fcstValue": "30.0~50.0mm"},
    {"category": "RN1", "fcstDate": "20261031", "fcstTime": "1000", "fcstValue": "1mm 미만"},
    {"category": "RN1", "fcstDate": "20261031", "fcstTime": "0900", "fcstValue": "9.0mm"},  # already over
]}}}}


def test_forecast_keeps_the_hours_ahead_in_order():
    assert parse_forecast(FORECAST, NOW) == [1.0, 50.0]


HEADER = "# YYMMDDHHMI   STN RN-15m RN-60m\n"


def rain_service(handler):
    return ParkingRainService(key=lambda: "a" * 22, aws_key=lambda: "b" * 22, transport=httpx.MockTransport(handler),
                              now=lambda: NOW)


def test_station_rows_keep_only_that_station():
    text = HEADER + "202610310900 156 0.0 1.5\n202610310900 722 0.0 9.0\n"
    assert parse_station_rows(text, "156") == [(datetime(2026, 10, 31, 9, 0, tzinfo=KST), 1.5)]


def test_past_asks_one_station_for_one_day_and_caches():
    seen = []

    def handler(request):
        seen.append(request.url)
        rows = "".join(f"{(NOW - timedelta(minutes=5, hours=h)).strftime('%Y%m%d%H%M')} 156 0.0 2.0\n" for h in range(24))
        return httpx.Response(200, content=(HEADER + rows).encode("euc-kr"))

    service = rain_service(handler)
    assert sum(service.past().hours) == 48.0
    assert service.past() is not None
    assert len(seen) == 1
    assert seen[0].params["stn"] == "156"
    assert (seen[0].params["tm1"], seen[0].params["tm2"]) == ("202610300916", "202610310915")


def test_failed_readings_are_unknown_not_dry():
    service = rain_service(lambda request: httpx.Response(500))
    assert service.past() is None
    assert service.forecast((59, 75)) is None


def test_forecast_sends_only_the_grid_and_uses_the_published_time():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=FORECAST)

    assert rain_service(handler).forecast((59, 75)) == [1.0, 50.0]
    assert (seen[0].params["nx"], seen[0].params["ny"]) == ("59", "75")
    assert seen[0].params["base_time"] == "0830"
    assert "lon" not in seen[0].params and "x" not in seen[0].params


def test_forecast_tries_the_hour_before_when_not_published():
    answers = [{"response": {"header": {"resultCode": "03"}}}, FORECAST]
    seen = []

    def handler(request):
        seen.append(request.url.params["base_time"])
        return httpx.Response(200, json=answers[len(seen) - 1])

    assert rain_service(handler).forecast((59, 75)) == [1.0, 50.0]
    assert seen == ["0830", "0730"]


class StubRain:
    past_value: PastRain | None = PastRain((0.0,) * 21 + (10.0, 10.0, 10.0), "2026-10-31T09:15:00+09:00", 1)
    forecast_value: list[float] | None = [0.0] * 6

    def past(self):
        return self.past_value

    def forecast(self, grid):
        return self.forecast_value


@pytest.fixture
def client():
    rain = StubRain()
    state = {"rain": rain}
    home_zone = make_zone("z-home", "flood_history", square(ORIGIN[0], LAT, 60), tier="high", name="출발지 침수 구역")
    layer = corridor_layer((home_zone,))
    app.dependency_overrides[get_parking_rain_service] = lambda: state["rain"]
    app.dependency_overrides[layer_dep] = lambda: layer
    with TestClient(app) as value:
        value.state = state
        yield value
    app.dependency_overrides.clear()


def test_api_demo_uses_the_labelled_sample(client):
    data = client.post("/api/parking/check", json={"lon": MANGWOL[0], "lat": MANGWOL[1], "demo": True}).json()
    assert data["demo"] is True
    assert data["rain"]["minutes"] == 30
    assert (data["zone"]["grade"], data["zone"]["name"]) == ("상습", "망월동 일대")


def test_api_real_rain_at_the_threshold(client):
    data = client.post("/api/parking/check", json={"lon": MANGWOL[0], "lat": MANGWOL[1]}).json()
    assert (data["demo"], data["status"], data["rain"]["minutes"], data["missing_hours"]) == (False, "known", 0, 1)


def test_api_counts_records_outside_the_buk_zones(client):
    zone = client.post("/api/parking/check", json={"lon": ORIGIN[0], "lat": ORIGIN[1]}).json()["zone"]
    assert (zone["kind"], zone["name"], zone["grade"]) == ("service_records", "출발지 침수 구역", None)


def test_api_no_record_is_not_called_safe_and_still_watches_rain(client):
    data = client.post("/api/parking/check", json={"lon": 126.84, "lat": 35.25}).json()
    assert data["zone"] is None
    assert data["rain"]["minutes"] == 0  # 30 mm in 3 hours, zone or no zone


def test_api_without_rain_data_is_unknown(client):
    client.state["rain"] = type("NoRain", (StubRain,), {"past_value": None})()
    data = client.post("/api/parking/check", json={"lon": MANGWOL[0], "lat": MANGWOL[1]}).json()
    assert (data["status"], data["rain"], data["forecast_ok"]) == ("unknown", None, False)


def test_api_without_forecast_says_so(client):
    client.state["rain"] = type("NoForecast", (StubRain,), {"forecast_value": None})()
    data = client.post("/api/parking/check", json={"lon": MANGWOL[0], "lat": MANGWOL[1]}).json()
    assert data["forecast_ok"] is False
    assert data["rain"]["forecast_hours"] == 0


def test_api_refuses_a_place_outside_the_service_area_without_echoing_it(client):
    response = client.post("/api/parking/check", json={"lon": 127.5, "lat": 36.5})
    assert response.status_code == 422
    assert "127.5" not in response.text
