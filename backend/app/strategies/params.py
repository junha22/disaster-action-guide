"""Per-request parameter overrides (requirement 4.7). Unknown keys or out-of-range values -> 422."""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..config import AppConfig, ZONE_TYPES


class ParamsError(ValueError):
    """Invalid parameter override. The message never contains request values."""


class _Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BufferOverrides(_Overrides):
    underpass: float | None = Field(None, ge=0, le=200)
    flood_history: float | None = Field(None, ge=0, le=200)
    riverside: float | None = Field(None, ge=0, le=200)


class WeightOverrides(_Overrides):
    underpass: float | None = Field(None, ge=0, le=10)
    flood_history: float | None = Field(None, ge=0, le=10)
    riverside: float | None = Field(None, ge=0, le=10)


class AlertOverrides(_Overrides):
    advisory: int | None = Field(None, ge=0, le=3)
    warning: int | None = Field(None, ge=0, le=3)


class CommonParams(_Overrides):
    avoid_buffer_m: BufferOverrides | None = None
    weights: WeightOverrides | None = None


class TieredParams(CommonParams):
    rain_thresholds_mm: tuple[float, float, float] | None = None
    alert_min_level: AlertOverrides | None = None

    @field_validator("rain_thresholds_mm")
    @classmethod
    def _increasing(cls, value):
        if value is not None and not (0 < value[0] < value[1] < value[2] <= 300):
            raise ValueError("must be three increasing values in (0, 300]")
        return value


class RerankParams(CommonParams):
    lambda_: float | None = Field(None, alias="lambda", ge=0, le=10)


def allowed_keys(model: type[BaseModel]) -> list[str]:
    return [field.alias or name for name, field in model.model_fields.items()]


def _merge(defaults: dict[str, float], override: BaseModel | None) -> dict[str, Any]:
    merged = dict(defaults)
    if override is not None:
        merged.update({k: v for k, v in override.model_dump().items() if v is not None})
    return merged


def parse_overrides(model: type[BaseModel], overrides: dict[str, Any] | None) -> BaseModel:
    try:
        return model.model_validate(overrides or {})
    except ValidationError as exc:
        problems = "; ".join(
            f"params.{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors(include_input=False))
        raise ParamsError(f"허용되지 않는 파라미터입니다 ({problems})") from None


def resolve(config: AppConfig, model: type[BaseModel], overrides: dict[str, Any] | None):
    from .base import ResolvedParams  # avoid import cycle

    parsed = parse_overrides(model, overrides)
    buffers = _merge({t: config.zone_types[t].avoid_buffer_m for t in ZONE_TYPES}, getattr(parsed, "avoid_buffer_m"))
    weights = _merge({t: config.zone_types[t].weight for t in ZONE_TYPES}, getattr(parsed, "weights"))
    thresholds = getattr(parsed, "rain_thresholds_mm", None) or config.rain_levels.thresholds_mm
    alert = _merge(config.alert_min_level.model_dump(), getattr(parsed, "alert_min_level", None))
    if alert["advisory"] > alert["warning"]:
        raise ParamsError("허용되지 않는 파라미터입니다 (params.alert_min_level: advisory must not exceed warning)")
    lambda_ = getattr(parsed, "lambda_", None)
    if lambda_ is None:
        lambda_ = float(config.strategies.get("rerank", {}).get("lambda", 1.0))
    return ResolvedParams(
        avoid_buffer_m=buffers, weights=weights, thresholds_mm=tuple(thresholds), alert_min_level=alert,
        avoid_by_level={k: tuple(v) for k, v in config.rain_levels.avoid_by_level.items()},
        labels={t: config.zone_types[t].label for t in ZONE_TYPES}, lambda_=float(lambda_))
