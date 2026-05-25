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
MODULES = [
    "app_config",
    "app_logger",
    "storage",
    "market_data.types",
    "market_data.client",
    "market_data.cache",
    "market_data.loader",
    "market_data.quality",
    "market_data.transforms",
    "market_data.features",
    "workers.loader_worker",
    "exporter",
    "analysis.feature_engineering",
    "backtesting.engine",
    "analysis_workspace",
    "backtest_panel",
    "strategy_consistency_panel",
    "api_server",
    "main_app",
]
MARKER = "__QRC_IMPORT_PROFILE__"


def _probe_module(module_name: str) -> dict:
    code = (
        "import importlib,json,time,traceback\n"
        f"start=time.perf_counter()\n"
        "try:\n"
        f" importlib.import_module({module_name!r})\n"
        " result={'ok':True,'error':None}\n"
        "except Exception as exc:\n"
        " result={'ok':False,'error':f'{type(exc).__name__}: {exc}'}\n"
        "result['import_seconds']=time.perf_counter()-start\n"
        f"print({MARKER!r}+json.dumps(result))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    wall_start = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    wall_seconds = time.perf_counter() - wall_start
    result = {"module": module_name, "wall_seconds": wall_seconds, "return_code": completed.returncode}
    payload = None
    for line in completed.stdout.splitlines():
        if line.startswith(MARKER):
            payload = json.loads(line[len(MARKER):])
    if payload is None:
        payload = {
            "ok": False,
            "error": (completed.stderr or completed.stdout or "probe produced no result").strip()[-500:],
            "import_seconds": None,
        }
    result.update(payload)
    return result


def write_reports(results: list[dict]) -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": sys.executable,
        "modules": results,
        "successful_import_count": sum(1 for row in results if row["ok"]),
        "failed_import_count": sum(1 for row in results if not row["ok"]),
    }
    (REPORT_DIR / "import_profile.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Import Profile",
        "",
        f"- Python: `{sys.executable}`",
        f"- Successful imports: {report['successful_import_count']}",
        f"- Failed imports: {report['failed_import_count']}",
        "",
        "| Module | Status | Import ms | Process ms | Error |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in results:
        import_ms = "-" if row["import_seconds"] is None else f"{row['import_seconds'] * 1000:.2f}"
        error = (row.get("error") or "").replace("|", "/")
        lines.append(
            f"| `{row['module']}` | {'OK' if row['ok'] else 'FAILED'} | "
            f"{import_ms} | {row['wall_seconds'] * 1000:.2f} | {error} |"
        )
    (REPORT_DIR / "import_profile.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    results = [_probe_module(module_name) for module_name in MODULES]
    report = write_reports(results)
    print(f"Import profile written to: {REPORT_DIR / 'import_profile.json'}")
    if report["failed_import_count"]:
        print("Some imports failed; see the report for missing dependencies or import-time errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
