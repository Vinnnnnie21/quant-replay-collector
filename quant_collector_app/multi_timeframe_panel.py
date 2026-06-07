"""Read-only UI panel for higher-timeframe replay context."""

from __future__ import annotations

import uuid
from typing import Any

import pandas as pd
from PySide6 import QtCore, QtWidgets

try:
    from app_i18n import tr
    from app_logger import get_logger
    from market_data import KlineLoader, LoadRequest, interval_to_ms
    from multi_timeframe import (
        build_multi_timeframe_context,
        find_context_bar_by_time,
        higher_timeframes_for,
        normalize_context_frame,
    )
except ImportError:  # pragma: no cover - package import path
    from .app_i18n import tr
    from .app_logger import get_logger
    from .market_data import KlineLoader, LoadRequest, interval_to_ms
    from .multi_timeframe import (
        build_multi_timeframe_context,
        find_context_bar_by_time,
        higher_timeframes_for,
        normalize_context_frame,
    )


logger = get_logger(__name__)
_SELECTABLE_CONTEXT_INTERVALS = ("5m", "15m", "1h", "4h")


class _MultiTimeframeLoadWorker(QtCore.QObject):
    finished = QtCore.Signal(str, object, object)

    def __init__(self):
        super().__init__()
        self.loader = KlineLoader()

    @QtCore.Slot(object)
    def load(self, payload: dict[str, Any]) -> None:
        request_id = str(payload["request_id"])
        frames: dict[str, pd.DataFrame] = {}
        failures: dict[str, str] = {}
        for request in payload["requests"]:
            try:
                frame, message = self.loader.load(request)
                if frame.empty:
                    failures[request.interval] = message or "No HTF bars returned."
                else:
                    frames[request.interval] = frame
            except Exception as exc:
                logger.exception("Higher-timeframe context loading failed for %s %s.", request.symbol, request.interval)
                failures[request.interval] = f"{type(exc).__name__}: {exc}"
        self.finished.emit(request_id, frames, failures)


