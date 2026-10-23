"""Auto-discovered business scenario modules for six-scenario coverage.

Each module in this package owns one scenario end to end: SQLite schema, demo
seed data, tool nodes, planner intents, risk rules, read-only API routes and
optional background automation. ``create_app`` discovers every module through
:func:`iter_scenario_modules`, so adding a scenario means dropping one file
into this package plus its tests -- core wiring never has to change.

See ``README.md`` in this package for the module contract.
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

DEMO_USER = "demo-user"
ALLOW_ENV = "AEGIS_SCENARIO_ALLOW"
STRICT_ENV = "AEGIS_SCENARIO_STRICT"

_MODULES: list[ModuleType] | None = None


def reset_scenario_cache() -> None:
    """Forget discovered modules (tests that switch scenario allowlists)."""
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
                f"场景模块 {info.name} 加载失败，已跳过：{exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    _MODULES = modules
    return modules


def iter_scenario_modules() -> Iterator[ModuleType]:
    """Yield scenario modules in deterministic name order."""
    yield from _load_modules()


def prepare_persistence(db: Database, user_id: str = DEMO_USER) -> list[ModuleType]:
    """Apply every scenario schema, then seed demo facts idempotently."""
    modules = list(iter_scenario_modules())
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


def register_scenario_tools(services: CoreServices, modules: list[ModuleType]) -> list[str]:
    """Register scenario tool nodes into the shared catalog and return names."""
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


def include_scenario_routers(
    app: FastAPI, services: CoreServices, modules: list[ModuleType]
) -> None:
    """Attach scenario read-only routers so the frontend can show real facts."""
    for module in modules:
        factory = getattr(module, "router", None)
        if not callable(factory):
            continue
        router = factory(services)
        if router is not None:
            app.include_router(router)


def start_scenario_background(services: CoreServices, modules: list[ModuleType]) -> None:
    """Start optional background automation (time dimension) at app startup."""
    for module in modules:
        starter = getattr(module, "start_background", None)
        if callable(starter):
            starter(services)


def stop_scenario_background(modules: list[ModuleType]) -> None:
    """Stop optional background automation at app shutdown."""
    for module in modules:
        stopper = getattr(module, "stop_background", None)
        if callable(stopper):
            stopper()
