from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"
OUTPUT_DIR = ROOT / "docs" / "screenshots"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for path in (ROOT, APP_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PySide6 import QtCore, QtWidgets

import main_app
from ui_style import OKX_DARK_THEME
import views.main_window_presentation as presentation


_load_app_settings = main_app.load_app_settings


def _screenshot_app_settings() -> dict:
    settings = _load_app_settings()
    settings["render_backend"] = "software"
    return settings


main_app.load_app_settings = _screenshot_app_settings
presentation.save_theme_settings = lambda _theme: None
MainWindow = main_app.MainWindow


def _settle(milliseconds: int = 900) -> None:
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _save(window: QtWidgets.QWidget, filename: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / filename
    pixmap = window.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"Failed to capture {target}")
    return target


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow()
    window.resize(1600, 900)
    window.apply_theme(OKX_DARK_THEME)
    window.show()
    _settle(1200)

    window.load_data()
    for _ in range(30):
        _settle(500)
        if not window._loading_data:
            break
    if not window.df.empty:
        window.df = window.df.tail(2000).reset_index(drop=True)
        window.cursor = len(window.df) - 1
        window.replay_controller.load_state(window.cursor, False, False, 0.0)
        window._render(force=True)
        _settle(1200)

    captured = [_save(window, "qrc-replay-workspace.png")]

    window.open_analysis_workspace()
    _settle(1200)
    analysis = window._analysis_workspace
    analysis.tabs.setCurrentWidget(analysis.performanceTab)
    _settle()
    captured.append(_save(window, "qrc-analysis-workspace.png"))

    analysis.tabs.setCurrentWidget(analysis.consistencyTab)
    window.strategyConsistencyPanel.run_audit()
    _settle()
    captured.append(_save(window, "qrc-consistency-audit.png"))

    analysis.tabs.setCurrentWidget(analysis.timeSeriesTab)
    analysis.run_time_series_diagnostics()
    _settle()
    captured.append(_save(window, "qrc-time-series-analysis.png"))

    window.close()
    app.processEvents()

    for path in captured:
        print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
