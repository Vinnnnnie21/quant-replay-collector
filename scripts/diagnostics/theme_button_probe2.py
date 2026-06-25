"""Minimal repro + experiment: which QSS makes a QPushButton actually paint white?

Creates standalone buttons on a black parent with different stylesheets, renders
them, and samples a CORNER pixel (background area, away from the text glyph). The
variant whose corner is #ffffff is the writing that actually fills the button.

Run from D:\\Trading:
    .\\.venv\\Scripts\\python.exe theme_button_probe2.py
"""

import sys

from PySide6 import QtCore, QtGui, QtWidgets


VARIANTS = {
    "A_current(bgcolor+whiteBorder+radius)":
        "QPushButton{background-color:#FFFFFF;color:#0B0B0C;border:1px solid #FFFFFF;border-radius:14px;padding:5px 14px;}",
    "B_background_shorthand":
        "QPushButton{background:#FFFFFF;color:#0B0B0C;border:1px solid #CCCCCC;border-radius:14px;padding:5px 14px;}",
    "C_no_border":
        "QPushButton{background-color:#FFFFFF;color:#0B0B0C;border-radius:14px;padding:5px 14px;}",
    "D_bgcolor_only":
        "QPushButton{background-color:#FFFFFF;color:#0B0B0C;}",
    "E_current+outline_none":
        "QPushButton{background-color:#FFFFFF;color:#0B0B0C;border:1px solid #FFFFFF;border-radius:14px;padding:5px 14px;outline:none;}",
    "F_border_style_explicit":
        "QPushButton{background-color:#FFFFFF;color:#0B0B0C;border-style:solid;border-width:1px;border-color:#FFFFFF;border-radius:14px;padding:5px 14px;}",
}


def corner_pixel(btn) -> str:
    img = btn.grab().toImage()
    # sample a few px in from the top-left corner (inside the border, away from text)
    return img.pixelColor(6, 6).name()


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    QtWidgets.QApplication.setStyle("Fusion")
    print("style:", app.style().objectName())

    # Mimic the app: palette Button = black.
    pal = app.palette()
    pal.setColor(QtGui.QPalette.Button, QtGui.QColor("#000000"))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#EAECEF"))
    app.setPalette(pal)

    container = QtWidgets.QWidget()
    container.setStyleSheet("background:#000000;")
    lay = QtWidgets.QVBoxLayout(container)
    buttons = {}
    for name, qss in VARIANTS.items():
        b = QtWidgets.QPushButton("开多")
        b.setStyleSheet(qss)
        b.setMinimumHeight(34)
        lay.addWidget(b)
        buttons[name] = b
    container.resize(360, 360)
    container.show()
    app.processEvents()

    print("\n=== corner pixel (#ffffff means the white fill actually paints) ===")
    for name, b in buttons.items():
        print(f"  {name:42s} -> {corner_pixel(b)}")

    container.close()


if __name__ == "__main__":
    main()
