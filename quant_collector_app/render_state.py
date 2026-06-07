from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RenderState:
    """Dirty flags for chart rendering.

    The flags describe why a render is needed. They intentionally do not own
    any Qt object so they can be unit-tested without a GUI runtime.
    """

    market_data_changed: bool = True
    cursor_changed: bool = True
    visible_range_changed: bool = True
    events_changed: bool = True
    price_changed: bool = True
    header_changed: bool = True
    multi_timeframe_changed: bool = True
    theme_changed: bool = True

    def any_dirty(self) -> bool:
        return any(
            (
                self.market_data_changed,
                self.cursor_changed,
                self.visible_range_changed,
                self.events_changed,
                self.price_changed,
                self.header_changed,
                self.multi_timeframe_changed,
                self.theme_changed,
            )
        )

    def clear(self) -> None:
        self.market_data_changed = False
        self.cursor_changed = False
        self.visible_range_changed = False
        self.events_changed = False
        self.price_changed = False
        self.header_changed = False
        self.multi_timeframe_changed = False
        self.theme_changed = False

    def mark_market_data_changed(self) -> None:
        self.market_data_changed = True
        self.cursor_changed = True
        self.visible_range_changed = True
        self.events_changed = True
        self.price_changed = True
        self.header_changed = True
        self.multi_timeframe_changed = True

    def mark_cursor_changed(self) -> None:
        self.cursor_changed = True
        self.price_changed = True
        self.header_changed = True
        self.multi_timeframe_changed = True

    def mark_visible_range_changed(self) -> None:
        self.visible_range_changed = True
        self.price_changed = True

    def mark_events_changed(self) -> None:
        self.events_changed = True
        self.header_changed = True

    def mark_header_changed(self) -> None:
        self.header_changed = True

    def mark_multi_timeframe_changed(self) -> None:
        self.multi_timeframe_changed = True

    def mark_theme_changed(self) -> None:
        self.theme_changed = True
        self.visible_range_changed = True
        self.events_changed = True
        self.price_changed = True
        self.header_changed = True

    def should_refresh_series(self) -> bool:
        return (
            self.market_data_changed
            or self.cursor_changed
            or self.visible_range_changed
            or self.theme_changed
        )

    def should_refresh_autoscale(self) -> bool:
        return (
            self.market_data_changed
            or self.cursor_changed
            or self.visible_range_changed
            or self.price_changed
            or self.theme_changed
        )

    def should_refresh_markers(self) -> bool:
        return (
            self.market_data_changed
            or self.cursor_changed
            or self.events_changed
            or self.theme_changed
        )

    def should_refresh_price_line(self) -> bool:
        return (
            self.market_data_changed
            or self.cursor_changed
            or self.visible_range_changed
            or self.price_changed
            or self.theme_changed
        )

    def should_refresh_multi_timeframe(self) -> bool:
        return (
            self.market_data_changed
            or self.cursor_changed
            or self.multi_timeframe_changed
        )

    def should_refresh_header(self) -> bool:
        return (
            self.market_data_changed
            or self.cursor_changed
            or self.header_changed
            or self.theme_changed
        )
