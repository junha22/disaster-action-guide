"""Requirement 1 with httpx.MockTransport: no real Kakao calls."""
import logging

import httpx
from fastapi.testclient import TestClient
import pytest

from app.context import kakao
from app.main import app

GWANGJU = {"id": "1", "place_name": "광주역", "address_name": "광주 북구 중흥동 611",
           "road_address_name": "광주 북구 무등로 235", "x": "126.909", "y": "35.165"}
GYEONGGI = {"id": "2", "place_name": "경기광주역", "address_name": "경기 광주시 역동 1",
            "road_address_name": "경기 광주시 역동로 1", "x": "127.25", "y": "37.41"}


def kakao_service(handler, key="kakao-test-key"):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)
    return kakao.KakaoSearch(key=lambda: key, transport=httpx.MockTransport(wrapped)), calls


def client_with(service):
    app.dependency_overrides[kakao.get_search_service] = lambda: service
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_keyword_results_mark_outside_gwangju_and_send_only_query_and_box():
    svc, calls = kakao_service(lambda r: httpx.Response(200, json={"documents": [GWANGJU, GYEONGGI]}))
    result = svc.search("광주역")
    assert result["mode"] == "kakao"
    first, second = result["items"]
    assert first["selectable"] and first["name"] == "광주역" and first["address"].startswith("광주 북구")
    assert not second["selectable"] and second["reason"] == "데모 지역 밖"
    request = calls[0]
    assert request.headers["Authorization"] == "KakaoAK kakao-test-key"
    assert set(request.url.params) == {"query", "rect", "size"}
    assert request.url.params["rect"] == "126.63,35.04,127.03,35.27" and request.url.params["size"] == "10"


def test_address_search_is_used_when_keyword_has_no_result():
    address = {"address_name": "광주 서구 내방로 111", "x": "126.8514", "y": "35.16",
               "address": {"region_1depth_name": "광주"}}

    def handler(request):
        if request.url.path.endswith("keyword.json"):
            return httpx.Response(200, json={"documents": []})
        return httpx.Response(200, json={"documents": [address]})
    svc, calls = kakao_service(handler)
    result = svc.search("내방로 111")
    assert [c.url.path for c in calls] == ["/v2/local/search/keyword.json", "/v2/local/search/address.json"]
    assert result["items"][0]["selectable"] and result["items"][0]["name"] == "광주 서구 내방로 111"


def test_current_full_gwangju_admin_name_is_selectable():
    place = {"id": "3", "place_name": "광주송정역",
             "address_name": "전남광주통합특별시 광산구 송정동 1003-1",
             "road_address_name": "전남광주통합특별시 광산구 상무대로 201",
             "x": "126.7908", "y": "35.1377"}
    svc, _ = kakao_service(lambda r: httpx.Response(200, json={"documents": [place]}))
    result = svc.search("광주송정역")
    assert result["items"][0]["selectable"]


def test_missing_key_uses_demo_points_without_network():
    svc, calls = kakao_service(lambda r: httpx.Response(200, json={}), key=None)
    result = svc.search("광주역")
    assert calls == [] and result["mode"] == "demo" and "카카오 API 키" in result["notice"]
    assert result["items"][0]["name"] == "광주역"
    assert 5 <= len(result["items"]) <= 8 and all(i["selectable"] for i in result["items"])


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(401, json={"errorType": "AccessDeniedError"}),
    lambda r: httpx.Response(429, json={}),
    lambda r: httpx.Response(500, text="oops"),
    lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)),
])
def test_kakao_failures_fall_back_to_demo_points(handler):
    svc, _ = kakao_service(handler)
    result = svc.search("광주역")
    assert result["mode"] == "demo" and "연결하지 못해" in result["notice"]


@pytest.mark.parametrize("query", ["광", " 광 ", "", "x" * 51])
def test_short_or_long_queries_are_rejected_without_echo(query):
    svc, calls = kakao_service(lambda r: httpx.Response(200, json={"documents": []}))
    with client_with(svc) as client:
        response = client.post("/api/search", json={"query": query})
    assert response.status_code == 422 and calls == []
    if query.strip():
        assert query.strip() not in response.text


def test_search_api_and_query_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    svc, _ = kakao_service(lambda r: httpx.Response(200, json={"documents": [GWANGJU]}))
    with client_with(svc) as client:
        body = client.post("/api/search", json={"query": "  비밀검색어역  "}).json()
        config = client.get("/api/app-config").json()
    assert body["mode"] == "kakao" and config["search_mode"] == "kakao"
    assert "비밀검색어" not in caplog.text and "kakao-test-key" not in caplog.text
    assert "kakao-test-key" not in str(body)
