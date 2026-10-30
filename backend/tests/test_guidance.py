"""Turn-by-turn guidance: Valhalla parsing with a fake actor, and the API with the fake engine."""
import logging

from fastapi.testclient import TestClient
import pytest

from app.engines import get_engine
from app.engines.base import EngineUnavailable, NoRouteFound
from app.engines.fake import FakeCandidate, FakeEngine
from app.engines.valhalla import build_guidance_request, parse_guidance
from app.main import app

COORDS = [[126.80, 35.15], [126.85, 35.15], [126.90, 35.15]]
TRIP = {"trip": {"legs": [{"maneuvers": [
    {"type": 1, "length": 1.205, "time": 88.76, "street_names": ["광산로"]},
    {"type": 9, "length": 7.511, "time": 461.5, "street_names": ["22", "상무대로"]},
    {"type": 15, "length": 2.303, "time": 156.6, "street_names": ["1"]},
    {"type": 8, "length": 0.07, "time": 6.4},
    {"type": 99, "length": 0.1, "time": 1.0, "street_names": []},
    {"type": 4, "length": 0.0, "time": 0.0},
]}]}}


@pytest.fixture
def client():
    engine = FakeEngine([FakeCandidate([(126.80, 35.15), (126.90, 35.15)], 600.0)])
    app.dependency_overrides[get_engine] = lambda: engine
    with TestClient(app) as test_client:
        test_client.engine = engine
        yield test_client
    app.dependency_overrides.clear()


def test_parse_maps_kinds_units_and_road_names():
    steps = parse_guidance(TRIP)
    assert [s["kind"] for s in steps] == ["depart", "slight_right", "left", "straight", "straight", "arrive"]
    assert steps[0] == {"kind": "depart", "name": "광산로", "distance_m": 1205.0, "duration_s": 88.76}
    assert steps[1]["name"] == "상무대로"  # a real name wins over the route number
    assert steps[2]["name"] == "1번 도로"
    assert steps[3]["name"] == "" and steps[4]["name"] == ""


def test_parse_without_legs_is_no_route():
    with pytest.raises(NoRouteFound):
        parse_guidance({"trip": {"legs": []}})


def test_request_follows_the_given_shape_and_avoids_the_osrm_format():
    request = build_guidance_request([(126.8, 35.15), (126.9, 35.16)])
    assert request["shape"] == [{"lon": 126.8, "lat": 35.15}, {"lon": 126.9, "lat": 35.16}]
    assert request["format"] == "json" and request["directions_type"] == "maneuvers"


def test_api_returns_steps(client):
    response = client.post("/api/route/guidance", json={"coordinates": COORDS})
    assert response.status_code == 200
    steps = response.json()["steps"]
    assert steps[0]["kind"] == "depart" and steps[-1]["kind"] == "arrive"


@pytest.mark.parametrize("body", [
    {"coordinates": [[126.80, 35.15]]},
    {"coordinates": "x"},
    {"coordinates": COORDS, "extra": 1},
    {"coordinates": [[127.5, 37.5], [127.6, 37.6]]},
])
def test_api_rejects_bad_input(client, body):
    assert client.post("/api/route/guidance", json=body).status_code == 422


@pytest.mark.parametrize("error, status", [(EngineUnavailable(), 503), (NoRouteFound(), 422)])
def test_api_maps_engine_errors(client, error, status):
    client.engine.error = error
    assert client.post("/api/route/guidance", json={"coordinates": COORDS}).status_code == status


def test_api_does_not_log_coordinates(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post("/api/route/guidance", json={"coordinates": COORDS})
    assert "126.85" not in caplog.text
