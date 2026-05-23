from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from app_config import (
    DEFAULT_FEE_BPS,
    DEFAULT_FILL_MODE,
    DEFAULT_INITIAL_EQUITY,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_THEME,
    DEFAULT_TRADE_NOTIONAL,
    THEME_PRESETS,
    load_theme_settings,
)
from app_i18n import tr
from app_settings import load_app_settings, save_app_settings
from execution import FILL_MODES
from ui_style import SPACING, style_primary_button, style_secondary_button


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, app_window, parent=None):
        super().__init__(parent or app_window)
        self.app_window = app_window
        self.app_settings = load_app_settings()
        self.current_language = str(getattr(app_window, "current_language", None) or self.app_settings.get("language") or "zh_CN")
        self.theme = dict(load_theme_settings())
        self.resize(560, 520)
        self._color_edits: dict[str, QtWidgets.QLineEdit] = {}
        self._build_ui()
        self._load_from_app()
        self.retranslate_ui()

    def _tr(self, key: str, default: str | None = None) -> str:
        return tr(key, self.current_language, default)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        root.setSpacing(SPACING["md"])

        self.tabs = QtWidgets.QTabWidget()
        self.appearanceTab = self._appearance_tab()
        self.languageTab = self._language_tab()
        self.executionTab = self._execution_tab()
        self.aiTab = self._ai_tab()
        self.tabs.addTab(self.appearanceTab, "")
        self.tabs.addTab(self.languageTab, "")
        self.tabs.addTab(self.executionTab, "")
        self.tabs.addTab(self.aiTab, "")
        root.addWidget(self.tabs, stretch=1)

        self.buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.okButton = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        self.cancelButton = self.buttonBox.button(QtWidgets.QDialogButtonBox.Cancel)
        if self.okButton is not None:
            self.okButton.setStyleSheet(style_primary_button())
        if self.cancelButton is not None:
            self.cancelButton.setStyleSheet(style_secondary_button())
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        root.addWidget(self.buttonBox)

    def _appearance_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        layout.setSpacing(SPACING["md"])

        form = QtWidgets.QFormLayout()
        form.setSpacing(SPACING["sm"])
        self.themePresetBox = QtWidgets.QComboBox()
        self.themePresetBox.addItems(list(THEME_PRESETS.keys()))
        form.addRow("主题预设", self.themePresetBox)

        for key, label in (
            ("candle_up", "上涨 K 线颜色"),
            ("candle_down", "下跌 K 线颜色"),
            ("grid", "网格颜色"),
            ("crosshair", "十字光标颜色"),
        ):
            form.addRow(label, self._color_row(key))

        self.gridAlphaSlider = self._slider(0, 100)
        self.crosshairAlphaSlider = self._slider(0, 255)
        form.addRow("网格透明度", self.gridAlphaSlider)
        form.addRow("十字光标透明度", self.crosshairAlphaSlider)
        layout.addLayout(form)

        hint = QtWidgets.QLabel("外观设置会立即影响主图表和交易面板。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.themePresetBox.currentTextChanged.connect(self._on_preset_changed)
        return tab

    def _language_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        layout.setSpacing(SPACING["md"])
        form = QtWidgets.QFormLayout()
        self.languageBox = QtWidgets.QComboBox()
        self.languageBox.addItem("中文", "zh_CN")
        self.languageBox.addItem("English", "en_US")
        self.languageBox.currentIndexChanged.connect(self._on_language_changed)
        form.addRow("界面语言", self.languageBox)
        layout.addLayout(form)
        hint = QtWidgets.QLabel("本阶段只保存语言配置，并翻译主要入口。完整国际化后续完善。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return tab

    def _execution_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        form.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        form.setSpacing(SPACING["sm"])

        self.fillModeBox = QtWidgets.QComboBox()
        for mode in FILL_MODES:
            self.fillModeBox.addItem(self._fill_mode_label(mode), mode)
        self.feeBpsSpin = self._double_spin(0.0, 100.0, DEFAULT_FEE_BPS)
        self.slippageBpsSpin = self._double_spin(0.0, 100.0, DEFAULT_SLIPPAGE_BPS)
        self.tradeNotionalSpin = self._double_spin(1.0, 1_000_000_000.0, DEFAULT_TRADE_NOTIONAL)
        self.initialEquitySpin = self._double_spin(1.0, 1_000_000_000.0, DEFAULT_INITIAL_EQUITY)

        form.addRow("成交模式", self.fillModeBox)
        form.addRow("手续费 bps", self.feeBpsSpin)
        form.addRow("滑点 bps", self.slippageBpsSpin)
        form.addRow("每笔名义金额", self.tradeNotionalSpin)
        form.addRow("初始权益", self.initialEquitySpin)
        return tab

    def _ai_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        layout.setSpacing(SPACING["md"])
        form = QtWidgets.QFormLayout()
        self.providerBox = QtWidgets.QComboBox()
        self.providerBox.addItems(["mock", "openai", "custom_http"])
        self.localApiLabel = QtWidgets.QLabel(str(self.app_settings.get("local_api_url") or "http://127.0.0.1:8765"))
        form.addRow("LLM provider", self.providerBox)
        form.addRow("本地 API", self.localApiLabel)
        layout.addLayout(form)
        warning = QtWidgets.QLabel("API Key 只从环境变量读取，不在界面保存明文。AI 只解释研究结果，不提供投资建议。")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addStretch(1)
        return tab

    def _color_row(self, key: str) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText("#21b26f")
        button = QtWidgets.QPushButton("选择")
        button.setStyleSheet(style_secondary_button())
        button.clicked.connect(lambda _=False, k=key: self._choose_color(k))
        layout.addWidget(edit, stretch=1)
        layout.addWidget(button)
        self._color_edits[key] = edit
        return row

    @staticmethod
    def _slider(minimum: int, maximum: int) -> QtWidgets.QSlider:
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(minimum, maximum)
        return slider

    @staticmethod
    def _double_spin(minimum: float, maximum: float, value: float) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setValue(float(value))
        return spin

    @staticmethod
    def _fill_mode_label(mode: Any) -> str:
        return {"MID": "中间价", "CLOSE": "收盘价", "OPEN": "开盘价"}.get(str(mode or "").upper(), str(mode or ""))

    def _main_widget_value(self, name: str, default: Any) -> Any:
        widget = getattr(self.app_window, name, None)
        if widget is None:
            return default
        try:
            return widget.value()
        except Exception:
            try:
                return widget.currentData() or widget.currentText()
            except Exception:
                return default

    def _load_from_app(self):
        preset = str(self.theme.get("name") or DEFAULT_THEME.get("name") or "")
        idx = self.themePresetBox.findText(preset)
        self.themePresetBox.setCurrentIndex(max(0, idx))
        self._load_theme_controls(self.theme)

        language = str(self.app_settings.get("language") or "zh_CN")
        idx = self.languageBox.findData(language)
        self.languageBox.setCurrentIndex(max(0, idx))
        provider = str(self.app_settings.get("llm_provider") or "mock")
        idx = self.providerBox.findText(provider)
        self.providerBox.setCurrentIndex(max(0, idx))

        self._set_fill_mode_value(self._main_widget_value("fillModeBox", DEFAULT_FILL_MODE))
        self.feeBpsSpin.setValue(float(self._main_widget_value("feeBpsSpin", DEFAULT_FEE_BPS)))
        self.slippageBpsSpin.setValue(float(self._main_widget_value("slippageBpsSpin", DEFAULT_SLIPPAGE_BPS)))
        self.tradeNotionalSpin.setValue(float(self._main_widget_value("tradeNotionalSpin", DEFAULT_TRADE_NOTIONAL)))
        self.initialEquitySpin.setValue(float(self._main_widget_value("initialEquitySpin", DEFAULT_INITIAL_EQUITY)))

    def _on_language_changed(self):
        if hasattr(self, "languageBox"):
            self.current_language = str(self.languageBox.currentData() or "zh_CN")
        if hasattr(self, "tabs"):
            self.retranslate_ui()

    def _load_theme_controls(self, theme: dict[str, Any]):
        for key, edit in self._color_edits.items():
            edit.setText(str(theme.get(key) or DEFAULT_THEME.get(key) or ""))
        self.gridAlphaSlider.setValue(int(float(theme.get("grid_alpha", DEFAULT_THEME.get("grid_alpha", 22)))))
        self.crosshairAlphaSlider.setValue(int(float(theme.get("crosshair_alpha", DEFAULT_THEME.get("crosshair_alpha", 130)))))

    def _on_preset_changed(self, name: str):
        preset = THEME_PRESETS.get(name)
        if preset:
            self.theme = dict(DEFAULT_THEME)
            self.theme.update(preset)
            self._load_theme_controls(self.theme)

    def _choose_color(self, key: str):
        edit = self._color_edits[key]
        current = QtGui.QColor(edit.text())
        color = QtWidgets.QColorDialog.getColor(current if current.isValid() else QtGui.QColor("#ffffff"), self, "选择颜色")
        if color.isValid():
            edit.setText(color.name())

    def _set_fill_mode_value(self, mode: Any):
        value = str(mode or DEFAULT_FILL_MODE).strip().upper()
        for idx in range(self.fillModeBox.count()):
            if str(self.fillModeBox.itemData(idx) or "").upper() == value:
                self.fillModeBox.setCurrentIndex(idx)
                return

    def _build_theme_payload(self) -> dict[str, Any]:
        theme = dict(DEFAULT_THEME)
        preset = THEME_PRESETS.get(self.themePresetBox.currentText())
        if preset:
            theme.update(preset)
        for key, edit in self._color_edits.items():
            value = edit.text().strip()
            if value:
                theme[key] = value
        theme["grid_alpha"] = int(self.gridAlphaSlider.value())
        theme["crosshair_alpha"] = int(self.crosshairAlphaSlider.value())
        return theme

    def retranslate_ui(self):
        self.setWindowTitle(self._tr("settings_center"))
        self.tabs.setTabText(self.tabs.indexOf(self.appearanceTab), self._tr("appearance_settings"))
        self.tabs.setTabText(self.tabs.indexOf(self.languageTab), self._tr("language_settings"))
        self.tabs.setTabText(self.tabs.indexOf(self.executionTab), self._tr("execution_cost_settings"))
        self.tabs.setTabText(self.tabs.indexOf(self.aiTab), self._tr("ai_api_settings"))
        if self.okButton is not None:
            self.okButton.setText(self._tr("save_and_apply"))
        if self.cancelButton is not None:
            self.cancelButton.setText(self._tr("cancel"))

    def _apply_execution_settings(self):
        app = self.app_window
        mapping = (
            ("feeBpsSpin", self.feeBpsSpin.value()),
            ("slippageBpsSpin", self.slippageBpsSpin.value()),
            ("tradeNotionalSpin", self.tradeNotionalSpin.value()),
            ("initialEquitySpin", self.initialEquitySpin.value()),
        )
        if hasattr(app, "_set_fill_mode_value"):
            app.fillModeBox.blockSignals(True)
            app._set_fill_mode_value(self.fillModeBox.currentData() or self.fillModeBox.currentText())
            app.fillModeBox.blockSignals(False)
        for name, value in mapping:
            widget = getattr(app, name, None)
            if widget is None:
                continue
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        if hasattr(app, "on_execution_settings_changed"):
            app.on_execution_settings_changed()

    def accept(self):
        theme = self._build_theme_payload()
        if hasattr(self.app_window, "apply_theme"):
            self.app_window.apply_theme(theme)
        self._apply_execution_settings()
        language = self.languageBox.currentData() or "zh_CN"
        settings = dict(self.app_settings)
        settings.update(
            {
                "language": language,
                "llm_provider": self.providerBox.currentText(),
                "local_api_url": "http://127.0.0.1:8765",
                "fill_mode": self.fillModeBox.currentData() or self.fillModeBox.currentText(),
                "fee_bps": self.feeBpsSpin.value(),
                "slippage_bps": self.slippageBpsSpin.value(),
                "trade_notional": self.tradeNotionalSpin.value(),
                "initial_equity": self.initialEquitySpin.value(),
            }
        )
        save_app_settings(settings)
        self.current_language = str(language)
        if hasattr(self.app_window, "apply_language"):
            self.app_window.apply_language(self.current_language)
        super().accept()
