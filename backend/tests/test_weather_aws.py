"""Per-minute AWS rainfall, falling back to the hourly observation."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.context.weather_aws import AwsFormatError, Station, nearest_rain, parse_minute_table, parse_stations
from app.context.weather_kma import AWS_MINUTE_URL, AWS_STATIONS_URL, HUB_ALERT_URL, HUB_NCST_URL, KmaWeatherService

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 31, 9, 0, tzinfo=KST)
SERVICE_KEY, AWS_KEY = "a" * 22, "b" * 22
HEADER = """#START7777
# YYMMDDHHMI   STN    WD1    WS1    WDS    WSS   WD10   WS10     TA     RE RN-15m RN-60m RN-12H RN-DAY     HM     PA     PS     TD
#        KST    ID    deg    m/s    deg    m/s    deg    m/s      C      1     mm     mm     mm     mm      %    hPa    hPa      C
"""


def row(stn, rn60, at="202610310857"):
    return f"{at} {stn:>5} 63.4 0.1 40.0 0.3 36.3 0.4 14.4 -99.9 0.0 {rn60} 0.0 0.0 87.6 1014.0 1022.4 12.4\n"


TABLE = HEADER + row(156, 35.5) + row(316, 90.0) + row(722, -99.9) + row(708, 12.0) + "#7777END\n"
STATIONS = """#START7777
# STN LON LAT STN_SP HT HT_WD LAU STN STN_KO STN_EN FCT_ID LAW_ID BASIN LAW_ADDR
  156 126.89156 35.17294 01211111 72.38 10.00 0 156 광주 Gwangju 11F20501 2917010600 ---- 광주 북구
  316 126.98810 35.13421 01211111 916.00 10.00 0 156 무등산 ---- 11F20501 2911010100 ---- 광주 동구
  722 126.93330 35.14000 01211111 60.00 10.00 0 156 조선대 ---- 11F20501 2911010100 ---- 광주 동구
  708 126.79100 35.17000 01211111 20.00 10.00 0 156 광산 ---- 11F20501 2920010100 ---- 광주 광산구
#7777END
"""
NCST = {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [{"category": "RN1", "obsrValue": "1"}]}}}}
ALERTS = [{"REG_UP": "L1130000", "REG_ID": "L1130110", "WRN": "호우", "LVL": "경보", "CMD": "발표"}]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def service(minute=TABLE, stations=STATIONS, status=200, aws_key=AWS_KEY, clock=None):
    calls = []

    def handler(request):
        url = str(request.url).split("?")[0]
        calls.append(request.url)
        if url == AWS_MINUTE_URL:
            return httpx.Response(status, content=minute.encode("euc-kr"))
        if url == AWS_STATIONS_URL:
            return httpx.Response(status, content=stations.encode("euc-kr"))
        if url == HUB_ALERT_URL:
            return httpx.Response(200, json=ALERTS)
        assert url == HUB_NCST_URL
        return httpx.Response(200, json=NCST)

    svc = KmaWeatherService(key=lambda: SERVICE_KEY, aws_key=lambda: aws_key, transport=httpx.MockTransport(handler),
                            clock=clock or Clock(), now=lambda: NOW)
    return svc, calls


def urls(calls, url):
    return [c for c in calls if str(c).split("?")[0] == url]


def test_rain_comes_from_the_nearest_station_with_a_reading():
    svc, calls = service()
    s = svc.get((126.909, 35.176))
    assert (s.rn1_mm, s.station, s.available) == (35.5, "광주", True)
    assert s.observed_at == "2026-10-31T08:57:00+09:00"
    assert s.alert == "warning"
    assert urls(calls, HUB_NCST_URL) == []


def test_the_two_keys_go_to_their_own_apis():
    svc, calls = service()
    svc.get((126.909, 35.176))
    assert all(c.params["authKey"] == AWS_KEY for c in urls(calls, AWS_MINUTE_URL) + urls(calls, AWS_STATIONS_URL))
    assert all(c.params["authKey"] == SERVICE_KEY for c in urls(calls, HUB_ALERT_URL))


def test_no_time_is_asked_for_and_no_coordinates_are_sent():
    svc, calls = service()
    svc.get((126.909, 35.176))
    params = urls(calls, AWS_MINUTE_URL)[0].params
    assert "tm" not in params and "tm2" not in params and "lon" not in params and "lat" not in params


def test_missing_reading_is_skipped_not_read_as_dry():
    # 조선대 (722) is closest here but has no reading.
    svc, _ = service()
    assert svc.get((126.935, 35.14)).station == "광주"


def test_mountain_station_is_not_used():
    svc, _ = service()
    assert svc.get((126.988, 35.134)).station != "무등산"


def test_many_places_share_one_table_and_it_refreshes_after_two_minutes():
    clock = Clock()
    svc, calls = service(clock=clock)
    svc.get((126.909, 35.176))
    svc.get((126.79, 35.17))
    svc.get()
    assert len(urls(calls, AWS_MINUTE_URL)) == 1 and len(urls(calls, AWS_STATIONS_URL)) == 1
    clock.t += 119
    svc.get((126.909, 35.176))
    assert len(urls(calls, AWS_MINUTE_URL)) == 1
    clock.t += 2
    svc.get((126.909, 35.176))
    assert len(urls(calls, AWS_MINUTE_URL)) == 2 and len(urls(calls, AWS_STATIONS_URL)) == 1


@pytest.mark.parametrize("kwargs", [{"aws_key": ""}, {"status": 403}, {"minute": "<html>error</html>"}, {"minute": HEADER},
                                    {"stations": "#nothing\n"}])
def test_falls_back_to_the_hourly_observation(kwargs):
    svc, calls = service(**kwargs)
    s = svc.get((126.909, 35.176))
    assert s.available and s.rn1_mm == 1.0 and s.station is None
    assert len(urls(calls, HUB_NCST_URL)) >= 1


def test_a_failing_aws_is_not_retried_for_a_minute():
    clock = Clock()
    svc, calls = service(status=403, clock=clock)
    svc.get((126.909, 35.176))
    svc.get((126.79, 35.17))
    assert len(urls(calls, AWS_STATIONS_URL)) == 1
    clock.t += 61
    svc.get((126.5, 34.9))
    assert len(urls(calls, AWS_STATIONS_URL)) == 2


def test_no_station_nearby_falls_back():
    svc, calls = service()
    s = svc.get((127.66, 34.76))  # 여수: the stations in this table are all in Gwangju
    assert s.station is None and s.rn1_mm == 1.0 and urls(calls, HUB_NCST_URL)


def test_old_reading_is_not_used():
    svc, _ = service(minute=HEADER + row(156, 35.5, at="202610310800"))
    assert svc.get((126.909, 35.176)).station is None


def test_parsers_reject_other_shapes():
    with pytest.raises(AwsFormatError):
        parse_minute_table(row(156, 1.0))  # no header
    with pytest.raises(AwsFormatError):
        parse_stations("#only comments\n")
    assert parse_stations(STATIONS)["316"].height_m == 916.0
    assert parse_minute_table(TABLE)["156"][1] == 35.5


def test_nearest_needs_a_station_within_range():
    stations = [Station("1", "먼곳", 127.5, 35.16, 10.0)]
    table = {"1": (NOW, 5.0)}
    assert nearest_rain(stations, table, 126.85, 35.16, NOW) is None
