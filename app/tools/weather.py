"""实时天气与空气质量工具（Open-Meteo，免 API Key）。

M4 只负责“取数 + 归一化”，不负责穿衣/带伞建议；建议由工作流层的
advice 模块基于结构化天气信号生成，保证数据与决策分离。
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

from ..config import (
    AIR_QUALITY_FALLBACK_URL,
    AIR_QUALITY_URL,
    CACHE_DIR,
    DEFAULT_CITY,
    FORECAST_FALLBACK_URL,
    FORECAST_URL,
    GEOCODE_CACHE_TTL,
    GEOCODING_FALLBACK_URL,
    GEOCODING_URL,
    HTTP_TIMEOUT,
    WEATHER_CACHE_TTL,
)
from ..utils import now_local, write_json
from .base import ToolContext, ToolError, ToolParam, ToolSpec, ToolRegistry

WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("晴", "sun"),
    1: ("大部晴朗", "sun"),
    2: ("多云", "cloud"),
    3: ("阴", "cloud"),
    45: ("有雾", "fog"),
    48: ("雾凇", "fog"),
    51: ("小毛毛雨", "rain"),
    53: ("毛毛雨", "rain"),
    55: ("较强毛毛雨", "rain"),
    56: ("冻毛毛雨", "rain"),
    57: ("强冻毛毛雨", "rain"),
    61: ("小雨", "rain"),
    63: ("中雨", "rain"),
    65: ("大雨", "rain"),
    66: ("冻雨", "rain"),
    67: ("强冻雨", "rain"),
    71: ("小雪", "snow"),
    73: ("中雪", "snow"),
    75: ("大雪", "snow"),
    77: ("米雪", "snow"),
    80: ("小阵雨", "rain"),
    81: ("阵雨", "rain"),
    82: ("强阵雨", "rain"),
    85: ("小阵雪", "snow"),
    86: ("强阵雪", "snow"),
    95: ("雷阵雨", "storm"),
    96: ("雷阵雨伴冰雹", "storm"),
    99: ("强雷阵雨伴冰雹", "storm"),
}

# 校园常见地点/别称映射到城市，减少地名歧义
CITY_ALIASES = {
    "郑州大学主校区": "郑州",
    "郑州大学": "郑州",
    "郑大": "郑州",
    "主校区": "郑州",
    "高新区": "郑州",
    "中原": "郑州",
    "河南": "郑州",
    "校园": "郑州",
    "学校": "郑州",
    "宿舍": "郑州",
    "郑州": "郑州",
    "北京": "北京",
    "上海": "上海",
    "广州": "广州",
    "深圳": "深圳",
    "南京": "南京",
    "武汉": "武汉",
    "成都": "成都",
    "西安": "西安",
    "天津": "天津",
    "重庆": "重庆",
    "苏州": "苏州",
    "厦门": "厦门",
    "长沙": "长沙",
    "青岛": "青岛",
    "大连": "大连",
    "宁波": "宁波",
    "温州": "温州",
    "绍兴": "绍兴",
    "嘉兴": "嘉兴",
    "金华": "金华",
    "合肥": "合肥",
    "福州": "福州",
    "济南": "济南",
    "郑州": "郑州",
    "昆明": "昆明",
    "贵阳": "贵阳",
    "南宁": "南宁",
    "海口": "海口",
    "三亚": "三亚",
    "哈尔滨": "哈尔滨",
    "长春": "长春",
    "沈阳": "沈阳",
    "石家庄": "石家庄",
    "太原": "太原",
    "兰州": "兰州",
    "西宁": "西宁",
    "银川": "银川",
    "乌鲁木齐": "乌鲁木齐",
    "拉萨": "拉萨",
    "呼和浩特": "呼和浩特",
    "香港": "香港",
    "澳门": "澳门",
    "台北": "台北",
}

WEATHER_MEMORY: dict[str, tuple[float, Any]] = {}
GEOCODE_MEMORY: dict[str, tuple[float, dict[str, Any]]] = {}


def describe_code(code: int | None) -> tuple[str, str]:
    return WEATHER_CODES.get(int(code or 0), ("未知天气", "unknown"))


def _cache_path(prefix: str, key: str) -> Any:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:18]
    return CACHE_DIR / f"{prefix}_{digest}.json"


def _disk_get(prefix: str, key: str, ttl: int) -> Any | None:
    path = _cache_path(prefix, key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("_cached_at", 0)) <= ttl:
            return payload.get("data")
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return None


def _disk_get_stale(prefix: str, key: str) -> Any | None:
    path = _cache_path(prefix, key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("data")
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _disk_set(prefix: str, key: str, data: Any) -> None:
    path = _cache_path(prefix, key)
    write_json(path, {"_cached_at": time.time(), "data": data})


def _http_json(
    url: str, params: dict[str, Any], fallback_url: str | None = None
) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    candidates = [url] + ([fallback_url] if fallback_url else [])
    last_error: Exception | None = None
    for target in candidates:
        request = urllib.request.Request(
            f"{target}?{query}",
            headers={
                "User-Agent": "QingyuCampusAgent/1.0 (course project; contact: demo@example.com)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise ToolError(
                    "WEATHER_HTTP_ERROR",
                    f"天气服务返回 HTTP {exc.code}，请检查查询参数。",
                    retryable=False,
                ) from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.3)
    raise ToolError(
        "WEATHER_NETWORK_ERROR",
        "暂时连不上天气服务，请检查网络后重试。",
        retryable=True,
        details={"reason": str(last_error)},
    )


def geocode(city: str) -> dict[str, Any]:
    city = (city or DEFAULT_CITY).strip()
    canonical = CITY_ALIASES.get(city, city)
    key = f"{canonical}|zh"
    cached = GEOCODE_MEMORY.get(key)
    if cached and time.time() - cached[0] < GEOCODE_CACHE_TTL:
        return cached[1]
    disk = _disk_get("geocode", key, GEOCODE_CACHE_TTL)
    if disk:
        GEOCODE_MEMORY[key] = (time.time(), disk)
        return disk

    payload = _http_json(
        GEOCODING_URL,
        {"name": canonical, "count": 6, "language": "zh", "format": "json"},
        GEOCODING_FALLBACK_URL,
    )
    results = payload.get("results") or []
    if not results:
        raise ToolError(
            "CITY_NOT_FOUND",
            f"没有找到“{city}”对应的城市，请换一个城市名试试。",
            details={"city": city},
        )

    # 优先中国境内、人口较多的城市，避免同名地点
    def rank(item: dict[str, Any]) -> tuple[int, int]:
        return (
            0 if item.get("country_code") == "CN" else 1,
            -(int(item.get("population") or 0)),
        )

    best = sorted(results, key=rank)[0]
    resolved = {
        "query": city,
        "name": best.get("name") or canonical,
        "country": best.get("country") or "",
        "admin1": best.get("admin1") or "",
        "latitude": float(best["latitude"]),
        "longitude": float(best["longitude"]),
        "timezone": best.get("timezone") or "Asia/Shanghai",
        "population": best.get("population"),
    }
    GEOCODE_MEMORY[key] = (time.time(), resolved)
    _disk_set("geocode", key, resolved)
    return resolved


def fetch_weather(city: str, when: str = "today") -> tuple[dict[str, Any], bool]:
    """返回 (原始预报, 是否使用过期缓存)。"""
    location = geocode(city)
    key = f"{location['latitude']:.3f},{location['longitude']:.3f}|{when}"
    cached = WEATHER_MEMORY.get(key)
    if cached and time.time() - cached[0] < WEATHER_CACHE_TTL:
        return cached[1], False
    disk = _disk_get("forecast", key, WEATHER_CACHE_TTL)
    if disk:
        WEATHER_MEMORY[key] = (time.time(), disk)
        return disk, False

    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m"
        ),
        "hourly": (
            "temperature_2m,apparent_temperature,precipitation_probability,"
            "precipitation,weather_code,wind_speed_10m"
        ),
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,uv_index_max,sunrise,sunset"
        ),
        "timezone": "Asia/Shanghai",
        "forecast_days": 4,
        "forecast_hours": 72,
        "wind_speed_unit": "kmh",
    }
    try:
        payload = _http_json(FORECAST_URL, params, FORECAST_FALLBACK_URL)
    except ToolError:
        stale = _disk_get_stale("forecast", key)
        if stale:
            return stale, True
        raise
    WEATHER_MEMORY[key] = (time.time(), payload)
    _disk_set("forecast", key, payload)
    return payload, False


def _daily_at(payload: dict[str, Any], offset: int) -> dict[str, Any]:
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    if offset >= len(dates):
        raise ToolError("DATE_OUT_OF_RANGE", "预报只覆盖未来 4 天，请换个日期。")
    idx = offset
    code = (daily.get("weather_code") or [0])[idx]
    desc, icon = describe_code(code)
    return {
        "date": dates[idx],
        "weather_code": code,
        "weather": desc,
        "icon": icon,
        "temp_max": (daily.get("temperature_2m_max") or [None])[idx],
        "temp_min": (daily.get("temperature_2m_min") or [None])[idx],
        "rain_probability": (daily.get("precipitation_probability_max") or [None])[idx],
        "uv_index": (daily.get("uv_index_max") or [None])[idx],
        "sunrise": (daily.get("sunrise") or [None])[idx],
        "sunset": (daily.get("sunset") or [None])[idx],
    }


def _hourly_rows(payload: dict[str, Any], date: str) -> list[dict[str, Any]]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    rows: list[dict[str, Any]] = []
    for idx, stamp in enumerate(times):
        if not str(stamp).startswith(date):
            continue
        rows.append(
            {
                "time": stamp,
                "hour": int(str(stamp)[11:13]),
                "temperature": (hourly.get("temperature_2m") or [None])[idx],
                "apparent": (hourly.get("apparent_temperature") or [None])[idx],
                "rain_probability": (hourly.get("precipitation_probability") or [None])[idx],
                "precipitation": (hourly.get("precipitation") or [None])[idx],
                "weather_code": (hourly.get("weather_code") or [None])[idx],
                "wind_speed": (hourly.get("wind_speed_10m") or [None])[idx],
            }
        )
    return rows


def best_window(
    rows: list[dict[str, Any]],
    *,
    preferred_hour: int | None = None,
    date_label: str = "",
) -> dict[str, Any] | None:
    """在 06:00–21:00 中寻找连续 2 小时最适宜外出的窗口。"""
    if not rows:
        return None
    candidates: list[dict[str, Any]] = []
    for idx, row in enumerate(rows[:-1]):
        hour = row["hour"]
        if hour < 6 or hour > 21:
            continue
        nxt = rows[idx + 1]
        if nxt["hour"] != hour + 1:
            continue
        probs = [row.get("rain_probability"), nxt.get("rain_probability")]
        probs = [p for p in probs if p is not None]
        if not probs:
            continue
        rain_prob = sum(probs) / len(probs)
        temps = [
            t for t in (row.get("apparent"), nxt.get("apparent")) if t is not None
        ]
        temp = sum(temps) / len(temps) if temps else 20
        wind = max(
            [w for w in (row.get("wind_speed"), nxt.get("wind_speed")) if w is not None]
            or [0]
        )
        # 分数越低越好：降水权重最高，温度偏离 22℃ 与大风次之
        score = rain_prob + abs(temp - 22) * 2 + max(0, wind - 20) * 0.8
        if preferred_hour is not None:
            # 用户指定时间时，优先看该时间前后，不强制完全相等
            score += abs(hour - preferred_hour) * 6
        candidates.append(
            {
                "start": f"{hour:02d}:00",
                "end": f"{hour + 2:02d}:00",
                "rain_probability": round(rain_prob, 1),
                "temperature": round(temp, 1),
                "wind_speed": round(wind, 1),
                "score": round(score, 1),
                "hour": hour,
            }
        )
    if not candidates:
        return None
    best = min(candidates, key=lambda item: item["score"])
    best["label"] = f"{date_label}{best['start']}–{best['end']}"
    best["advice"] = (
        "适合出门"
        if best["rain_probability"] < 30 and 10 <= best["temperature"] <= 30
        else "可以出门，注意天气变化"
        if best["rain_probability"] < 55
        else "不太适合长时间户外活动"
    )
    return best


def get_weather(
    ctx: ToolContext,
    city: str = DEFAULT_CITY,
    when: str = "today",
    preferred_hour: int | None = None,
) -> dict[str, Any]:
    when = when if when in {"today", "tomorrow", "dayafter"} else "today"
    offset = {"today": 0, "tomorrow": 1, "dayafter": 2}[when]
    label_map = {"today": "今天", "tomorrow": "明天", "dayafter": "后天"}
    payload, stale = fetch_weather(city, when)
    location = geocode(city)
    today = now_local().date()
    target_date = today + timedelta(days=offset)
    daily = _daily_at(payload, offset)
    rows = _hourly_rows(payload, target_date.isoformat())

    current = None
    if offset == 0:
        cur = payload.get("current") or {}
        code = cur.get("weather_code")
        desc, icon = describe_code(code)
        current = {
            "time": cur.get("time"),
            "temperature": cur.get("temperature_2m"),
            "apparent": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"),
            "precipitation": cur.get("precipitation"),
            "weather_code": code,
            "weather": desc,
            "icon": icon,
            "wind_speed": cur.get("wind_speed_10m"),
        }

    # 只保留当前时刻之后的小时（今天）
    now_hour = now_local().hour
    if offset == 0:
        rows = [r for r in rows if r["hour"] >= max(0, now_hour - 1)]
        if not rows:
            rows = _hourly_rows(payload, target_date.isoformat())
    window = best_window(
        rows,
        preferred_hour=preferred_hour,
        date_label="今天" if offset == 0 else label_map[when],
    )

    date_label = f"{label_map[when]}（{target_date.month}月{target_date.day}日）"
    ctx.citations.append(
        {
            "type": "weather",
            "title": "Open-Meteo 实时天气",
            "url": "https://open-meteo.com/",
            "time": (current or {}).get("time") or now_local().isoformat(timespec="minutes"),
        }
    )

    data = {
        "city": location["name"],
        "admin": location["admin1"],
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "timezone": location["timezone"],
        "when": when,
        "date": target_date.isoformat(),
        "date_label": date_label,
        "current": current,
        "daily": daily,
        "hourly": rows[:14],
        "best_window": window,
        "stale_cache": stale,
        "source": "Open-Meteo",
        "fetched_at": now_local().isoformat(timespec="minutes"),
    }
    current_text = ""
    if current and current.get("temperature") is not None:
        current_text = (
            f"此刻 {current['temperature']}℃，体感 {current['apparent']}℃，"
            f"{current['weather']}"
        )
    data["_summary"] = (
        f"{location['name']}{date_label}：{current_text or daily['weather']}，"
        f"{daily['temp_min']}–{daily['temp_max']}℃。"
    )
    return data


def air_quality(ctx: ToolContext, city: str = DEFAULT_CITY) -> dict[str, Any]:
    location = geocode(city)
    payload = _http_json(
        AIR_QUALITY_URL,
        {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": "pm2_5,pm10,us_aqi",
            "timezone": "Asia/Shanghai",
        },
        AIR_QUALITY_FALLBACK_URL,
    )
    current = payload.get("current") or {}
    aqi = current.get("us_aqi")
    level = "未知"
    if isinstance(aqi, (int, float)):
        if aqi <= 50:
            level = "优"
        elif aqi <= 100:
            level = "良"
        elif aqi <= 150:
            level = "轻度污染"
        else:
            level = "中重度污染"
    data = {
        "city": location["name"],
        "time": current.get("time"),
        "us_aqi": aqi,
        "pm2_5": current.get("pm2_5"),
        "pm10": current.get("pm10"),
        "level": level,
        "source": "Open-Meteo Air Quality",
        "_summary": f"{location['name']}空气质量 {level}（US AQI {aqi}）。",
    }
    ctx.citations.append(
        {
            "type": "air",
            "title": "Open-Meteo 空气质量",
            "url": "https://open-meteo.com/en/docs/air-quality-api",
            "time": current.get("time") or "",
        }
    )
    return data


def register(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="weather.get",
            description="查询指定城市今天/明天/后天的实时天气、逐小时降水概率、气温与最佳外出窗口。",
            category="weather",
            params=[
                ToolParam("city", "string", "城市名，默认郑州", required=False, default=DEFAULT_CITY),
                ToolParam(
                    "when",
                    "string",
                    "today / tomorrow / dayafter，默认 today",
                    required=False,
                    default="today",
                ),
                ToolParam("preferred_hour", "integer", "用户希望出门的小时（0-23）", required=False),
            ],
            handler=get_weather,
            timeout_s=15,
        )
    )
    registry.register(
        ToolSpec(
            name="weather.air_quality",
            description="查询城市当前空气质量（US AQI、PM2.5、PM10）。",
            category="weather",
            params=[
                ToolParam("city", "string", "城市名，默认郑州", required=False, default=DEFAULT_CITY)
            ],
            handler=air_quality,
            timeout_s=15,
        )
    )
