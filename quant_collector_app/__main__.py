from __future__ import annotations

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def main() -> int:
    try:
        from main_app import main as launch
    except ModuleNotFoundError as exc:
        if exc.name in {"PySide6", "pyqtgraph", "pandas", "numpy", "requests"}:
            raise SystemExit(
                f"Missing dependency: {exc.name}. "
                "Install requirements with: python -m pip install -r quant_collector_app/requirements.txt"
            ) from exc
        raise
    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
