"""Pin the fix: in the REAL window tree, does the global role QSS fail to paint the
button background, and which remedy restores it?

Samples a CORNER pixel (background, away from text) of a neutral button:
  1. as-is (global role QSS only)        -> expected: dark (the bug)
  2. after unpolish/polish               -> does a re-polish fix it?
  3. after setting a LOCAL stylesheet     -> expected: white (proven remedy)

Run from D:\\Trading:
    .\\.venv\\Scripts\\python.exe theme_button_probe3.py
"""

import sys

from pathlib import Path as _ProbeRoot
_ROOT = _ProbeRoot(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "quant_collector_app"))
sys.path.insert(0, str(_ROOT / "tests"))

from PySide6 import QtWidgets  # noqa: E402

from app_config import THEME_PRESETS  # noqa: E402
import views.main_window_presentation as presentation  # noqa: E402
from views.main_window_layout import build_main_window_ui  # noqa: E402
from test_main_window_layout import _LayoutHost  # noqa: E402


def corner(btn) -> str:
    img = btn.grab().toImage()
    return img.pixelColor(8, 8).name()


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    host = _LayoutHost()
    build_main_window_ui(host)
    presentation.apply_main_window_theme(host, THEME_PRESETS["OKX 暗色"])
    host.resize(1400, 900)
    host.show()
    app.processEvents()

    b = host.btnLoadPlay  # primaryButton
    print("1) global role QSS only      :", corner(b))

    st = b.style()
    if st is not None:
        st.unpolish(b)
        st.polish(b)
    b.update()
    app.processEvents()
    print("2) after unpolish/polish     :", corner(b))

    b.setStyleSheet(
        "QPushButton{background-color:#FFFFFF;color:#0B0B0C;"
        "border:1px solid #FFFFFF;border-radius:14px;padding:5px 14px;}"
    )
    app.processEvents()
    print("3) after LOCAL stylesheet    :", corner(b))

    try:
        host.multiTimeframePanel.shutdown()
    except Exception:
        pass
    host.close()


if __name__ == "__main__":
    main()
