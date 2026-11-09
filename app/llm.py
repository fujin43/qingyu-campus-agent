"""DeepSeek OpenAI 兼容接口：只负责“规划”，不直接执行工具。

LLM 输出严格限定为 Plan JSON；参数校验、工具调用、文件写入仍由
M3/M7 完成。这样既用上了外部 API，又保留了确定性兜底。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_PLANNER_ENABLED,
    LLM_TIMEOUT,
)
from .planner import Plan, Planner, extract_fields
from .prompts import SYSTEM_PROMPT
from .templates_meta import TEMPLATES, find_template_id, normalize_fields
from .utils import now_local

ALLOWED_WORKFLOWS = {
    "weather_brief",
    "weather_air",
    "campus_qa",
    "trip_plan",
    "doc_fill",
    "memory_update",
    "help",
    "out_of_scope",
    "clarify",
}

PLANNER_PROTOCOL = """
# 规划阶段输出契约（覆盖上面的“不要输出 JSON”）
你现在只做“规划”，不直接回复用户，也不执行工具。只输出一个 JSON 对象，不要 Markdown 代码块。
JSON 字段：
{
  "intent": "weather_brief|weather_air|campus_qa|trip_plan|doc_fill|memory_update|help|out_of_scope|clarify",
  "workflow": "与 intent 相同，从允许列表中选择",
  "confidence": 0.0-1.0,
  "reason": "一句话说明",
  "clarify": "仅当 workflow=clarify 时给用户的问题，否则 null",
  "args": {
    "city": "城市名，可省略",
    "when": "today|tomorrow|dayafter",
    "preferred_hour": 0-23,
    "destination": "图书馆等",
    "make_card": true,
    "template_id": "activity_signup|leave_request",
    "fields": {"姓名": "…", "学号": "…"},
    "query": "校园知识检索词",
    "key": "记忆键",
    "value": "记忆值"
  }
}
规则：
- 只输出 JSON，不要解释，不要调用工具。
- 文档填写必须给 template_id；字段用中文键；缺字段也照常返回 doc_fill，后续会 validate 后追问。
- 出行/计划/生成卡片优先 trip_plan；单纯问天气用 weather_brief。
- 不确定时 workflow=clarify，并在 clarify 里只问一个最关键的问题。
""".strip()


class LLMError(Exception):
    def __init__(self, message: str, *, code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DeepSeekClient:
    def __init__(
        self,
        api_key: str = DEEPSEEK_API_KEY,
        base_url: str = DEEPSEEK_BASE_URL,
        model: str = DEEPSEEK_MODEL,
        timeout: int = LLM_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise LLMError(
                f"DeepSeek HTTP {exc.code}: {detail}",
                code="LLM_HTTP_ERROR",
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"DeepSeek 网络错误：{exc}", code="LLM_NETWORK_ERROR") from exc

    def plan_json(
        self,
        text: str,
        *,
        profile: dict[str, Any],
        pending: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        system = (
            SYSTEM_PROMPT
            + "\n\n"
            + PLANNER_PROTOCOL
            + "\n\n# 可用工作流\n"
            + "、".join(sorted(ALLOWED_WORKFLOWS))
        )
        user = json.dumps(
            {
                "now": now_local().isoformat(timespec="minutes"),
                "profile": profile,
                "pending": pending,
                "user_input": text,
            },
            ensure_ascii=False,
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
        }
        started = time.perf_counter()
        data = self._post(payload)
        elapsed = int((time.perf_counter() - started) * 1000)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("DeepSeek 返回为空", code="LLM_EMPTY")
        content = (choices[0].get("message") or {}).get("content") or ""
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"DeepSeek 未返回合法 JSON：{content[:160]}",
                code="LLM_INVALID_JSON",
            ) from exc
        meta = {
            "provider": "deepseek",
            "model": data.get("model") or self.model,
            "duration_ms": elapsed,
            "usage": data.get("usage") or {},
            "ok": True,
        }
        return parsed, meta


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        number = int(value)
        return number if 0 <= number <= 23 else None
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "y", "是"}


class LLMPlanner:
    """LLM 规划 + 规则兜底。

    - 安全、取消、pending 续接交给规则规划器，保证状态确定；
    - 高置信度的文档/出行/超范围规则会约束 workflow，LLM 只补槽位；
    - 任何 API/JSON 异常都退回规则规划器，不阻塞用户。
    """

    def __init__(self, rule: Planner, client: DeepSeekClient) -> None:
        self.rule = rule
        self.client = client

    def plan(self, session_id: str, text: str) -> Plan:
        profile = self.rule.memory.all_profile(session_id)
        pending = self.rule.memory.get_pending(session_id)
        rule_plan = self.rule.plan(session_id, text)

        # 安全/取消/pending 续接：规则优先，避免 LLM 破坏状态
        if (
            not text.strip()
            or rule_plan.intent in {"security", "cancel"}
            or (pending and pending.get("action") == "doc_fill")
        ):
            rule_plan.planner = "rule"
            return rule_plan

        started = time.perf_counter()
        try:
            raw, meta = self.client.plan_json(text, profile=profile, pending=pending)
            plan = self._to_plan(raw, text, rule_plan, profile)
            plan.planner = "llm"
            plan.llm_meta = meta
            return plan
        except Exception as exc:  # noqa: BLE001
            rule_plan.planner = "rule_fallback"
            rule_plan.llm_meta = {
                "provider": "deepseek",
                "ok": False,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "error": str(exc)[:240],
            }
            return rule_plan

    def _to_plan(
        self,
        raw: dict[str, Any],
        text: str,
        rule_plan: Plan,
        profile: dict[str, Any],
    ) -> Plan:
        workflow = str(raw.get("workflow") or raw.get("intent") or "").strip()
        intent = str(raw.get("intent") or workflow).strip()
        if workflow not in ALLOWED_WORKFLOWS:
            raise LLMError(f"非法 workflow：{workflow}", code="LLM_BAD_WORKFLOW")

        # 高置信规则约束：避免 LLM 把“填表”误判成聊天、把“生成出行卡”缩成天气
        if rule_plan.workflow in {"doc_fill", "trip_plan", "out_of_scope"} and rule_plan.confidence >= 0.9:
            workflow = rule_plan.workflow
            intent = rule_plan.intent

        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        if workflow == "weather_brief" or workflow == "weather_air":
            args = {
                "city": args.get("city") or rule_plan.args.get("city") or profile.get("default_city") or "郑州",
                "when": args.get("when") or rule_plan.args.get("when") or "today",
                "preferred_hour": _as_int(args.get("preferred_hour"))
                if args.get("preferred_hour") is not None
                else rule_plan.args.get("preferred_hour"),
            }
        elif workflow == "campus_qa":
            args = {"query": args.get("query") or text}
        elif workflow == "trip_plan":
            args = {
                "city": args.get("city") or rule_plan.args.get("city") or profile.get("default_city") or "郑州",
                "when": args.get("when") or rule_plan.args.get("when") or "today",
                "preferred_hour": _as_int(args.get("preferred_hour"))
                if args.get("preferred_hour") is not None
                else rule_plan.args.get("preferred_hour"),
                "destination": args.get("destination") or rule_plan.args.get("destination") or "校园",
                "make_card": bool(
                    (_as_bool(args.get("make_card")) if "make_card" in args else False)
                    or rule_plan.args.get("make_card")
                ),
                "source_text": text,
            }
        elif workflow == "doc_fill":
            template_id = (
                args.get("template_id")
                or rule_plan.args.get("template_id")
                or find_template_id(text)
            )
            if template_id not in TEMPLATES:
                raise LLMError("doc_fill 缺少合法 template_id", code="LLM_BAD_TEMPLATE")
            raw_fields = args.get("fields") if isinstance(args.get("fields"), dict) else {}
            fields = dict(rule_plan.args.get("fields") or {})
            fields.update(normalize_fields(raw_fields))
            args = {
                "template_id": template_id,
                "fields": fields,
                "resumed": False,
                "source_text": text,
            }
        elif workflow == "memory_update":
            args = {
                "key": args.get("key") or rule_plan.args.get("key") or "default_city",
                "value": args.get("value") or rule_plan.args.get("value") or "",
            }
        elif workflow == "clarify":
            clarify = raw.get("clarify") or rule_plan.clarify or "请再具体说明一下你的需求。"
            return Plan(
                intent="clarify",
                workflow="clarify",
                args={},
                confidence=float(raw.get("confidence") or 0.5),
                reason=str(raw.get("reason") or "LLM 请求澄清")[:300],
                clarify=str(clarify)[:500],
            )
        elif workflow == "out_of_scope":
            args = {"kind": "scope"}
        else:
            args = {}

        return Plan(
            intent=intent if intent in ALLOWED_WORKFLOWS else workflow,
            workflow=workflow,
            args=args,
            confidence=max(0.0, min(1.0, float(raw.get("confidence") or 0.7))),
            reason=str(raw.get("reason") or "LLM 规划")[:300],
            clarify=raw.get("clarify") if isinstance(raw.get("clarify"), str) else None,
        )


def build_planner(memory) -> Planner:
    rule = Planner(memory)
    if LLM_PLANNER_ENABLED:
        client = DeepSeekClient()
        if client.available:
            return LLMPlanner(rule, client)  # type: ignore[return-value]
    return rule
