"""Runtime probe: why are OKX role buttons not painting their white QSS background?

Builds the real main-window UI, applies the OKX dark theme, then for a few role
buttons prints the facts that decide the cause:
  - role property (must be primaryButton/secondaryButton/successButton/...)
  - local styleSheet (should be empty; non-empty means an override)
  - graphicsEffect (should be None; non-None means an effect strips the bg)
  - autoFillBackground + palette Button colour
  - the ACTUAL rendered centre pixel of the button (ground truth)

Run from D:\\Trading:
    .\\.venv\\Scripts\\python.exe theme_button_probe.py
"""

import sys

from pathlib import Path as _ProbeRoot
_ROOT = _ProbeRoot(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "quant_collector_app"))
sys.path.insert(0, str(_ROOT / "tests"))

from PySide6 import QtGui, QtWidgets  # noqa: E402

from app_config import THEME_PRESETS  # noqa: E402
import views.main_window_presentation as presentation  # noqa: E402
from views.main_window_layout import build_main_window_ui  # noqa: E402
from test_main_window_layout import _LayoutHost  # noqa: E402


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    print("Qt style in use:", app.style().objectName())

    host = _LayoutHost()
    build_main_window_ui(host)
    okx = THEME_PRESETS["OKX 暗色"]
    presentation.apply_main_window_theme(host, okx)
    host.resize(1400, 900)
    host.show()
    app.processEvents()

    print("active theme name:", host.theme_settings.get("name"))
    print("active btn_bg:", host.theme_settings.get("btn_bg"))

    for name in ("btnApplyMarket", "btnLoadPlay", "btnStep", "btnOpenLong", "btnOpenShort"):
        b = getattr(host, name, None)
        if b is None:
            print(f"--- {name}: MISSING")
            continue
        try:
            img = b.grab().toImage()
            px = img.pixelColor(b.width() // 2, b.height() // 2).name()
        except Exception as exc:  # pragma: no cover
            px = f"<grab failed: {exc!r}>"
        print(f"--- {name}")
        print("   class            :", type(b).__name__)
        print("   role             :", b.property("role"))
        print("   localStyleSheet  :", repr(b.styleSheet()))
        print("   graphicsEffect   :", b.graphicsEffect())
        print("   autoFillBg       :", b.autoFillBackground())
        print("   palette Button   :", b.palette().color(QtGui.QPalette.Button).name())
        print("   RENDERED CENTRE  :", px)

    try:
        host.multiTimeframePanel.shutdown()
    except Exception:
        pass
    host.close()


if __name__ == "__main__":
    main()
