"""Route API with the fake engine (requirements 4.2, 4.3, 5.4, 5.7, 7.3, 7.4)."""
import logging
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from app.api.deps import layer_dep
from app.context.weather_kma import WeatherSnapshot, get_weather_service, unavailable_snapshot
from app.engines import get_engine
from app.engines.base import EngineUnavailable, NoRouteFound
from app.engines.fake import FakeCandidate, FakeEngine
from app.main import app
from app.strategies import registry
from app.strategies.base import baseline_routes, make_plan
from app.strategies.params import CommonParams

from routing_fixtures import CANDIDATES, DESTINATION, ORIGIN, corridor_layer

LOCAL_DATA = Path(__file__).resolve().parents[2] / ".local-data"


class StubWeather:
    def __init__(self, snapshot):
        self.snapshot, self.calls = snapshot, 0

    def get(self, point=None):
        self.calls += 1
        self.point = point
        return self.snapshot


KMA_55 = WeatherSnapshot(True, 55.0, "none", "없음", "ok", "2026-10-30T18:00:00+09:00", None)


def fake_engine(**kwargs):
    return FakeEngine([FakeCandidate(c["coords"], c["duration"]) for c in CANDIDATES], **kwargs)


@pytest.fixture
def setup():
    state = {"engine": fake_engine(), "weather": StubWeather(KMA_55)}
    app.dependency_overrides[get_engine] = lambda: state["engine"]
    app.dependency_overrides[layer_dep] = corridor_layer
    app.dependency_overrides[get_weather_service] = lambda: state["weather"]
    with TestClient(app) as client:
        yield client, state
    app.dependency_overrides.clear()


def body(**overrides):
    base = {"origin": {"lon": ORIGIN[0], "lat": ORIGIN[1]},
            "destination": {"lon": DESTINATION[0], "lat": DESTINATION[1]},
            "strategy": "tiered_rain", "weather_override": {"rn1_mm": 55, "alert": "none"}}
    return {**base, **overrides}


@pytest.mark.parametrize("name", ["baseline", "hard_exclude", "tiered_rain", "rerank"])
def test_every_strategy_answers_in_the_same_format(setup, name):
    client, _ = setup
    data = client.post("/api/route", json=body(strategy=name)).json()
    assert set(data) == {"strategy", "route", "alternatives", "baseline", "explanation", "metrics", "weather"}
    assert data["strategy"]["name"] == name
    assert data["route"]["geometry"]["type"] == "LineString" and "duration" in data["route"]


# avoid_types lists types with at least one avoided group; level 1 avoids only high flood zones.
@pytest.mark.parametrize("rn1, status, types", [
    (0, "no_avoid_level", []), (35, "avoided", ["underpass", "flood_history"]),
    (55, "avoided", ["underpass", "flood_history"]), (75, "avoided", ["underpass", "flood_history", "riverside"]),
])
def test_demo_override_drives_the_level(setup, rn1, status, types):
    client, state = setup
    data = client.post("/api/route", json=body(weather_override={"rn1_mm": rn1, "alert": "none"})).json()
    assert data["explanation"]["status"] == status and data["explanation"]["avoid_types"] == types
    assert data["weather"]["source"] == "demo" and data["weather"]["real_weather_applied"] is False
    assert state["weather"].calls == 0  # demo values do not call the KMA


def test_kma_values_are_used_without_override(setup):
    client, state = setup
    data = client.post("/api/route", json=body(weather_override=None)).json()
    assert data["weather"] == {**data["weather"], "source": "kma", "rn1_mm": 55.0, "level": 2,
                               "real_weather_applied": True}
    state["weather"].snapshot = unavailable_snapshot()
    data = client.post("/api/route", json=body(weather_override=None)).json()
    assert data["weather"]["source"] == "unavailable" and data["weather"]["real_weather_applied"] is False
    assert data["explanation"]["level"] == 0


@pytest.mark.parametrize("payload", [
    body(origin={"lon": 129.0, "lat": 35.1}),
    body(strategy="no_such_strategy"),
    body(params={"lambda": 3}),
    body(strategy="rerank", params={"lambda": 99}),
    body(weather_override={"rn1_mm": 301}),
    body(extra=True),
    {"origin": {"lon": ORIGIN[0], "lat": ORIGIN[1]}},
])
def test_invalid_requests_are_422_without_echoing_coordinates(setup, payload):
    client, _ = setup
    response = client.post("/api/route", json=payload)
    assert response.status_code == 422
    assert "126.8" not in response.text and "35.15" not in response.text


