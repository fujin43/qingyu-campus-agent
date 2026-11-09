"""晴雨校园助手启动脚本。

用法：
    python run.py
    python run.py --port 8765 --open
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# pythonw / 无控制台启动时，把 stdout/stderr 落到文件，便于排查崩溃
if sys.stdout is None or sys.stderr is None:
    log_dir = ROOT / "data" / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    _log = open(log_dir / "server.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = _log
    sys.stderr = _log

from app.server import main  # noqa: E402

if __name__ == "__main__":
    # Windows 免安装版：默认监听局域网并自动打开浏览器
    if getattr(sys, "frozen", False):
        if "--host" not in sys.argv:
            sys.argv += ["--host", "0.0.0.0"]
        if "--open" not in sys.argv:
            sys.argv += ["--open"]
    try:
        main()
    except BaseException:
        traceback.print_exc()
        raise
