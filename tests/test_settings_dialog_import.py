from __future__ import annotations

import os
import re

import pytest


def test_settings_and_analysis_workspace_importable():
    pytest.importorskip("PySide6")

    from analysis_workspace import AnalysisWorkspace
    from main_app import MainWindow
    from settings_dialog import SettingsDialog

    assert AnalysisWorkspace is not None
    assert SettingsDialog is not None
    assert hasattr(MainWindow, "apply_language")
    assert hasattr(MainWindow, "retranslate_ui")


def test_settings_dialog_exposes_and_saves_chart_render_backend(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    import settings_dialog
    from settings_dialog import SettingsDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = QtWidgets.QWidget()
    host.current_language = "zh_CN"
    captured = {}
    monkeypatch.setattr(settings_dialog, "load_app_settings", lambda: {"language": "zh_CN", "render_backend": "hardware"})
    monkeypatch.setattr(settings_dialog, "save_app_settings", lambda settings: captured.update(settings))

    dialog = SettingsDialog(host)
    assert dialog.renderBackendBox.currentData() == "hardware"
    dialog.renderBackendBox.setCurrentIndex(dialog.renderBackendBox.findData("software"))
    dialog.accept()

    assert captured["render_backend"] == "software"
    dialog.close()
    host.close()
    app.processEvents()


def test_settings_numeric_inputs_do_not_change_on_wheel(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtCore = pytest.importorskip("PySide6.QtCore")
    QtGui = pytest.importorskip("PySide6.QtGui")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    import settings_dialog
    from settings_dialog import SettingsDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = QtWidgets.QWidget()
    host.current_language = "zh_CN"
    monkeypatch.setattr(settings_dialog, "load_app_settings", lambda: {"language": "zh_CN"})
    dialog = SettingsDialog(host)
    before = dialog.cacheLimitSpin.value()
    local = QtCore.QPointF(dialog.cacheLimitSpin.rect().center())
    event = QtGui.QWheelEvent(
        local,
        QtCore.QPointF(dialog.cacheLimitSpin.mapToGlobal(local.toPoint())),
        QtCore.QPoint(),
        QtCore.QPoint(0, -120),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.ScrollUpdate,
        False,
    )

    QtWidgets.QApplication.sendEvent(dialog.cacheLimitSpin, event)

    assert dialog.cacheLimitSpin.value() == before
    dialog.close()
    host.close()
    app.processEvents()


def test_english_settings_dialog_contains_no_chinese_user_interface_text(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    import settings_dialog
    from settings_dialog import SettingsDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = QtWidgets.QWidget()
    host.current_language = "en_US"
    monkeypatch.setattr(
        settings_dialog,
        "load_app_settings",
        lambda: {"language": "en_US", "render_backend": "hardware"},
    )
    dialog = SettingsDialog(host)
    try:
        texts: list[str] = [dialog.windowTitle()]
        for widget in dialog.findChildren(QtWidgets.QWidget):
            if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
                texts.append(widget.text())
            if isinstance(widget, QtWidgets.QTabWidget):
                texts.extend(widget.tabText(index) for index in range(widget.count()))
            if isinstance(widget, QtWidgets.QComboBox):
                texts.extend(widget.itemText(index) for index in range(widget.count()))

        assert sorted({text for text in texts if re.search(r"[\u3400-\u9fff]", text)}) == []
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_ai_provider_selector_shows_localized_labels_but_keeps_canonical_values(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    import settings_dialog
    from settings_dialog import SettingsDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = QtWidgets.QWidget()
    host.current_language = "zh_CN"
    monkeypatch.setattr(settings_dialog, "load_app_settings", lambda: {"language": "zh_CN"})
    dialog = SettingsDialog(host)
    try:
        assert [
            dialog.providerBox.itemData(index)
            for index in range(dialog.providerBox.count())
        ] == ["mock", "openai", "custom_http"]
        assert [
            dialog.providerBox.itemText(index)
            for index in range(dialog.providerBox.count())
        ] == ["模拟服务", "OpenAI", "自定义 HTTP 服务"]
    finally:
        dialog.close()
        host.close()
        app.processEvents()
