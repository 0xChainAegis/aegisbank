#!/usr/bin/env python3
"""Record the current six-module source bytes, with explicit LF normalization.

No third-party dependencies are needed. Git discovers tracked and unignored new
files; source archives without .git use the same assembler allowlist to scan.
The retained source_commit is provenance, never the final integration commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from assemble import _plan

ROOT = Path(__file__).resolve().parent.parent
GROUPS = ("fronted", "backend", "agent", "NLP", "plans", "skills")
BASELINE = "654c986ffcac5aa2b5e42baf8bbfa144c6b6eaec"
FRONTEND_FIX = "49201c2846a114f32ec458b295a788548be1c0ee"
REVIEW = "e2fd54424e07d8a2e45f352509f7f306b879f27c"
DESCRIPTIONS = {
    "fronted": "React 控制台、API 类型与请求、确认和恢复交互、样式与前端回归测试。",
    "backend": "FastAPI 入口、配置、SQLite 与 Mock Bank Core、依赖、运行脚本和后端测试。",
    "agent": "权限网关、动态风险、调度、执行守卫、MFA、补偿、熔断和审计。",
    "NLP": "金额规范化、规则与可选 LLM Planner、P0 语义防线和受限澄清。",
    "plans": "ExecutionPlan 契约、确定性 Plan Compiler 和历史架构规划文档。",
    "skills": "工具注册、银行业务工具、场景发现及六场景业务模块。",
}


def source_paths() -> list[tuple[str, str, str, Path]]:
    # Use the assembler's read-only plan so discovery, allowlists, collision and
    # symlink checks have a single implementation. This does not write .runtime.
    selected = []
    for runtime_path, record in _plan(ROOT).items():
        for name in record.sources:
            group, relative = name.split("/", 1)
            selected.append((group, relative, runtime_path, ROOT / name))
    return sorted(selected, key=lambda item: (GROUPS.index(item[0]), item[1]))


def normalize_text_sources(sources: list[tuple[str, str, str, Path]]) -> int:
    changed = 0
    for group, relative, _runtime, source in sources:
        raw = source.read_bytes()
        if b"\r\n" not in raw or b"\0" in raw:
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        source.write_bytes(raw.replace(b"\r\n", b"\n"))
        print(f"NORMALIZE LF {group}/{relative}")
        changed += 1
    return changed


def manifest(group: str, sources: list[tuple[str, str, str, Path]]) -> dict:
    entries = []
    for selected_group, relative, runtime_path, source in sources:
        if selected_group != group:
            continue
        raw = source.read_bytes()
        entries.append({"group": group, "path": relative, "runtime_path": runtime_path,
                        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    payload = {
        "schema_version": "aegisbank-package-manifest/v2",
        "source_commit": BASELINE,
        "source_commit_role": "Original upstream export baseline; not the integration commit.",
        "group": group,
        "integration_note": (
            "Six categorized modules remain the source of truth. Tests and validation scripts "
            "were restored, and frontend fixes were integrated; these are not unchanged exports."
        ),
        "current_hashes": {
            "meaning": "bytes and sha256 describe current allowlisted working-tree source files.",
            "discovery": "Git tracked/unignored source; without .git, the same safe archive allowlist. Git errors never trigger archive fallback.",
            "path_base": f"{group}/",
            "runtime_mapping": "Remove the module prefix; backend/.env.example is the sole special mapping.",
            "excludes": "_PACKAGE, hidden files, dependency/cache/build output, backend/data, runtime databases and lock caches",
            "license_metadata": "The unchanged MIT LICENSE is retained beside this manifest, outside runtime source hashes.",
        },
        "files": entries,
    }
    if group == "fronted":
        payload["frontend_fix_commit"] = FRONTEND_FIX
        payload["frontend_review_commit"] = REVIEW
    return payload


def package_readme(group: str, payload: dict) -> str:
    note = (
        f"前端修复来自 `{FRONTEND_FIX}`，组织协作与可复现性评审版本为 `{REVIEW}`。"
        if group == "fronted" else
        "本次整合恢复或更新必要的验证与说明材料；业务执行链没有新增旁路。"
    )
    files = "\n".join(f"- `{item['path']}`" for item in payload["files"])
    return f"""# {group} 源码包说明

