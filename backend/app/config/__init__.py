"""strategies.yaml loader. Read on first use (never at import time) and validated."""
from functools import lru_cache
from pathlib import Path
import threading
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import yaml

CONFIG_PATH = Path(__file__).with_name("strategies.yaml")
ZONE_TYPES: tuple[str, ...] = ("underpass", "flood_history", "riverside")
ALERTS: tuple[str, ...] = ("none", "advisory", "warning")
MAX_LEVEL = 3


class ConfigError(RuntimeError):
    """strategies.yaml is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ZoneTypeConfig(_Strict):
    label: str = Field(min_length=1)
    weight: float = Field(ge=0, le=10)
    avoid_buffer_m: float = Field(ge=0, le=200)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class RainLevels(_Strict):
    thresholds_mm: tuple[float, float, float]
    avoid_by_level: dict[int, tuple[str, ...]]

    @model_validator(mode="after")
    def _check(self):
        t = self.thresholds_mm
        if not (0 < t[0] < t[1] < t[2] <= 300):
            raise ValueError("thresholds_mm must be increasing values in (0, 300]")
        if sorted(self.avoid_by_level) != list(range(MAX_LEVEL + 1)):
            raise ValueError("avoid_by_level must define levels 0..3")
        previous: set[str] = set()
        for level in range(MAX_LEVEL + 1):
            current = set(self.avoid_by_level[level])
            unknown = current - set(ZONE_TYPES)
            if unknown:
                raise ValueError(f"unknown zone types at level {level}: {sorted(unknown)}")
            if not previous <= current:
                raise ValueError("avoided types must accumulate as the level rises")
            previous = current
        return self


class AlertMinLevel(_Strict):
    advisory: int = Field(ge=0, le=MAX_LEVEL)
    warning: int = Field(ge=0, le=MAX_LEVEL)

    @model_validator(mode="after")
    def _order(self):
        if self.advisory > self.warning:
            raise ValueError("advisory level must not exceed warning level")
        return self


class EngineConfig(_Strict):
    timeout_s: float = Field(gt=0, le=60)


class AppConfig(_Strict):
    version: int
    zone_types: dict[str, ZoneTypeConfig]
    rain_levels: RainLevels
    alert_min_level: AlertMinLevel
    default_strategy: str
    strategies: dict[str, dict[str, Any]] = Field(default_factory=dict)
    engine: EngineConfig

    @model_validator(mode="after")
    def _types(self):
        if set(self.zone_types) != set(ZONE_TYPES):
            raise ValueError(f"zone_types must be exactly {list(ZONE_TYPES)}")
        return self


_lock = threading.Lock()


def parse_config(data: Any) -> AppConfig:
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"strategies.yaml 설정 오류: {problems}") from None


@lru_cache(maxsize=1)
def _load(path: Path) -> AppConfig:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"strategies.yaml을 읽지 못했습니다: {type(exc).__name__}") from None
    return parse_config(data)


def get_config() -> AppConfig:
    with _lock:
        return _load(CONFIG_PATH)


def rain_level(rn1_mm: float, alert: str, thresholds_mm, alert_min_level: dict[str, int]) -> int:
    """Level from 1-hour rainfall, raised to the alert minimum (design.md 3.1)."""
    level = sum(1 for t in thresholds_mm if rn1_mm >= t)
    if alert in ("advisory", "warning"):
        level = max(level, alert_min_level[alert])
    return min(level, MAX_LEVEL)
