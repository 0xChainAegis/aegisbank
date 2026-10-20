#!/usr/bin/env python3
"""Render the AegisBank architecture diagram to a standalone SVG."""

from __future__ import annotations

from html import escape
from pathlib import Path

WIDTH, HEIGHT = 1960, 1580
OUT = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "aegisbank-architecture.svg"

BG = "#f4f6f0"
PANEL = "#fbfcf8"
INK = "#172525"
MUTED = "#6f7b76"
LINE = "#d9dfd6"
TEAL = "#0f5c53"
TEAL_SOFT = "#e5f0eb"
AMBER = "#a96713"
AMBER_SOFT = "#fbf4e6"
RED = "#a6382e"
RED_SOFT = "#f7e5e1"
GREEN = "#1d7153"
GREEN_SOFT = "#e4f0e9"
DATA = "#eef1eb"
EXTERNAL = "#f1f2f5"
EXTERNAL_LINE = "#777f8c"

parts: list[str] = []


def add(value: str) -> None:
    parts.append(value)


def text(x: float, y: float, value: str, size: int = 12, weight: int = 400,
         fill: str = INK, anchor: str = "start", mono: bool = False,
         opacity: float = 1.0) -> None:
    family = "'Cascadia Mono','SFMono-Regular',Consolas,monospace" if mono else "'Segoe UI','Microsoft YaHei',sans-serif"
    add(
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" opacity="{opacity}">'
        f"{escape(value)}</text>"
    )


def multiline(x: float, y: float, lines: list[str], size: int = 10, fill: str = MUTED,
              weight: int = 400, line_height: int = 14) -> None:
    for index, line in enumerate(lines):
        text(x, y + index * line_height, line, size=size, fill=fill, weight=weight)


def box(x: float, y: float, w: float, h: float, title: str, lines: list[str],
        *, fill: str = TEAL_SOFT, stroke: str = TEAL, dashed: bool = False,
        tag: str | None = None) -> None:
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    add(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="13" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="1.4"{dash}/>'
    )
    text(x + 14, y + 23, title, size=13, weight=650, fill=INK)
    multiline(x + 14, y + 42, lines)
    if tag:
        tag_w = max(44, len(tag) * 6.5 + 12)
        add(
            f'<rect x="{x + w - tag_w - 10}" y="{y + 10}" width="{tag_w}" height="18" '
            f'rx="9" fill="rgba(255,255,255,0.7)" stroke="{stroke}" stroke-width="0.8"/>'
        )
        text(x + w - tag_w / 2 - 10, y + 23, tag, size=8, weight=700, fill=stroke, anchor="middle", mono=True)


def layer(x: float, y: float, w: float, h: float, title: str, subtitle: str,
          color: str, dashed: bool = False) -> None:
    dash = ' stroke-dasharray="9 7"' if dashed else ""
    add(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22" fill="{PANEL}" '
        f'stroke="{color}" stroke-opacity="0.35" stroke-width="1.4"{dash}/>'
    )
    add(f'<rect x="{x}" y="{y}" width="7" height="{h}" rx="3.5" fill="{color}" opacity="0.85"/>')
    text(x + 24, y + 27, title, size=13, weight=750, fill=color)
    text(x + 24, y + 45, subtitle, size=9, fill=MUTED)


def arrow(points: list[tuple[float, float]], color: str = TEAL, dashed: bool = False,
          label: str | None = None, label_pos: tuple[float, float] | None = None) -> None:
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash} marker-end="url(#arrow-{color[1:]})"/>')
    if label and label_pos:
        lx, ly = label_pos
        add(f'<circle cx="{lx}" cy="{ly}" r="10" fill="{BG}" stroke="{color}" stroke-width="1.5"/>')
        text(lx, ly + 4, label, size=9, weight=700, fill=color, anchor="middle", mono=True)


def external_box(x: float, y: float, w: float, h: float, title: str, lines: list[str],
                 dashed: bool = True) -> None:
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    add(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{EXTERNAL}" '
        f'stroke="{EXTERNAL_LINE}" stroke-width="1.3"{dash}/>'
    )
    text(x + 15, y + 24, title, size=13, weight=650, fill="#30394a")
    multiline(x + 15, y + 44, lines, size=10, fill="#687181")


# Canvas and defs
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">')
add('<defs>')
add('<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#163b35" flood-opacity="0.07"/></filter>')
add(f'<pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M 32 0 L 0 0 0 32" fill="none" stroke="{TEAL}" stroke-opacity="0.035"/></pattern>')
for color in (TEAL, AMBER, RED, EXTERNAL_LINE):
    add(f'<marker id="arrow-{color[1:]}" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="{color}"/></marker>')
