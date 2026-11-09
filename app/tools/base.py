"""工具契约、注册中心与统一调用入口。

设计原则：
1. 规划层不直接 import 具体工具，只通过 ToolRegistry.invoke() 调用；
2. 每次调用都做参数校验、异常归一化、耗时统计与轨迹记录；
3. 工具返回结构化的 ToolResult，便于工作流判断成功/失败/降级。
"""
from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..utils import compact_text, mask_sensitive, now_iso


class ToolError(Exception):
    """工具内部可预期的业务异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


@dataclass
class ToolParam:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "default": self.default,
        }


@dataclass
class ToolSpec:
    name: str
    description: str
    params: list[ToolParam]
    handler: Callable[..., dict[str, Any]]
    category: str = "general"
    side_effect: str = "read"  # read | write
    timeout_s: float = 15.0
    scopes: tuple[str, ...] = ("public",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "side_effect": self.side_effect,
            "timeout_s": self.timeout_s,
            "params": [p.to_dict() for p in self.params],
        }


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    error: dict[str, Any] | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "summary": self.summary,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ToolContext:
    """一次会话回合内共享的上下文。"""

    session_id: str
    user_text: str
    memory: Any
    trace: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    step_counter: int = 0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"重复注册工具：{spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_specs(self) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self._tools.values()]

    def openai_tools(self) -> list[dict[str, Any]]:
        """导出为 OpenAI/DeepSeek function calling 兼容格式。"""
        result = []
        for spec in self._tools.values():
            props = {
                p.name: {"type": p.type, "description": p.description}
                for p in spec.params
            }
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": {
                            "type": "object",
                            "properties": props,
                            "required": [p.name for p in spec.params if p.required],
                        },
                    },
                }
            )
        return result

    @staticmethod
    def _check_type(value: Any, expected: str) -> bool:
        checks = {
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
        }
        return checks.get(expected, lambda _v: True)(value)

    def invoke(
        self, name: str, args: dict[str, Any] | None, ctx: ToolContext
    ) -> ToolResult:
        start = time.perf_counter()
        args = dict(args or {})
        spec = self._tools.get(name)
        ctx.step_counter += 1
        step = ctx.step_counter

        if spec is None:
            result = self._fail(
                "TOOL_NOT_FOUND",
                f"未注册的工具：{name}",
                start,
            )
            self._record(ctx, step, name, "unknown", args, result)
            return result

        # 1) 参数校验
        normalized: dict[str, Any] = {}
        errors: list[str] = []
        for p in spec.params:
            if p.name in args and args[p.name] is not None:
                if not self._check_type(args[p.name], p.type):
                    errors.append(f"{p.name} 应为 {p.type}")
                else:
                    normalized[p.name] = args[p.name]
            elif p.required:
                errors.append(f"缺少必填参数 {p.name}")
            elif p.default is not None:
                normalized[p.name] = p.default

        if errors:
            result = self._fail(
                "INVALID_ARGUMENTS",
                "参数校验失败：" + "；".join(errors),
                start,
                details={"errors": errors},
            )
            self._record(ctx, step, name, spec.category, args, result)
            return result

        # 2) 写操作保护
        if spec.side_effect == "write" and ctx.dry_run:
            result = self._fail(
                "WRITE_BLOCKED",
                "当前为只读模式，已阻止写操作。",
                start,
            )
            self._record(ctx, step, name, spec.category, args, result)
            return result

        # 3) 执行
        try:
            raw = spec.handler(ctx, **normalized)
            if isinstance(raw, ToolResult):
                result = raw
                result.duration_ms = int((time.perf_counter() - start) * 1000)
            else:
                data = raw or {}
                summary = data.pop("_summary", "") if isinstance(data, dict) else ""
                result = ToolResult(
                    ok=True,
                    data=data,
                    summary=summary or compact_text(str(data), 120),
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )
        except ToolError as exc:
            result = self._fail(
                exc.code,
                exc.message,
                start,
                retryable=exc.retryable,
                details=exc.details,
            )
        except Exception as exc:  # noqa: BLE001 - 工具边界必须兜底
            result = self._fail(
                "TOOL_INTERNAL_ERROR",
                f"工具执行异常：{type(exc).__name__}: {exc}",
                start,
            )

        self._record(ctx, step, name, spec.category, args, result)
        return result

    @staticmethod
    def _fail(
        code: str,
        message: str,
        start: float,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(
            ok=False,
            summary=message,
            error={
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details or {},
            },
            duration_ms=int((time.perf_counter() - start) * 1000),
        )

    @staticmethod
    def _record(
        ctx: ToolContext,
        step: int,
        name: str,
        category: str,
        args: dict[str, Any],
        result: ToolResult,
    ) -> None:
        display_args = {
            k: mask_sensitive(v) if isinstance(v, str) else v for k, v in args.items()
        }
        event = {
            "step": step,
            "tool": name,
            "category": category,
            "arguments": display_args,
            "status": "ok" if result.ok else "error",
            "summary": result.summary,
            "duration_ms": result.duration_ms,
            "error_code": (result.error or {}).get("code"),
            "timestamp": now_iso(),
        }
        ctx.trace.append(event)
