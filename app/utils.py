"""通用工具函数。"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import TIMEZONE


def now_local() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def today_str() -> str:
    return now_local().strftime("%Y-%m-%d")


def stamp() -> str:
    return now_local().strftime("%Y%m%d_%H%M%S")


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        # utf-8-sig 兼容 Windows 编辑器/PowerShell 可能写入的 BOM
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_filename(name: str, fallback: str = "文档") -> str:
    """去掉 Windows 不允许的字符，并限制长度。"""
    name = unicodedata.normalize("NFKC", str(name or "")).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or fallback)[:80]


def mask_sensitive(text: str) -> str:
    """对手机号、身份证号做展示级脱敏。"""
    text = re.sub(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)", r"\1****\3", text)
    text = re.sub(r"(?<!\d)(\d{6})(\d{8})(\d{4})(?!\d)", r"\1********\3", text)
    return text


def compact_text(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_iso_minutes(value: str) -> int:
    """把 '18:30' / '2026-11-12 08:00' 转成分钟，用于时间窗比较。"""
    m = re.search(r"(\d{1,2}):(\d{2})", value or "")
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2))


def cn_date(dt: datetime | None = None) -> str:
    dt = dt or now_local()
    week = "一二三四五六日"[dt.weekday()]
    return f"{dt.year}年{dt.month}月{dt.day}日（周{week}）"
