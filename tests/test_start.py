"""Launcher safety: existing data, occupied ports, readiness and process ownership."""

from __future__ import annotations

import importlib.util
import json
import select
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/start.py"
SPEC = importlib.util.spec_from_file_location("aegis_start", SCRIPT)
LAUNCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCH)


class StartTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aegis-start-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        package = self.root / "fronted/frontend/package.json"
        package.parent.mkdir(parents=True)
        package.write_text(json.dumps({"engines": {"node": "^22.22.2 || ^24.15.0 || >=26.0.0"}}))
        self.launcher = LAUNCH.Launcher(self.root, None, 0.01)

    def test_supported_node_boundaries_and_rejected_versions(self):
        engines = "^22.22.2 || ^24.15.0 || >=26.0.0"
        for version in ("v22.22.2", "v22.23.3", "v24.15.0", "v26.0.0"):
            with self.subTest(version=version):
                self.assertTrue(LAUNCH.node_supported(version, engines))
        for version in ("v22.22.1", "v23.9.0", "v24.14.9", "v25.0.0", "v26.0.0-rc1"):
            with self.subTest(version=version):
                self.assertFalse(LAUNCH.node_supported(version, engines))

    def test_occupied_port_is_refused_without_stopping_its_owner(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = server.getsockname()[1]
            with self.assertRaisesRegex(LAUNCH.LaunchError, str(port)):
                LAUNCH.check_ports([port])
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                connection, _ = server.accept()
                connection.close()

    def test_duplicate_launcher_lock_is_rejected_and_can_be_reacquired_after_exit(self):
        lock = self.root / "launcher.lock"
        with (
            LAUNCH.launch_lock(lock),
            self.assertRaisesRegex(LAUNCH.LaunchError, "已有启动进程"),
            LAUNCH.launch_lock(lock),
        ):
            self.fail("duplicate launcher acquired the lock")
        with LAUNCH.launch_lock(lock):
            self.assertTrue(lock.exists())

    def prepare(self, steps):
        with (
            patch.object(LAUNCH.shutil, "which", side_effect=lambda name: "/fake/" + name),
            patch.object(LAUNCH.subprocess, "check_output", return_value="v22.23.3"),
            patch.object(
                self.launcher, "run_step", side_effect=lambda *args, **kwargs: steps.append(args)
            ),
        ):
            return self.launcher.prepare()

    def test_existing_database_is_never_reseeded_or_reset(self):
        database = self.launcher.database
        database.parent.mkdir(parents=True)
        content = b"existing simulated transfers and audit history"
        database.write_bytes(content)
        steps = []
        self.prepare(steps)
        self.assertEqual(database.read_bytes(), content)
        self.assertFalse(any("aegisbank_api.demo_seed" in step[1] for step in steps))

    def test_first_start_uses_non_destructive_seed_without_reset_flag(self):
        steps = []
        self.prepare(steps)
        seeds = [step[1] for step in steps if "aegisbank_api.demo_seed" in step[1]]
        self.assertEqual(len(seeds), 1)
        self.assertNotIn("--reset", seeds[0])
        self.assertEqual(seeds[0][-1], self.launcher.database)

    def test_dependency_install_cannot_wait_for_a_hidden_confirmation_prompt(self):
        environment_before = dict(self.launcher.env)
        with (
            patch.object(LAUNCH.shutil, "which", side_effect=lambda name: "/fake/" + name),
            patch.object(LAUNCH.subprocess, "check_output", return_value="v22.23.3"),
            patch.object(self.launcher, "run_step") as run,
        ):
            self.launcher.prepare()
        install = next(call for call in run.call_args_list if "安装冻结的前端依赖" in call.args[0])
        self.assertEqual(install.kwargs["env"]["CI"], "true")
        self.assertEqual(self.launcher.env, environment_before)

    def test_not_ready_proxy_or_invalid_audit_never_announces_success(self):
        live = SimpleNamespace(poll=lambda: None)
        for failed in ("backend", "proxy", "audit"):
            with self.subTest(failed=failed):

                def response(url, failed=failed):
                    if "audit/verify" in url:
                        return {"valid": failed != "audit"}
                    component = "proxy" if ":5173/" in url else "backend"
                    return {"status": "not_ready" if component == failed else "ready"}

                with (
                    patch.object(self.launcher, "spawn", return_value=live),
                    patch.object(LAUNCH, "request_json", side_effect=response),
                    patch.object(LAUNCH, "say") as say,
                ):
                    with self.assertRaisesRegex(LAUNCH.LaunchError, "未在"):
                        self.launcher.serve(Path("python"), "pnpm", True)
                    self.assertFalse(any("已就绪" in str(call) for call in say.call_args_list))

    def test_service_exit_cannot_be_mistaken_for_foreign_healthy_server(self):
        dead = SimpleNamespace(poll=lambda: 1)
        with (
            patch.object(LAUNCH, "request_json", return_value={"status": "ready", "valid": True}),
            self.assertRaisesRegex(LAUNCH.LaunchError, "提前退出"),
        ):
            self.launcher.wait_ready([dead])

    def test_shutdown_stops_owned_descendants_and_leaves_other_process_alive(self):
        sleeper = "import time; time.sleep(60)"
        foreign = subprocess.Popen([sys.executable, "-c", sleeper], start_new_session=True)
        self.addCleanup(LAUNCH.stop_processes, [foreign], 0.2)
        code = (
            "import subprocess,sys,time; "
            f"p=subprocess.Popen([sys.executable,'-c',{sleeper!r}]); "
            "print(p.pid,flush=True); time.sleep(60)"
        )
        owned = subprocess.Popen(
            [sys.executable, "-c", code],
            start_new_session=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(LAUNCH.stop_processes, [owned], 0.2)
        self.addCleanup(owned.stdout.close)
        readable, _, _ = select.select([owned.stdout], [], [], 5)
        self.assertTrue(readable, "owned process failed to report its child")
        descendant = int(owned.stdout.readline())
        LAUNCH.stop_processes([owned], 0.2)
        self.assertIsNotNone(owned.poll())
        self.assertIsNone(foreign.poll())
        status = Path(f"/proc/{descendant}/stat")
        if status.exists():
            self.assertEqual(
                status.read_text().split()[2], "Z", "owned descendant is still running"
            )

    def test_help_and_invalid_timeout_do_not_require_dependencies_or_launch_services(self):
        help_result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--no-browser", help_result.stdout)
        invalid = subprocess.run(
            [sys.executable, str(SCRIPT), "--startup-timeout", "nan"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse((self.root / ".runtime").exists())


if __name__ == "__main__":
    unittest.main()