class MultiTimeframePanel(QtWidgets.QWidget):
    requestLoad = QtCore.Signal(object)
    loadFailed = QtCore.Signal(str, str)

    def __init__(self, language: str = "zh_CN", parent=None, start_worker: bool = True):
        super().__init__(parent)
        self.language = language
        self._context_frames: dict[str, pd.DataFrame] = {}
        self._context_errors: dict[str, str] = {}
        self._latest_context: dict[str, dict[str, Any]] = {}
        self._last_render_context_key: tuple[Any, ...] | None = None
        self._last_summary_context_key: tuple[Any, ...] | None = None
        self._configured_primary: str | None = None
        self._active_request_id: str | None = None
        self._last_request_args: tuple[Any, ...] | None = None
        self._primary_row: pd.Series | dict[str, Any] | None = None
        self._worker_thread: QtCore.QThread | None = None
        self._worker: _MultiTimeframeLoadWorker | None = None
        self._build_ui()
        if start_worker:
            self._worker_thread = QtCore.QThread(self)
            self._worker = _MultiTimeframeLoadWorker()
            self._worker.moveToThread(self._worker_thread)
            self.requestLoad.connect(self._worker.load, QtCore.Qt.QueuedConnection)
            self._worker.finished.connect(self._on_loaded)
            self._worker_thread.start()
        self.retranslate_ui(language)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.noticeLabel = QtWidgets.QLabel()
        self.noticeLabel.setWordWrap(True)
        self.noticeLabel.setProperty("role", "muted")
        layout.addWidget(self.noticeLabel)
        selection = QtWidgets.QHBoxLayout()
        self.intervalChecks: dict[str, QtWidgets.QCheckBox] = {}
        for interval in _SELECTABLE_CONTEXT_INTERVALS:
            checkbox = QtWidgets.QCheckBox(interval)
            checkbox.toggled.connect(self._on_selection_changed)
            selection.addWidget(checkbox)
            self.intervalChecks[interval] = checkbox
        selection.addStretch(1)
        layout.addLayout(selection)
        self.summaryText = QtWidgets.QPlainTextEdit()
        self.summaryText.setReadOnly(True)
        self.summaryText.setMinimumHeight(250)
        layout.addWidget(self.summaryText, stretch=1)

    def retranslate_ui(self, language: str | None = None) -> None:
        if language:
            self.language = language
        self.noticeLabel.setText(tr("multi_timeframe_readonly_notice", self.language))
        if not self._latest_context and not self._context_errors:
            self.summaryText.setPlainText(tr("multi_timeframe_waiting", self.language))
        elif self._latest_context:
            self._render_context(self._latest_context)

    def configure_for_primary(self, primary_interval: str) -> None:
        primary = str(primary_interval).strip()
        if self._configured_primary == primary:
            return
        defaults = set(higher_timeframes_for(primary))
        try:
            primary_ms = interval_to_ms(primary)
        except ValueError:
            primary_ms = 0
        for interval, checkbox in self.intervalChecks.items():
            checkbox.blockSignals(True)
            enabled = interval_to_ms(interval) > primary_ms
            checkbox.setEnabled(enabled)
            checkbox.setChecked(enabled and interval in defaults)
            checkbox.blockSignals(False)
        self._configured_primary = primary

    def selected_intervals(self) -> tuple[str, ...]:
        return tuple(
            interval
            for interval, checkbox in self.intervalChecks.items()
            if checkbox.isEnabled() and checkbox.isChecked()
        )

    def build_load_requests(self, symbol: str, primary_interval: str, start_dt_bjt, end_dt_bjt) -> list[LoadRequest]:
        self.configure_for_primary(primary_interval)
        return [
            LoadRequest(
                symbol=str(symbol).strip().upper(),
                interval=interval,
                start_dt_bjt=start_dt_bjt,
                end_dt_bjt=end_dt_bjt,
                use_cache=True,
            )
            for interval in self.selected_intervals()
        ]

    def request_context_load(self, symbol: str, primary_interval: str, start_dt_bjt, end_dt_bjt) -> None:
        self._last_request_args = (symbol, primary_interval, start_dt_bjt, end_dt_bjt)
        requests = self.build_load_requests(symbol, primary_interval, start_dt_bjt, end_dt_bjt)
        self._context_frames = {}
        self._context_errors = {}
        self._latest_context = {}
        if not requests:
            self.summaryText.setPlainText(tr("multi_timeframe_no_selection", self.language))
            return
        self._active_request_id = uuid.uuid4().hex
        self.summaryText.setPlainText(tr("multi_timeframe_loading", self.language))
        if self._worker is not None:
            self.requestLoad.emit({"request_id": self._active_request_id, "requests": requests})

    def _on_selection_changed(self, _checked: bool) -> None:
        if self._last_request_args is not None:
            self.request_context_load(*self._last_request_args)

    @QtCore.Slot(str, object, object)
    def _on_loaded(self, request_id: str, frames: dict[str, pd.DataFrame], failures: dict[str, str]) -> None:
        if request_id != self._active_request_id:
            return
        self.set_context_frames(frames, failures)
        if self._primary_row is not None:
            self.refresh_for_primary_row(self._primary_row)
        for interval, error in failures.items():
            self.loadFailed.emit(interval, error)

    def set_context_frames(
        self,
        frames: dict[str, pd.DataFrame],
        errors: dict[str, str] | None = None,
    ) -> None:
        self._context_frames = {
            interval: normalize_context_frame(frame, interval)
            for interval, frame in dict(frames).items()
        }
        self._context_errors = dict(errors or {})
        self._latest_context = {}
        self._last_render_context_key = None
        self._last_summary_context_key = None
        if self._context_errors and not self._context_frames:
            detail = "\n".join(f"{interval}: {error}" for interval, error in self._context_errors.items())
            self.summaryText.setPlainText(f"{tr('multi_timeframe_load_failed', self.language)}\n{detail}")

    def mark_stale(self) -> None:
        self._active_request_id = None
        self._context_frames = {}
        self._context_errors = {}
        self._latest_context = {}
        self._last_render_context_key = None
        self._last_summary_context_key = None
        self._primary_row = None
        self.summaryText.setPlainText(tr("multi_timeframe_stale", self.language))

    def refresh_for_primary_row(self, primary_row: pd.Series | dict[str, Any]) -> dict[str, dict[str, Any]]:
        self._primary_row = primary_row.copy() if hasattr(primary_row, "copy") else dict(primary_row)
        if not self._context_frames:
            return {}
        summary_key = self._context_summary_key(primary_row)
        if summary_key != self._last_summary_context_key:
            self._latest_context = build_multi_timeframe_context(primary_row, self._context_frames)
            self._last_summary_context_key = summary_key
        key = self._context_render_key(self._latest_context)
        if key != self._last_render_context_key:
            self._render_context(self._latest_context)
            self._last_render_context_key = key
        return self._latest_context

    def _context_summary_key(self, primary_row: pd.Series | dict[str, Any]) -> tuple[Any, ...]:
        current_time = primary_row.get("open_time_bjt") if hasattr(primary_row, "get") else None
        if current_time is None:
            return tuple((interval, "missing_primary_time", None, None) for interval in sorted(self._context_frames))
        visible_time = pd.Timestamp(current_time)
        if visible_time.tzinfo is None:
            visible_time = visible_time.tz_localize("Asia/Shanghai")
        else:
            visible_time = visible_time.tz_convert("Asia/Shanghai")
        keys: list[tuple[Any, ...]] = []
        for interval, frame in sorted(self._context_frames.items()):
            match = find_context_bar_by_time(frame, visible_time, interval)
            containing_index = match.get("htf_bar_index") if match.get("sync_status") == "contains_cursor" else None
            if match.get("sync_status") == "contains_cursor":
                completed = frame[frame["_close_time"] <= visible_time] if "_close_time" in frame.columns else pd.DataFrame()
                visible_index = (
                    int(completed.iloc[-1]["bar_index"])
                    if not completed.empty and "bar_index" in completed.columns
                    else None
                )
                sync_status = "previous_completed_for_no_future"
            else:
                visible_index = match.get("htf_bar_index")
                sync_status = match.get("sync_status")
            keys.append((interval, sync_status, visible_index, containing_index))
        return tuple(keys)

    def _context_render_key(self, context: dict[str, dict[str, Any]]) -> tuple[Any, ...]:
        return tuple(
            (
                interval,
                state.get("sync_status"),
                state.get("htf_bar_index"),
                state.get("containing_htf_bar_index"),
                state.get("history_status"),
            )
            for interval, state in sorted(context.items())
        )

    def _render_context(self, context: dict[str, dict[str, Any]]) -> None:
        lines = [tr("multi_timeframe_readonly_notice", self.language), ""]
        for interval in self.selected_intervals() or tuple(context):
            state = context.get(interval)
            if not state:
                continue
            lines.append(f"[{interval}] {state['sync_status']}")
            lines.append(
                "  HTF time: {time} | close: {close}".format(
                    time=state["htf_open_time_bjt"] or "-",
                    close="-" if state["close"] is None else f"{state['close']:.6g}",
                )
            )
            if state["history_status"] != "available":
                lines.append(f"  {tr('multi_timeframe_insufficient_history', self.language)} ({state['available_bars']}/20)")
            else:
                lines.append(
                    "  ret20: {ret:.4%} | vol20: {vol:.4%} | trend: {trend} | vol: {vol_regime}".format(
                        ret=state["pre_simple_ret_20"],
                        vol=state["realized_vol_20"],
                        trend=state["trend_regime"],
                        vol_regime=state["volatility_regime"],
                    )
                )
        if self._context_errors:
            lines.append("")
            lines.append(tr("multi_timeframe_load_failed", self.language))
            lines.extend(f"  {interval}: {error}" for interval, error in self._context_errors.items())
        self.summaryText.setPlainText("\n".join(lines))

    def shutdown(self) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(1000)


__all__ = ["MultiTimeframePanel"]
