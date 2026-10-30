"""Manual check on the real Valhalla tiles (not part of pytest, requirement 5.7).

Runs scenario A (광주송정역 -> 광주역, tiered_rain, 0/35/55/75 mm) plus scenario D and prints
what each step avoids. Run from the project root:

    conda run -n disaster-action-guide python data_pipeline/check_demo_scenario.py
"""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_config  # noqa: E402
from app.context.weather_mock import demo_weather  # noqa: E402
from app.engines.valhalla import ValhallaEngine  # noqa: E402
from app.risk.layer import get_risk_layer  # noqa: E402
from app.strategies.base import RouteRequest, StrategyContext  # noqa: E402
from app.strategies.params import resolve  # noqa: E402
from app.strategies.registry import get_strategy  # noqa: E402


def point(name: str) -> tuple[float, float]:
    data = json.loads((ROOT / "backend/app/data/demo_points.json").read_text(encoding="utf-8"))
    p = next(p for p in data["points"] if p["name"].startswith(name))
    return (p["lon"], p["lat"])


def plan(engine, name: str, rn1: float, origin, destination):
    strategy = get_strategy(name)
    params = resolve(get_config(), strategy.params_model, None)
    ctx = StrategyContext(weather=demo_weather(rn1, "none", params), layer=get_risk_layer(), engine=engine,
                          params=params, deadline=time.monotonic() + 10)
    return strategy.plan(RouteRequest(origin, destination), ctx)


def main() -> int:
    engine = ValhallaEngine()
    origin, destination = point("광주송정역"), point("광주역")
    geometries = []
    print("rain  level  status            duration  distance  exposure  passed zones")
    for rn1 in (0, 35, 55, 75):
        p = plan(engine, "tiered_rain", rn1, origin, destination)
        m = p.metrics()["route"]
        passed = ", ".join(f"{z['id']}({z['length_m']:.0f}m)" for z in p.explanation.passed_zones) or "-"
        print(f"{rn1:>4}  {p.explanation.level:>5}  {p.explanation.status:<16}  {m['duration_s']:>7.0f}s"
              f"  {m['distance_m'] / 1000:>6.2f}km  {m['exposure_score']:>8.0f}  {passed}")
        geometries.append(p.route.osrm["geometry"]["coordinates"])
    distinct = all(geometries[i] != geometries[i - 1] for i in range(1, 4))
    print("SCENARIO_A_ALL_STEPS_DIFFER" if distinct else "SCENARIO_A_SOME_STEPS_EQUAL")
    d = plan(engine, "tiered_rain", 35, origin, point("농성지하차도"))
    print("scenario D:", d.explanation.status, "|", d.explanation.failure_reason)
    return 0 if distinct and d.explanation.status == "avoid_failed" else 1


if __name__ == "__main__":
    sys.exit(main())
