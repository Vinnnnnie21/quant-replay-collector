"""Decide the shadow: with the new LOCAL button stylesheet, does a drop shadow
preserve the button's background fill (or strip it like before)?

In the real window tree:
  1. after apply_main_window_theme  -> button interior should be dark-grey #202024
  2. after adding a drop shadow      -> still #202024 (safe) or #000000 (stripped)

Run from D:\\Trading:
    .\\.venv\\Scripts\\python.exe theme_button_probe4.py
"""

import sys

from pathlib import Path as _ProbeRoot
_ROOT = _ProbeRoot(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "quant_collector_app"))
sys.path.insert(0, str(_ROOT / "tests"))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from app_config import THEME_PRESETS  # noqa: E402
import views.main_window_presentation as presentation  # noqa: E402
from views.main_window_layout import build_main_window_ui  # noqa: E402
from test_main_window_layout import _LayoutHost  # noqa: E402


def interior(host, btn) -> str:
    # a point inside the button, left of centre (away from the text glyph)
    p = btn.mapTo(host, QtCore.QPoint(12, btn.height() // 2))
    return host.grab().toImage().pixelColor(p).name()


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    host = _LayoutHost()
    build_main_window_ui(host)
    presentation.apply_main_window_theme(host, THEME_PRESETS["OKX 暗色"])
    host.resize(1400, 900)
    host.show()
    app.processEvents()

    b = host.btnLoadPlay
    print("1) dark-grey local style only :", interior(host, b), "(expect ~#202024)")

    eff = QtWidgets.QGraphicsDropShadowEffect(b)
    eff.setBlurRadius(18)
    eff.setXOffset(0)
    eff.setYOffset(3)
    eff.setColor(QtGui.QColor(0, 0, 0, 160))
    b.setGraphicsEffect(eff)
    app.processEvents()
    print("2) after adding drop shadow    :", interior(host, b),
          "(#202024 = shadow safe; #000000 = shadow strips bg)")

    try:
        host.multiTimeframePanel.shutdown()
    except Exception:
        pass
    host.close()


if __name__ == "__main__":
    main()
