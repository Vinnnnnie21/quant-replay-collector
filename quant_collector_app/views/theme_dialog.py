from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app_config import DEFAULT_THEME, THEME_PRESETS


class ColorButton(QtWidgets.QPushButton):
    colorChanged = QtCore.Signal(str)

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedWidth(90)
        self.clicked.connect(self.choose_color)
        self._refresh()

    def color(self) -> str:
        return self._color

    def set_color(self, color: str):
        self._color = color
        self._refresh()

    def _refresh(self):
        foreground = "#000000" if QtGui.QColor(self._color).lightness() > 140 else "#ffffff"
        self.setText(self._color.upper())
        self.setStyleSheet(f"background:{self._color}; color: {foreground};")

    def choose_color(self):
        chosen = QtWidgets.QColorDialog.getColor(QtGui.QColor(self._color), self.window(), "选择颜色")
        if chosen.isValid():
            self._color = chosen.name()
            self._refresh()
            self.colorChanged.emit(self._color)


class ThemeDialog(QtWidgets.QDialog):
    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("主题/颜色面板")
        self.resize(560, 760)
        self.theme = dict(DEFAULT_THEME)
        self.theme.update(theme or {})
        self.buttons: dict[str, ColorButton] = {}
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(QtWidgets.QLabel("预设主题"))
        self.presetBox = QtWidgets.QComboBox()
        self.presetBox.addItems(list(THEME_PRESETS.keys()))
        preset_name = self.theme.get("name", DEFAULT_THEME.get("name", "交易暗色"))
        if preset_name not in THEME_PRESETS:
            preset_name = DEFAULT_THEME.get("name", "交易暗色")
        self.presetBox.setCurrentText(preset_name)
        self.btnApplyPreset = QtWidgets.QPushButton("应用预设")
        self.btnApplyPreset.clicked.connect(self.apply_preset)
        preset_row.addWidget(self.presetBox, 1)
        preset_row.addWidget(self.btnApplyPreset)
        root.addLayout(preset_row)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        wrap = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(wrap)
        fields = [
            ("window_bg", "主背景色"),
            ("panel_bg", "面板背景色"),
            ("base_bg", "图表背景色"),
            ("text", "主文字颜色"),
            ("axis", "坐标轴颜色"),
            ("grid", "网格线颜色"),
            ("candle_up", "K线上涨颜色"),
            ("candle_down", "K线下跌颜色"),
            ("volume_up", "成交量上涨颜色"),
            ("volume_down", "成交量下跌颜色"),
            ("wick", "影线颜色"),
            ("current_price_up", "当前价格上涨线"),
            ("current_price_down", "当前价格下跌线"),
            ("current_price_label_text", "当前价格标签文字"),
            ("crosshair", "十字光标颜色"),
            ("premium_buy", "买入溢价线颜色"),
            ("premium_sell", "卖出溢价线颜色"),
            ("premium_avg", "均价溢价线颜色"),
        ]
        for key, label in fields:
            button = ColorButton(self.theme.get(key, DEFAULT_THEME[key]))
            self.buttons[key] = button
            form.addRow(label, button)

        self.gridAlpha = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.gridAlpha.setRange(0, 100)
        self.gridAlpha.setValue(int(self.theme.get("grid_alpha", 28)))
        self.gridAlphaLabel = QtWidgets.QLabel(str(self.gridAlpha.value()))
        grid_row = QtWidgets.QHBoxLayout()
        grid_row.addWidget(self.gridAlpha, 1)
        grid_row.addWidget(self.gridAlphaLabel)
        self.gridAlpha.valueChanged.connect(lambda value: self.gridAlphaLabel.setText(str(value)))
        form.addRow("网格线透明度", grid_row)

        self.crosshairAlpha = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.crosshairAlpha.setRange(0, 255)
        self.crosshairAlpha.setValue(int(self.theme.get("crosshair_alpha", 140)))
        self.crosshairAlphaLabel = QtWidgets.QLabel(str(self.crosshairAlpha.value()))
        crosshair_row = QtWidgets.QHBoxLayout()
        crosshair_row.addWidget(self.crosshairAlpha, 1)
        crosshair_row.addWidget(self.crosshairAlphaLabel)
        self.crosshairAlpha.valueChanged.connect(lambda value: self.crosshairAlphaLabel.setText(str(value)))
        form.addRow("十字光标透明度", crosshair_row)

        scroll.setWidget(wrap)
        root.addWidget(scroll, 1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        root.addWidget(buttons)

    def apply_preset(self):
        preset = dict(DEFAULT_THEME)
        preset.update(THEME_PRESETS.get(self.presetBox.currentText(), {}))
        for key, button in self.buttons.items():
            button.set_color(preset.get(key, DEFAULT_THEME[key]))
        self.gridAlpha.setValue(int(preset.get("grid_alpha", DEFAULT_THEME["grid_alpha"])))
        self.crosshairAlpha.setValue(int(preset.get("crosshair_alpha", DEFAULT_THEME["crosshair_alpha"])))

    def restore_defaults(self):
        self.presetBox.setCurrentText(DEFAULT_THEME.get("name", "交易暗色"))
        self.apply_preset()

    def get_theme(self) -> dict:
        output = dict(DEFAULT_THEME)
        for key, button in self.buttons.items():
            output[key] = button.color()
        output["grid_alpha"] = int(self.gridAlpha.value())
        output["crosshair_alpha"] = int(self.crosshairAlpha.value())
        output["name"] = self.presetBox.currentText()
        return output


__all__ = ["ColorButton", "ThemeDialog"]
