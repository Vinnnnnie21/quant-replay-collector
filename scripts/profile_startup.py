from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"
REPORT_DIR = ROOT / "performance_reports"
MARKER = "__QRC_STARTUP_PROFILE__"


PROBE = r"""
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

result = {"ok": False, "steps": {}, "error": None, "optional_modules_deferred": [], "unexpected_optional_modules_loaded": []}
start = time.perf_counter()
try:
    qt_start = time.perf_counter()
    from PySide6 import QtWidgets
    result["steps"]["qt_import_seconds"] = time.perf_counter() - qt_start

    app_start = time.perf_counter()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    result["steps"]["qapplication_seconds"] = time.perf_counter() - app_start

    config_start = time.perf_counter()
    import app_config
    result["steps"]["app_config_import_seconds"] = time.perf_counter() - config_start

    import startup
    with tempfile.TemporaryDirectory(prefix="qrc_runtime_profile_") as runtime_temp:
        runtime_root = Path(runtime_temp)
        startup.DATA_DIR = runtime_root / "data"
        startup.CACHE_DIR = runtime_root / "cache"
        startup.EXPORT_DIR = runtime_root / "exports"
        startup.LOG_DIR = runtime_root / "logs"
        runtime_start = time.perf_counter()
        startup.bootstrap_runtime_dirs()
        result["steps"]["runtime_dirs_init_seconds"] = time.perf_counter() - runtime_start

    theme_start = time.perf_counter()
    app_config.load_theme_settings()
    result["steps"]["theme_load_seconds"] = time.perf_counter() - theme_start

    from storage import StorageManager
    with tempfile.TemporaryDirectory(prefix="qrc_profile_") as temp_dir:
        db_path = Path(temp_dir) / "startup.db"
        import app_logger
        app_logger.LOG_FILE = Path(temp_dir) / "profile.log"
        app_logger._ACTIVE_LOG_FILE = app_logger.LOG_FILE
        logging_start = time.perf_counter()
        app_logger.setup_logging()
        result["steps"]["logging_init_seconds"] = time.perf_counter() - logging_start
        storage_start = time.perf_counter()
        storage = StorageManager(db_path)
        result["steps"]["storage_init_seconds"] = time.perf_counter() - storage_start

        import main_app
        main_app.StorageManager = lambda: StorageManager(db_path)
        main_app.save_theme_settings = lambda _theme: None
        main_app.load_theme_settings = lambda: dict(main_app.DEFAULT_THEME)

        premium_method = main_app.MainWindow.request_premium_sample
        main_app.MainWindow.request_premium_sample = lambda self: None
        window_start = time.perf_counter()
        window = main_app.MainWindow()
        result["steps"]["main_window_init_seconds"] = time.perf_counter() - window_start
        main_app.MainWindow.request_premium_sample = premium_method

        from lazy_imports import deferred_module_names
        for name in deferred_module_names():
            if name in sys.modules:
                result["unexpected_optional_modules_loaded"].append(name)
            else:
                result["optional_modules_deferred"].append(name)

        render_start = time.perf_counter()
        window._render(force=True)
        result["steps"]["first_render_seconds"] = time.perf_counter() - render_start
        window.close()
        app.processEvents()
        import logging
        logging.shutdown()
    result["ok"] = True
except Exception as exc:
    result["error"] = f"{type(exc).__name__}: {exc}"
    result["traceback"] = traceback.format_exc(limit=5)
result["cold_probe_seconds"] = time.perf_counter() - start
print("__QRC_STARTUP_PROFILE__" + json.dumps(result))
"""


def run_probe() -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    wall_start = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    wall_seconds = time.perf_counter() - wall_start
    result = None
    for line in completed.stdout.splitlines():
        if line.startswith(MARKER):
            result = json.loads(line[len(MARKER):])
    if result is None:
        result = {
            "ok": False,
            "steps": {},
            "error": (completed.stderr or completed.stdout or "probe produced no result").strip()[-1000:],
        }
    result["process_wall_seconds"] = wall_seconds
    result["return_code"] = completed.returncode
    return result


def write_reports(result: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": sys.executable,
        **result,
    }
    (REPORT_DIR / "startup_profile.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Startup Profile",
        "",
        f"- Python: `{sys.executable}`",
        f"- Status: {'OK' if result.get('ok') else 'FAILED'}",
        f"- Cold process wall time: {result.get('process_wall_seconds', 0) * 1000:.2f} ms",
    ]
    if result.get("error"):
        lines.append(f"- Error: `{result['error']}`")
    lines.extend(
        [
            f"- Deferred optional modules: `{', '.join(result.get('optional_modules_deferred', [])) or 'none'}`",
            f"- Unexpected optional imports: `{', '.join(result.get('unexpected_optional_modules_loaded', [])) or 'none'}`",
        ]
    )
    lines.extend(["", "| Step | Time ms |", "| --- | ---: |"])
    for name, seconds in result.get("steps", {}).items():
        lines.append(f"| `{name}` | {seconds * 1000:.2f} |")
    (REPORT_DIR / "startup_profile.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    result = run_probe()
    write_reports(result)
    print(f"Startup profile written to: {REPORT_DIR / 'startup_profile.json'}")
    if not result.get("ok"):
        print(f"Startup probe unavailable: {result.get('error', 'unknown error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
