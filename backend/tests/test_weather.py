"""Requirement 2 with httpx.MockTransport: no real KMA calls."""
from datetime import datetime
import logging

import httpx
from fastapi.testclient import TestClient
import pytest

from app.context import weather_kma as kma
from app.main import app

KEY = "TEST%2BKEY%3D%3D"  # portal "Encoding" key form
DECODED = "TEST+KEY=="


def ncst(rn1="12.5", code="00"):
    return {"response": {"header": {"resultCode": code, "resultMsg": "NORMAL_SERVICE"},
                         "body": {"items": {"item": [{"category": "T1H", "obsrValue": "21.0"},
                                                     {"category": "RN1", "obsrValue": rn1}]}}}}


def warn(items, code="00"):
    return {"response": {"header": {"resultCode": code}, "body": {"items": {"item": items}}}}


def item(area="L1130000", stress=0, command=1, tm="202610301000", seq=1, var=2, cancel=0):
    return {"areaCode": area, "warnVar": var, "warnStress": stress, "command": command, "tmFc": tm,
            "tmSeq": seq, "cancel": cancel}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def service(handler, key=KEY, clock=None, now=datetime(2026, 10, 30, 18, 45, tzinfo=kma.KST)):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)
    svc = kma.KmaWeatherService(key=lambda: key, transport=httpx.MockTransport(wrapped),
                                clock=clock or Clock(), now=lambda: now)
    return svc, calls


def ok_handler(alerts=()):
    def handler(request):
        if request.url.path.endswith("getUltraSrtNcst"):
            return httpx.Response(200, json=ncst())
        return httpx.Response(200, json=warn(list(alerts)))
    return handler


def test_observation_request_uses_gwangju_grid_and_decoded_key():
    svc, calls = service(ok_handler())
    s = svc.get()
    assert s.available and s.rn1_mm == 12.5 and s.alert == "none" and s.alert_status == "ok"
    q = calls[0].url.params
    assert (q["nx"], q["ny"], q["dataType"]) == ("58", "74", "JSON")
    assert (q["base_date"], q["base_time"]) == ("20261030", "1800")
    assert q["serviceKey"] == DECODED
    w = calls[1].url.params
    assert (w["warningType"], w["fromTmFc"], w["toTmFc"]) == ("2", "20261028", "20261030")
    assert s.observed_at == "2026-10-30T18:00:00+09:00"


HUB_KEY = "Abc_123-defGHIjklMNOpq"
# Shapes copied from real wrn_now_data responses, fields space-padded as the API sends them.
GWANGJU_2025_WARNING = {"REG_UP": "L1130000", "REG_ID": "L1050100", "REG_KO": "광주광역시    ", "WRN": "호우  ", "LVL": "경보    ", "CMD": "변경"}
GWANGJU_2026_ADVISORY = {"REG_UP": "L1130100", "REG_ID": "L1130110", "REG_KO": "광주서부   ", "WRN": "호우  ", "LVL": "주의    ", "CMD": "발표"}
GWANGJU_PRELIMINARY = {"REG_UP": "L1130100", "REG_ID": "L1130120", "REG_KO": "광주동부   ", "WRN": "호우  ", "LVL": "예비    ", "CMD": "발표"}
GWANGJU_HEAT = {"REG_UP": "L1130100", "REG_ID": "L1130110", "REG_KO": "광주서부   ", "WRN": "폭염  ", "LVL": "경보    ", "CMD": "발표"}
GYEONGGI_GWANGJU = {"REG_UP": "L1010000", "REG_ID": "L1013400", "REG_KO": "광주시    ", "WRN": "호우  ", "LVL": "경보    ", "CMD": "발표"}
JEONNAM_WARNING = {"REG_UP": "L1050000", "REG_ID": "L1051200", "REG_KO": "순천시    ", "WRN": "호우  ", "LVL": "경보    ", "CMD": "변경"}


def hub_handler(alerts):
    def handler(request):
        if request.url.path.endswith("getUltraSrtNcst"):
            return httpx.Response(200, json=ncst())
        return httpx.Response(200, json=alerts)
    return handler


