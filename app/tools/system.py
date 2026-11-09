"""系统时间与记忆工具。"""
from __future__ import annotations

from typing import Any

from ..config import DEFAULT_CITY
from ..utils import cn_date, now_local
from .base import ToolContext, ToolParam, ToolSpec, ToolRegistry

ALLOWED_PROFILE_KEYS = {
    "default_city",
    "departure",
    "temperature_sensitivity",
    "nickname",
    "college",
    "student_id",
}


def time_now(ctx: ToolContext) -> dict[str, Any]:
    now = now_local()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "weekday": "周" + "一二三四五六日"[now.weekday()],
        "cn_date": cn_date(now),
        "timezone": "Asia/Shanghai",
        "_summary": f"{cn_date(now)} {now.strftime('%H:%M')}",
    }


def set_profile(ctx: ToolContext, key: str, value: str) -> dict[str, Any]:
    key = str(key).strip()
    aliases = {
        "城市": "default_city",
        "默认城市": "default_city",
        "出发地": "departure",
        "怕冷": "temperature_sensitivity",
        "怕热": "temperature_sensitivity",
        "昵称": "nickname",
        "名字": "nickname",
        "学院": "college",
        "学号": "student_id",
    }
    key = aliases.get(key, key)
    if key not in ALLOWED_PROFILE_KEYS:
        return {
            "saved": False,
            "reason": f"不支持记住字段 {key}",
            "_summary": "该偏好不在可保存范围内。",
        }
    if key == "temperature_sensitivity":
        value = "cold" if "冷" in str(value) else "warm" if "热" in str(value) else "normal"
    ctx.memory.set_profile(ctx.session_id, key, value)
    return {
        "saved": True,
        "key": key,
        "value": value,
        "_summary": f"已记住 {key}={value}",
    }


def get_profile(ctx: ToolContext) -> dict[str, Any]:
    profile = ctx.memory.all_profile(ctx.session_id)
    profile.setdefault("default_city", DEFAULT_CITY)
    return {
        "profile": profile,
        "_summary": "已读取 " + str(len(profile)) + " 条偏好。",
    }


def register(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="time.now",
            description="获取服务器当前日期、时间、星期与时区，用于解释“今天/明天/现在”。",
            category="system",
            params=[],
            handler=time_now,
            timeout_s=1,
        )
    )
    registry.register(
        ToolSpec(
            name="memory.set_profile",
            description="记住用户偏好，如默认城市、出发地、怕冷/怕热、昵称、学院。",
            category="memory",
            side_effect="write",
            params=[
                ToolParam("key", "string", "偏好键，如 default_city / departure / temperature_sensitivity"),
                ToolParam("value", "string", "偏好值"),
            ],
            handler=set_profile,
            timeout_s=2,
        )
    )
    registry.register(
        ToolSpec(
            name="memory.get_profile",
            description="读取当前会话已保存的用户偏好。",
            category="memory",
            params=[],
            handler=get_profile,
            timeout_s=2,
        )
    )
