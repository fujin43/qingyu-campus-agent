"""智能体编排入口：会话 → 规划 → 工作流 → 回复。"""
from __future__ import annotations

import time
from typing import Any

from .config import APP_NAME, APP_VERSION, DB_PATH, DEEPSEEK_MODEL, LLM_PLANNER_ENABLED
from .llm import build_planner
from .memory import MemoryStore
from .planner import Plan
from .prompts import SYSTEM_PROMPT, prompt_manifest
from .tools import build_registry
from .tools.base import ToolContext
from .utils import now_iso
from .workflows import WorkflowEngine


class CampusAgent:
    def __init__(self, db_path=DB_PATH) -> None:
        self.memory = MemoryStore(db_path)
        self.registry = build_registry()
        self.planner = build_planner(self.memory)
        self.engine = WorkflowEngine(self.registry)
        self.name = APP_NAME
        self.version = APP_VERSION

    def chat(self, session_id: str, text: str) -> dict[str, Any]:
        started = time.perf_counter()
        session_id = str(session_id or "default")[:80]
        text = str(text or "").strip()[:2000]
        self.memory.ensure_session(session_id)
        self.memory.add_message(session_id, "user", text)

        ctx = ToolContext(
            session_id=session_id,
            user_text=text,
            memory=self.memory,
        )
        plan: Plan | None = None
        try:
            plan = self.planner.plan(session_id, text)
            if plan.llm_meta:
                ctx.step_counter += 1
                meta = plan.llm_meta
                ok = bool(meta.get("ok"))
                ctx.trace.append(
                    {
                        "step": ctx.step_counter,
                        "tool": "llm.plan",
                        "category": "llm",
                        "arguments": {"model": meta.get("model", DEEPSEEK_MODEL)},
                        "status": "ok" if ok else "error",
                        "summary": (
                            f"DeepSeek 规划 → {plan.workflow}（{plan.confidence:.2f}）"
                            if ok
                            else "LLM 规划不可用，已降级规则规划器"
                        ),
                        "duration_ms": meta.get("duration_ms", 0),
                        "error_code": None if ok else "LLM_FALLBACK",
                        "timestamp": now_iso(),
                    }
                )
            output = self.engine.run(plan, ctx)
            reply = output.reply
            suggestions = output.suggestions
            workflow_meta = output.meta
        except Exception as exc:  # noqa: BLE001 - 会话入口必须兜底
            reply = (
                "抱歉，这次处理遇到了内部错误。你可以换一种说法再试，"
                "或先查一个简单问题（例如“郑州天气”）。"
            )
            suggestions = ["郑州天气", "图书馆开放时间", "帮我填活动报名表"]
            workflow_meta = {"error": f"{type(exc).__name__}: {exc}"}
            ctx.trace.append(
                {
                    "step": len(ctx.trace) + 1,
                    "tool": "agent.runtime",
                    "category": "system",
                    "arguments": {},
                    "status": "error",
                    "summary": f"{type(exc).__name__}: {exc}",
                    "duration_ms": 0,
                    "error_code": "AGENT_RUNTIME_ERROR",
                    "timestamp": now_iso(),
                }
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        citations = self._dedupe(ctx.citations)
        response = {
            "session_id": session_id,
            "reply": reply,
            "suggestions": suggestions,
            "intent": plan.intent if plan else "error",
            "workflow": plan.workflow if plan else "error",
            "planner": plan.planner if plan else "error",
            "plan": plan.to_dict() if plan else None,
            "trace": ctx.trace,
            "artifacts": ctx.artifacts,
            "citations": citations,
            "latency_ms": latency_ms,
            "timestamp": now_iso(),
            "meta": workflow_meta,
        }
        self.memory.add_message(
            session_id,
            "assistant",
            reply,
            {
                "intent": response["intent"],
                "workflow": response["workflow"],
                "artifacts": ctx.artifacts,
                "trace_count": len(ctx.trace),
                "latency_ms": latency_ms,
            },
        )
        return response

    def reset(self, session_id: str) -> None:
        self.memory.clear_pending(session_id)

    def profile(self, session_id: str) -> dict[str, Any]:
        data = self.memory.all_profile(session_id)
        data.setdefault("default_city", "郑州")
        return data

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "name": self.name,
            "version": self.version,
            "tools": len(self.registry.list_specs()),
            "tool_names": [spec["name"] for spec in self.registry.list_specs()],
            "planner": type(self.planner).__name__,
            "llm_enabled": bool(LLM_PLANNER_ENABLED),
            "llm_model": DEEPSEEK_MODEL if LLM_PLANNER_ENABLED else None,
            "time": now_iso(),
        }

    def manifest(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "system_prompt": SYSTEM_PROMPT,
            "prompt": prompt_manifest(),
            "tools": self.registry.list_specs(),
            "openai_tools": self.registry.openai_tools(),
        }

    @staticmethod
    def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = set()
        result = []
        for item in items:
            key = (item.get("type"), item.get("title"), item.get("entry"), item.get("time"))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def close(self) -> None:
        self.memory.close()
