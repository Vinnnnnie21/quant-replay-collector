"""Destructive manual-trade record actions kept outside MainWindow."""

from __future__ import annotations

from PySide6 import QtWidgets

try:
    from app_logger import get_logger
    from render_state import RenderState
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger
    from ..render_state import RenderState


logger = get_logger(__name__)


def _render_state(window) -> RenderState:
    getter = getattr(window, "_chart_render_state", None)
    if callable(getter):
        return getter()
    state = getattr(window, "render_state", None)
    if state is None:
        state = RenderState()
        window.render_state = state
    return state


def confirm_clear_trade_records(window) -> None:
    if window._loading_data or window.app_state.export.running:
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("clear_trade_records_title"),
            window.tr("clear_trade_records_busy"),
        )
        return
    response = QtWidgets.QMessageBox.warning(
        window,
        window.tr("clear_trade_records_title"),
        window.tr("clear_trade_records_warning"),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Cancel,
    )
    if response != QtWidgets.QMessageBox.Yes:
        return
    phrase, accepted = QtWidgets.QInputDialog.getText(
        window,
        window.tr("clear_trade_records_title"),
        window.tr("clear_trade_records_phrase_prompt"),
    )
    if not accepted:
        return
    if phrase.strip() != window.tr("clear_trade_records_phrase"):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("clear_trade_records_title"),
            window.tr("clear_trade_records_phrase_mismatch"),
        )
        return
    try:
        deleted = window.storage.clear_manual_research_records()
    except Exception as exc:
        window._operation_error(window.tr("clear_trade_records_failed"), exc)
        return

    window.playing = False
    window._accum = 0.0
    window.trades.clear()
    window.events.clear()
    window._trade_by_id.clear()
    window._event_by_id.clear()
    window.undo_stack.clear()
    window.redo_stack.clear()
    window.restoring_session_id = None
    window.restore_snapshot_pending = False
    window.session_id = window._new_id("sess")
    for checkbox in window.tag_checks:
        checkbox.setChecked(False)
    window.noteEdit.clear()
    window.detailText.setPlainText(window.tr("none"))
    window.replay_controller.load_state(window.cursor, False, window.follow_latest, 0.0)
    window.persist_session_state()
    _render_state(window).mark_events_changed()
    window._sync_markers()
    window._refresh_tables()
    window._render_dirty = True
    window._render(force=True)
    if window._analysis_workspace is not None:
        try:
            window._analysis_workspace.refresh()
        except Exception:
            logger.exception("Failed to refresh analysis workspace after clearing trade samples")
    message = window.tr("clear_trade_records_done").format(**deleted)
    window._log(message)
    QtWidgets.QMessageBox.information(window, window.tr("clear_trade_records_title"), message)


__all__ = ["confirm_clear_trade_records"]
