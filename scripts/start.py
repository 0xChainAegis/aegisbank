"""One-command local launcher; only Python and Node.js must be preinstalled."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
UI_URL = "http://127.0.0.1:5173/#/console"
PORTS = (8000, 5173)
UV_VERSION = "0.13.5"
PNPM_VERSION = "10.11.0"


class LaunchError(RuntimeError):
    """An actionable startup failure, never a successful launch."""


class Stopped(Exception):
    """The user stopped this launcher."""


def say(message: str) -> None:
    print(f"[AegisBank] {message}", flush=True)


def node_supported(version: str, engines: str) -> bool:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        return False
    actual = tuple(int(part) for part in match.groups())
    for alternative in engines.split("||"):
        rule = re.fullmatch(r"\s*(\^|>=)(\d+)\.(\d+)\.(\d+)\s*", alternative)
        if not rule:
            raise LaunchError(f"无法校验 Node.js 版本规则：{engines}")
        minimum = tuple(int(part) for part in rule.groups()[1:])
        if actual >= minimum and (rule[1] == ">=" or actual[0] == minimum[0]):
            return True
    return False


@contextmanager
def launch_lock(path: Path):
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LaunchError("本仓库已有启动进程；请使用原窗口，或先按 Ctrl+C 停止它。") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def check_ports(ports=PORTS) -> None:
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as error:
                raise LaunchError(
                    f"端口 {port} 已被占用；请先检查原服务，本次不会复用或终止它。"
                ) from error


def request_json(url: str):
    try:
        with urlopen(url, timeout=1) as response:
            if response.status == 200:
                return json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        pass
    return None


def stop_processes(processes: list[subprocess.Popen], grace: float = 4) -> None:
    # Every entry is spawned by this launcher in its own process group.
    for child in processes:
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    for child in processes:
        with suppress(subprocess.TimeoutExpired):
            child.wait(timeout=max(0.01, deadline - time.monotonic()))
    for child in processes:
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait()


class Launcher:
    def __init__(self, root: Path, database: Path | None, timeout: float):
        self.root = root.resolve()
        self.runtime = self.root / ".runtime"
        self.database = (database or self.runtime / "backend/data/quickstart.db").resolve()
        self.timeout = timeout
        self.processes: list[subprocess.Popen] = []
        self.handles = []
        self.stopping = False
        self.env = dict(os.environ)
        self.env.update(
            {
                "AEGIS_DATABASE_PATH": str(self.database),
                "AEGIS_PLANNER_MODE": "rule",
                "AEGIS_AUTOMATION_ENABLED": "false",
                "AEGIS_SANDBOX_ENABLED": "true",
            }
        )
        self.logs = (
            self.runtime
            / "launcher-logs"
            / (datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}")
        )

    def check_stop(self) -> None:
        if self.stopping:
            raise Stopped

    def spawn(self, argv, cwd: Path, log_name: str, *, env=None) -> subprocess.Popen:
        self.check_stop()
        self.logs.mkdir(parents=True, exist_ok=True)
        handle = (self.logs / log_name).open("ab")
        self.handles.append(handle)
        child = subprocess.Popen(
            [str(item) for item in argv],
            cwd=cwd,
            env=self.env if env is None else env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes.append(child)
        return child

    def run_step(self, message: str, argv, cwd: Path, *, env=None) -> None:
        say(message)
        child = self.spawn(argv, cwd, "setup.log", env=env)
        while child.poll() is None:
            self.check_stop()
            time.sleep(0.1)
        self.check_stop()
        if child.returncode:
            raise LaunchError(
                f"{message}失败（退出码 {child.returncode}）；日志：{self.logs / 'setup.log'}"
            )
        # Reap preparation groups now; the service list contains only live groups.
        stop_processes([child], grace=0)
        self.processes.remove(child)

    def prepare(self) -> tuple[Path, str]:
        if sys.version_info < (3, 11):  # noqa: UP036 - this entry checks older host interpreters
            raise LaunchError("请先安装 Python 3.11+，再执行 bash start.sh。")
        node = shutil.which("node")
        if not node:
            raise LaunchError("请先安装 Node.js（包含 npm），再执行 bash start.sh。")
        package = json.loads((self.root / "fronted/frontend/package.json").read_text())
        version = subprocess.check_output([node, "--version"], text=True).strip()
        if not node_supported(version, package["engines"]["node"]):
            raise LaunchError(
                f"当前 Node.js {version} 不受支持；需要 {package['engines']['node']}。"
            )
        self.run_step("组装当前源码…", [sys.executable, "scripts/assemble.py"], self.root)
        uv = shutil.which("uv")
        if not uv:
            tools = self.runtime / ".launcher-tools/.venv"
            uv = str(tools / "bin/uv")
            if not Path(uv).is_file():
                self.run_step(
                    "准备本项目的 Python 工具…", [sys.executable, "-m", "venv", tools], self.root
                )
                self.run_step(
                    "安装本项目的 uv…",
                    [tools / "bin/python", "-m", "pip", "install", f"uv=={UV_VERSION}"],
                    self.root,
                )
        pnpm = shutil.which("pnpm")
        if not pnpm:
            tools = self.runtime / ".launcher-tools/node"
            pnpm = str(tools / "node_modules/.bin/pnpm")
            if not Path(pnpm).is_file():
                npm = shutil.which("npm")
                if not npm:
                    raise LaunchError("未找到 npm，无法准备 pnpm；请安装包含 npm 的 Node.js。")
                self.run_step(
                    "安装本项目的 pnpm…",
                    [
                        npm,
                        "install",
                        "--prefix",
                        tools,
                        "--no-package-lock",
                        "--no-audit",
                        "--no-fund",
                        f"pnpm@{PNPM_VERSION}",
                    ],
                    self.root,
                )
        self.run_step(
            "安装冻结的 Python 依赖…", [uv, "sync", "--frozen", "--dev"], self.runtime / "backend"
        )
        self.run_step(
            "安装冻结的前端依赖…",
            [pnpm, "install", "--frozen-lockfile", "--prod=false"],
            self.runtime / "frontend",
            env={**self.env, "CI": "true"},
        )
        python = self.runtime / "backend/.venv/bin/python"
        if not self.database.exists():
            self.run_step(
                "初始化独立模拟演示库…",
                [python, "-m", "aegisbank_api.demo_seed", "--db", self.database],
                self.runtime / "backend",
            )
        else:
            say(f"保留已有演示数据：{self.database}")
        return python, pnpm

    def wait_ready(self, children: list[subprocess.Popen]) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.check_stop()
            if any(child.poll() is not None for child in children):
                raise LaunchError(f"服务提前退出；请查看日志：{self.logs}")
            ready = request_json("http://127.0.0.1:8000/api/health/ready")
            proxy = request_json("http://127.0.0.1:5173/api/health/ready")
            audit = request_json("http://127.0.0.1:8000/api/audit/verify")
            if (
                isinstance(ready, dict)
                and ready.get("status") == "ready"
                and isinstance(proxy, dict)
                and proxy.get("status") == "ready"
                and isinstance(audit, dict)
                and audit.get("valid") is True
            ):
                return
            time.sleep(0.2)
        raise LaunchError(f"服务未在 {self.timeout:g} 秒内就绪；本次启动将关闭。日志：{self.logs}")

    def serve(self, python: Path, pnpm: str, no_browser: bool) -> None:
        say("启动后端与银行助手，检查服务就绪和审计链…")
        backend = self.spawn(
            [
                python,
                "-m",
                "uvicorn",
                "aegisbank_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            self.runtime / "backend",
            "backend.log",
        )
        frontend = self.spawn(
            [pnpm, "exec", "vite", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
            self.runtime / "frontend",
            "frontend.log",
        )
        self.wait_ready([backend, frontend])
        say(f"已就绪，银行助手：{UI_URL}")
        say("当前为离线规则 Planner + Mock Bank Core，无需模型密钥。")
        say(
            f"演示库：{self.database}\n日志：{self.logs}\n"
            "按 Ctrl+C 同时停止前后端，演示数据会保留。"
        )
        if not no_browser:
            browser = (
                shutil.which("powershell.exe")
                if os.environ.get("WSL_DISTRO_NAME")
                else shutil.which("xdg-open")
            )
            if browser:
                argv = (
                    [browser, "-NoProfile", "-Command", "Start-Process", UI_URL]
                    if browser.endswith(".exe")
                    else [browser, UI_URL]
                )
                try:
                    subprocess.run(
                        argv,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    say("浏览器未能自动打开，请访问上面的银行助手地址。")
        while True:
            self.check_stop()
            if backend.poll() is not None or frontend.poll() is not None:
                raise LaunchError(
                    f"一项服务已退出，正在停止本次启动的另一项服务。日志：{self.logs}"
                )
            time.sleep(0.2)

    def close(self) -> None:
        stop_processes(self.processes)
        for handle in self.handles:
            handle.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AegisBank 一键启动：组装、安装、保留数据并启动服务"
    )
    parser.add_argument("--no-browser", action="store_true", help="仅输出地址，不自动打开浏览器")
    parser.add_argument("--database", type=Path, help="使用指定的模拟数据库；不会重置已有数据")
    parser.add_argument(
        "--startup-timeout", type=float, default=90, help="服务就绪超时秒数，默认90"
    )
    args = parser.parse_args()
    if sys.platform != "linux":
        say("请在 Linux 或 WSL 中执行 bash start.sh；原生 Windows Python 不受支持。")
        return 1
    if not math.isfinite(args.startup_timeout) or not 0 < args.startup_timeout <= 300:
        parser.error("--startup-timeout 必须在 0 到 300 秒之间")
    launcher = Launcher(ROOT, args.database, args.startup_timeout)

    def stop(_signum, _frame):
        launcher.stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with launch_lock(launcher.runtime / ".launcher.lock"):
            try:
                check_ports()
                python, pnpm = launcher.prepare()
                launcher.serve(python, pnpm, args.no_browser)
            finally:
                launcher.close()
    except (Stopped, KeyboardInterrupt):
        say("已停止本次启动的服务，演示数据已保留。")
        return 0
    except (LaunchError, OSError, subprocess.SubprocessError) as error:
        say(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
