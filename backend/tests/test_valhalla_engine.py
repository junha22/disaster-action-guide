"""Valhalla adapter with a fake Actor: no tiles, no native engine (requirement 5.7)."""
import json
import os
from pathlib import Path
import threading
import time

import pytest

from app.engines.base import EngineUnavailable, ExcludeLimitExceeded, LocationNotRoutable, NoRouteFound
from app.engines.valhalla import ValhallaEngine, ascii_path

ROUTE = {"geometry": {"type": "LineString", "coordinates": [[126.80, 35.15], [126.90, 35.15]]},
         "distance": 9100.0, "duration": 600.0, "weight": 610.0, "weight_name": "auto",
         "legs": [{"distance": 9100.0, "duration": 600.0, "weight": 610.0, "summary": "x",
                   "steps": [], "admins": [{"country_code": "KR"}]}]}


class FakeActor:
    def __init__(self, delay=0.0, error=None):
        self.delay, self.error = delay, error
        self.requests, self.active, self.max_active = [], 0, 0
        self._lock = threading.Lock()

    def route(self, request):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            self.requests.append(request)
            if self.error:
                raise self.error
            return {"code": "Ok", "routes": [ROUTE, ROUTE], "waypoints": [{"location": [0, 0]}]}
        finally:
            with self._lock:
                self.active -= 1


class CodedError(Exception):
    def __init__(self, code):
        super().__init__(f"secret detail {code}")
        self.code = code


def make_engine(tmp_path, actor, extract=True):
    tiles = tmp_path / "tiles.tar"
    if extract:
        tiles.write_bytes(b"x")
    config = {"mjolnir": {"tile_extract": str(tiles), "tile_dir": str(tmp_path / "none")},
              "logging": {"type": "std_out"},
              "service_limits": {"max_exclude_polygons_length": 300000, "max_exclude_polygons_vertices": 5000}}
    path = tmp_path / "valhalla.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    created = []

    def factory(cfg):
        created.append(cfg)
        return actor
    return ValhallaEngine(path, actor_factory=factory), created


def test_request_contract_and_osrm_output(tmp_path):
    actor = FakeActor()
    engine, created = make_engine(tmp_path, actor)
    ring = [[126.84, 35.14], [126.86, 35.14], [126.86, 35.16], [126.84, 35.14]]
    routes = engine.route((126.80, 35.15), (126.90, 35.15), exclude_polygons=[ring], alternates=2)
    request = actor.requests[0]
    assert request["costing"] == "auto" and request["format"] == "osrm"
    assert request["alternates"] == 2 and request["exclude_polygons"] == [ring]
    assert request["directions_type"] == "none" and request["shape_format"] == "geojson"
    assert request["locations"] == [{"lon": 126.80, "lat": 35.15}, {"lon": 126.90, "lat": 35.15}]
    assert len(routes) == 2 and routes[0]["geometry"] == ROUTE["geometry"]
    assert "admins" not in routes[0]["legs"][0]
    assert created[0]["logging"]["type"] == "" and created[0]["mjolnir"]["tile_dir"] == ""
    engine.route((126.80, 35.15), (126.90, 35.15))
    assert len(created) == 1  # actor reused
    assert "exclude_polygons" not in actor.requests[1]
    assert engine.exclude_limits().max_vertices == 5000


def test_missing_tiles_or_config_is_unavailable(tmp_path):
    engine, _ = make_engine(tmp_path, FakeActor(), extract=False)
    with pytest.raises(EngineUnavailable):
        engine.route((126.80, 35.15), (126.90, 35.15))
    with pytest.raises(EngineUnavailable):
        ValhallaEngine(tmp_path / "absent.json").route((126.80, 35.15), (126.90, 35.15))


def test_ascii_path_prefers_relative_and_rejects_non_ascii():
    base = Path("C:/3.2/해커톤/proj")
    assert ascii_path(base / ".local-data" / "tiles.tar", base / "backend") == os.path.join(
        "..", ".local-data", "tiles.tar")
    assert ascii_path(Path("C:/data/tiles.tar"), Path("C:/data")) == "tiles.tar"
    assert ascii_path(Path("C:/해커톤/tiles.tar"), Path("C:/other")) is None


