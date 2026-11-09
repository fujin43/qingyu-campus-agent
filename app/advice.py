"""把结构化天气信号转成可执行建议。

这是 M7 工作流中的纯函数，不访问网络、不写文件，便于单元测试。
"""
from __future__ import annotations

from typing import Any


def _pick_temp(weather: dict[str, Any]) -> tuple[float, float, float]:
    """返回 (当前体感, 最低温, 最高温)。"""
    current = weather.get("current") or {}
    daily = weather.get("daily") or {}
    apparent = current.get("apparent")
    temp_min = daily.get("temp_min")
    temp_max = daily.get("temp_max")
    if apparent is None:
        lo = float(temp_min if temp_min is not None else 18)
        hi = float(temp_max if temp_max is not None else 24)
        apparent = (lo + hi) / 2
    return (
        float(apparent),
        float(temp_min if temp_min is not None else apparent),
        float(temp_max if temp_max is not None else apparent),
    )


def clothing_for(apparent: float, sensitivity: str = "normal") -> tuple[str, str]:
    offset = {"cold": -2, "warm": 2}.get(sensitivity, 0)
    t = apparent + offset
    if t <= 4:
        return "厚羽绒服 + 保暖内搭", "严寒"
    if t <= 10:
        return "羽绒服/厚大衣 + 毛衣", "寒冷"
    if t <= 16:
        return "大衣/夹克 + 长袖", "偏凉"
    if t <= 21:
        return "薄外套 + 长袖/卫衣", "舒适偏凉"
    if t <= 27:
        return "长袖或短袖 + 轻薄外套", "舒适"
    if t <= 32:
        return "短袖 + 透气长裤/裙装", "偏热"
    return "短袖短裤 + 防晒", "炎热"


def build_advice(weather: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or {}
    sensitivity = str(profile.get("temperature_sensitivity") or "normal")
    current = weather.get("current") or {}
    daily = weather.get("daily") or {}
    window = weather.get("best_window") or {}

    apparent, temp_min, temp_max = _pick_temp(weather)
    clothing, feel = clothing_for(apparent, sensitivity)

    rain_prob = daily.get("rain_probability")
    if rain_prob is None and window:
        rain_prob = window.get("rain_probability")
    rain_prob = float(rain_prob or 0)
    current_precip = float(current.get("precipitation") or 0)
    code = int((current.get("weather_code") or daily.get("weather_code") or 0))
    is_rain_code = code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}

    if current_precip > 0 or rain_prob >= 55:
        umbrella = "一定要带伞"
        umbrella_level = "must"
    elif rain_prob >= 25 or is_rain_code:
        umbrella = "建议带折叠伞备用"
        umbrella_level = "maybe"
    else:
        umbrella = "可以不带伞"
        umbrella_level = "none"

    wind = float(current.get("wind_speed") or 0)
    wind_tip = "风力较大，注意防风" if wind >= 30 else "风力不大"

    uv = daily.get("uv_index")
    uv_tip = ""
    if isinstance(uv, (int, float)):
        if uv >= 7:
            uv_tip = "紫外线强，建议防晒"
        elif uv >= 4:
            uv_tip = "紫外线中等，可做基础防晒"

    temp_gap = temp_max - temp_min
    layer_tip = "早晚温差大，建议洋葱式穿衣" if temp_gap >= 8 else "全天温差不大"

    checklist = []
    if umbrella_level != "none":
        checklist.append("折叠伞")
    if feel in {"严寒", "寒冷", "偏凉"}:
        checklist.append("外套")
    if isinstance(uv, (int, float)) and uv >= 4:
        checklist.append("防晒")
    checklist.append("校园卡")
    checklist.append("水杯")

    summary_parts = [clothing, umbrella]
    if wind >= 30:
        summary_parts.append("注意防风")
    if isinstance(uv, (int, float)) and uv >= 7:
        summary_parts.append("做好防晒")

    return {
        "apparent": round(apparent, 1),
        "temp_min": round(temp_min, 1),
        "temp_max": round(temp_max, 1),
        "feel": feel,
        "clothing": clothing,
        "umbrella": umbrella,
        "umbrella_level": umbrella_level,
        "rain_probability": round(rain_prob, 1),
        "wind_tip": wind_tip,
        "uv_tip": uv_tip,
        "layer_tip": layer_tip,
        "checklist": checklist,
        "summary": "；".join(summary_parts),
        "best_window": window,
    }
