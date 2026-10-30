"""Valhalla adapter (requirement 5.2-5.6, design.md 6.2).

- The Actor is created on the first route request and reused.
- pyvalhalla releases the GIL during route() and one actor_t is not safe for concurrent use,
  so creation and every call run on a single worker thread.
- Each request waits at most timeout_s. A running C++ computation cannot be interrupted;
  the caller gets EngineUnavailable while the worker finishes in the background.
- Native code cannot open non-ASCII paths on this machine, so tile paths are passed relative
  to the working directory (or absolute) only when ASCII.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import copy
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable, Sequence

from .base import (EngineUnavailable, ExcludeLimitExceeded, ExcludeLimits, GuidanceStep, LocationNotRoutable,
                   LonLat, NoRouteFound, OsrmRoute, Ring)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / ".local-data" / "valhalla" / "valhalla.json"

# ValhallaError.code values (checked against pyvalhalla 3.9.1 responses).
NO_ROUTE_CODES = {170, 442}
LOCATION_CODES = {171}
EXCLUDE_LIMIT_CODES = {167, 176}
# Valhalla maneuver type -> engine-neutral kind. Anything unlisted reads as going straight on.
MANEUVER_KINDS = {
    1: "depart", 2: "depart", 3: "depart", 4: "arrive", 5: "arrive", 6: "arrive",
    9: "slight_right", 10: "right", 11: "sharp_right", 12: "uturn", 13: "uturn", 14: "sharp_left", 15: "left",
    16: "slight_left", 18: "slight_right", 19: "slight_left", 20: "slight_right", 21: "slight_left",
    23: "slight_right", 24: "slight_left", 25: "merge", 26: "roundabout", 37: "merge", 38: "merge",
}


def ascii_path(path: Path, cwd: Path) -> str | None:
    try:
        relative = os.path.relpath(path, cwd)
    except ValueError:  # different drive
        relative = None
    if relative and relative.isascii():
        return relative
    if str(path).isascii():
        return str(path)
    return None


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def build_request(origin: LonLat, destination: LonLat, exclude_polygons: Sequence[Ring],
                  alternates: int) -> dict[str, Any]:
    request: dict[str, Any] = {
        "locations": [{"lon": origin[0], "lat": origin[1]}, {"lon": destination[0], "lat": destination[1]}],
        "costing": "auto",
        "format": "osrm",
        "shape_format": "geojson",
        # Narrative generation returns invalid UTF-8 on Windows; turn-by-turn is out of scope.
        "directions_type": "none",
        "alternates": int(alternates),
    }
    if exclude_polygons:
        request["exclude_polygons"] = [[[float(x), float(y)] for x, y in ring] for ring in exclude_polygons]
    return request


def build_guidance_request(coordinates: Sequence[LonLat]) -> dict[str, Any]:
    # format=json: only the OSRM serializer hits the Windows street-name encoding bug noted above.
    return {
        "shape": [{"lon": lon, "lat": lat} for lon, lat in coordinates],
        "costing": "auto",
        "shape_match": "map_snap",
        "format": "json",
        "directions_type": "maneuvers",
    }


def _road_name(names: Any) -> str:
    """Prefer a real name over a route number: ['22', '상무대로'] -> 상무대로, ['1'] -> 1번 도로."""
    names = [str(n).strip() for n in (names or []) if str(n).strip()]
    named = next((n for n in names if not n.isdigit()), None)
    if named:
        return named
    return f"{names[0]}번 도로" if names else ""


def parse_guidance(response: dict[str, Any]) -> list[GuidanceStep]:
    legs = (response.get("trip") or {}).get("legs") or []
    if not legs:
        raise NoRouteFound()
    return [{"kind": MANEUVER_KINDS.get(m.get("type"), "straight"),
             "name": _road_name(m.get("street_names")),
             "distance_m": float(m.get("length", 0.0)) * 1000.0,
             "duration_s": float(m.get("time", 0.0))}
            for leg in legs for m in leg.get("maneuvers", [])]


def _normalize(route: dict[str, Any]) -> OsrmRoute:
    # Street names (summary, waypoint names) are dropped: unused, and possibly mis-encoded.
    legs = [{"distance": leg.get("distance", 0.0), "duration": leg.get("duration", 0.0),
             "weight": leg.get("weight", 0.0), "summary": "", "steps": []}
            for leg in route.get("legs", [])]
    return {"geometry": route["geometry"], "distance": route["distance"], "duration": route["duration"],
            "weight": route.get("weight", route["duration"]), "weight_name": route.get("weight_name", "auto"),
            "legs": legs}


def _map_error(exc: Exception) -> Exception:
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        return EngineUnavailable()
    if code in LOCATION_CODES:
        return LocationNotRoutable()
    if code in EXCLUDE_LIMIT_CODES:
        return ExcludeLimitExceeded()
    return NoRouteFound()


def _recover_response(exc: UnicodeDecodeError) -> dict[str, Any]:
    """pyvalhalla 3.9.1 on Windows writes some bytes of Korean street names as '\\uFFFFFF80',
    so the OSRM response (waypoints[].name) is not valid UTF-8. Only names are affected and
    names are discarded by _normalize, so decode with replacement and keep the numbers/geometry."""
    raw = exc.object if isinstance(exc.object, (bytes, bytearray)) else b""
    try:
        data = json.loads(bytes(raw).decode("utf-8", errors="replace"))
    except ValueError:
        raise EngineUnavailable() from None
    if not isinstance(data, dict) or "routes" not in data:
        raise EngineUnavailable()
    return data


def _default_actor_factory(config: dict[str, Any]):
    import valhalla  # deferred: never imported at app import time

    actor = valhalla.Actor(config)
    temp = getattr(actor, "_temp_file_path", None)  # config copy written by pyvalhalla
    if temp:
        try:
            os.remove(temp)
        except OSError:
            pass
    return actor


class ValhallaEngine:
    name = "valhalla"

    def __init__(self, config_path: Path | str | None = None,
                 actor_factory: Callable[[dict[str, Any]], Any] | None = None):
        self._config_path = Path(config_path or os.environ.get("VALHALLA_CONFIG") or DEFAULT_CONFIG)
        self._actor_factory = actor_factory or _default_actor_factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="valhalla")
        self._lock = threading.Lock()
        self._config: dict[str, Any] | None = None
        self._actor = None

    def _load_config(self) -> dict[str, Any]:
        with self._lock:
            if self._config is not None:
                return self._config
            try:
                config = json.loads(self._config_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise EngineUnavailable() from None
            mjolnir = config.setdefault("mjolnir", {})
            cwd = Path.cwd()
            extract = _resolve(mjolnir["tile_extract"]) if mjolnir.get("tile_extract") else None
            tile_dir = _resolve(mjolnir["tile_dir"]) if mjolnir.get("tile_dir") else None
            if extract and extract.is_file():
                chosen = ascii_path(extract, cwd)
                mjolnir["tile_extract"], mjolnir["tile_dir"] = chosen, ""
            elif tile_dir and tile_dir.is_dir() and any(tile_dir.iterdir()):
                chosen = ascii_path(tile_dir, cwd)
                mjolnir["tile_extract"], mjolnir["tile_dir"] = "", chosen
            else:
                raise EngineUnavailable()
            if chosen is None:
                raise EngineUnavailable()
            config.setdefault("logging", {})["type"] = ""  # keep locations out of logs
            self._config = config
            return config

    def exclude_limits(self) -> ExcludeLimits:
        limits = self._load_config().get("service_limits", {})
        return ExcludeLimits(max_perimeter_m=float(limits.get("max_exclude_polygons_length", 10000)),
                             max_vertices=int(limits.get("max_exclude_polygons_vertices", 100)))

    def _ensure_actor(self) -> None:
        if self._actor is None:
            try:
                self._actor = self._actor_factory(copy.deepcopy(self._load_config()))
            except EngineUnavailable:
                raise
            except Exception:
                raise EngineUnavailable() from None

    def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        self._ensure_actor()
        try:
            return self._actor.route(request)
        except UnicodeDecodeError as exc:
            return _recover_response(exc)
        except Exception as exc:
            raise _map_error(exc) from None

    def _call_trace(self, request: dict[str, Any]) -> dict[str, Any]:
        self._ensure_actor()
        try:
            return self._actor.trace_route(request)
        except Exception as exc:
            raise _map_error(exc) from None

    def guidance(self, coordinates: Sequence[LonLat], *, timeout_s: float = 10.0) -> list[GuidanceStep]:
        self._load_config()
        future = self._executor.submit(self._call_trace, build_guidance_request(coordinates))
        try:
            response = future.result(timeout=timeout_s)
        except FutureTimeout:
            raise EngineUnavailable() from None
        return parse_guidance(response)

    def route(self, origin: LonLat, destination: LonLat, *, exclude_polygons: Sequence[Ring] = (),
              alternates: int = 0, timeout_s: float = 10.0) -> list[OsrmRoute]:
        if timeout_s <= 0:
            raise EngineUnavailable()
        self._load_config()
        request = build_request(origin, destination, exclude_polygons, alternates)
        future = self._executor.submit(self._call, request)
        try:
            response = future.result(timeout=timeout_s)
        except FutureTimeout:
            raise EngineUnavailable() from None
        routes = response.get("routes") or []
        if not routes:
            raise NoRouteFound()
        return [_normalize(r) for r in routes]
