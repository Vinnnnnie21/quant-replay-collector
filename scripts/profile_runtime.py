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
MARKER = "__QRC_RUNTIME_PROFILE__"


PROBE = r"""
import json
import time
import tracemalloc
import traceback

result = {"ok": False, "render_samples": [], "error": None}
try:
    import numpy as np
    from PySide6 import QtWidgets
    from market_data import CandlestickItem, VolumeItem
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tracemalloc.start()
    for count in (1000, 10000, 50000):
        x = np.arange(count, dtype=float)
        close = 100.0 + np.sin(x / 10.0)
        open_price = close - 0.05
        high = close + 0.2
        low = close - 0.2
        volume = 1000.0 + (x % 100)
        up = close >= open_price
        candles = CandlestickItem()
        volumes = VolumeItem()
        start = time.perf_counter()
        candles.set_data(x, open_price, high, low, close)
        volumes.set_data(x, volume, up)
        app.processEvents()
        elapsed = time.perf_counter() - start
        current, peak = tracemalloc.get_traced_memory()
        result["render_samples"].append({
            "bars": count,
            "seconds": elapsed,
            "current_memory_bytes": current,
            "peak_memory_bytes": peak,
        })
    tracemalloc.stop()
    result["ok"] = True
except Exception as exc:
    result["error"] = f"{type(exc).__name__}: {exc}"
    result["traceback"] = traceback.format_exc(limit=5)
print("__QRC_RUNTIME_PROFILE__" + json.dumps(result))
"""


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
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
    result = None
    for line in completed.stdout.splitlines():
        if line.startswith(MARKER):
            result = json.loads(line[len(MARKER):])
    if result is None:
        result = {"ok": False, "render_samples": [], "error": (completed.stderr or completed.stdout).strip()[-1000:]}
    result.update(
        {
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "python": sys.executable,
            "process_wall_seconds": time.perf_counter() - wall_start,
        }
    )
    (REPORT_DIR / "runtime_profile.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = ["# Runtime Profile", "", f"- Status: {'OK' if result['ok'] else 'FAILED'}"]
    if result.get("error"):
        lines.append(f"- Error: `{result['error']}`")
    lines.extend(["", "| Bars | Render ms | Peak MiB |", "| ---: | ---: | ---: |"])
    for row in result.get("render_samples", []):
        lines.append(f"| {row['bars']} | {row['seconds'] * 1000:.2f} | {row['peak_memory_bytes'] / 1048576:.2f} |")
    (REPORT_DIR / "runtime_profile.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Runtime profile written to: {REPORT_DIR / 'runtime_profile.json'}")
    if not result["ok"]:
        print(f"Runtime probe unavailable: {result.get('error', 'unknown error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
