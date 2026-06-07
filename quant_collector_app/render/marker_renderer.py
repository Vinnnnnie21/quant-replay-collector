from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

import pandas as pd


MarkerPoints = tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class MarkerPayloads:
    display_interval: str
    open_long: MarkerPoints
    open_short: MarkerPoints
    close_long: MarkerPoints
    close_short: MarkerPoints

    @property
    def marker_key(self) -> tuple[Any, ...]:
        return (
            self.display_interval,
            self.open_long,
            self.open_short,
            self.close_long,
            self.close_short,
        )


def _event_index(event: dict[str, Any]) -> int | None:
    try:
        index = int(event.get("bar_index"))
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def build_marker_payloads(
    df: pd.DataFrame,
    events: list[dict[str, Any]],
    *,
    cursor: int,
    display_interval: str,
    sample_interval: str,
) -> MarkerPayloads:
    open_long: list[tuple[int, float]] = []
    open_short: list[tuple[int, float]] = []
    close_long: list[tuple[int, float]] = []
    close_short: list[tuple[int, float]] = []
    display = str(display_interval or "").strip()
    sample = str(sample_interval or "").strip()
    cur = int(cursor)
    row_count = len(df)

    for event in events:
        event_interval = str(event.get("interval") or sample or "").strip()
        if event_interval and event_interval != display:
            continue
        index = _event_index(event)
        if index is None or index > cur or index >= row_count:
            continue
        event_type = str(event.get("event_type") or "").upper()
        side = str(event.get("side") or "").upper()
        if event_type == "OPEN" and side == "LONG":
            open_long.append((index, float(df.iloc[index]["low"])))
        elif event_type == "OPEN" and side == "SHORT":
            open_short.append((index, float(df.iloc[index]["high"])))
        elif event_type == "CLOSE" and side == "LONG":
            close_long.append((index, float(df.iloc[index]["high"])))
        elif event_type == "CLOSE" and side == "SHORT":
            close_short.append((index, float(df.iloc[index]["low"])))

    return MarkerPayloads(
        display_interval=display,
        open_long=tuple(open_long),
        open_short=tuple(open_short),
        close_long=tuple(close_long),
        close_short=tuple(close_short),
    )


class MarkerPayloadCache:
    """Index event markers once and reuse payloads between event boundaries."""

    def __init__(self) -> None:
        self._index_key: tuple[Any, ...] | None = None
        self._display_interval = ""
        self._points: dict[str, MarkerPoints] = {}
        self._point_indexes: dict[str, tuple[int, ...]] = {}
        self._boundaries: tuple[int, ...] = ()
        self._payload_bucket: int | None = None
        self._payload: MarkerPayloads | None = None

    def payload_for(
        self,
        df: pd.DataFrame,
        events: list[dict[str, Any]],
        *,
        cursor: int,
        display_interval: str,
        sample_interval: str,
        events_changed: bool = False,
    ) -> MarkerPayloads:
        display = str(display_interval or "").strip()
        sample = str(sample_interval or "").strip()
        index_key = (id(df), len(df), len(events), display, sample)
        if events_changed or index_key != self._index_key:
            self._rebuild_index(df, events, display_interval=display, sample_interval=sample)
            self._index_key = index_key

        bucket = bisect_right(self._boundaries, int(cursor))
        if self._payload is not None and bucket == self._payload_bucket:
            return self._payload

        self._payload_bucket = bucket
        self._payload = MarkerPayloads(
            display_interval=self._display_interval,
            open_long=self._visible_points("open_long", cursor),
            open_short=self._visible_points("open_short", cursor),
            close_long=self._visible_points("close_long", cursor),
            close_short=self._visible_points("close_short", cursor),
        )
        return self._payload

    def invalidate(self) -> None:
        self._index_key = None
        self._payload_bucket = None
        self._payload = None

    def _rebuild_index(
        self,
        df: pd.DataFrame,
        events: list[dict[str, Any]],
        *,
        display_interval: str,
        sample_interval: str,
    ) -> None:
        full = build_marker_payloads(
            df,
            events,
            cursor=max(-1, len(df) - 1),
            display_interval=display_interval,
            sample_interval=sample_interval,
        )
        self._display_interval = full.display_interval
        self._points = {
            "open_long": tuple(sorted(full.open_long)),
            "open_short": tuple(sorted(full.open_short)),
            "close_long": tuple(sorted(full.close_long)),
            "close_short": tuple(sorted(full.close_short)),
        }
        self._point_indexes = {
            name: tuple(point[0] for point in points)
            for name, points in self._points.items()
        }
        self._boundaries = tuple(
            sorted({index for indexes in self._point_indexes.values() for index in indexes})
        )
        self._payload_bucket = None
        self._payload = None

    def _visible_points(self, name: str, cursor: int) -> MarkerPoints:
        end = bisect_right(self._point_indexes.get(name, ()), int(cursor))
        return self._points.get(name, ())[:end]


__all__ = ["MarkerPayloadCache", "MarkerPayloads", "build_marker_payloads"]