add('</defs>')
add(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>')
add(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#grid)"/>')

# Header
text(54, 56, "AegisBank", size=30, weight=800, fill=INK)
text(215, 56, "可信银行智能体 · 完整目标架构", size=20, weight=600, fill=TEAL)
text(54, 83, "LLM proposes · deterministic compiler validates · trust gateway authorizes · tool runtime executes · audit evidence records", size=11, fill=MUTED, mono=True)

# Legend
legend_x = 1490
add(f'<rect x="{legend_x}" y="28" width="415" height="58" rx="13" fill="{PANEL}" stroke="{LINE}"/>')
for idx, (label, fill, stroke, dashed) in enumerate([
    ("已落地", TEAL_SOFT, TEAL, False),
    ("规划中", AMBER_SOFT, AMBER, True),
    ("数据/证据", DATA, MUTED, False),
]):
    x = legend_x + 18 + idx * 132
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    add(f'<rect x="{x}" y="43" width="14" height="14" rx="4" fill="{fill}" stroke="{stroke}"{dash}/>')
    text(x + 21, 55, label, size=10, fill=INK)

# Layers
layer(50, 112, 1400, 168, "01 · 交互层", "用户只通过受控接口与 Agent 协作", TEAL)
interaction = [
    ("对话与任务输入", ["自然语言 / 快捷任务", "展示结构化计划"]),
    ("计划预览", ["步骤、参数、依赖", "风险与假设可视化"]),
    ("分级确认", ["黄色轻量确认", "红色二次校验"]),
    ("权限控制台", ["按工具授权", "一键撤回"]),
    ("审计与证据", ["全量操作时间线", "哈希链完整性校验"]),
]
for index, (title, lines) in enumerate(interaction):
    box(76 + index * 274, 170, 252, 78, title, lines)

layer(50, 310, 1400, 270, "02 · 接入与编排层", "Planner 只产出结构化计划，不能直接执行工具", TEAL)
api_boxes = [
    (76, "API Gateway", ["REST + OpenAPI", "统一输入契约"], 160),
    (250, "Planner Interface", ["可插拔接口", "Rule / LLM / Auto"], 180),
    (444, "Planner Adapters", ["RuleBasedPlanner", "OpenAI-compatible LLM"], 260),
    (718, "Plan Compiler", ["Schema / Tool / Cycle", "DAG 拓扑 + plan hash"], 220),
    (952, "DAG Scheduler", ["拓扑排序执行", "暂停 / 恢复 / 超时"], 200),
    (1166, "Confirmation SM", ["pending → approved", "rejected / expired / blocked"], 254),
]
for x, title, lines, width in api_boxes:
    box(x, 374, width, 92, title, lines, tag="CORE")

text(76, 500, "Planner 输出契约", size=10, weight=700, fill=TEAL, mono=True)
box(76, 512, 1240, 48, "ExecutionPlan/v1", ["intent · steps[] · arguments · depends_on · confidence · assumptions · needs_clarification · clarification"], fill="#f6f9f5", stroke=LINE)

layer(50, 610, 1400, 286, "03 · 信任边界", "任何工具调用都必须穿过统一网关；默认拒绝，高风险升级", RED, dashed=True)
trust_boxes = [
    (76, "Identity & Context", ["用户 / 会话 / 设备", "上下文最小化"], 210, TEAL_SOFT, TEAL, False),
    (301, "Permission Gateway", ["capability + scope", "撤回立即生效"], 220, TEAL_SOFT, TEAL, False),
    (536, "Risk Engine", ["GREEN / YELLOW / RED", "动态风险升级"], 200, TEAL_SOFT, TEAL, False),
    (751, "Injection Guard", ["Prompt Injection", "越权 / 绕过检测"], 205, TEAL_SOFT, TEAL, False),
    (971, "Action Envelope", ["plan hash + nonce", "expiry + consent"], 205, TEAL_SOFT, TEAL, False),
    (1191, "Policy Decision", ["allow / confirm", "reauth / deny"], 235, TEAL_SOFT, TEAL, False),
]
for x, title, lines, width, fill, stroke, dashed in trust_boxes:
    box(x, 677, width, 86, title, lines, fill=fill, stroke=stroke, dashed=dashed, tag="P0" if title != "Action Envelope" else "P1")

box(76, 781, 420, 78, "Fact / Intent Consistency", ["计划参数与原始意图一致性", "Phase 2: 事实校验 + 二次模型审查"], fill=AMBER_SOFT, stroke=AMBER, dashed=True, tag="P2")
box(516, 781, 420, 78, "Anomaly Circuit Breaker", ["金额 / 频次 / 设备 / 收款方异常", "熔断、降级与人工复核"], fill=AMBER_SOFT, stroke=AMBER, dashed=True, tag="P2")
box(956, 781, 470, 78, "Audit Emitter", ["每次决策同步产生结构化证据", "plan_hash + action_hash + decision reason"], fill=GREEN_SOFT, stroke=GREEN, tag="P0")

layer(50, 930, 1400, 228, "04 · 工具运行时", "工具是独立插件；Manifest 必须声明风险、权限和输入输出 Schema", TEAL)
tool_boxes = [
    (76, "Tool SDK / Registry", ["工具清单与 Manifest", "参数校验 / 幂等键"], 220),
    (311, "query_bill", ["GREEN · billing:read", "只读账单查询"], 190),
    (516, "adjust_repayment_date", ["YELLOW · card:manage", "账户设置变更"], 220),
    (751, "transfer", ["RED · transfer:execute", "资金变动"], 190),
    (956, "Sandbox / Adapter", ["timeout / idempotency", "Mock → Banking API"], 220),
    (1191, "Tool Result Normalizer", ["统一输出 Schema", "结果进入审计链"], 235),
]
for x, title, lines, width in tool_boxes:
    stroke = GREEN if title == "query_bill" else AMBER if title == "adjust_repayment_date" else RED if title == "transfer" else TEAL
    fill = GREEN_SOFT if title == "query_bill" else AMBER_SOFT if title == "adjust_repayment_date" else RED_SOFT if title == "transfer" else TEAL_SOFT
    box(x, 998, width, 86, title, lines, fill=fill, stroke=stroke)

layer(50, 1192, 1400, 210, "05 · 数据与证据层", "MVP 使用 SQLite；生产迁移到银行合规存储与 WORM 审计", MUTED)
data_boxes = [
    (76, "Permission Store", ["user × tool × grant", "updated_at"], 220, DATA, MUTED, False),
    (311, "Pending Actions", ["DAG + plan snapshot", "TTL / status"], 220, DATA, MUTED, False),
    (546, "Audit Hash Chain", ["SHA-256 prev_hash", "entry_hash + 6 fields"], 220, DATA, MUTED, False),
    (781, "Policy / Planner Config", ["mode / model / rule set", "无密钥入库"], 220, DATA, MUTED, False),
    (1016, "WORM / Signed Vault", ["Ed25519 / KMS", "合规只追加存储"], 250, AMBER_SOFT, AMBER, True),
    (1281, "Observability", ["trace / metrics / alerts", "OpenTelemetry -> APM"], 145, AMBER_SOFT, AMBER, True),
]
for x, title, lines, width, fill, stroke, dashed in data_boxes:
    box(x, 1255, width, 86, title, lines, fill=fill, stroke=stroke, dashed=dashed)

# External systems column
layer(1480, 310, 425, 1092, "06 · 外部系统", "通过合规适配器接入；MVP 全部使用 Mock", EXTERNAL_LINE, dashed=True)
externals = [
    (370, "LLM Provider", ["OpenAI-compatible endpoint", "私有化 / 国内模型可替换"]),
    (510, "Identity Provider", ["OIDC / MFA / 设备指纹", "生产替换 demo-user"]),
    (650, "Core Banking Sandbox", ["账户 / 账单 / 转账 API", "Phase 2 接入"]),
    (790, "KMS / Audit Vault", ["密钥管理 + WORM", "审计签名与合规留存"]),
    (930, "Observability Stack", ["OpenTelemetry / Prometheus", "Grafana / 告警"]),
    (1070, "Policy Engine", ["OPA / Cedar", "Phase 2 策略外置"]),
]
for y, title, lines in externals:
    external_box(1510, y, 365, 104, title, lines, dashed=title not in {"LLM Provider"})

# Main flow arrows
arrow([(210, 285), (210, 374)], label="1", label_pos=(210, 330))
arrow([(236, 420), (250, 420)], label=None)
arrow([(430, 420), (444, 420)], label="2", label_pos=(437, 408))
arrow([(624, 420), (718, 420)], label="3", label_pos=(671, 408))
arrow([(938, 420), (952, 420)], label="4", label_pos=(945, 408))
arrow([(1152, 420), (1166, 420)], label=None)
arrow([(1010, 466), (1010, 677)], label="5", label_pos=(1010, 568))
arrow([(870, 763), (870, 998)], label="6", label_pos=(870, 880))
arrow([(870, 1084), (870, 1255)], label="7", label_pos=(870, 1170))
arrow([(1166, 466), (1300, 677)], color=TEAL, label="pause", label_pos=(1242, 558))
arrow([(1060, 859), (1060, 998)], color=GREEN)
arrow([(1200, 1084), (1200, 1255)], color=GREEN)

# External integrations
arrow([(704, 385), (1510, 422)], color=AMBER, dashed=True, label="model", label_pos=(1110, 394))
arrow([(411, 677), (1510, 562)], color=AMBER, dashed=True, label="identity", label_pos=(955, 604))
arrow([(1080, 1084), (1510, 702)], color=AMBER, dashed=True, label="banking", label_pos=(1320, 900))
arrow([(1110, 1255), (1510, 842)], color=AMBER, dashed=True, label="audit", label_pos=(1330, 1052))
arrow([(1396, 420), (1510, 1080)], color=AMBER, dashed=True, label="policy", label_pos=(1462, 810))

# Footer
add(f'<rect x="50" y="1440" width="1855" height="98" rx="16" fill="{INK}"/>')
text(76, 1473, "TRUST INVARIANTS", size=10, weight=700, fill="#9ed9c8", mono=True)
text(76, 1498, "1. LLM 不直接调用工具   2. 所有调用经过权限网关   3. 确认绑定精确动作哈希   4. 执行后必有可验证审计证据", size=14, weight=600, fill="#f4f7f2")
text(76, 1522, "5. 高风险默认暂停   6. 计划必须通过确定性 Schema + DAG 编译   7. 生产不存储全量金融数据，不引入 P2P / 去中心化身份", size=11, fill="#b9c9c1")

add("</svg>")
OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
print(f"rendered {OUT}")
