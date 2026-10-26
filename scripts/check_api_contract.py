#!/usr/bin/env python3
"""Guard the frontend/backend HTTP contract.

The frontend source is authoritative for which /api paths it calls. The
assembled backend exposes those paths through FastAPI OpenAPI. Run this after
``python3 scripts/assemble.py``:

    python3 scripts/check_api_contract.py

It fails if the frontend calls a path that the backend does not expose. Extra
backend paths are allowed (scenario, trust and ops endpoints may be used later).
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FRONTEND_API = REPO / "fronted" / "frontend" / "src" / "api.ts"
RUNTIME_BACKEND = REPO / ".runtime" / "backend"

PATH_LITERAL = re.compile(r"(['\"`])(/[^'\"`]*)\1", re.S)
TEMPLATE_PARAM = re.compile(r"/\$\{[^}]+\}")
TEMPLATE_SUFFIX = re.compile(r"\$\{[^}]+\}")
PARAM = re.compile(r"\{[^}]+\}")


def frontend_paths() -> set[str]:
    if not FRONTEND_API.is_file():
        raise SystemExit(f"Frontend API source not found: {FRONTEND_API}")
    text = FRONTEND_API.read_text(encoding="utf-8")
    paths: set[str] = set()
    for match in PATH_LITERAL.finditer(text):
        raw = match.group(2).split("?", 1)[0]
        if raw == "/api":
            continue
        # Template path parameters (/actions/${id}/journal) become {param}.
        raw = TEMPLATE_PARAM.sub("/{param}", raw)
        # Query-string suffixes (/wealth/products${query}) disappear.
        raw = TEMPLATE_SUFFIX.sub("", raw)
        if raw.startswith("/") and len(raw) > 1:
            paths.add(raw)
    return paths


def backend_paths() -> set[str]:
    if not (RUNTIME_BACKEND / "aegisbank_api").is_dir():
        raise SystemExit(
            "Assembled backend not found. Run: python3 scripts/assemble.py"
        )
    sys.path.insert(0, str(RUNTIME_BACKEND))
    try:
        from aegisbank_api.main import create_app
    except ModuleNotFoundError as error:
        raise SystemExit(
            "Backend dependencies are not available to this interpreter. Run "
            "from .runtime/backend with: uv run --frozen python ../../scripts/check_api_contract.py"
        ) from error

    with tempfile.TemporaryDirectory(prefix="aegis-contract-") as tmp:
        app = create_app(database_path=Path(tmp) / "contract.db")
        return set(app.openapi().get("paths", {}).keys())


def shape(path: str) -> str:
    return PARAM.sub("{param}", path)


def main() -> int:
    frontend = {"/api" + path for path in frontend_paths()}
    backend = backend_paths()
    backend_shapes = {shape(path) for path in backend}
    missing = sorted(path for path in frontend if shape(path) not in backend_shapes)
    print(f"Frontend /api paths: {len(frontend)}")
    print(f"Backend OpenAPI paths: {len(backend)}")
    if missing:
        print("Unmatched frontend paths:")
        for path in missing:
            print(f"  - {path}")
        return 1
    print("API contract OK: every frontend path exists in backend OpenAPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())