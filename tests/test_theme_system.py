from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import app_config
from ui_style import (
    COLORS,
    EXCHANGE_DARK_THEME,
    THEME_SCHEMA_VERSION,
    build_app_qss,
    normalize_theme_settings,
    style_danger_button,
    style_danger_ghost_button,
    style_primary_button,
    style_success_button,
)


# Canonical "Claude 暗色" neutral palette (the default COLORS in ui_style.py).
# OKX 暗色 is a separate selectable preset and is covered in test_okx_theme_preset.py.
REFERENCE_COLORS = {
    "bg_primary": "#1F1F1E",
    "bg_secondary": "#262626",
    "bg_tertiary": "#2C2C2A",
    "bg_card": "#2A2A28",
    "bg_input": "#1C1C1A",
    "bg_hover": "#31312F",
    "bg_pressed": "#181816",
    "border_default": "#3A3733",
    "border_strong": "#4A4742",
    "divider": "#2E2D2B",
    "text_primary": "#F6F6F4",
    "text_secondary": "#B5B3AD",
    "text_tertiary": "#8F8D83",
    "text_disabled": "#5C5A55",
    "accent": "#7A7772",
    "accent_hover": "#8E8B86",
    "accent_soft": "#22211F",
    "focus": "#6B6863",
    "success": "#22C55E",
    "success_soft": "#123522",
    "danger": "#EF4444",
    "danger_soft": "#3A1719",
    "warning": "#F59E0B",
    "warning_soft": "#39280D",
    "info": "#3B82F6",
    "selection": "#2E2E2C",
    "chart_bg": "#1F1F1E",
    "chart_up": "#22C55E",
    "chart_down": "#EF4444",
    "chart_volume_up": "#198C48",
    "chart_volume_down": "#AF3434",
    "chart_grid": "#2E2D2B",
    "chart_axis": "#6B6863",
    "chart_crosshair": "#8C8983",
    "chart_wick": "#B0ADA7",
}


def _qss_block(qss: str, selector: str) -> str:
    start = qss.index(selector)
    end = qss.index("}", start)
    return qss[start:end]


def test_reference_theme_tokens_are_present_and_separated():
    for key, expected in REFERENCE_COLORS.items():
        assert COLORS[key] == expected

    assert THEME_SCHEMA_VERSION == 3
    assert COLORS["accent"] != COLORS["warning"]
    assert COLORS["accent"] != COLORS["selection"]
    assert COLORS["chart_crosshair"] != COLORS["accent"]
    assert COLORS["warning"] != COLORS["accent"]
    assert COLORS["info"] == "#3B82F6"


def test_qss_uses_neutral_selection_and_limited_accent_usage():
    qss = build_app_qss(EXCHANGE_DARK_THEME)

    for old_value in ("#F0B90B", "rgb(240, 185, 11)", "rgba(240,185,11", "#2D7DFF"):
        assert old_value not in qss

    button = _qss_block(qss, "QPushButton {")
    assert f"background-color: {COLORS['bg_card']}" in button
    assert f"border: 1px solid {COLORS['border_default']}" in button
    assert COLORS["accent"] not in button

    table_selected = _qss_block(qss, "QTableWidget::item:selected")
    assert COLORS["selection"] in table_selected
    assert COLORS["accent"] not in table_selected

    tab_selected = _qss_block(qss, "QTabBar::tab:selected")
    assert f"border-bottom: 2px solid {COLORS['accent']}" in tab_selected
    assert f"background-color: {COLORS['accent']}" not in tab_selected

    slider_subpage = _qss_block(qss, "QSlider::sub-page:horizontal")
    slider_addpage = _qss_block(qss, "QSlider::add-page:horizontal")
    slider_handle = _qss_block(qss, "QSlider::handle:horizontal")
    assert COLORS["focus"] in slider_subpage
    assert COLORS["divider"] in slider_addpage
    assert COLORS["text_secondary"] in slider_handle
    assert COLORS["accent"] not in slider_subpage


