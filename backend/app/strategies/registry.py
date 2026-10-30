"""@register("name") and discovery of every module in this package (requirement 4.3)."""
import importlib
import pkgutil
import threading
from typing import Any

from .. import strategies as _package
from .base import Strategy

_SKIP = {"base", "registry", "params"}
_registry: dict[str, type] = {}
_lock = threading.RLock()
_discovered = False


class UnknownStrategy(KeyError):
    pass


def register(name: str):
    def decorator(cls):
        with _lock:
            existing = _registry.get(name)
            if existing is not None and existing is not cls:
                raise ValueError(f"strategy name already registered: {name}")
            cls.name = name
            _registry[name] = cls
        return cls
    return decorator


def discover() -> None:
    global _discovered
    with _lock:
        if _discovered:
            return
        for module in pkgutil.iter_modules(_package.__path__):
            if module.name.startswith("_") or module.name in _SKIP:
                continue
            importlib.import_module(f"{_package.__name__}.{module.name}")
        _discovered = True


def reset_discovery() -> None:
    """For tests that add modules to the package path."""
    global _discovered
    with _lock:
        _discovered = False


def unregister(name: str) -> None:
    with _lock:
        _registry.pop(name, None)


def get_strategy(name: str) -> Strategy:
    discover()
    cls = _registry.get(name)
    if cls is None:
        raise UnknownStrategy(name)
    return cls()


def list_strategies(default: str | None = None) -> list[dict[str, Any]]:
    from .params import allowed_keys

    discover()
    names = sorted(_registry, key=lambda n: (n != default, n))
    return [{"name": n, "label": _registry[n].label, "description": _registry[n].description,
             "default": n == default, "params": allowed_keys(_registry[n].params_model)} for n in names]
