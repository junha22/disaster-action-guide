"""Routing engine adapters. get_engine() is the FastAPI dependency; tests override it."""
from functools import lru_cache

from .base import RoutingEngine


@lru_cache(maxsize=1)
def get_engine() -> RoutingEngine:
    from .valhalla import ValhallaEngine  # creating the adapter loads nothing yet

    return ValhallaEngine()