def test_qss_uses_root_background_and_explicit_container_roles():
    custom_theme = dict(EXCHANGE_DARK_THEME)
    custom_theme.update(
        {
            "theme_schema_version": THEME_SCHEMA_VERSION,
            "bg_primary": "#101820",
            "bg_secondary": "#203040",
            "bg_tertiary": "#304050",
            "bg_card": "#405060",
            "bg_input": "#102030",
            "border_default": "#506070",
            "divider": "#607080",
            "text_primary": "#DDEEFF",
            "selection": "#223344",
            "accent": "#AA8844",
        }
    )
    qss = build_app_qss(custom_theme)

    widget = _qss_block(qss, "QWidget {")
    assert "background-color" not in widget
    assert "QMainWindow," in qss
    assert "QWidget#appRoot" in qss

    assert "#203040" in _qss_block(qss, 'QFrame[role="header"]')
    assert "#203040" in _qss_block(qss, 'QFrame[role="sidebar"]')
    assert "#304050" in _qss_block(qss, 'QGroupBox[role="sideSection"]')
    assert "#405060" in _qss_block(qss, 'QFrame[role="statusBlock"]')
    assert "#102030" in _qss_block(qss, "QLineEdit,")
    assert "#506070" in _qss_block(qss, 'QGroupBox[role="sideSection"]')
    assert "#607080" in _qss_block(qss, "QSplitter::handle")


def test_button_role_styles_use_reference_semantics():
    primary = style_primary_button()
    success = style_success_button()
    danger = style_danger_button()
    danger_ghost = style_danger_ghost_button()

    assert f"background-color: {COLORS['bg_tertiary']}" in primary
    assert f"border: 1px solid {COLORS['border_strong']}" in primary
    assert f"border-color: {COLORS['accent']}" in primary
    assert f"background-color: {COLORS['accent']}" not in primary

    assert COLORS["success_soft"] in success
    assert COLORS["success"] in success
    assert COLORS["danger_soft"] in danger
    assert COLORS["danger"] in danger
    assert "transparent" in danger_ghost
    assert COLORS["accent"] not in danger_ghost


def test_theme_normalization_migrates_old_or_invalid_runtime_settings():
    legacy = normalize_theme_settings(
        {
            "name": EXCHANGE_DARK_THEME["name"],
            "window_bg": "#F0B90B",
            "panel_bg": "#C89B3C",
            "grid": "#C89B3C",
            "crosshair": "#C89B3C",
        }
    )

    assert legacy["theme_schema_version"] == THEME_SCHEMA_VERSION
    assert legacy["window_bg"] == COLORS["bg_primary"]
    assert legacy["panel_bg"] == COLORS["bg_secondary"]
    assert legacy["grid"] == COLORS["chart_grid"]
    assert legacy["crosshair"] == COLORS["chart_crosshair"]

    invalid = normalize_theme_settings(
        {
            "theme_schema_version": THEME_SCHEMA_VERSION,
            "name": EXCHANGE_DARK_THEME["name"],
            "window_bg": "not-a-color",
            "panel_bg": "#121820",
            "grid_alpha": 999,
        }
    )
    assert invalid["window_bg"] == COLORS["bg_primary"]
    assert invalid["bg_primary"] == COLORS["bg_primary"]
    assert invalid["panel_bg"] == "#121820"
    assert invalid["bg_secondary"] == "#121820"
    assert invalid["grid_alpha"] <= 20

    v2 = normalize_theme_settings(
        {
            "theme_schema_version": 2,
            "name": EXCHANGE_DARK_THEME["name"],
            "panel_bg": "#223344",
            "panel_bg_alt": "#334455",
            "base_bg": "#101112",
            "grid": "#445566",
        }
    )
    assert v2["theme_schema_version"] == THEME_SCHEMA_VERSION
    assert v2["bg_secondary"] == "#223344"
    assert v2["bg_card"] == "#334455"
    assert v2["chart_bg"] == "#101112"
    assert v2["chart_grid"] == "#445566"


def test_load_and_save_theme_settings_normalizes_runtime_json(tmp_path, monkeypatch):
    path = tmp_path / "theme_settings.json"
    path.write_text(json.dumps({"name": EXCHANGE_DARK_THEME["name"], "window_bg": "#F0B90B"}), encoding="utf-8")
    monkeypatch.setattr(app_config, "THEME_CONFIG_PATH", path)

    loaded = app_config.load_theme_settings()
    app_config.save_theme_settings(loaded)
    reloaded = app_config.load_theme_settings()

    assert loaded["theme_schema_version"] == THEME_SCHEMA_VERSION
    assert loaded["window_bg"] == COLORS["bg_primary"]
    assert reloaded == loaded
    assert json.loads(path.read_text(encoding="utf-8"))["theme_schema_version"] == THEME_SCHEMA_VERSION


