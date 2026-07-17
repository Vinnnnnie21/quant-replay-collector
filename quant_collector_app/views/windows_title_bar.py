"""Keep the Windows native title bar aligned with the active application theme."""

from __future__ import annotations

import sys
from typing import Protocol

from PySide6 import QtGui


class _TitleBarApi(Protocol):
    def apply(
        self,
        hwnd: int,
        *,
        dark: bool,
        caption_color: str,
        text_color: str,
    ) -> bool: ...


class _WindowsDwmTitleBarApi:
    _USE_IMMERSIVE_DARK_MODE = 20
    _USE_IMMERSIVE_DARK_MODE_LEGACY = 19
    _CAPTION_COLOR = 35
    _TEXT_COLOR = 36

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._set_window_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
        self._set_window_attribute.argtypes = (
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        self._set_window_attribute.restype = ctypes.c_long

    @staticmethod
    def _color_ref(value: str) -> int:
        color = QtGui.QColor(value)
        return color.red() | (color.green() << 8) | (color.blue() << 16)

    def _set_dword(self, hwnd: int, attribute: int, value: int) -> bool:
        data = self._ctypes.c_uint32(value)
        result = self._set_window_attribute(
            self._wintypes.HWND(hwnd),
            attribute,
            self._ctypes.byref(data),
            self._ctypes.sizeof(data),
        )
        return result == 0

    def apply(
        self,
        hwnd: int,
        *,
        dark: bool,
        caption_color: str,
        text_color: str,
    ) -> bool:
        dark_mode_applied = self._set_dword(
            hwnd,
            self._USE_IMMERSIVE_DARK_MODE,
            int(dark),
        )
        if not dark_mode_applied:
            dark_mode_applied = self._set_dword(
                hwnd,
                self._USE_IMMERSIVE_DARK_MODE_LEGACY,
                int(dark),
            )
        caption_applied = self._set_dword(
            hwnd,
            self._CAPTION_COLOR,
            self._color_ref(caption_color),
        )
        text_applied = self._set_dword(
            hwnd,
            self._TEXT_COLOR,
            self._color_ref(text_color),
        )
        return dark_mode_applied or caption_applied or text_applied


def apply_windows_title_bar_theme(
    window,
    theme: dict,
    *,
    native_api: _TitleBarApi | None = None,
) -> bool:
    """Apply light/dark caption colors without replacing the native window frame."""

    if native_api is None:
        if sys.platform != "win32":
            return False
        try:
            native_api = _WindowsDwmTitleBarApi()
        except (AttributeError, OSError):
            return False

    background = QtGui.QColor(str(theme.get("bg_primary", "#FFFFFF")))
    foreground = QtGui.QColor(str(theme.get("text_primary", "#18181B")))
    if not background.isValid():
        background = QtGui.QColor("#FFFFFF")
    if not foreground.isValid():
        foreground = QtGui.QColor("#18181B")
    try:
        return native_api.apply(
            int(window.winId()),
            dark=background.lightnessF() < 0.5,
            caption_color=background.name().upper(),
            text_color=foreground.name().upper(),
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False


__all__ = ["apply_windows_title_bar_theme"]
