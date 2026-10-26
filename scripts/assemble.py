#!/usr/bin/env python3
"""Assemble the six source modules into the disposable .runtime directory.

Source modules stay authoritative. Only files recorded in the previous assembly
manifest may be updated or removed; databases, environments and dependencies
inside .runtime are never assembly inputs or cleanup targets.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MODULES = ("NLP", "agent", "backend", "fronted", "plans", "skills")
TOP_LEVELS = frozenset({"backend", "frontend", "docs", "scripts"})
MANIFEST_NAME = ".assembly-manifest.json"
IGNORED_PARTS = frozenset(
    {"_PACKAGE", "node_modules", "venv", "__pycache__", "dist", "build", "coverage"}
)
GENERATED_SUFFIXES = frozenset({".pyc", ".pyo", ".db", ".sqlite", ".sqlite3"})


class AssemblyError(RuntimeError):
    """An invalid input must be fixed before assembly can change any files."""


@dataclass
class SourceFile:
    data: bytes
    sha256: str
    sources: list[str]
    executable: bool


def _parts(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\0" in value:
        raise AssemblyError(f"Unsafe relative path: {value!r}")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise AssemblyError(f"Unsafe relative path: {value!r}")
    return parts


def _ignored(parts: tuple[str, ...]) -> bool:
    if parts == ("backend", ".env.example"):
        return False
    return (
        any(part.startswith(".") or part in IGNORED_PARTS for part in parts)
        or parts[:2] == ("backend", "data")
        or PurePosixPath(*parts).suffix.lower() in GENERATED_SUFFIXES
        or (parts[-1].endswith(".lock") and parts[-1] != "uv.lock")
    )


def _validate_destination(value: str) -> tuple[str, ...]:
    parts = _parts(value)
    if len(parts) < 2 or parts[0] not in TOP_LEVELS or _ignored(parts):
        raise AssemblyError(f"Not an allowed generated source path: {value!r}")
    return parts


def _destination(source: str) -> str | None:
    parts = _parts(source)
    if parts[0] not in MODULES:
        return None
    if parts == ("backend", ".env.example"):
        return "backend/.env.example"
    if len(parts) < 3 or parts[1] not in TOP_LEVELS:
        return None
    relative = parts[1:]
    if _ignored(relative):
        return None
    return "/".join(relative)


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _safe_path(root: Path, parts: tuple[str, ...]) -> Path:
    path = root
    for index, part in enumerate(parts):
        path = path / part
        if _is_link(path):
            raise AssemblyError(f"Symbolic links and junctions are not allowed: {path}")
        if index < len(parts) - 1 and path.exists() and not path.is_dir():
            raise AssemblyError(f"A parent path is not a directory: {path}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise AssemblyError(f"Path escapes its root: {path}")
    return path


def _git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", *arguments, "--", *MODULES],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise AssemblyError(
            "Assembly requires a Git checkout and an available git command."
        ) from error
    return result.stdout


def _source_entries(root: Path) -> list[tuple[str, str | None]]:
    if not (root / ".git").exists() and not _is_link(root / ".git"):
        return _archive_entries(root)
    entries: dict[str, str | None] = {}
    for record in _git(root, "--cached", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, _object_id, stage = metadata.decode("ascii").split()
        name = raw_path.decode("utf-8", errors="surrogateescape")
        if stage != "0":
            raise AssemblyError(f"Resolve the Git merge conflict first: {name}")
        entries[name] = mode
    for raw_path in _git(root, "--others", "--exclude-standard", "-z").split(b"\0"):
        if raw_path:
            entries.setdefault(raw_path.decode("utf-8", errors="surrogateescape"), None)
    return sorted(entries.items())


def _archive_entries(root: Path) -> list[tuple[str, None]]:
    """Source ZIPs have no Git metadata; use the same explicit path policy."""
    entries: list[tuple[str, None]] = []
    for module in MODULES:
        for directory, names, filenames in os.walk(root / module, followlinks=False):
            parent = Path(directory)
            kept = []
            for name in sorted(names):
                path = parent / name
                relative = path.relative_to(root).as_posix()
                parts = _parts(relative)
                allowed = (
                    parts[1] in TOP_LEVELS
                    if len(parts) == 2
                    else _destination(relative) is not None
                )
                if not allowed:
                    continue
                if _is_link(path):
                    raise AssemblyError(f"Symbolic links and junctions are not allowed: {path}")
                kept.append(name)
            names[:] = kept
            for name in sorted(filenames):
                entries.append(((parent / name).relative_to(root).as_posix(), None))
    return sorted(entries)


def _plan(root: Path) -> dict[str, SourceFile]:
    for module in MODULES:
        path = _safe_path(root, (module,))
        if not path.is_dir():
            raise AssemblyError(f"Missing source module directory: {module}")
    files: dict[str, SourceFile] = {}
    case_names: dict[str, str] = {}
    for source, mode in _source_entries(root):
        destination = _destination(source)
        if destination is None:
            continue
        if mode not in {None, "100644", "100755"}:
            raise AssemblyError(f"Unsupported Git file mode (links are forbidden): {source}")
        path = _safe_path(root, _parts(source))
        if not path.exists():
            # A working-tree deletion is an input deletion even before staging.
            continue
        if not stat.S_ISREG(path.lstat().st_mode):
            raise AssemblyError(f"Source is not a regular file: {source}")
        previous_name = case_names.setdefault(destination.casefold(), destination)
        if previous_name != destination:
            raise AssemblyError(
                f"Case-insensitive output collision: {previous_name} / {destination}"
            )
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        executable = mode == "100755" or (mode is None and bool(path.stat().st_mode & stat.S_IXUSR))
        previous = files.get(destination)
        if previous:
            if previous.data != data:
                raise AssemblyError(
                    f"Conflicting source files for {destination}: {previous.sources[0]} / {source}"
                )
            previous.sources.append(source)
            previous.executable = previous.executable or executable
        else:
            files[destination] = SourceFile(data, digest, [source], executable)
    if not files:
        raise AssemblyError("No source files were found; refusing to clear an existing runtime.")
    for name in files:
        for parent in PurePosixPath(name).parents:
            collision = case_names.get(parent.as_posix().casefold())
            if collision:
                raise AssemblyError(f"Output file/directory collision: {collision} / {name}")
    return files


def _load_manifest(output: Path) -> dict[str, str]:
    path = _safe_path(output, (MANIFEST_NAME,))
    if not path.exists():
        return {}
    if not path.is_file():
        raise AssemblyError("The assembly manifest is not a regular file.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise AssemblyError("The previous assembly manifest is unreadable.") from error
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("files"), dict)
    ):
        raise AssemblyError("The previous assembly manifest has an unsupported format.")
    files: dict[str, str] = {}
    folded: set[str] = set()
    for name, record in value["files"].items():
        _validate_destination(name)
        if name.casefold() in folded:
            raise AssemblyError(f"Duplicate manifest destination: {name}")
        folded.add(name.casefold())
        digest = record.get("sha256") if isinstance(record, dict) else None
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise AssemblyError(f"Invalid manifest digest: {name}")
        files[name] = digest
    return files


def _current_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if not stat.S_ISREG(path.lstat().st_mode):
        raise AssemblyError(f"Generated source path is not a regular file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, data: bytes, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".assemble-", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        temporary.chmod(0o755 if executable else 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def assemble(repo_root: Path) -> dict[str, int | str]:
    root = repo_root.resolve()
    output = _safe_path(root, (".runtime",))
    if output.exists() and not output.is_dir():
        raise AssemblyError(".runtime must be a directory, not a file.")
    planned = _plan(root)
    previous = _load_manifest(output)
    current: dict[str, str | None] = {}
    # Complete preflight before creating directories, overwriting or deleting.
    for name in sorted(planned.keys() | previous.keys()):
        target = _safe_path(output, _validate_destination(name))
        digest = _current_digest(target)
        current[name] = digest
        if digest is None:
            continue
        if name not in previous:
            raise AssemblyError(f"Refusing to overwrite an unmanaged runtime file: {name}")
        if digest != previous[name] and (name not in planned or digest != planned[name].sha256):
            raise AssemblyError(
                f"Generated source was edited locally; move the edit to its module: {name}"
            )

    written = 0
    removed = 0
    for name, source in sorted(planned.items()):
        if current[name] != source.sha256:
            _atomic_write(output.joinpath(*_parts(name)), source.data, source.executable)
            written += 1
    for name in sorted(previous.keys() - planned.keys()):
        if current[name] is not None:
            output.joinpath(*_parts(name)).unlink()
            removed += 1
    manifest = {
        "version": 1,
        "files": {
            name: {"sha256": source.sha256, "sources": source.sources}
            for name, source in sorted(planned.items())
        },
    }
    _atomic_write(
        output / MANIFEST_NAME,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return {"output": str(output), "files": len(planned), "written": written, "removed": removed}


def main() -> int:
    if len(sys.argv) != 1:
        print(
            "Usage: python3 scripts/assemble.py (output is always repo/.runtime)", file=sys.stderr
        )
        return 2
    try:
        result = assemble(Path(__file__).resolve().parents[1])
    except (AssemblyError, OSError) as error:
        print(f"Assembly failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Assembled {result['files']} files into {result['output']} "
        f"({result['written']} written, {result['removed']} removed)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
