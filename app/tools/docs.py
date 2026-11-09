"""文档工具：模板校验、占位符填充、出行计划卡生成。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from ..config import OUTPUT_DIR, TEMPLATE_DIR
from ..templates_meta import TEMPLATES, normalize_fields
from ..utils import now_local, safe_filename, stamp, today_str
from .base import ToolContext, ToolError, ToolParam, ToolSpec, ToolRegistry


def _set_cell_shading(cell, color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)


def _set_cell_text(cell, text: str, bold: bool = False, size: int = 10.5) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run(str(text))
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def _set_page_number_footer(section, text: str) -> None:
    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run(text)
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x7B, 0x96, 0xAA)
    run.font.name = "宋体"


def _replace_in_paragraph(paragraph, mapping: dict[str, str]) -> int:
    """优先按 run 替换以保留格式；跨 run 占位符再整体回填。"""
    replaced = 0
    for run in paragraph.runs:
        original = run.text
        for key, value in mapping.items():
            token = "{{" + key + "}}"
            if token in run.text:
                run.text = run.text.replace(token, str(value))
                replaced += 1
        if run.text == original:
            continue
    joined = "".join(run.text for run in paragraph.runs)
    if "{{" in joined and "}}" in joined:
        new_text = joined
        for key, value in mapping.items():
            token = "{{" + key + "}}"
            if token in new_text:
                new_text = new_text.replace(token, str(value))
                replaced += 1
        if new_text != joined and paragraph.runs:
            paragraph.runs[0].text = new_text
            for run in paragraph.runs[1:]:
                run.text = ""
    return replaced


def _iter_paragraphs(doc):
    for paragraph in doc.paragraphs:
        yield paragraph
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    yield paragraph
                for nested in cell.tables:
                    for row2 in nested.rows:
                        for cell2 in row2.cells:
                            for paragraph in cell2.paragraphs:
                                yield paragraph
    for section in doc.sections:
        for part in (section.header, section.footer):
            for paragraph in part.paragraphs:
                yield paragraph
            for table in part.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            yield paragraph


def _all_text(doc) -> str:
    return "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )


def _artifact(path: Path, display_name: str) -> dict[str, Any]:
    return {
        "type": "docx",
        "name": display_name,
        "filename": path.name,
        "path": str(path),
        "url": "/files/" + path.name,
        "size": path.stat().st_size,
        "created_at": now_local().isoformat(timespec="seconds"),
    }


def list_templates(ctx: ToolContext) -> dict[str, Any]:
    rows = []
    for key, value in TEMPLATES.items():
        exists = (TEMPLATE_DIR / value["filename"]).exists()
        rows.append(
            {
                "id": key,
                "name": value["name"],
                "description": value["description"],
                "required": value["required"],
                "ready": exists,
            }
        )
    return {
        "templates": rows,
        "_summary": "可用模板：" + "、".join(row["name"] for row in rows),
    }


def validate(ctx: ToolContext, template_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    if template_id not in TEMPLATES:
        raise ToolError("TEMPLATE_NOT_FOUND", f"没有名为 {template_id} 的模板。")
    meta = TEMPLATES[template_id]
    normalized = normalize_fields(fields or {})
    missing = [name for name in meta["required"] if not normalized.get(name)]
    unknown = [name for name in normalized if name not in meta["fields"] and name != "申请日期"]
    if template_id == "leave_request" and normalized.get("开始时间") and normalized.get("结束时间"):
        try:
            start = _parse_dt(normalized["开始时间"])
            end = _parse_dt(normalized["结束时间"])
            if end <= start:
                raise ToolError("INVALID_TIME_RANGE", "结束时间必须晚于开始时间。")
            if not normalized.get("请假天数"):
                hours = (end - start).total_seconds() / 3600
                # 按 8 小时工作日折算，最少 0.5 天
                days = max(0.5, round(hours / 8 * 2) / 2)
                normalized["请假天数"] = (
                    str(int(days)) if float(days).is_integer() else f"{days:g}"
                )
        except ValueError as exc:
            raise ToolError(
                "INVALID_TIME_FORMAT",
                "时间格式无法识别，请用 2026-11-12 08:00 这样的格式。",
            ) from exc
    return {
        "template_id": template_id,
        "template_name": meta["name"],
        "fields": normalized,
        "missing": missing,
        "unknown": unknown,
        "complete": not missing,
        "_summary": (
            f"{meta['name']}字段完整。"
            if not missing
            else f"{meta['name']}还缺 {len(missing)} 项：" + "、".join(missing)
        ),
    }


def _parse_dt(value: str):
    from datetime import datetime

    value = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(value)


def fill(ctx: ToolContext, template_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    check = validate(ctx, template_id, fields)
    if check["missing"]:
        raise ToolError(
            "MISSING_FIELDS",
            "还缺少必填字段：" + "、".join(check["missing"]),
            details={"missing": check["missing"], "fields": check["fields"]},
        )
    meta = TEMPLATES[template_id]
    template_path = TEMPLATE_DIR / meta["filename"]
    if not template_path.exists():
        raise ToolError("TEMPLATE_FILE_MISSING", f"模板文件不存在：{meta['filename']}")

    normalized = check["fields"]
    normalized.setdefault("申请日期", today_str())
    normalized.setdefault("备注", "无")
    # 未填写的可选字段统一显示为“—”，避免模板占位符残留
    for name in meta["fields"]:
        normalized.setdefault(name, "—")

    doc = Document(str(template_path))
    replaced = 0
    for paragraph in _iter_paragraphs(doc):
        replaced += _replace_in_paragraph(paragraph, normalized)

    # 在页脚补一条生成说明
    for section in doc.sections:
        footer_text = f"由晴雨校园助手生成 · {now_local().strftime('%Y-%m-%d %H:%M')} · 请核对后提交"
        _set_page_number_footer(section, footer_text)

    remaining = re.findall(r"\{\{[^}]+\}\}", _all_text(doc))
    if remaining:
        raise ToolError(
            "TEMPLATE_RENDER_ERROR",
            "模板中仍有未替换的占位符：" + "、".join(sorted(set(remaining))),
        )

    display = f"{meta['name']}_{normalized.get('姓名', '学生')}"
    filename = safe_filename(f"{display}_{stamp()}.docx")
    path = OUTPUT_DIR / filename
    doc.save(str(path))

    artifact = _artifact(path, display)
    artifact["fields"] = normalized
    artifact["template_id"] = template_id
    ctx.artifacts.append(artifact)
    written = sum(1 for value in normalized.values() if value not in {"", "—"})
    return {
        "artifact": artifact,
        "fields": normalized,
        "replaced_count": replaced,
        "_summary": f"已生成《{display}》，共写入 {written} 个字段。",
    }


def plan_card(
    ctx: ToolContext,
    city: str,
    date_label: str,
    weather_line: str,
    advice_line: str,
    window_line: str = "",
    knowledge_line: str = "",
    checklist: list[str] | None = None,
    destination: str = "校园出行",
) -> dict[str, Any]:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.4)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("校园出行计划卡")
    run.bold = True
    run.font.size = Pt(22)
    run.font.name = "微软雅黑"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    run.font.color.rgb = RGBColor(0x0B, 0x2B, 0x3B)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = subtitle.add_run(f"{city} · {destination} · {date_label}")
    sub_run.font.size = Pt(10.5)
    sub_run.font.color.rgb = RGBColor(0x4A, 0x64, 0x77)

    doc.add_paragraph("")
    rows = [
        ("目的地", destination),
        ("天气概况", weather_line),
        ("出行窗口", window_line or "以实时天气为准"),
        ("穿衣与携带", advice_line),
        ("校园信息", knowledge_line or "未检索到额外校园信息"),
        ("随身清单", "、".join(checklist or ["校园卡", "水杯"])),
    ]
    table = doc.add_table(rows=len(rows), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    table.autofit = False
    for idx, (key, value) in enumerate(rows):
        left, right = table.rows[idx].cells
        left.width = Cm(3.2)
        right.width = Cm(13.2)
        _set_cell_text(left, key, bold=True)
        _set_cell_text(right, value)
        _set_cell_shading(left, "E8F2F7")

    doc.add_paragraph("")
    tip = doc.add_paragraph()
    tip.alignment = WD_ALIGN_PARAGRAPH.LEFT
    tip_run = tip.add_run(
        "提示：本卡由天气、校园知识库与文档工具自动组合生成；"
        "天气数据来自 Open-Meteo，校园信息为示例知识库，请以学校最新通知为准。"
    )
    tip_run.font.size = Pt(9)
    tip_run.font.color.rgb = RGBColor(0x7B, 0x96, 0xAA)

    for sec in doc.sections:
        _set_page_number_footer(sec, f"晴雨校园助手 · {now_local().strftime('%Y-%m-%d %H:%M')}")

    filename = safe_filename(f"校园出行计划卡_{destination}_{stamp()}.docx")
    path = OUTPUT_DIR / filename
    doc.save(str(path))
    artifact = _artifact(path, f"校园出行计划卡 · {destination}")
    ctx.artifacts.append(artifact)
    return {
        "artifact": artifact,
        "checklist": checklist or [],
        "_summary": f"已生成校园出行计划卡：{path.name}",
    }


def register(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="doc.list_templates",
            description="列出系统内置的可填写文档模板及其必填字段。",
            category="document",
            params=[],
            handler=list_templates,
            timeout_s=3,
        )
    )
    registry.register(
        ToolSpec(
            name="doc.validate",
            description="校验文档模板字段是否完整、时间范围是否合法，返回缺失字段。",
            category="document",
            params=[
                ToolParam("template_id", "string", "模板 ID：activity_signup 或 leave_request"),
                ToolParam("fields", "object", "待填写的字段键值对"),
            ],
            handler=validate,
            timeout_s=3,
        )
    )
    registry.register(
        ToolSpec(
            name="doc.fill",
            description="把字段写入指定 DOCX 模板并生成可下载文档；写操作，需字段完整。",
            category="document",
            side_effect="write",
            params=[
                ToolParam("template_id", "string", "模板 ID：activity_signup 或 leave_request"),
                ToolParam("fields", "object", "已校验的字段键值对"),
            ],
            handler=fill,
            timeout_s=10,
        )
    )
    registry.register(
        ToolSpec(
            name="doc.plan_card",
            description="把天气、校园信息、出行窗口与随身清单组合成一张 DOCX 出行计划卡。",
            category="document",
            side_effect="write",
            params=[
                ToolParam("city", "string", "城市"),
                ToolParam("date_label", "string", "日期标签，如 明天（11月9日）"),
                ToolParam("weather_line", "string", "天气概况"),
                ToolParam("advice_line", "string", "穿衣与携带建议"),
                ToolParam("window_line", "string", "推荐出行窗口", required=False, default=""),
                ToolParam("knowledge_line", "string", "校园知识摘要", required=False, default=""),
                ToolParam("checklist", "array", "随身清单", required=False, default=None),
                ToolParam(
                    "destination",
                    "string",
                    "目的地，如 图书馆",
                    required=False,
                    default="校园出行",
                ),
            ],
            handler=plan_card,
            timeout_s=10,
        )
    )