def test_api_hub_key_uses_the_hub_host_and_auth_param():
    svc, calls = service(hub_handler([]), key=HUB_KEY)
    s = svc.get()
    assert s.available and s.alert == "none" and s.alert_status == "ok"
    assert [c.url.host for c in calls] == ["apihub.kma.go.kr", "apihub.kma.go.kr"]
    assert all(c.url.params["authKey"] == HUB_KEY and "serviceKey" not in c.url.params for c in calls)
    assert calls[1].url.path.endswith("wrn_now_data.php")
    assert (calls[1].url.params["fe"], calls[1].url.params["tm"]) == ("f", "202610301845")


@pytest.mark.parametrize("items, expected", [
    ([], "none"),
    ([GWANGJU_2025_WARNING], "warning"),
    ([GWANGJU_2026_ADVISORY], "advisory"),
    ([GWANGJU_2026_ADVISORY, GWANGJU_2025_WARNING], "warning"),
    ([GWANGJU_PRELIMINARY], "none"),
    ([GWANGJU_HEAT], "none"),
    ([GYEONGGI_GWANGJU, JEONNAM_WARNING], "none"),
    ([{**GWANGJU_2025_WARNING, "CMD": "해제"}], "none"),
])
def test_hub_alert_counts_only_heavy_rain_in_effect_in_gwangju(items, expected):
    assert kma.parse_hub_alert(items)[0] == expected


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="2005년 7월 1일부터 조회 가능합니다."),
    httpx.Response(200, json={"result": {"status": 403}}),
    httpx.Response(403, json={"result": {"status": 403}}),
])
def test_hub_alert_errors_are_reported_not_read_as_no_alert(response):
    def handler(request):
        return httpx.Response(200, json=ncst()) if request.url.path.endswith("getUltraSrtNcst") else response
    s = service(handler, key=HUB_KEY)[0].get()
    assert s.available and s.alert_status == "failed" and s.alert_label == "특보 확인 실패"


def test_newest_hour_is_tried_first_then_the_previous_one():
    now = datetime(2026, 10, 30, 18, 5, tzinfo=kma.KST)

    def handler(request):
        if request.url.params.get("base_time") == "1800":
            return httpx.Response(200, json=ncst(code="03"))
        return httpx.Response(200, json=ncst()) if request.url.path.endswith("getUltraSrtNcst") else httpx.Response(200, json=warn([]))
    svc, calls = service(handler, now=now)
    s = svc.get()
    assert [c.url.params["base_time"] for c in calls[:2]] == ["1800", "1700"]
    assert s.available and s.observed_at == "2026-10-30T17:00:00+09:00"


def test_no_published_hour_means_unavailable():
    svc, _ = service(lambda request: httpx.Response(200, json=ncst(code="03")))
    assert not svc.get().available


def test_portal_key_stays_on_the_portal_host():
    svc, calls = service(ok_handler(), key="a" * 64)
    assert svc.get().available
    assert [c.url.host for c in calls] == ["apis.data.go.kr", "apis.data.go.kr"]
    assert all(c.url.params["serviceKey"] == "a" * 64 and "authKey" not in c.url.params for c in calls)


def test_hub_rejecting_the_alert_api_keeps_rainfall_and_reports_the_alert_failure():
    def handler(request):
        if request.url.path.endswith("getUltraSrtNcst"):
            return httpx.Response(200, json=ncst())
        return httpx.Response(403, json={"result": {"status": 403, "message": "허용되지 않은 API 입니다."}})
    svc, _ = service(handler, key="Abc_123-defGHIjklMNOpq")
    s = svc.get()
    assert s.available and s.rn1_mm == 12.5
    assert s.alert_status == "failed" and s.alert_label == "특보 확인 실패"


@pytest.mark.parametrize("hour, minute, newest, previous", [
    (18, 39, "2026-10-30 18:00", "2026-10-30 17:00"),
    (0, 5, "2026-10-30 00:00", "2026-10-29 23:00"),
])
def test_observation_hours(hour, minute, newest, previous):
    hours = kma.observation_hours(datetime(2026, 10, 30, hour, minute, tzinfo=kma.KST))
    assert [t.strftime("%Y-%m-%d %H:%M") for t in hours] == [newest, previous]


