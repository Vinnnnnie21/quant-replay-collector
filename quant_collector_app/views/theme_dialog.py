from __future__ import annotations

from PySide6 import QtWidgets

from app_config import DEFAULT_THEME, THEME_PRESETS
from ui_style import normalize_theme_settings


class ThemeDialog(QtWidgets.QDialog):
    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("主题/颜色面板")
        self.resize(420, 180)
        self.theme = normalize_theme_settings(theme or DEFAULT_THEME)
        self.buttons: dict[str, object] = {}
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

        hint = QtWidgets.QLabel("当前阶段使用完整主题预设，避免只修改少数字段导致背景层级失衡。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        root.addWidget(buttons)

    def apply_preset(self):
        self.theme = normalize_theme_settings(THEME_PRESETS.get(self.presetBox.currentText(), DEFAULT_THEME))

    def restore_defaults(self):
        self.presetBox.setCurrentText(DEFAULT_THEME.get("name", "交易暗色"))
        self.apply_preset()

    def get_theme(self) -> dict:
        preset = dict(THEME_PRESETS.get(self.presetBox.currentText(), DEFAULT_THEME))
        preset["name"] = self.presetBox.currentText()
        return normalize_theme_settings(preset)


__all__ = ["ThemeDialog"]
