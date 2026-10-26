"""Filesystem boundaries and repeatability of the six-module assembler."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "assemble.py"
SPEC = importlib.util.spec_from_file_location("aegis_assemble", SCRIPT)
assert SPEC and SPEC.loader
ASSEMBLER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ASSEMBLER
SPEC.loader.exec_module(ASSEMBLER)


class AssembleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="aegis-assemble-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        for module in ASSEMBLER.MODULES:
            (self.root / module).mkdir()
        self.write("backend/backend/pyproject.toml", "[project]\nname='fixture'\n")
        self.track()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def track(self) -> None:
        subprocess.run(["git", "-C", str(self.root), "add", "--all"], check=True)

    def runtime(self, name: str) -> Path:
        return self.root / ".runtime" / name

    def test_merges_allowed_roots_and_env_example_without_modifying_modules(self) -> None:
        sources = {
            "agent/backend/aegisbank_api/audit.py": "AUDIT = True\n",
            "NLP/backend/aegisbank_api/planning/rule.py": "RULE = True\n",
            "fronted/frontend/src/App.tsx": "export default 1;\n",
            "plans/docs/ARCHITECTURE.md": "Architecture\n",
            "backend/scripts/dev.sh": "#!/bin/sh\n",
            "backend/.env.example": "AEGIS_PLANNER_MODE=rule\n",
        }
        for name, content in sources.items():
            self.write(name, content)
        result = ASSEMBLER.assemble(self.root)
        self.assertEqual(result["files"], 7)
        for name, content in sources.items():
            relative = (
                name.split("/", 1)[1] if name != "backend/.env.example" else "backend/.env.example"
            )
            self.assertEqual(self.runtime(relative).read_text(encoding="utf-8"), content)
            self.assertEqual((self.root / name).read_text(encoding="utf-8"), content)

    def test_includes_unstaged_source_and_respects_git_ignores(self) -> None:
        self.write(".gitignore", "ignored.py\n.runtime/\n")
        self.write("agent/backend/new.py", "new source")
        self.write("agent/backend/ignored.py", "not an input")
        ASSEMBLER.assemble(self.root)
        self.assertTrue(self.runtime("backend/new.py").is_file())
        self.assertFalse(self.runtime("backend/ignored.py").exists())

    def test_assembles_source_archive_without_git_metadata(self) -> None:
        self.write("fronted/frontend/package.json", '{"name":"archive-fixture"}')
        self.write("agent/backend/new.py", "source archive")
        self.write("agent/backend/data/private.db", "runtime data")
        archive = self.root.parent / "archive"
        archive.mkdir()
        for module in ASSEMBLER.MODULES:
            shutil.copytree(self.root / module, archive / module)
        self.assertFalse((archive / ".git").exists())
        result = ASSEMBLER.assemble(archive)
        self.assertEqual(result["files"], 3)
        self.assertEqual((archive / ".runtime/backend/new.py").read_text(), "source archive")
        self.assertFalse((archive / ".runtime/backend/data/private.db").exists())

    def test_git_checkout_errors_do_not_fall_back_to_archive_scanning(self) -> None:
        with patch.object(ASSEMBLER.subprocess, "run", side_effect=FileNotFoundError("no git")):
            with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "Git checkout"):
                ASSEMBLER.assemble(self.root)
        self.assertFalse(self.runtime(ASSEMBLER.MANIFEST_NAME).exists())

    def test_archive_rejects_linked_source_directories(self) -> None:
        archive = self.root.parent / "archive-links"
        archive.mkdir()
        for module in ASSEMBLER.MODULES:
            shutil.copytree(self.root / module, archive / module)
        directory = archive / "agent/backend"
        directory.mkdir()
        outside = self.root.parent / "external-source"
        outside.mkdir()
        (outside / "secret.py").write_text("outside", encoding="utf-8")
        self.make_link(directory / "linked", outside, True)
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "links"):
            ASSEMBLER.assemble(archive)
        self.assertFalse((archive / ".runtime").exists())

    def test_identical_duplicate_paths_are_allowed(self) -> None:
        self.write("agent/backend/common.py", "same")
        self.write("skills/backend/common.py", "same")
        ASSEMBLER.assemble(self.root)
        manifest = json.loads(self.runtime(ASSEMBLER.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]["backend/common.py"]["sources"]), 2)

    def test_conflicting_duplicates_fail_before_any_runtime_change(self) -> None:
        ASSEMBLER.assemble(self.root)
        old_manifest = self.runtime(ASSEMBLER.MANIFEST_NAME).read_bytes()
        self.write("agent/backend/common.py", "first")
        self.write("skills/backend/common.py", "second")
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "Conflicting"):
            ASSEMBLER.assemble(self.root)
        self.assertEqual(self.runtime(ASSEMBLER.MANIFEST_NAME).read_bytes(), old_manifest)
        self.assertFalse(self.runtime("backend/common.py").exists())

    def test_repeat_assembly_updates_and_deletes_only_owned_sources(self) -> None:
        change = self.write("agent/backend/change.py", "version 1")
        remove = self.write("agent/backend/remove.py", "delete me")
        self.track()
        ASSEMBLER.assemble(self.root)
        keep = {
            "backend/data/aegisbank.db": "database",
            "backend/.venv/marker": "environment",
            "frontend/node_modules/marker": "dependencies",
            "frontend/dist/index.html": "build output",
            "backend/unmanaged.txt": "user file",
        }
        for name, text in keep.items():
            path = self.runtime(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        change.write_text("version 2", encoding="utf-8")
        remove.unlink()
        result = ASSEMBLER.assemble(self.root)
        self.assertEqual(result["removed"], 1)
        self.assertEqual(self.runtime("backend/change.py").read_text(), "version 2")
        self.assertFalse(self.runtime("backend/remove.py").exists())
        for name, text in keep.items():
            self.assertEqual(self.runtime(name).read_text(encoding="utf-8"), text)
        self.assertEqual(ASSEMBLER.assemble(self.root)["written"], 0)

    def test_refuses_overwriting_or_deleting_a_modified_generated_file(self) -> None:
        source = self.write("agent/backend/edit.py", "original")
        ASSEMBLER.assemble(self.root)
        self.runtime("backend/edit.py").write_text("local edit", encoding="utf-8")
        for deletion in (False, True):
            if deletion:
                source.unlink()
            with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "edited locally"):
                ASSEMBLER.assemble(self.root)
            self.assertEqual(self.runtime("backend/edit.py").read_text(), "local edit")

    def test_refuses_overwriting_an_unmanaged_source_target(self) -> None:
        self.write("agent/backend/new.py", "module")
        path = self.runtime("backend/new.py")
        path.parent.mkdir(parents=True)
        path.write_text("manual", encoding="utf-8")
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "unmanaged"):
            ASSEMBLER.assemble(self.root)
        self.assertEqual(path.read_text(), "manual")

    def test_excludes_metadata_secrets_dependencies_and_runtime_data(self) -> None:
        ignored = [
            "backend/_PACKAGE/backend/MANIFEST.json",
            "backend/README.md",
            "fronted/frontend/node_modules/dep.js",
            "fronted/frontend/dist/index.html",
            "agent/backend/.venv/pyvenv.cfg",
            "agent/backend/data/aegisbank.db",
            "agent/backend/__pycache__/x.pyc",
            "agent/backend/.env",
            "agent/backend/test.sqlite",
            "plans/docs/.cache/file.md",
            "agent/backend/request.lock",
        ]
        for name in ignored:
            self.write(name, "do not copy")
        self.track()
        result = ASSEMBLER.assemble(self.root)
        self.assertEqual(result["files"], 1)

    def test_rejects_traversal_and_runtime_directories_in_manifest(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        for unsafe in (
            "../outside.txt",
            "backend/../../outside.txt",
            "backend/data/aegisbank.db",
            "frontend/node_modules/pkg.js",
            "/outside.txt",
            "C:/outside.txt",
            "backend\\outside.txt",
        ):
            with self.subTest(path=unsafe):
                self.runtime("").mkdir(exist_ok=True)
                self.runtime(ASSEMBLER.MANIFEST_NAME).write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "files": {unsafe: {"sha256": hashlib.sha256(b"keep").hexdigest()}},
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(ASSEMBLER.AssemblyError):
                    ASSEMBLER.assemble(self.root)
                self.assertEqual(outside.read_text(), "keep")

    def make_link(self, link: Path, target: Path, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symbolic links are unavailable on this platform: {error}")

    def test_rejects_source_symlinks(self) -> None:
        source = self.root / "agent" / "backend" / "link.py"
        source.parent.mkdir(parents=True)
        outside = self.root / "outside.py"
        outside.write_text("outside", encoding="utf-8")
        self.make_link(source, outside)
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "links"):
            ASSEMBLER.assemble(self.root)
        self.assertFalse(self.runtime(ASSEMBLER.MANIFEST_NAME).exists())

    def test_rejects_output_symlinks_and_invalid_output_file(self) -> None:
        output = self.runtime("")
        output.write_text("not a directory", encoding="utf-8")
        with self.assertRaises(ASSEMBLER.AssemblyError):
            ASSEMBLER.assemble(self.root)
        output.unlink()
        outside = self.root.parent / "outside-runtime"
        outside.mkdir()
        self.make_link(output, outside, True)
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "links"):
            ASSEMBLER.assemble(self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_rejects_runtime_parent_symlinks(self) -> None:
        self.write("agent/backend/a.py", "source")
        self.runtime("").mkdir()
        outside = self.root.parent / "outside-backend"
        outside.mkdir()
        self.make_link(self.runtime("backend"), outside, True)
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "links"):
            ASSEMBLER.assemble(self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_rejects_output_file_directory_collision(self) -> None:
        self.write("agent/backend/item", "file")
        self.write("skills/backend/item/child.py", "child")
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "file/directory collision"):
            ASSEMBLER.assemble(self.root)
        self.assertFalse(self.runtime(ASSEMBLER.MANIFEST_NAME).exists())

    @unittest.skipIf(os.name == "nt", "Windows cannot create distinct case-only paths")
    def test_rejects_case_only_collisions(self) -> None:
        self.write("agent/backend/File.py", "first")
        self.write("skills/backend/file.py", "second")
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "Case-insensitive"):
            ASSEMBLER.assemble(self.root)

    def test_cli_rejects_custom_output_paths(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--output", "../escape"], capture_output=True
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"always repo/.runtime", result.stderr)


if __name__ == "__main__":
    unittest.main()