def test_results_are_cached_for_ten_minutes():
    clock = Clock()
    svc, calls = service(ok_handler(), clock=clock)
    svc.get()
    clock.t += 599
    svc.get()
    assert len(calls) == 2  # observation + alert, once
    clock.t += 2
    svc.get()
    assert len(calls) == 4


def test_missing_key_is_unavailable_without_network():
    svc, calls = service(ok_handler(), key="")
    s = svc.get()
    assert not s.available and s.message == "기상 정보를 가져오지 못했습니다" and calls == []


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<OpenAPI_ServiceResponse><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR"),
    httpx.Response(500, json={}),
    httpx.Response(200, json=ncst(code="30")),
    httpx.Response(200, json=ncst(rn1="abc")),
])
def test_observation_failures_are_unavailable(response):
    svc, _ = service(lambda request: response)
    s = svc.get()
    assert not s.available and s.rn1_mm is None


def test_timeout_is_unavailable_and_failure_cached_one_minute():
    clock = Clock()

    def handler(request):
        raise httpx.ConnectTimeout("timeout", request=request)
    svc, calls = service(handler, clock=clock)
    assert not svc.get().available
    clock.t += 30
    svc.get()
    assert len(calls) == 1
    clock.t += 31
    svc.get()
    assert len(calls) == 2


def test_alert_failure_keeps_rainfall():
    def handler(request):
        if request.url.path.endswith("getUltraSrtNcst"):
            return httpx.Response(200, json=ncst("35"))
        return httpx.Response(502)
    s, _ = service(handler)
    snap = s.get()
    assert snap.available and snap.rn1_mm == 35 and snap.alert == "none" and snap.alert_status == "failed"


@pytest.mark.parametrize("items, expected", [
    ([], "none"),
    ([item(area="L1013400", stress=1)], "none"),  # 경기 광주시
    ([item(var=1, stress=1)], "none"),            # 강풍
    ([item(area="L1130110", stress=0)], "advisory"),
    ([item(stress=0, command=1, tm="202610300900"), item(stress=0, command=8, tm="202610301100"),
      item(stress=1, command=7, tm="202610301100")], "warning"),
    ([item(stress=1, command=1, tm="202610300900"), item(stress=1, command=2, tm="202610301200")], "none"),
    ([item(stress=1, cancel=1)], "none"),
    ([item(stress=1, command=3)], "warning"),
])
def test_alert_parsing(items, expected):
    assert kma.parse_alert(warn(items))[0] == expected


def test_alert_nodata_and_severe_warning_label():
    assert kma.parse_alert(warn([], code="03")) == ("none", "없음")
    assert kma.parse_alert(warn([item(stress=2)])) == ("warning", "호우경보 (중대)")
    assert kma.parse_alert({"response": {"header": {"resultCode": "00"},
                                         "body": {"items": {"item": item(stress=0)}}}})[0] == "advisory"


def test_key_never_appears_in_logs_or_api_response(caplog):
    caplog.set_level(logging.DEBUG)
    svc, _ = service(ok_handler([item(stress=0)]))
    app.dependency_overrides[kma.get_weather_service] = lambda: svc
    try:
        with TestClient(app) as client:
            body = client.get("/api/weather").json()
    finally:
        app.dependency_overrides.clear()
    assert body["available"] and body["rn1_mm"] == 12.5 and body["alert"] == "advisory"
    assert body["level"] == 1 and body["source"] == "kma" and body["grid"] == {"nx": 58, "ny": 74}
    for secret in ("TEST", DECODED, KEY):
        assert secret not in str(body) and secret not in caplog.text


def test_weather_api_without_key():
    svc, _ = service(ok_handler(), key=None)
    app.dependency_overrides[kma.get_weather_service] = lambda: svc
    try:
        with TestClient(app) as client:
            body = client.get("/api/weather").json()
    finally:
        app.dependency_overrides.clear()
    assert body == {**body, "available": False, "source": "unavailable", "level": None,
                    "message": "기상 정보를 가져오지 못했습니다"}
