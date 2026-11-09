"""意图识别、槽位抽取与工作流路由。

规则规划器的目标不是“像大模型一样聊天”，而是把 V3 提示词里的决策表
变成可复现、可测试的代码路径；LLM 模式可复用同一份 Plan 结构。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import DEFAULT_CITY
from .templates_meta import FIELD_ALIASES, TEMPLATES, find_template_id, normalize_fields
from .tools.weather import CITY_ALIASES


@dataclass
class Plan:
    intent: str
    workflow: str
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.8
    reason: str = ""
    clarify: str | None = None
    planner: str = "rule"
    llm_meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "workflow": self.workflow,
            "args": self.args,
            "confidence": self.confidence,
            "reason": self.reason,
            "clarify": self.clarify,
            "planner": self.planner,
        }


SECURITY_PATTERNS = [
    r"系统提示词",
    r"系统提示",
    r"system\s*prompt",
    r"忽略(之前|以上|前面|所有)的?指令",
    r"ignore\s+(all\s+)?(previous|above)\s+instructions",
    r"开发者模式",
    r"developer\s+mode",
    r"打印.*(提示词|prompt)",
    r"repeat\s+your\s+prompt",
    r"jailbreak",
]

OUT_OF_SCOPE_PATTERNS = [
    r"写(一篇|个)?.*(论文|作文|小说|文案)",
    r"翻译(一下|成)",
    r"写代码",
    r"炒股|股票|基金",
    r"医疗诊断|看病|开药",
    r"法律咨询|起诉",
    r"帮我作弊|代考",
]

DOC_HINTS = r"(填写|填一下|填个|填表|生成|制作|做一?份|导出).{0,8}(表|文档|docx|报名|请假)"
WEATHER_HINTS = r"(天气|气温|多少度|下雨|降雨|带伞|穿什么|冷不冷|热不热|风大|空气质量|aqi|雾霾)"
TRIP_HINTS = r"(出门|出行|去图书馆|去上课|去食堂|去操场|去体育馆|去地铁站|安排|计划|行程|出行卡)"
CAMPUS_HINTS = (
    r"(图书馆|校车|摆渡车|班车|食堂|校园卡|饭卡|快递|驿站|报修|维修|请假流程|"
    r"场地|教室|报告厅|社团|校园网|wifi|打印|复印|体育馆|操场|自习室|研讨间|"
    r"校园服务|教务处|学工部|后勤)"
)


def _extract_when(text: str) -> str:
    if "后天" in text:
        return "dayafter"
    if "明天" in text or "明早" in text or "明晚" in text:
        return "tomorrow"
    return "today"


def _extract_hour(text: str) -> int | None:
    # 先匹配 “8点/8:00/8：00”
    match = re.search(r"(?<!\d)(\d{1,2})\s*(?:点|[:：])\s*(\d{1,2})?", text)
    if not match:
        return None
    hour = int(match.group(1))
    if hour > 23:
        return None
    if ("下午" in text or "晚上" in text) and hour < 12:
        hour += 12
    if "中午" in text and hour < 11:
        hour += 12
    return hour


def _extract_city(text: str, profile: dict[str, Any]) -> str:
    # 显式城市名优先（按长度降序，避免“郑州”被“郑州东”截断）
    for name in sorted(CITY_ALIASES, key=len, reverse=True):
        if name in text:
            return CITY_ALIASES[name]
    match = re.search(
        r"([\u4e00-\u9fa5]{2,6})(?:市)?(?:今天|明天|后天|现在|的)?(?:天气|气温|下雨|降雨)",
        text,
    )
    if match:
        candidate = re.sub(r"^(查|看|问|一下|帮我|请)", "", match.group(1))
        if candidate and candidate not in {"今天", "明天", "后天", "现在"}:
            return candidate
    return str(profile.get("default_city") or DEFAULT_CITY)


def _extract_destination(text: str) -> str:
    for place in [
        "图书馆",
        "教学楼",
        "食堂",
        "体育馆",
        "操场",
        "地铁站",
        "宿舍",
        "快递点",
        "行政楼",
        "自习室",
    ]:
        if place in text:
            return place
    match = re.search(r"去([\u4e00-\u9fa5A-Za-z0-9]{2,8})", text)
    if match:
        return re.sub(r"(，|。|,|；|;).*$", "", match.group(1))
    return "校园"


def extract_fields(text: str) -> dict[str, str]:
    """抽取“姓名=林晓，学号=20231234”这类键值对。"""
    fields: dict[str, str] = {}
    # 只用已知字段名做锚点，避免把“帮我填写活动报名表：”误当字段
    aliases = sorted(FIELD_ALIASES, key=len, reverse=True)
    alias_pattern = "|".join(re.escape(item) for item in aliases)
    pattern = re.compile(
        rf"({alias_pattern})\s*[=:：]\s*([^，,；;\n]+)"
    )
    for match in pattern.finditer(text):
        key = match.group(1).strip()
        value = match.group(2).strip().strip("。；;")
        fields[key] = value
    # “我叫林晓”只用于昵称，不直接写入正式表格
    return normalize_fields(fields)


def _memory_action(text: str) -> tuple[str, str] | None:
    if "我怕冷" in text or "怕冷" in text:
        return "temperature_sensitivity", "cold"
    if "我怕热" in text or "怕热" in text:
        return "temperature_sensitivity", "warm"
    if "我叫" in text:
        match = re.search(r"我叫([\u4e00-\u9fa5A-Za-z0-9]{1,12})", text)
        if match:
            return "nickname", match.group(1)
    match = re.search(r"(?:默认城市|以后在|我住在|我在)([\u4e00-\u9fa5]{2,6})", text)
    if match:
        return "default_city", match.group(1)
    match = re.search(r"(?:出发地|从)(宿舍|东区|西区|南门|北门|地铁站)", text)
    if match:
        return "departure", match.group(1)
    if "记住" in text:
        return "default_city", _extract_city(text, {})
    return None


class Planner:
    def __init__(self, memory) -> None:
        self.memory = memory

    def plan(self, session_id: str, text: str) -> Plan:
        text = (text or "").strip()
        profile = self.memory.all_profile(session_id)
        pending = self.memory.get_pending(session_id)

        if not text:
            return Plan(
                intent="clarify",
                workflow="clarify",
                clarify="我在。你可以让我查天气、找校园信息，或填写报名表/请假表。",
                confidence=1.0,
                reason="空输入",
            )

        # 1) 安全：提示词泄露/注入
        for pattern in SECURITY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return Plan(
                    intent="security",
                    workflow="out_of_scope",
                    args={"kind": "security"},
                    confidence=0.99,
                    reason="命中提示词注入/泄露模式",
                )

        # 2) 取消待补全任务
        if pending and re.search(r"(取消|算了|不填了|先不填|不用了)", text):
            self.memory.clear_pending(session_id)
            return Plan(
                intent="cancel",
                workflow="cancel",
                args={"message": "已取消本次填写，待补全的字段不会保存。"},
                confidence=0.99,
                reason="用户取消 pending 任务",
            )

        # 3) 待补全的文档：优先续接
        if pending and pending.get("action") == "doc_fill":
            payload = pending.get("payload") or {}
            template_id = payload.get("template_id")
            fields = dict(payload.get("fields") or {})
            fields.update(extract_fields(text))
            if template_id not in TEMPLATES:
                self.memory.clear_pending(session_id)
            else:
                return Plan(
                    intent="doc_fill",
                    workflow="doc_fill",
                    args={
                        "template_id": template_id,
                        "fields": fields,
                        "resumed": True,
                        "source_text": text,
                    },
                    confidence=0.98,
                    reason="续接上一轮未完成的文档填写",
                )

        # 4) 文档填写
        template_id = find_template_id(text)
        doc_hint = bool(re.search(DOC_HINTS, text))
        if template_id or (doc_hint and re.search(r"(表|文档|docx)", text)):
            if not template_id:
                return Plan(
                    intent="doc_fill",
                    workflow="clarify_template",
                    args={"text": text},
                    clarify="我可以填写《校园活动报名表》或《学生请假申请表》。你想填哪一份？",
                    confidence=0.86,
                    reason="识别到填表意图但未识别模板",
                )
            fields = extract_fields(text)
            # 把上一轮 pending 的字段合并（如果用户换了模板则重新开始）
            if pending and pending.get("action") == "doc_fill":
                old = pending.get("payload") or {}
                if old.get("template_id") == template_id:
                    merged = dict(old.get("fields") or {})
                    merged.update(fields)
                    fields = merged
            return Plan(
                intent="doc_fill",
                workflow="doc_fill",
                args={
                    "template_id": template_id,
                    "fields": fields,
                    "resumed": False,
                    "source_text": text,
                },
                confidence=0.96,
                reason=f"识别到模板 {template_id}",
            )

        # 5) 综合出行
        if re.search(TRIP_HINTS, text) and (
            re.search(WEATHER_HINTS, text)
            or "图书馆" in text
            or "出行卡" in text
            or "计划卡" in text
        ):
            destination = _extract_destination(text)
            city = _extract_city(text, profile)
            make_card = bool(re.search(r"(卡片|计划卡|出行卡|文档|生成|导出)", text))
            return Plan(
                intent="trip_plan",
                workflow="trip_plan",
                args={
                    "city": city,
                    "when": _extract_when(text),
                    "preferred_hour": _extract_hour(text),
                    "destination": destination,
                    "make_card": make_card,
                    "source_text": text,
                },
                confidence=0.94,
                reason="出行意图 + 天气/校园信息需求",
            )

        # 6) 天气
        if re.search(WEATHER_HINTS, text, re.IGNORECASE):
            city = _extract_city(text, profile)
            air = bool(re.search(r"(空气|aqi|雾霾|pm2\.?5)", text, re.IGNORECASE))
            return Plan(
                intent="weather_air" if air else "weather_brief",
                workflow="weather_air" if air else "weather_brief",
                args={
                    "city": city,
                    "when": _extract_when(text),
                    "preferred_hour": _extract_hour(text),
                },
                confidence=0.95,
                reason="天气关键词",
            )

        # 7) 校园知识库
        if re.search(CAMPUS_HINTS, text, re.IGNORECASE):
            return Plan(
                intent="campus_qa",
                workflow="campus_qa",
                args={"query": text},
                confidence=0.9,
                reason="校园知识库关键词",
            )

        # 8) 记忆
        memory_action = _memory_action(text)
        if memory_action:
            key, value = memory_action
            return Plan(
                intent="memory_update",
                workflow="memory_update",
                args={"key": key, "value": value},
                confidence=0.92,
                reason="记忆偏好表达",
            )

        # 9) 帮助
        if re.search(r"(你好|您好|你是谁|能做什么|会什么|帮助|功能|怎么用|菜单)", text):
            return Plan(
                intent="help",
                workflow="help",
                confidence=0.98,
                reason="问候/能力询问",
            )

        # 10) 超范围
        for pattern in OUT_OF_SCOPE_PATTERNS:
            if re.search(pattern, text):
                return Plan(
                    intent="out_of_scope",
                    workflow="out_of_scope",
                    args={"kind": "scope"},
                    confidence=0.95,
                    reason="超出校园出行/事务范围",
                )

        # 11) 兜底澄清
        return Plan(
            intent="clarify",
            workflow="clarify",
            clarify=(
                "我主要帮你做四件事：①查实时天气与带伞/穿衣建议；"
                "②查图书馆、校车等校园信息；③填写报名表/请假表；"
                "④把天气和校园信息组合成出行计划卡。你想先做哪一件？"
            ),
            confidence=0.55,
            reason="未命中明确意图",
        )
