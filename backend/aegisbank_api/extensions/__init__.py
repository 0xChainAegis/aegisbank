"""Auto-discovered core extensions for stage 2A cross-cutting capabilities.

Every module in this package owns one cross-cutting concern (compensation /
rollback, suspicious-behaviour breaker, MFA providers, execution sandbox, IM
channel, role matrix). ``create_app`` discovers them automatically so the core
wiring never changes when a new capability is added.

Module contract (all parts optional except ``NAME``):

```python
NAME = "compensation"
SCHEMA_SQL = "CREATE TABLE IF NOT EXISTS ..."     # optional, executed idempotently
def seed(db, user_id, services) -> None: ...      # optional, idempotent demo data
def activate(services) -> None: ...               # optional, wiring after scheduler build
def tools(services) -> list[BaseTool]: ...        # optional, extra tool nodes
def router(services) -> APIRouter | None: ...     # optional, read/write endpoints
def start_background(services) -> None: ...       # optional, demo workers
def stop_background() -> None: ...                # optional, paired with start_background
```

Parallel-development switches: ``AEGIS_EXTENSION_ALLOW=a,b`` loads a subset,
``AEGIS_EXTENSION_ALLOW=none`` loads none, ``AEGIS_EXTENSION_STRICT=0`` skips
modules that fail to import (development only).
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import warnings
from collections.abc import Iterator
from types import ModuleType

from fastapi import FastAPI

from ..db import Database
from ..services import CoreServices

ALLOW_ENV = "AEGIS_EXTENSION_ALLOW"
STRICT_ENV = "AEGIS_EXTENSION_STRICT"

_MODULES: list[ModuleType] | None = None


def reset_extension_cache() -> None:
    """Forget discovered module list (tests that switch allowlists)."""
    global _MODULES
    _MODULES = None


def _allowlist() -> set[str] | None:
    raw = os.environ.get(ALLOW_ENV, "").strip()
    if not raw:
        return None
    if raw.lower() == "none":
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _strict() -> bool:
    return os.environ.get(STRICT_ENV, "1").strip().lower() not in {"0", "false", "no"}


def _load_modules() -> list[ModuleType]:
    global _MODULES
    if _MODULES is not None:
        return _MODULES
    allow = _allowlist()
    strict = _strict()
    modules: list[ModuleType] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda item: item.name):
        if info.name.startswith("_"):
            continue
        if allow is not None and info.name not in allow:
            continue
        try:
            modules.append(importlib.import_module(f"{__name__}.{info.name}"))
        except Exception as exc:  # noqa: BLE001 - tolerant mode is a dev switch
            if strict:
                raise
            warnings.warn(
                f"核心扩展模块 {info.name} 加载失败，已跳过：{exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    _MODULES = modules
    return modules


def iter_extension_modules() -> Iterator[ModuleType]:
    """Yield extension modules in deterministic name order."""
    yield from _load_modules()


def prepare_extensions(db: Database, user_id: str = "demo-user") -> list[ModuleType]:
    """Apply every extension schema, then seed idempotent demo data."""
    modules = list(iter_extension_modules())
    for module in modules:
        schema = str(getattr(module, "SCHEMA_SQL", "") or "")
        if schema.strip():
            with db.transaction() as conn:
                conn.executescript(schema)
    for module in modules:
        seed = getattr(module, "seed", None)
        if callable(seed):
            seed(db, user_id)
    return modules


def activate_extensions(services: CoreServices, modules: list[ModuleType]) -> None:
    """Let modules attach themselves to the runtime once services exist."""
    for module in modules:
        activate = getattr(module, "activate", None)
        if callable(activate):
            activate(services)


def register_extension_tools(
    services: CoreServices, modules: list[ModuleType]
) -> list[str]:
    """Register optional tool nodes contributed by extension modules."""
    registry = services.require_registry()
    registered: list[str] = []
    for module in modules:
        factory = getattr(module, "tools", None)
        if not callable(factory):
            continue
        for tool in factory(services):
            registry.register(tool)
            registered.append(tool.metadata.name)
    return registered


def include_extension_routers(
    app: FastAPI, services: CoreServices, modules: list[ModuleType]
) -> None:
    """Attach extension routers (ops/trust/IM endpoints)."""
    for module in modules:
        factory = getattr(module, "router", None)
        if not callable(factory):
            continue
        router = factory(services)
        if router is not None:
            app.include_router(router)


def start_extension_background(services: CoreServices, modules: list[ModuleType]) -> None:
    """Start optional extension workers at app startup."""
    for module in modules:
        starter = getattr(module, "start_background", None)
        if callable(starter):
            starter(services)


def stop_extension_background(modules: list[ModuleType]) -> None:
    """Stop optional extension workers at app shutdown."""
    for module in modules:
        stopper = getattr(module, "stop_background", None)
        if callable(stopper):
            stopper()
