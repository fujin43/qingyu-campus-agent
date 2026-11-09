"""工具装配入口。"""
from __future__ import annotations

from . import campus, docs, system, weather
from .base import ToolContext, ToolRegistry, ToolResult, ToolSpec

__all__ = [
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "build_registry",
]


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    weather.register(registry)
    campus.register(registry)
    docs.register(registry)
    system.register(registry)
    return registry