def test_engine_unavailable_is_503_and_missing_baseline_is_422(setup):
    client, state = setup
    state["engine"] = fake_engine(error=EngineUnavailable())
    response = client.post("/api/route", json=body())
    assert response.status_code == 503 and response.json()["detail"] == "경로 엔진에 연결할 수 없습니다"
    assert len(state["engine"].calls) == 1  # no automatic retry
    state["engine"] = fake_engine(error=NoRouteFound())
    response = client.post("/api/route", json=body())
    assert response.status_code == 422 and "경로를 찾지 못했습니다" in response.json()["detail"]


def test_avoid_failure_warns_and_lists_the_zones(setup):
    client, _ = setup
    data = client.post("/api/route", json=body(destination={"lon": 126.82, "lat": 35.15},
                                               weather_override={"rn1_mm": 35})).json()
    e = data["explanation"]
    assert e["status"] == "avoid_failed" and e["warning"] == "위험 구역을 피하는 경로를 찾지 못했습니다."
    assert "목적지가" in e["failure_reason"]
    assert e["passed_zones"] and len(e["passed_zones"]) <= len(e["baseline_passed_zones"])


def test_registered_strategy_is_usable_without_api_changes(setup):
    client, _ = setup

    @registry.register("tmp_api_strategy")
    class TmpApi:
        label, description, params_model = "tmp", "tmp", CommonParams

        def plan(self, request, ctx):
            route = baseline_routes(ctx, request)[0]
            return make_plan(ctx, route=route, baseline=route, status="baseline")
    try:
        assert "tmp_api_strategy" in [s["name"] for s in client.get("/api/strategies").json()]
        assert client.post("/api/route", json=body(strategy="tmp_api_strategy")).status_code == 200
    finally:
        registry.unregister("tmp_api_strategy")


def test_metadata_endpoints(setup):
    client, _ = setup
    strategies = client.get("/api/strategies").json()
    assert strategies[0]["name"] == "tiered_rain" and strategies[0]["default"]
    zones = client.get("/api/risk-zones").json()
    assert zones["type"] == "FeatureCollection" and zones["metadata"]["has_dummy"]
    props = {f["properties"]["id"]: f["properties"] for f in zones["features"]}
    assert props["z-flood_history"]["group"] == "flood_history.normal"
    assert props["z-flood_history"]["risk_tier"] == "normal" and "low_pct" in props["z-flood_history"]
    assert props["z-underpass"]["group"] == "underpass" and props["z-underpass"]["risk_tier"] is None
    config = client.get("/api/app-config").json()
    assert config["level_rules"]["thresholds_mm"] == [30, 50, 70]
    assert config["level_rules"]["avoid_by_level"]["1"] == ["underpass", "flood_history.high"]
    assert config["level_rules"]["hard_by_level"]["2"] == ["underpass", "flood_history.high"]
    assert config["level_rules"]["soft_by_level"]["2"] == ["flood_history.normal", "flood_history.raised"]
    assert config["level_rules"]["avoid_by_level"]["3"] == ["underpass", "flood_history.high", "flood_history.normal",
                                                            "flood_history.raised", "riverside"]
    assert config["zone_groups"]["flood_history.raised"] == {"type": "flood_history", "tier": "raised",
                                                             "label": "침수 이력(주변보다 높은 편)",
                                                             "tier_label": "주변보다 높은 편"}
    assert config["zone_groups"]["underpass"]["tier"] is None
    assert len(client.get("/api/demo-points").json()) == 7
    assert client.get("/api/health").json()["status"] == "ok"


def snapshot_dir(path: Path):
    if not path.exists():
        return set()
    return {(p.relative_to(path).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
            for p in path.rglob("*") if p.is_file()}


def test_locations_are_not_logged_or_stored(setup, caplog):
    client, _ = setup
    caplog.set_level(logging.DEBUG)
    before_records = client.get("/api/records").json()
    before_files = snapshot_dir(LOCAL_DATA)
    marker = {"lon": 126.812345, "lat": 35.154321}
    for name in ("tiered_rain", "rerank"):
        assert client.post("/api/route", json=body(strategy=name, origin=marker)).status_code == 200
    client.post("/api/route", json=body(origin={"lon": 129.123456, "lat": 35.1}))
    assert "126.812345" not in caplog.text and "35.154321" not in caplog.text
    assert "129.123456" not in caplog.text
    assert client.get("/api/records").json() == before_records
    assert snapshot_dir(LOCAL_DATA) == before_files


def test_tests_never_load_the_native_engine():
    """Requirement 5.7: every test above runs on the fake adapter."""
    assert "valhalla" not in sys.modules