{DESCRIPTIONS[group]}

六个分类目录保留为团队源码修改入口。它们相互依赖，不能作为六个独立应用分别启动；在仓库根目录运行 `python3 scripts/assemble.py`，即可组装到 `.runtime/` 后按[根 README](../../../README.md)启动和验证。生成目录不是第二份维护源码，不应手工修改或提交。

## 来源和当前状态

原始导出基线为 `{BASELINE}`。同目录 `MANIFEST.json` 中的 `source_commit` 仅表示该历史起点，不是整合最终提交，也不表示当前文件全部原样复制。

{note}

当前运行白名单包含 **{len(payload['files'])} 个文件**，`bytes` 和 `sha256` 记录这些文件的当前字节；`path` 相对本分类目录，`runtime_path` 表示组装后的路径。后端测试、前端测试和验证脚本已经按职责恢复，不再采用最初资料包的“排除全部测试”口径。

根 `docs/` 和 `deliverables/` 是团队阅读、验收及比赛材料入口；包内旧文档保留背景，不单独维护新主线。旧 `plans/README.md` 和 `plans/AGENTS.md` 属历史来源说明，不进入运行组装白名单。`_PACKAGE` 为来源、许可与校验元数据，不复制进 `.runtime/`。

## 更新和核验

在仓库根目录执行 `python3 scripts/update_manifests.py` 更新六包清单，或加 `--check` 仅核验。需要与仓库 LF 规则对齐时，显式加 `--normalize-line-endings`，脚本会记录行尾格式处理；默认更新与检查不会隐式改写源码。

Git checkout 中扫描已跟踪或未被忽略的新文件；没有 `.git` 的源码归档使用同一白名单安全扫描。已有 Git checkout 中的 Git 命令错误会停止处理，不会静默改用归档扫描。真实 `.env`、本地数据、依赖、缓存和构建产物不进入清单。MIT 许可及原作者声明保留在同目录 `LICENSE`。

整合原因、历史与修复映射见[整合记录](../../../docs/INTEGRATION-2026-10-26.md)。根 `文件清单.csv` 和 `排除清单.csv` 是最初导出的历史快照，不是当前文件或测试状态的权威清单。

## 当前运行源文件

{files}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check without writing")
    parser.add_argument("--normalize-line-endings", action="store_true",
                        help="explicitly normalize UTF-8 text source CRLF to LF before recording")
    args = parser.parse_args()
    if args.check and args.normalize_line_endings:
        parser.error("--check cannot be combined with --normalize-line-endings")
    sources = source_paths()
    if args.normalize_line_endings:
        print(f"Normalized {normalize_text_sources(sources)} text source files to LF.")
    failures = []
    for group in GROUPS:
        payload = manifest(group, sources)
        if not payload["files"]:
            raise ValueError(f"No allowlisted source found for {group}; refusing empty manifest")
        directory = ROOT / group / "_PACKAGE" / group
        if directory.is_symlink() or not directory.resolve().is_relative_to(ROOT / group):
            raise ValueError(f"Unsafe metadata directory: {directory}")
        outputs = {
            directory / "MANIFEST.json": json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            directory / "README.md": package_readme(group, payload),
        }
        for path, content in outputs.items():
            expected = content.encode("utf-8")
            if args.check:
                if not path.exists() or path.read_bytes() != expected:
                    failures.append(path.relative_to(ROOT).as_posix())
            else:
                directory.mkdir(parents=True, exist_ok=True)
                path.write_bytes(expected)
        print(f"{group}: {len(payload['files'])} source files")
    if failures:
        print("Manifest metadata needs updating: " + ", ".join(failures))
        return 1
    print("Manifest check passed." if args.check else "Updated all six package manifests and READMEs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