def test_main_theme_source_files_do_not_reintroduce_old_highlights():
    root = Path(__file__).resolve().parents[1]
    checked = [
        "quant_collector_app/ui_style.py",
        "quant_collector_app/views/main_window_layout.py",
        "quant_collector_app/views/main_window_presentation.py",
        "quant_collector_app/views/candlestick_item.py",
        "quant_collector_app/views/volume_item.py",
        "quant_collector_app/render/chart_render_adapter.py",
    ]
    forbidden = ("#F0B90B", "240, 185, 11", "0xF0, 0xB9, 0x0B", "#2D7DFF", "#C89B3C", "#A88A54")
    for relative in checked:
        text = (root / relative).read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in text


def test_qt_palette_and_chart_items_use_reference_colors(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    QtGui = pytest.importorskip("PySide6.QtGui")
    QtCore = pytest.importorskip("PySide6.QtCore")
    pytest.importorskip("pyqtgraph")

    import views.main_window_presentation as presentation
    from test_main_window_layout import _LayoutHost
    from views.candlestick_item import CandlestickItem
    from views.main_window_layout import build_main_window_ui
    from views.volume_item import VolumeItem

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    build_main_window_ui(host)
    monkeypatch.setattr(presentation, "save_theme_settings", lambda _theme: None)

    presentation.apply_main_window_theme(host, {"name": EXCHANGE_DARK_THEME["name"]})
    palette = app.palette()

    assert palette.color(QtGui.QPalette.Window) == QtGui.QColor(COLORS["bg_primary"])
    assert palette.color(QtGui.QPalette.Base) == QtGui.QColor(COLORS["bg_input"])
    assert palette.color(QtGui.QPalette.AlternateBase) == QtGui.QColor(COLORS["bg_secondary"])
    assert palette.color(QtGui.QPalette.Text) == QtGui.QColor(COLORS["text_primary"])
    assert palette.color(QtGui.QPalette.WindowText) == QtGui.QColor(COLORS["text_primary"])
    assert palette.color(QtGui.QPalette.Button) == QtGui.QColor(COLORS["bg_card"])
    assert palette.color(QtGui.QPalette.ButtonText) == QtGui.QColor(COLORS["text_primary"])
    assert palette.color(QtGui.QPalette.Highlight) == QtGui.QColor(COLORS["selection"])
    assert palette.color(QtGui.QPalette.HighlightedText) == QtGui.QColor(COLORS["text_primary"])
    assert palette.color(QtGui.QPalette.PlaceholderText) == QtGui.QColor(COLORS["text_tertiary"])

    candle = CandlestickItem()
    volume = VolumeItem()
    assert candle._pen_up.color() == QtGui.QColor(COLORS["chart_up"])
    assert candle._pen_dn.color() == QtGui.QColor(COLORS["chart_down"])
    assert candle._wick_pen.color() == QtGui.QColor(COLORS["chart_wick"])
    assert volume._brush_up.color() == QtGui.QColor(COLORS["chart_volume_up"])
    assert volume._brush_dn.color() == QtGui.QColor(COLORS["chart_volume_down"])
    assert host.theme_settings["grid"] == COLORS["chart_grid"]
    assert host.theme_settings["axis"] == COLORS["chart_axis"]
    assert host.theme_settings["crosshair"] == COLORS["chart_crosshair"]
    assert host.theme_settings["crosshair"] != host.theme_settings["accent"]

    host.multiTimeframePanel.shutdown()
    host.close()
    app.processEvents()


def _rendered_color(host, widget, x: int, y: int):
    QtCore = pytest.importorskip("PySide6.QtCore")
    point = widget.mapTo(host, QtCore.QPoint(x, y))
    image = host.grab().toImage()
    return image.pixelColor(point)


def _assert_color_close(actual, expected, tolerance: int = 8):
    QtGui = pytest.importorskip("PySide6.QtGui")
    expected_color = QtGui.QColor(expected)
    assert abs(actual.red() - expected_color.red()) <= tolerance
    assert abs(actual.green() - expected_color.green()) <= tolerance
    assert abs(actual.blue() - expected_color.blue()) <= tolerance


def test_main_window_effective_background_layers_and_no_local_button_styles(monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("pyqtgraph")

    import views.main_window_presentation as presentation
    from test_main_window_layout import _LayoutHost
    from views.main_window_layout import build_main_window_ui

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    try:
        build_main_window_ui(host)
        monkeypatch.setattr(presentation, "save_theme_settings", lambda _theme: None)
        presentation.apply_main_window_theme(host, EXCHANGE_DARK_THEME)
        host.resize(1366, 768)
        host.show()
        app.processEvents()

        expected_roles = {
            "appRoot": (COLORS["bg_primary"], (host.width() - 6, host.height() - 46)),
            "headerBar": (COLORS["bg_secondary"], (host.headerTitleLabel.x() + 4, host.headerBar.height() - 8)),
            "leftSidebar": (COLORS["bg_secondary"], (3, host.leftSidebar.height() // 2)),
            "marketSection": (COLORS["bg_tertiary"], (12, host.dataBox.height() - 10)),
            "chartCard": (COLORS["bg_primary"], (host.chartCard.width() - 8, host.chartCard.height() - 8)),
            "rightPanel": (COLORS["bg_secondary"], (host.rightPanel.width() - 6, host.rightPanel.height() - 6)),
            "currentStatusCard": (COLORS["bg_card"], (host.currentStatusCard.width() - 8, 8)),
            "bottomTabs": (COLORS["bg_secondary"], (host.bottomTabs.width() - 8, host.bottomTabs.height() - 8)),
            "logDrawer": (COLORS["bg_secondary"], (host.logDrawer.width() // 2, host.logDrawer.height() - 5)),
            "symbolBox": (COLORS["bg_input"], (12, host.symbolBox.height() - 6)),
        }
        for name, (expected, point) in expected_roles.items():
            widget = host.findChild(QtWidgets.QWidget, name)
            assert widget is not None, name
            assert widget.isVisibleTo(host), name
            color = _rendered_color(host, widget, point[0], point[1])
            _assert_color_close(color, expected)

        button_roles = {
            host.btnApplyMarket: "primaryButton",
            host.btnLoadPlay: "primaryButton",
            host.btnStep: "secondaryButton",
            host.btnToEnd: "secondaryButton",
            host.btnFollow: "secondaryButton",
            host.btnResetView: "secondaryButton",
            host.btnOpenLong: "successButton",
            host.btnCloseLong: "successButton",
            host.btnOpenShort: "dangerButton",
            host.btnCloseShort: "dangerButton",
            host.btnUndo: "secondaryButton",
            host.btnRedo: "secondaryButton",
            host.btnClearTradeRecords: "dangerGhostButton",
            host.btnApplyEventMeta: "secondaryButton",
            host.btnExport: "primaryButton",
            host.btnAnalysis: "secondaryButton",
            host.btnSettings: "secondaryButton",
            host.btnToggleDetail: "secondaryButton",
        }
        from ui_style import LOCAL_STYLE_BUTTON_ROLES

        for button, role in button_roles.items():
            assert button.property("role") == role
            # Roles that need an explicit fill carry a LOCAL stylesheet (a
            # window-level stylesheet does not paint their background on Fusion).
            if role in LOCAL_STYLE_BUTTON_ROLES:
                assert button.styleSheet().strip() != ""
            else:
                assert button.styleSheet().strip() == ""

        dump_path = tmp_path / "effective_theme_dump.txt"
        dump = presentation.dump_widget_theme(host, dump_path)
        assert dump_path.read_text(encoding="utf-8") == dump
        assert "objectName=appRoot" in dump
        assert "objectName=marketSection" in dump
        assert "role=sideSection" in dump
        assert "localStyleSheet=False" in dump
    finally:
        if hasattr(host, "multiTimeframePanel"):
            host.multiTimeframePanel.shutdown()
        host.close()
        app.processEvents()


def test_theme_dialog_uses_preset_level_theme_tokens_only():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")

    from views.theme_dialog import ThemeDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = ThemeDialog(EXCHANGE_DARK_THEME)

    assert dialog.buttons == {}
    assert len(dialog.findChildren(QtWidgets.QComboBox)) == 1
    theme = dialog.get_theme()
    assert theme["theme_schema_version"] == THEME_SCHEMA_VERSION
    for key in REFERENCE_COLORS:
        assert key in theme

    dialog.close()
    app.processEvents()
