# ruff: noqa: E501
"""Export submission candidates from Markdown; Office PDF rendering is separate.

Optional dependencies: python-docx==1.2.0, python-pptx==1.0.2, pillow==13.0.0.
Use --pdf with ReportLab for PDFs from the same Markdown (not Word pagination).
This script never changes banking data or marks human reviews complete.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor as PptColor
from pptx.util import Inches as PptInches
from pptx.util import Pt as PptPt

ROOT = Path(__file__).resolve().parents[1]
NAVY = "10283F"
TEAL = "087E8B"
FONT = "Microsoft YaHei"


def plain(value: str) -> str:
    value = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return value.replace("**", "").replace("`", "").removeprefix("> ")


def architecture(output: Path) -> None:
    image = Image.new("RGB", (1800, 670), "#F2F6FA")
    draw = ImageDraw.Draw(image)
    fonts = [
        Path("/mnt/c/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    font_path = next((item for item in fonts if item.exists()), None)
    if font_path is None:
        raise RuntimeError("A CJK font is required; install Noto Sans CJK")
    title = ImageFont.truetype(str(font_path), 42)
    body = ImageFont.truetype(str(font_path), 27)
    draw.text((45, 22), "AegisBank · 计划、授权、执行与证据", font=title, fill=f"#{NAVY}")
    labels = [
        ("用户入口", "Web / IM 适配器"),
        ("语义与 Planner", "只提交候选计划"),
        ("Plan Compiler", "Schema / DAG / 哈希"),
        ("风险与统一网关", "只升不降 / 最小权限"),
        ("审计与业务回执", "哈希链 / 证据分层"),
        ("Mock Bank Core", "确定性模拟金融事实"),
        ("ToolExecutor", "SandboxGuard 守卫"),
        ("确认与 DAG 调度", "Envelope / MFA / 补偿"),
    ]
    for index, (name, detail) in enumerate(labels):
        col, row = index % 4, index // 4
        x, y = 45 + col * 440, 130 + row * 260
        draw.rounded_rectangle((x, y, x + 390, y + 170), 20, fill="white", outline=f"#{TEAL}", width=3)
        draw.text((x + 20, y + 32), name, font=body, fill=f"#{NAVY}")
        draw.text((x + 20, y + 95), detail, font=body, fill="#4A6072")
        if col < 3:
            arrow = "→" if row == 0 else "←"
            draw.text((x + 401, y + 60), arrow, font=title, fill=f"#{TEAL}")
    draw.text((1640, 316), "↓", font=title, fill=f"#{TEAL}")
    draw.text((45, 605), "所有写入与补偿经过同一网关、执行守卫及审计；模型不授权、不执行。", font=body, fill=f"#{NAVY}")
    image.save(output)


def export_word(source: Path, output: Path, image_path: Path) -> None:
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.65)
    section.left_margin = section.right_margin = Inches(0.7)
    for name in ["Normal", "Title", "Heading 1", "Heading 2", "Heading 3"]:
        style = document.styles[name]
        style.font.name = FONT
        style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        style.font.color.rgb = RGBColor.from_string(NAVY)
    document.styles["Normal"].font.size = Pt(10.5)
    document.styles["Normal"].paragraph_format.space_after = Pt(6)
    document.styles["Normal"].paragraph_format.line_spacing = 1.15
    section.header.paragraphs[0].text = "AegisBank  |  2026-10-31 自动收尾候选版"
    footer = section.footer.paragraphs[0]
    footer.text = "模拟银行原型 · 人工验收与正式提交另行确认  |  "
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    table = None
    in_code = False
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if line.startswith("!["):
            document.add_picture(str(image_path), width=Inches(6.6))
            continue
        if line.startswith("|"):
            cells = [plain(item.strip()) for item in line.strip("|").split("|")]
            if all(re.fullmatch(r"[-: ]+", item) for item in cells):
                continue
            if table is None:
                table = document.add_table(rows=0, cols=len(cells))
                table.style = "Light Shading Accent 1"
            row = table.add_row()
            for cell, value in zip(row.cells, cells, strict=True):
                cell.text = value
            continue
        table = None
        if not line.strip():
            continue
        heading = re.match(r"^(#{1,4}) (.*)", line)
        if heading:
            level = len(heading[1]) - 1
            document.add_heading(plain(heading[2]), level=level)
        else:
            paragraph = document.add_paragraph(plain(line))
            if in_code:
                for run in paragraph.runs:
                    run.font.size = Pt(9)
    document.save(output)


def export_pdf(source: Path, output: Path, image_path: Path) -> None:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Image as PdfImage
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    fonts = [Path("/mnt/c/Windows/Fonts/msyh.ttc"),
             Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")]
    font_path = next((path for path in fonts if path.exists()), None)
    if font_path is None:
        raise RuntimeError("PDF export requires a CJK TrueType font")
    pdfmetrics.registerFont(TTFont("AegisCJK", str(font_path)))
    body = ParagraphStyle("Body", fontName="AegisCJK", fontSize=10, leading=16,
                          wordWrap="CJK", spaceAfter=8, textColor=colors.HexColor(f"#{NAVY}"))
    heading = ParagraphStyle("Heading", parent=body, fontSize=15, leading=22,
                             spaceBefore=12, spaceAfter=9, keepWithNext=True)
    title = ParagraphStyle("Title", parent=heading, fontSize=22, leading=30)
    cell_style = ParagraphStyle("Cell", parent=body, fontSize=8, leading=12, spaceAfter=0)
    blocks = []
    rows = []

    def add_table():
        if not rows:
            return
        count = len(rows[0])
        table = Table(rows.copy(), colWidths=[505 / count] * count, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F1F4")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C4D2DE")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        blocks.append(table)
        rows.clear()

    for line in source.read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            cells = [item.strip() for item in line.strip("|").split("|")]
            if not all(re.fullmatch(r"[-: ]+", item) for item in cells):
                rows.append([Paragraph(escape(plain(item)), cell_style) for item in cells])
            continue
        add_table()
        if not line.strip() or line.startswith("```"):
            continue
        if line.startswith("!["):
            blocks.append(PdfImage(str(image_path), width=505, height=188))
            continue
        match = re.match(r"^(#{1,4}) (.*)", line)
        text = match[2] if match else line
        style = title if match and len(match[1]) == 1 else heading if match else body
        blocks.append(Paragraph(escape(plain(text)), style))
    add_table()

    def footer(canvas, document):
        canvas.setFont("AegisCJK", 8)
        canvas.setFillColor(colors.HexColor("#526579"))
        canvas.drawString(45, 24, f"AegisBank · 2026-10-31 候选版 · 同源 PDF / ReportLab  |  {document.page}")

    document = SimpleDocTemplate(str(output), pagesize=A4, leftMargin=45, rightMargin=45,
                                 topMargin=40, bottomMargin=42)
    document.build(blocks, onFirstPage=footer, onLaterPages=footer)


def textbox(slide, x, y, width, height, text, size=22, color=NAVY, bold=False):
    shape = slide.shapes.add_textbox(PptInches(x), PptInches(y), PptInches(width), PptInches(height))
    frame = shape.text_frame
    frame.word_wrap = True
    for index, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = line
        paragraph.space_after = PptPt(14)
        for run in paragraph.runs:
            run.font.name = FONT
            run.font.size = PptPt(size)
            run.font.bold = bold
            run.font.color.rgb = PptColor.from_string(color)
    return shape


def export_ppt(output: Path, image_path: Path) -> None:
    presentation = Presentation()
    presentation.slide_width = PptInches(13.333)
    presentation.slide_height = PptInches(7.5)
    slides = [
        ("AegisBank", "用自然语言办理模拟银行业务\n计划可核对 · 授权不继承 · 结果有证据", "可信银行 AI 智能体原型；所有金融数据与资金变动均为模拟。"),
        ("比赛目标与交付范围", "六类代表场景：转账 / 账单 / 理财 / 卡片 / 订阅 / 跨场景\n绿黄红分级、审计、熔断、沙箱、有序 DAG 与人工接管\n自然语言能力有界；歧义时澄清，禁止猜测执行", "先演示三个核心场景，其余复用六场景自动检查证据。"),
        ("一条受控执行链", "architecture", "Planner 只生成候选；编译、授权、风险、执行与证据由确定性代码控制。"),
        ("绿 / 黄 / 红：风险只升不降", "绿色：余额、账单等查询自动执行\n黄色：小额转账（日累计含本次≤1000元）明确确认\n红色：累计>1000元、挂失、理财申购等确认＋演示MFA\n模型不能降低工具基线风险", "演示 OTP 和模拟生物识别仅证明流程，不能视为生产强认证。"),
        ("补槽与金额修订：确认只属于当前草稿", "给妈妈转钱 → 五百 → 改成三百\n新计划 / 新 nonce / 重新评级 / 重新确认\n旧确认409；最终只有一笔300元模拟转账\n最近金额与收款人从本人已完成流水回读", "展示真实自动联调截图，并说明 CDP 自动交互不是独立人工验收。"),
        ("执行前复核与重试安全", "ActionEnvelope：计划、参数、风险、权限、nonce、有效期\nIdempotency-Key：重试返回首次结果，避免重复扣款\n版本冲突、过期、撤权阻断；服务未ready时禁止写入\n结果UNKNOWN先核对，不盲目重试", "同一会话仅有一个活动草稿；历史查询按演示用户隔离。"),
        ("DAG、中断、补偿与人工接管", "账单分析 → 引用异常订阅 → 取消订阅\n步骤间暂停 / 恢复，已完成节点不重复执行\n可补偿失败逆序回退，再做风险与权限复核\n不可逆或结果未知：人工处理，并写入审计", "预置有界 DAG 不是自由组合；不可逆操作不能承诺自动回滚。"),
        ("安全机制与可追溯证据", "注入整条拒绝；真实结果只来自 Mock Bank Core\n按用户熔断，operator 解锁并审计\nToolExecutor + SandboxGuard：网络、超时、体积、白名单\nSHA-256 审计链与来源分层；不是独立存证", "沙箱是进程内逻辑约束；线程超时不等于 OS 强制终止。"),
        ("离线评测：公开失败与适用边界", "复用冻结语料与表达家族隔离，保留全部失败样本\n开发集与已查看的保留集分别报告，不混为未见成绩\n安全反例检查业务库变化；规则与模型成绩分开\n人工金标复核pending；真实模型按用户决定暂缓", "具体本轮数字见收尾报告及JSON原始证据；95%不作为已取得成绩。"),
        ("自动验收与复现", "后端 / 前端 / 组装器 / 六场景 / API契约 / lint / build\n真实桌面与390px视口：Chromium → Vite → FastAPI → 新SQLite\n独立库种子重置、readiness与审计检查\n干净源码归档复现，记录版本与SHA-256", "自动化通过只覆盖已知用例，不能替代人工手机、键盘和读屏验收。"),
        ("当前边界与人工剩余", "全部数据模拟；无生产身份、真实MFA、真实IM、OS隔离\nU3个性化 / U5通用组合与条件规划未实施\n人工：金标裁决、独立体验、录屏及正式提交\n答辩≤10分钟、视频≤5分钟须实际计时", "明确哪些已自动验证、哪些仍需人工签署，不将候选包描述为已提交。"),
        ("演示与交付入口", "账单绿色查询 → 转账补槽与修订 → 卡片红色演示MFA\n再展开DAG、注入拒绝与审计证据\nREADME / 部署 / 测试 / 技术文档 / 安全自评\ngithub.com/0xChainAegis/aegisbank", "感谢评委；演示失败按部署说明恢复独立模拟库，UNKNOWN不自动重试。"),
    ]
    for index, (title, body, notes) in enumerate(slides, 1):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = PptColor.from_string("F5F8FB")
        textbox(slide, 0.65, 0.35, 11.9, 0.45, "AEGISBANK  /  2026-10-31  /  模拟银行原型", 14, TEAL, True)
        textbox(slide, 0.65, 1.0, 12, 1.0, title, 32, NAVY, True)
        if body == "architecture":
            slide.shapes.add_picture(str(image_path), PptInches(0.65), PptInches(2.1), width=PptInches(12.0))
        else:
            textbox(slide, 0.8, 2.3, 11.75, 4.1, body, 23)
        textbox(slide, 0.7, 7.0, 11.8, 0.3, f"0xChainAegis  ·  候选材料，人工验收另列  |  {index:02d} / {len(slides):02d}", 11, "526579")
        slide.notes_slide.notes_text_frame.text = f"建议讲解40秒（需人工实际计时）。{notes}"
    presentation.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "deliverables/current")
    parser.add_argument("--pdf", action="store_true", help="Export same-source PDFs using ReportLab")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    diagram = args.output / "architecture.png"
    architecture(diagram)
    for source, name in [
        ("02-技术文档.md", "02-AegisBank-技术文档.docx"),
        ("05-安全自评报告.md", "04-AegisBank-安全自评报告.docx"),
    ]:
        export_word(ROOT / "deliverables" / source, args.output / name, diagram)
        if args.pdf:
            export_pdf(ROOT / "deliverables" / source, args.output / Path(name).with_suffix(".pdf"), diagram)
    export_ppt(args.output / "03-AegisBank-答辩材料.pptx", diagram)
    print(f"Exported Word/PPT candidates to {args.output}; PDF/rendering and human sign-off remain separate.")


if __name__ == "__main__":
    main()
