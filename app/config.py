"""全局配置：路径、默认值、外部接口。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "晴雨校园助手"
APP_VERSION = "1.0.0"
APP_SLOGAN = "查天气 · 给建议 · 填表单 · 答校务"

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：可写数据与 web 资源放在 exe 同级目录
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TEMPLATE_DIR = DATA_DIR / "templates"
RUNTIME_DIR = DATA_DIR / "runtime"
OUTPUT_DIR = RUNTIME_DIR / "outputs"
CACHE_DIR = RUNTIME_DIR / "cache"
DB_PATH = RUNTIME_DIR / "memory.sqlite3"
FAQ_PATH = DATA_DIR / "campus_faq.json"
WEB_DIR = ROOT / "web"

DEFAULT_CITY = "郑州"
DEFAULT_CAMPUS = "郑州大学主校区"
TIMEZONE = "Asia/Shanghai"

# 公网只读天气接口：HTTP 优先（TLS 握手在部分校园网下不稳定），HTTPS 兜底。
GEOCODING_URL = "http://geocoding-api.open-meteo.com/v1/search"
GEOCODING_FALLBACK_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "http://api.open-meteo.com/v1/forecast"
FORECAST_FALLBACK_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "http://air-quality-api.open-meteo.com/v1/air-quality"
AIR_QUALITY_FALLBACK_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

WEATHER_CACHE_TTL = 600          # 实时天气缓存 10 分钟
GEOCODE_CACHE_TTL = 24 * 3600    # 地名缓存 24 小时
HTTP_TIMEOUT = 9

def _load_local_env() -> None:
    """无第三方依赖地读取项目根目录 .env；不覆盖已有环境变量。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                os.environ.setdefault(key, value)
    except OSError:
        pass


_load_local_env()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
LLM_PLANNER_ENABLED = (
    os.getenv("LLM_PLANNER", "true").strip().lower() not in {"0", "false", "no"}
    and bool(DEEPSEEK_API_KEY)
)
LLM_TIMEOUT = 30

for _p in (DATA_DIR, TEMPLATE_DIR, RUNTIME_DIR, OUTPUT_DIR, CACHE_DIR):
    _p.mkdir(parents=True, exist_ok=True)
