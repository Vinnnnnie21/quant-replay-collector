from __future__ import annotations

from PySide6 import QtWidgets

from app_config import DEFAULT_THEME, THEME_PRESETS
from app_i18n import tr
from ui_style import normalize_theme_settings
from views.i18n_bindings import add_combo_item, bind_text


class ThemeDialog(QtWidgets.QDialog):
    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self.current_language = str(
            getattr(parent, "current_language", "zh_CN") or "zh_CN"
        )
        self.setWindowTitle(tr("theme.dialog_title", self.current_language))
        self.resize(420, 180)
        self.theme = normalize_theme_settings(theme or DEFAULT_THEME)
        self.buttons: dict[str, object] = {}
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        preset_row = QtWidgets.QHBoxLayout()
        preset_label = QtWidgets.QLabel()
        bind_text(
            preset_label,
            "theme.preset",
            lambda key: tr(key, self.current_language),
        )
        preset_row.addWidget(preset_label)
        self.presetBox = QtWidgets.QComboBox()
        for name in THEME_PRESETS:
            key = "settings.theme.dark" if name == "暗色" else "settings.theme.light"
            add_combo_item(
                self.presetBox,
                key,
                name,
                lambda value: tr(value, self.current_language),
            )
        preset_name = self.theme.get("name", DEFAULT_THEME.get("name", "浅色"))
        if preset_name not in THEME_PRESETS:
            preset_name = DEFAULT_THEME.get("name", "浅色")
        self.presetBox.setCurrentIndex(max(0, self.presetBox.findData(preset_name)))
        self.btnApplyPreset = QtWidgets.QPushButton()
        bind_text(
            self.btnApplyPreset,
            "theme.apply_preset",
            lambda key: tr(key, self.current_language),
        )
        self.btnApplyPreset.clicked.connect(self.apply_preset)
        preset_row.addWidget(self.presetBox, 1)
        preset_row.addWidget(self.btnApplyPreset)
        root.addLayout(preset_row)

        hint = QtWidgets.QLabel()
        bind_text(
            hint,
            "theme.hint",
            lambda key: tr(key, self.current_language),
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText(
            tr("cancel", self.current_language)
        )
        buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).setText(
            tr("theme.restore_defaults", self.current_language)
        )
        root.addWidget(buttons)

    def apply_preset(self):
        self.theme = normalize_theme_settings(
            THEME_PRESETS.get(self.presetBox.currentData(), DEFAULT_THEME)
        )

    def restore_defaults(self):
        self.presetBox.setCurrentIndex(
            max(0, self.presetBox.findData(DEFAULT_THEME.get("name", "浅色")))
        )
        self.apply_preset()

    def get_theme(self) -> dict:
        preset_name = self.presetBox.currentData()
        preset = dict(THEME_PRESETS.get(preset_name, DEFAULT_THEME))
        preset["name"] = preset_name
        return normalize_theme_settings(preset)


__all__ = ["ThemeDialog"]
