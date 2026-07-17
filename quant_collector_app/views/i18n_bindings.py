"""Small, state-preserving translation bindings for Qt widgets."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6 import QtCore, QtWidgets


Translator = Callable[[str], str]
_COMBO_I18N_ROLE = int(QtCore.Qt.UserRole) + 91


def bind_text(
    widget: QtWidgets.QWidget,
    key: str,
    translator: Translator,
    *,
    suffix: str = "",
) -> QtWidgets.QWidget:
    widget.setProperty("i18nTextKey", key)
    widget.setProperty("i18nTextSuffix", suffix)
    widget.setText(f"{translator(key)}{suffix}")
    return widget


def bind_tooltip(widget: QtWidgets.QWidget, key: str, translator: Translator) -> None:
    widget.setProperty("i18nToolTipKey", key)
    widget.setToolTip(translator(key))


def bind_placeholder(widget: QtWidgets.QWidget, key: str, translator: Translator) -> None:
    widget.setProperty("i18nPlaceholderKey", key)
    widget.setPlaceholderText(translator(key))


def bind_group_title(
    group: QtWidgets.QGroupBox,
    key: str,
    translator: Translator,
) -> QtWidgets.QGroupBox:
    group.setProperty("i18nTitleKey", key)
    group.setTitle(translator(key))
    return group


def bind_plain_text(widget: QtWidgets.QPlainTextEdit, key: str, translator: Translator) -> None:
    widget.setProperty("i18nPlainTextKey", key)
    widget.setPlainText(translator(key))


def bind_table_headers(
    table: QtWidgets.QTableWidget,
    keys: Iterable[str],
    translator: Translator,
) -> None:
    table._qrc_i18n_header_keys = tuple(keys)
    table.setHorizontalHeaderLabels(
        [translator(key) if key else "" for key in table._qrc_i18n_header_keys]
    )


def add_combo_item(
    combo: QtWidgets.QComboBox,
    key: str,
    data,
    translator: Translator,
) -> None:
    combo.addItem(translator(key), data)
    combo.setItemData(combo.count() - 1, key, _COMBO_I18N_ROLE)


def bind_combo_item(
    combo: QtWidgets.QComboBox,
    index: int,
    key: str,
    translator: Translator,
) -> None:
    combo.setItemData(index, key, _COMBO_I18N_ROLE)
    combo.setItemText(index, translator(key))


def add_tab(
    tabs: QtWidgets.QTabWidget,
    page: QtWidgets.QWidget,
    key: str,
    translator: Translator,
) -> int:
    index = tabs.addTab(page, translator(key))
    bindings = getattr(tabs, "_qrc_i18n_tabs", [])
    bindings.append((page, key))
    tabs._qrc_i18n_tabs = bindings
    return index


def bind_tab(
    tabs: QtWidgets.QTabWidget,
    page: QtWidgets.QWidget,
    key: str,
    translator: Translator,
) -> None:
    index = tabs.indexOf(page)
    if index < 0:
        return
    bindings = [
        (bound_page, bound_key)
        for bound_page, bound_key in getattr(tabs, "_qrc_i18n_tabs", [])
        if bound_page is not page
    ]
    bindings.append((page, key))
    tabs._qrc_i18n_tabs = bindings
    tabs.setTabText(index, translator(key))


def retranslate_bound_widgets(root: QtWidgets.QWidget, translator: Translator) -> None:
    widgets = (root, *root.findChildren(QtWidgets.QWidget))
    for widget in widgets:
        text_key = widget.property("i18nTextKey")
        if text_key and hasattr(widget, "setText"):
            suffix = str(widget.property("i18nTextSuffix") or "")
            widget.setText(f"{translator(str(text_key))}{suffix}")

        tooltip_key = widget.property("i18nToolTipKey")
        if tooltip_key:
            widget.setToolTip(translator(str(tooltip_key)))

        placeholder_key = widget.property("i18nPlaceholderKey")
        if placeholder_key and hasattr(widget, "setPlaceholderText"):
            widget.setPlaceholderText(translator(str(placeholder_key)))

        title_key = widget.property("i18nTitleKey")
        if title_key and isinstance(widget, QtWidgets.QGroupBox):
            widget.setTitle(translator(str(title_key)))

        plain_text_key = widget.property("i18nPlainTextKey")
        if plain_text_key and isinstance(widget, QtWidgets.QPlainTextEdit):
            widget.setPlainText(translator(str(plain_text_key)))

        if isinstance(widget, QtWidgets.QTableWidget):
            keys = getattr(widget, "_qrc_i18n_header_keys", ())
            if keys:
                widget.setHorizontalHeaderLabels(
                    [translator(key) if key else "" for key in keys]
                )

        if isinstance(widget, QtWidgets.QComboBox):
            for index in range(widget.count()):
                key = widget.itemData(index, _COMBO_I18N_ROLE)
                if key:
                    widget.setItemText(index, translator(str(key)))

        if isinstance(widget, QtWidgets.QTabWidget):
            for page, key in getattr(widget, "_qrc_i18n_tabs", ()):
                index = widget.indexOf(page)
                if index >= 0:
                    widget.setTabText(index, translator(key))


__all__ = [
    "add_combo_item",
    "add_tab",
    "bind_combo_item",
    "bind_group_title",
    "bind_placeholder",
    "bind_plain_text",
    "bind_table_headers",
    "bind_tab",
    "bind_text",
    "bind_tooltip",
    "retranslate_bound_widgets",
]
