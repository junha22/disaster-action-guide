"""strategies.yaml loader. Read on first use (never at import time) and validated."""
from functools import lru_cache
from pathlib import Path
import threading
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import yaml

CONFIG_PATH = Path(__file__).with_name("strategies.yaml")
ZONE_TYPES: tuple[str, ...] = ("underpass", "flood_history", "riverside")
# Terrain tiers of a zone type, most cautious first (design.md 5.8). A zone of such a type with no
# known tier is put in the first one.
ZONE_TIERS: dict[str, tuple[str, ...]] = {"flood_history": ("high", "normal", "raised")}
ALERTS: tuple[str, ...] = ("none", "advisory", "warning")
MAX_LEVEL = 3


# ---- avoidance groups: a type without tiers ("underpass") or "type.tier" ("flood_history.high") ----

def groups_of(zone_type: str) -> tuple[str, ...]:
    tiers = ZONE_TIERS.get(zone_type)
    return tuple(f"{zone_type}.{t}" for t in tiers) if tiers else (zone_type,)


ZONE_GROUPS: tuple[str, ...] = tuple(g for t in ZONE_TYPES for g in groups_of(t))


def zone_group(zone_type: str, tier: str | None = None) -> str:
    tiers = ZONE_TIERS.get(zone_type)
    if not tiers:
        return zone_type
    return f"{zone_type}.{tier if tier in tiers else tiers[0]}"


def group_type(group: str) -> str:
    return group.split(".", 1)[0]


def group_tier(group: str) -> str | None:
    return group.split(".", 1)[1] if "." in group else None


def expand_groups(keys: Iterable[str]) -> tuple[str, ...]:
    """Type names become all their groups, group keys stay. Canonical order, unknown keys dropped."""
    wanted: set[str] = set()
    for key in keys:
        wanted.update(groups_of(key) if key in ZONE_TYPES else (key,))
    return tuple(g for g in ZONE_GROUPS if g in wanted)


def types_of(groups: Iterable[str]) -> tuple[str, ...]:
    """Types that have at least one of the groups, in canonical order."""
    wanted = {group_type(g) for g in groups}
    return tuple(t for t in ZONE_TYPES if t in wanted)


class ConfigError(RuntimeError):
    """strategies.yaml is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TierConfig(_Strict):
    label: str = Field(min_length=1)
    # Multiplies the type's soft penalty for zones of this tier (design.md 5.8).
    penalty_scale: float = Field(default=1.0, ge=0, le=5)


class ZoneTypeConfig(_Strict):
    label: str = Field(min_length=1)
    weight: float = Field(ge=0, le=10)
    avoid_buffer_m: float = Field(ge=0, le=200)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    entry_penalty_s: float = Field(default=0, ge=0, le=3600)
    per_m_penalty_s: float = Field(default=0, ge=0, le=60)
    tiers: dict[str, TierConfig] = Field(default_factory=dict)


class LevelAvoid(_Strict):
    """Groups avoided at one rain level: hard = never chosen, soft = penalized (design.md 5.7, 5.8).

    Entries are type names (all tiers of the type) or group keys such as "flood_history.high".
    """
    hard: tuple[str, ...] = ()
    soft: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _legacy_list(cls, value):
        # Older format: a plain list meant "exclude these types" -> all hard.
        if isinstance(value, (list, tuple)):
            return {"hard": list(value), "soft": []}
        return value

    @property
    def hard_groups(self) -> tuple[str, ...]:
        return expand_groups(self.hard)

    @property
    def soft_groups(self) -> tuple[str, ...]:
        return expand_groups(self.soft)

    @property
    def all_groups(self) -> tuple[str, ...]:
        return expand_groups((*self.hard, *self.soft))

    @property
    def all(self) -> tuple[str, ...]:
        """Types with at least one avoided group."""
        return types_of(self.all_groups)


class RainLevels(_Strict):
    thresholds_mm: tuple[float, float, float]
    avoid_by_level: dict[int, LevelAvoid]

    @model_validator(mode="after")
    def _check(self):
        t = self.thresholds_mm
        if not (0 < t[0] < t[1] < t[2] <= 300):
            raise ValueError("thresholds_mm must be increasing values in (0, 300]")
        if sorted(self.avoid_by_level) != list(range(MAX_LEVEL + 1)):
            raise ValueError("avoid_by_level must define levels 0..3")
        previous_hard: set[str] = set()
        previous_all: set[str] = set()
        for level in range(MAX_LEVEL + 1):
            entry = self.avoid_by_level[level]
            unknown = set(entry.hard) | set(entry.soft)
            unknown -= set(ZONE_TYPES) | set(ZONE_GROUPS)
            if unknown:
                raise ValueError(f"unknown zone types at level {level}: {sorted(unknown)}")
            hard, soft = set(entry.hard_groups), set(entry.soft_groups)
            if hard & soft:
                raise ValueError(f"level {level}: a type cannot be both hard and soft")
            if not (previous_hard <= hard and previous_all <= hard | soft):
                raise ValueError("avoided types must accumulate as the level rises")
            previous_hard, previous_all = hard, hard | soft
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
        for t in ZONE_TYPES:
            expected = ZONE_TIERS.get(t, ())
            if set(self.zone_types[t].tiers) != set(expected):
                raise ValueError(f"zone_types.{t}.tiers must be exactly {list(expected)}")
        return self

    def group_labels(self) -> dict[str, str]:
        """"침수 이력(우선 회피)" for tiered groups, the type label otherwise."""
        labels = {}
        for group in ZONE_GROUPS:
            cfg, tier = self.zone_types[group_type(group)], group_tier(group)
            labels[group] = f"{cfg.label}({cfg.tiers[tier].label})" if tier else cfg.label
        return labels

    def penalty_scales(self) -> dict[str, float]:
        scales = {}
        for group in ZONE_GROUPS:
            tier = group_tier(group)
            scales[group] = self.zone_types[group_type(group)].tiers[tier].penalty_scale if tier else 1.0
        return scales


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
