from __future__ import annotations

from views.windows_title_bar import apply_windows_title_bar_theme


class _Window:
    def winId(self) -> int:
        return 4242


class _RecordingTitleBarApi:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def apply(self, hwnd: int, *, dark: bool, caption_color: str, text_color: str) -> bool:
        self.calls.append(
            {
                "hwnd": hwnd,
                "dark": dark,
                "caption_color": caption_color,
                "text_color": text_color,
            }
        )
        return True


def test_light_theme_requests_a_white_native_title_bar_with_dark_text():
    api = _RecordingTitleBarApi()

    applied = apply_windows_title_bar_theme(
        _Window(),
        {"bg_primary": "#FFFFFF", "text_primary": "#18181B"},
        native_api=api,
    )

    assert applied is True
    assert api.calls == [
        {
            "hwnd": 4242,
            "dark": False,
            "caption_color": "#FFFFFF",
            "text_color": "#18181B",
        }
    ]


def test_dark_theme_keeps_a_dark_native_title_bar_with_light_text():
    api = _RecordingTitleBarApi()

    applied = apply_windows_title_bar_theme(
        _Window(),
        {"bg_primary": "#000000", "text_primary": "#F5F5F5"},
        native_api=api,
    )

    assert applied is True
    assert api.calls == [
        {
            "hwnd": 4242,
            "dark": True,
            "caption_color": "#000000",
            "text_color": "#F5F5F5",
        }
    ]
