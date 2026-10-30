"""Dependencies that turn data/config problems into fixed 500 messages."""
from fastapi import HTTPException

from ..config import AppConfig, ConfigError, get_config
from ..risk.layer import RiskDataError, RiskLayer, get_risk_layer


def config_dep() -> AppConfig:
    try:
        return get_config()
    except ConfigError as exc:
        raise HTTPException(500, str(exc)) from None


def layer_dep() -> RiskLayer:
    try:
        return get_risk_layer()
    except RiskDataError as exc:
        raise HTTPException(500, str(exc)) from None