def test_non_ascii_tile_path_is_unavailable(tmp_path, monkeypatch):
    folder = tmp_path / "해커톤"
    folder.mkdir()
    monkeypatch.chdir(tmp_path)
    tiles = folder / "tiles.tar"
    tiles.write_bytes(b"x")
    path = tmp_path / "valhalla.json"
    path.write_text(json.dumps({"mjolnir": {"tile_extract": str(tiles)}}), encoding="utf-8")
    monkeypatch.chdir(folder.parent.parent)
    # relative from tmp_path's parent still contains the Korean folder, and so does the absolute path
    with pytest.raises(EngineUnavailable):
        ValhallaEngine(path, actor_factory=lambda cfg: FakeActor()).route((126.8, 35.15), (126.9, 35.15))


def test_concurrent_requests_are_serialized(tmp_path):
    actor = FakeActor(delay=0.05)
    engine, _ = make_engine(tmp_path, actor)
    threads = [threading.Thread(target=engine.route, args=((126.80, 35.15), (126.90, 35.15)))
               for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(actor.requests) == 5 and actor.max_active == 1


def test_timeout_returns_unavailable_without_retry(tmp_path):
    actor = FakeActor(delay=0.4)
    engine, _ = make_engine(tmp_path, actor)
    with pytest.raises(EngineUnavailable):
        engine.route((126.80, 35.15), (126.90, 35.15), timeout_s=0.05)
    with pytest.raises(EngineUnavailable):
        engine.route((126.80, 35.15), (126.90, 35.15), timeout_s=0)
    time.sleep(0.5)
    assert len(actor.requests) == 1


@pytest.mark.parametrize("error, expected", [
    (CodedError(442), NoRouteFound), (CodedError(171), LocationNotRoutable),
    (CodedError(176), ExcludeLimitExceeded), (CodedError(167), ExcludeLimitExceeded),
    (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), EngineUnavailable),
])
def test_engine_errors_are_mapped_and_sanitized(tmp_path, error, expected):
    engine, _ = make_engine(tmp_path, FakeActor(error=error))
    with pytest.raises(expected) as info:
        engine.route((126.80, 35.15), (126.90, 35.15))
    assert "secret" not in str(info.value)


def test_mis_encoded_street_names_are_recovered(tmp_path):
    # Bytes as produced by pyvalhalla on Windows for the name "농성지하차도" (byte 0x80 escaped).
    raw = (b'{"code":"Ok","waypoints":[{"name":"\xeb\x86\x8d\xec\x84\xb1\xec\xa7\\uFFFFFF80\xed\x95\x98",'
           b'"location":[126.88,35.15]}],"routes":' + json.dumps([ROUTE]).encode() + b'}')
    error = UnicodeDecodeError("utf-8", raw, raw.index(b"\xec\xa7"), raw.index(b"\xec\xa7") + 2, "invalid")
    engine, _ = make_engine(tmp_path, FakeActor(error=error))
    routes = engine.route((126.80, 35.15), (126.88, 35.15))
    assert routes[0]["geometry"] == ROUTE["geometry"] and routes[0]["legs"][0]["summary"] == ""
    assert "waypoints" not in routes[0]


def test_actor_creation_failure_is_unavailable(tmp_path):
    path = tmp_path / "valhalla.json"
    (tmp_path / "tiles.tar").write_bytes(b"x")
    path.write_text(json.dumps({"mjolnir": {"tile_extract": str(tmp_path / "tiles.tar")}}), encoding="utf-8")

    def broken(cfg):
        raise RuntimeError("cannot open C:/secret")
    with pytest.raises(EngineUnavailable):
        ValhallaEngine(path, actor_factory=broken).route((126.8, 35.15), (126.9, 35.15))
