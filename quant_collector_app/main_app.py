from __future__ import annotations

import json
import math
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from app_icon import apply_application_icon
from app_config import (
    APP_NAME,
    APP_VERSION,
    LOG_DIR,
    DEFAULT_INITIAL_EQUITY,
    DEFAULT_TRADE_NOTIONAL,
    DEFAULT_FEE_BPS,
    DEFAULT_SLIPPAGE_BPS,
    DEFAULT_FILL_MODE,
    BINANCE_TOP_MARKET_CAP_SYMBOLS,
    EXPORT_DIR,
    load_theme_settings,
)
from app_logger import get_logger, install_exception_hook
from app_i18n import tr as i18n_tr, translate_for
from app_settings import load_app_settings, save_app_settings
from database_backup import backup_database_if_needed
from execution import ExecutionSettings
from market_data import bjt_now_iso, clamp
from premium_monitor import PremiumWorker
from premium_controller import PremiumController
from presenters.formatters import (
    fill_mode_label,
    format_event_detail,
    format_trade_detail,
)
from presenters.table_presenter import (
    populate_equity_table,
    populate_event_study_table,
    populate_event_table,
    populate_recent_event_list,
    populate_trade_tables,
)
from presenters.status_presenter import (
    refresh_premium_plot,
    show_market_dirty_feedback,
    update_current_price_line,
    update_header,
    update_load_play_button,
    update_trade_buttons_enabled,
)
from replay_controller import ReplayController
from render_state import RenderState
from safe_shutdown import SafeShutdownCoordinator
from render.chart_render_adapter import (
    autoscale_y,
    clamp_xrange,
    current_xrange,
    mark_rendered,
    on_chart_drag_finished as apply_chart_drag_finished,
    on_chart_drag_started as apply_chart_drag_started,
    on_price_view_range_changed as apply_price_view_range_change,
    rebuild_items,
    refresh_multi_timeframe_context,
    render_active_drag_frame,
    render_chart,
    set_xrange,
    should_render_now,
    soft_follow_should_apply,
    sync_markers,
)
from controllers.analysis_controller import AnalysisRefreshController
from controllers.daily_backup_controller import DailyBackupController
from controllers.export_task_controller import ExportTaskController
from controllers.market_data_controller import (
    accept_loaded_market_key as apply_loaded_market_key,
    clear_timeframe_switch_pending,
    current_market_key,
    is_market_params_dirty,
    load_data as request_market_data_load,
    load_multi_timeframe_context,
    load_or_toggle_play as apply_load_or_toggle_play,
    normalized_symbol,
    on_interval_changed_for_dynamic_switch as apply_dynamic_interval_change,
    on_load_progress as apply_load_progress,
    on_loaded as apply_loaded_market_data,
    on_market_params_changed as apply_market_params_change,
    on_multi_timeframe_load_failed as apply_multi_timeframe_load_failure,
    persist_loaded_market_data,
)
from controllers.replay_ui_controller import (
    adjust_speed as replay_adjust_speed,
    current_speed as replay_current_speed,
    jump_to_end as replay_jump_to_end,
    on_speed_changed as apply_speed_change,
    on_timer as apply_replay_timer,
    on_user_interaction as apply_user_chart_interaction,
    reset_view as reset_replay_view,
    step_once as replay_step_once,
    toggle_follow as replay_toggle_follow,
    toggle_play as replay_toggle_play,
)
from controllers.trade_action_controller import (
    ActionCommand,
    apply_close_trade_result,
    apply_open_trade_result,
    apply_tp_sl_triggers,
    current_bar as current_trade_bar,
    current_tags_and_note as current_trade_tags_and_note,
    display_interval,
    execute_command as execute_trade_command,
    is_display_interval_same_as_sample_interval,
    is_trade_recording_allowed,
    pause_replay_for_manual_trade,
    raise_trade_action_error,
    redo as redo_trade_command,
    request_close_trade as apply_close_trade_request,
    request_open_trade as apply_open_trade_request,
    sample_interval,
    selected_open_trade as find_selected_open_trade,
    start_new_session_for_current_display_interval as start_trade_sample_session,
    trade_use_case,
    undo as undo_trade_command,
    undo_close_trade_result,
    undo_open_trade_result,
    warn_trade_interval_mismatch,
)


from controllers.trade_record_controller import (
    confirm_clear_trade_records as apply_clear_trade_records,
    confirm_delete_selected_trade as apply_delete_selected_trade,
    confirm_delete_session_trade as apply_delete_session_trade,
    confirm_delete_performance_session as apply_delete_performance_session,
    confirm_delete_trade_range as apply_delete_trade_range,
    preview_trade_data_range as apply_preview_trade_data_range,
    refresh_trade_management_sessions as apply_refresh_trade_management_sessions,
    load_trade_management_session_trades as apply_load_trade_management_session_trades,
)
from controllers.session_resume_controller import (
    continue_performance_session as apply_continue_performance_session,
    refresh_replay_performance_sessions as apply_refresh_replay_performance_sessions,
)
from services.analysis_refresh import (
    AnalysisRefreshRequest,
    AnalysisRefreshResult,
    PublishedMarketData,
    build_dataset_summary_text,
    build_event_study_summary_frame,
)
from services.session_service import (
    build_session_restore_plan,
    save_session_state,
    should_autosave,
)
from services.export_service import build_export_task_request
from services.ui_message_localizer import localize_worker_message
from services.trade_use_cases import TradeActionResult, TradeUseCase
from ui_watchdog import UiFreezeWatchdog
from state import AppState
from startup import bootstrap_runtime_dirs, configure_logging
from storage import StorageManager
from task_lifecycle import BackgroundTaskLifecycle
from trade_controller import TradeController
from render.marker_renderer import MarkerPayloadCache
from views.main_window_layout import build_main_window_ui
from views.main_window_connections import (
    add_window_shortcut,
    connect_main_window_signals,
    focus_is_text_entry,
    setup_table,
)
from views.main_window_presentation import (
    apply_main_window_theme,
    retranslate_main_window_ui,
)
from views.session_ui_adapter import (
    apply_session_restore_plan,
    build_session_save_input,
)
from views.theme_dialog import ThemeDialog
from workers.loader_worker import LoaderWorker


ROLE_ID = QtCore.Qt.UserRole
UI_TICK_INTERVAL_MS = 8
INTERACTION_RENDER_INTERVAL_MS = 8
logger = get_logger(__name__)


def _maybe_log_slow_operation(target: Any, name: str, started: float) -> None:
    log_slow = getattr(target, "_log_slow_operation", None)
    if callable(log_slow):
        log_slow(name, started)


class MainWindow(QtWidgets.QMainWindow):
    requestLoad = QtCore.Signal(object)
    requestPremium = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1820, 980)

        self.storage = StorageManager()
        self.trade_controller = TradeController(self.storage, export_version=APP_VERSION)
        self.trade_use_cases = TradeUseCase(self.trade_controller)
        self.exporter = None
        self.export_controller = None
        self.premium_controller = PremiumController()
        self.replay_controller = ReplayController()
        self.app_state = AppState()
        self.task_lifecycle = BackgroundTaskLifecycle()
        self._export_success_callback = None

        self.df = pd.DataFrame()
        self._market_data_generation = 0
        self.cursor = 0
        self._drawn_n = -1
        self._last_rebuild_key = None
        self._last_cursor_for_series = -1
        self._accum = 0.0
        self._last_tick = QtCore.QElapsedTimer()
        self._last_tick.start()
        self.playing = False
        self.follow_latest = False
        self.user_view_lock = False
        self.last_user_interaction = 0.0
        self.window_bars = 140
        self.pad_right = 8
        self._base_bars_per_sec = 1.0
        self.manual_xrange: tuple[float, float] | None = None
        self._programmatic_view_update = False
        self._chart_drag_active = False
        self._loading_data = False
        self._loaded_market_key: tuple[str, str, str, str] | None = None
        self._pending_market_key: tuple[str, str, str, str] | None = None
        self._display_market_key: tuple[str, str, str, str] | None = None
        self._sample_market_key: tuple[str, str, str, str] | None = None
        self._sample_cursor_bar_index = 0
        self.market_dirty = False
        self._timeframe_switch_pending = False
        self._pending_time_anchor_bjt = None
        self._pending_view_time_span_seconds: float | None = None
        self._pending_was_playing = False
        self._pending_follow_latest = False
        self._pending_switch_from_interval: str | None = None
        self._pending_switch_to_interval: str | None = None
        self._queued_dynamic_interval: str | None = None
        self._render_dirty = True
        self.render_state = RenderState()
        self._marker_payload_cache = MarkerPayloadCache()
        self._last_marker_sync_key = None
        self._last_multi_timeframe_refresh_key = None
        self._last_render_msec = 0
        self._render_interval_ms = 50
        self._interaction_render_interval_ms = INTERACTION_RENDER_INTERVAL_MS
        self._trade_transaction_active = False
        self._last_autosave_msec = 0
        self.theme_settings = load_theme_settings()
        self.app_settings = load_app_settings()
        self.current_language = str(self.app_settings.get("language") or "zh_CN")

        self.session_id = None
        self.restoring_session_id = None
        self.restore_snapshot_pending = False
        self._restoring_session_settings = False

        self.trades: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.undo_stack: list[ActionCommand] = []
        self.redo_stack: list[ActionCommand] = []
        self._is_replaying_history = False
        self._event_by_id: dict[str, dict[str, Any]] = {}
        self._trade_by_id: dict[str, dict[str, Any]] = {}
        self._shortcuts: list[QtGui.QShortcut] = []
        self._analysis_workspace = None
        self._analysis_performance_payload = None
        self.analysis_refresh_controller = AnalysisRefreshController(
            snapshot_factory=self._analysis_refresh_request,
            is_playing=lambda: bool(self.playing),
            lifecycle=self.task_lifecycle,
            parent=self,
        )
        self.analysis_refresh_controller.resultReady.connect(self._apply_analysis_refresh_result)
        self.analysis_refresh_controller.failed.connect(self._on_analysis_refresh_failed)
        self.export_task_controller = ExportTaskController(lifecycle=self.task_lifecycle, parent=self)
        self.export_task_controller.finished.connect(self._on_export_finished)
        self.export_task_controller.failed.connect(self._on_export_failed)
        self.export_task_controller.cancelled.connect(self._on_export_cancelled)

        self.loader_thread = QtCore.QThread(self)
        self.loader = LoaderWorker()
        self.loader.moveToThread(self.loader_thread)
        self.loader_thread.start()

        self.premium_thread = QtCore.QThread(self)
        self.premium_worker = PremiumWorker()
        self.premium_worker.moveToThread(self.premium_thread)
        self.premium_thread.start()

        self._build_ui()
        self._handling_close_event = False
        self._safe_shutdown_coordinator = SafeShutdownCoordinator(
            lifecycle=self.task_lifecycle,
            save=self._save_for_shutdown,
            stop_producers=self._stop_shutdown_producers,
            show_status=self.status.setText,
            schedule_poll=lambda callback: QtCore.QTimer.singleShot(50, callback),
            finalize=self._finalize_shutdown,
        )
        self.daily_backup_controller = DailyBackupController(
            db_path=self.storage.db_path,
            backup_dir=self.storage.backup_dir,
            lifecycle=self.task_lifecycle,
            parent=self,
        )
        self.daily_backup_controller.progress.connect(self._on_daily_backup_progress)
        self.daily_backup_controller.finished.connect(self._on_daily_backup_finished)
        self.daily_backup_controller.failed.connect(self._on_daily_backup_failed)
        self.daily_backup_controller.cancelled.connect(self._on_daily_backup_cancelled)
        self._restore_layout_preferences()
        self.analysis_refresh_controller.progress.connect(self.status.setText)
        self.export_task_controller.progress.connect(
            lambda message: self.status.setText(
                localize_worker_message(message, self.tr)
            )
        )
        self._connect()
        self._install_theme()
        self.apply_theme(self.theme_settings)

        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(UI_TICK_INTERVAL_MS)

        self.autosave_timer = QtCore.QTimer(self)
        self.autosave_timer.timeout.connect(self._on_autosave_timer)
        self.autosave_timer.start(2000)

        self.premium_timer = QtCore.QTimer(self)
        self.premium_timer.timeout.connect(self.request_premium_sample)
        self.premium_timer.start(30_000)
        self.request_premium_sample()
        self.ui_watchdog = UiFreezeWatchdog(log_dir=LOG_DIR, parent=self)

        self._restore_latest_session_if_any()
        self.refresh_replay_performance_sessions()
        self.daily_backup_controller.schedule()

    def closeEvent(self, event: QtGui.QCloseEvent):
        self._handling_close_event = True
        try:
            ready = self._safe_shutdown_coordinator.request_close()
        finally:
            self._handling_close_event = False
        if ready:
            self._shutdown_graphics()
            event.accept()
        else:
            event.ignore()

    def _shutdown_graphics(self) -> None:
        for widget_name in ("premiumPlot", "glw"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.shutdown()

    def _save_for_shutdown(self) -> None:
        try:
            self.persist_session_state()
        except Exception:
            logger.exception("关闭窗口时保存会话失败")

    def _stop_shutdown_producers(self) -> None:
        for timer_name in ("timer", "autosave_timer", "premium_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()

    def _backup_local_database(self) -> dict[str, Any]:
        try:
            return backup_database_if_needed(
                self.storage.db_path,
                self.storage.backup_dir,
            )
        except Exception as exc:
            logger.exception("Local database backup failed.")
            message = translate_for(self, "log.backup_failed").format(
                error=f"{type(exc).__name__}: {exc}"
            )
            self.status.setText(message)
            self._log(message)
            return {"status": "failed", "error": message}

    def _on_daily_backup_finished(self, result: dict[str, Any]) -> None:
        status = str(result.get("status") or "ok")
        self._log(self.tr("log.backup_finished").format(status=status))
        self._on_daily_backup_progress(self.tr("worker.backup.complete"))

    def _on_daily_backup_progress(self, message: str) -> None:
        active_tasks = set(getattr(self.task_lifecycle, "active_tasks", ()))
        if active_tasks - {"daily_backup"}:
            return
        self.status.setText(
            localize_worker_message(message, lambda key: translate_for(self, key))
        )

    def _on_daily_backup_failed(self, error: str) -> None:
        message = self.tr("log.backup_failed").format(error=error)
        logger.error("Daily database backup failed: %s", error)
        self.status.setText(message)
        self._log(message)

    def _on_daily_backup_cancelled(self) -> None:
        self._log(self.tr("log.backup_cancelled"))

    def _finalize_shutdown(self) -> bool:
        for timer_name in ("timer", "autosave_timer", "premium_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        panel_stopped = True
        if hasattr(self, "multiTimeframePanel"):
            panel_stopped = self.multiTimeframePanel.shutdown() is not False
        if hasattr(self, "ui_watchdog"):
            self.ui_watchdog.shutdown()
        workspace_stopped = True
        workspace = getattr(self, "_analysis_workspace", None)
        if workspace is not None:
            workspace_stopped = workspace.shutdown() is not False
        controllers_stopped = True
        daily_backup_controller = getattr(self, "daily_backup_controller", None)
        if daily_backup_controller is not None:
            controllers_stopped = daily_backup_controller.shutdown() is not False
        controllers_stopped = (
            self.export_task_controller.shutdown() is not False
            and controllers_stopped
        )
        controllers_stopped = (
            self.analysis_refresh_controller.shutdown() is not False
            and controllers_stopped
        )
        stopped = True
        for thread in (self.loader_thread, self.premium_thread):
            if thread.isRunning():
                thread.quit()
                stopped = False
        if (
            not panel_stopped
            or not workspace_stopped
            or not controllers_stopped
            or not stopped
        ):
            return False
        if not self._handling_close_event:
            QtCore.QTimer.singleShot(0, self.close)
        return True

    # ---------- UI ----------
    def _build_ui(self):
        build_main_window_ui(self)

    def _setup_table(self, table: QtWidgets.QTableWidget):
        setup_table(table)

    def tr(self, key: str, default: str | None = None) -> str:
        return i18n_tr(key, self.current_language, default)

    def apply_language(self, language: str):
        self.current_language = str(language or "zh_CN")
        settings = load_app_settings()
        settings["language"] = self.current_language
        save_app_settings(settings)
        self.retranslate_ui()
        if hasattr(self, "_refresh_tables"):
            self._refresh_tables(include_heavy=False)
        if hasattr(self, "detailText"):
            self.detailText.setPlainText(self.tr("ui.no_details"))
        for attr in ("_analysis_workspace",):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "retranslate_ui"):
                widget.retranslate_ui()

    def retranslate_ui(self):
        retranslate_main_window_ui(self)

    def _add_shortcut(self, sequence, handler):
        return add_window_shortcut(self, sequence, handler)

    def _focus_is_text_entry(self) -> bool:
        return focus_is_text_entry()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "symbolBox", None) and event.type() == QtCore.QEvent.MouseButtonPress:
            self.toggle_symbol_panel(not self.symbolPanel.isVisible())
            return True
        return super().eventFilter(obj, event)

    def _install_theme(self):
        QtWidgets.QApplication.instance().setStyle("Fusion")
        pg.setConfigOptions(antialias=False)

    def _set_widget_role(self, widget: QtWidgets.QWidget, role: str):
        widget.setProperty("role", role)
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()

    def apply_theme(self, theme: dict):
        apply_main_window_theme(self, theme)

    def open_theme_dialog(self):
        dlg = ThemeDialog(self.theme_settings, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.apply_theme(dlg.get_theme())
            self._log(self.tr("log.theme_applied"))

    def open_settings_dialog(self):
        from settings_dialog import SettingsDialog

        dlg = SettingsDialog(self)
        try:
            from views.main_window_presentation import apply_role_button_styles, apply_themed_input_styles
            from views.widget_effects import apply_role_button_shadows

            apply_role_button_styles(dlg, self.theme_settings)
            apply_themed_input_styles(dlg, self.theme_settings)
            apply_role_button_shadows(dlg)
        except Exception:
            pass
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._update_header()
            self._log(self.tr("log.settings_applied"))

    def open_analysis_workspace(self):
        from analysis_workspace import AnalysisWorkspace

        if self.backtestPanel is None:
            from backtest_panel import BacktestPanel

            self.backtestPanel = BacktestPanel(self)
        if self.strategyConsistencyPanel is None:
            from strategy_consistency_panel import StrategyConsistencyPanel

            self.strategyConsistencyPanel = StrategyConsistencyPanel(self)
        if not hasattr(self, "_analysis_workspace") or self._analysis_workspace is None:
            self._analysis_workspace = AnalysisWorkspace(
                self,
                parent=self.workspaceStack,
                embedded=True,
            )
            self._analysis_workspace.setObjectName("analysisWorkspace")
            self.workspaceStack.addWidget(self._analysis_workspace)
            saved_subtab = int((self.app_settings or {}).get("analysis_subtab", 0) or 0)
            self._analysis_workspace.tabs.setCurrentIndex(
                max(0, min(self._analysis_workspace.tabs.count() - 1, saved_subtab))
            )
            self._analysis_workspace.tabs.currentChanged.connect(
                lambda *_args: self._save_layout_preferences()
            )
        try:
            from views.main_window_presentation import apply_role_button_styles, apply_themed_input_styles
            from views.widget_effects import apply_role_button_shadows

            for _panel in (self.backtestPanel, self.strategyConsistencyPanel, self._analysis_workspace):
                apply_role_button_styles(_panel, self.theme_settings)
                apply_themed_input_styles(_panel, self.theme_settings)
                apply_role_button_shadows(_panel)
        except Exception:
            pass
        try:
            self._analysis_workspace.refresh()
        except Exception as exc:
            self._log(
                self.tr("log.analysis_workspace_refresh_failed").format(
                    error=f"{type(exc).__name__}: {exc}"
                )
            )
        self.workspaceStack.setCurrentWidget(self._analysis_workspace)
        self.btnAnalysisWorkspace.setChecked(True)

    def open_replay_workspace(self):
        self.workspaceStack.setCurrentWidget(self.replayWorkspace)
        self.btnReplayWorkspace.setChecked(True)

    def _restore_layout_preferences(self):
        settings = self.app_settings or {}
        right_visible = bool(settings.get("right_panel_visible", True))
        self.btnToggleRightPanel.setChecked(right_visible)
        right_width = max(300, min(460, int(settings.get("right_panel_width", 360) or 360)))
        self._expanded_right_panel_width = right_width
        self.bodySplitter.setSizes([1180, right_width])
        right_tab = max(0, min(self.rightTabs.count() - 1, int(settings.get("right_panel_tab", 0) or 0)))
        self.rightTabs.setCurrentIndex(right_tab)

        bottom_visible = bool(settings.get("bottom_panel_visible", True))
        self.btnToggleBottomPanel.setChecked(not bottom_visible)
        self.bottomTabs.setVisible(bottom_visible)
        sizes = settings.get("bottom_splitter_sizes", [720, 220])
        if isinstance(sizes, list) and len(sizes) == 2 and all(int(value) > 0 for value in sizes):
            self.centerSplitter.setSizes([int(sizes[0]), int(sizes[1])])

    def _save_layout_preferences(self):
        settings = load_app_settings()
        body_sizes = self.bodySplitter.sizes()
        center_sizes = self.centerSplitter.sizes()
        settings.update(
            {
                "right_panel_visible": self.rightTabs.isVisible(),
                "right_panel_width": self._expanded_right_panel_width if not self.rightTabs.isVisible() else (body_sizes[-1] if len(body_sizes) == 2 and body_sizes[-1] >= 300 else 360),
                "right_panel_tab": self.rightTabs.currentIndex(),
                "bottom_panel_visible": self.bottomTabs.isVisible(),
                "bottom_splitter_sizes": center_sizes if len(center_sizes) == 2 and all(center_sizes) else [720, 220],
                "analysis_subtab": self._analysis_workspace.tabs.currentIndex() if self._analysis_workspace is not None else int(settings.get("analysis_subtab", 0) or 0),
            }
        )
        self.app_settings = settings
        save_app_settings(settings)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "rightPanel"):
            return
        if self.width() < 1500 and self.rightTabs.isVisible():
            self._right_panel_auto_collapsed = True
            blocked = self.btnToggleRightPanel.blockSignals(True)
            self.btnToggleRightPanel.setChecked(False)
            self.btnToggleRightPanel.blockSignals(blocked)
            self._set_right_panel_expanded(False)
        elif self.width() >= 1600 and getattr(self, "_right_panel_auto_collapsed", False):
            self._right_panel_auto_collapsed = False
            if bool((self.app_settings or {}).get("right_panel_visible", True)):
                blocked = self.btnToggleRightPanel.blockSignals(True)
                self.btnToggleRightPanel.setChecked(True)
                self.btnToggleRightPanel.blockSignals(blocked)
                self._set_right_panel_expanded(True)

    def toggle_detail_panel(self, hidden: bool):
        self.detailText.setVisible(not hidden)
        self.btnToggleDetail.setText(
            self.tr("ui.show_details") if hidden else self.tr("ui.hide_details")
        )

    def toggle_log_drawer(self, collapsed: bool):
        self.log.setVisible(not collapsed)
        self.logSummaryLabel.setVisible(collapsed)
        if collapsed:
            self.logDrawer.setMinimumHeight(32)
            self.logDrawer.setMaximumHeight(36)
            self.btnToggleLog.setText(self.tr("ui.expand_log"))
        else:
            expanded_height = max(160, min(260, int(max(1, self.height()) * 0.23)))
            self.logDrawer.setMinimumHeight(120)
            self.logDrawer.setMaximumHeight(expanded_height)
            self.btnToggleLog.setText(self.tr("ui.collapse_log"))

    def toggle_symbol_panel(self, expanded: bool):
        self.symbolPanel.setVisible(expanded)
        if expanded:
            self.symbolSearchEdit.setFocus()

    def filter_symbol_list(self, text: str):
        keyword = text.strip().upper()
        self.symbolList.clear()
        for symbol in BINANCE_TOP_MARKET_CAP_SYMBOLS:
            if not keyword or keyword in symbol:
                self.symbolList.addItem(symbol)

    def on_symbol_item_selected(self, item: QtWidgets.QListWidgetItem):
        if item is not None:
            self._set_symbol_value(item.text())
            self.toggle_symbol_panel(False)

    def _set_symbol_value(self, symbol: str):
        value = str(symbol or "").strip().upper()
        if not value:
            return
        if self.symbolBox.findText(value, QtCore.Qt.MatchFixedString) < 0:
            self.symbolBox.addItem(value)
        self.symbolBox.setCurrentText(value)

    def _fill_mode_value(self) -> str:
        data = self.fillModeBox.currentData()
        value = data if data is not None else self.fillModeBox.currentText()
        return str(value or DEFAULT_FILL_MODE).strip().upper()

    def _set_fill_mode_value(self, mode: Any):
        value = str(mode or DEFAULT_FILL_MODE).strip().upper()
        for idx in range(self.fillModeBox.count()):
            if str(self.fillModeBox.itemData(idx) or "").upper() == value:
                self.fillModeBox.setCurrentIndex(idx)
                return
        self.fillModeBox.addItem(fill_mode_label(value), value)
        self.fillModeBox.setCurrentIndex(self.fillModeBox.count() - 1)

    def on_price_view_range_changed(self, _viewbox, view_range):
        apply_price_view_range_change(self, view_range)

    def on_chart_drag_started(self):
        apply_chart_drag_started(self)

    def on_chart_drag_finished(self):
        apply_chart_drag_finished(self)

    def _connect(self):
        connect_main_window_signals(self)

    # ---------- Session ----------
    def _restore_latest_session_if_any(self):
        last = self.storage.get_latest_session()
        if not last:
            self.session_id = self._new_id("sess")
            return
        try:
            plan = build_session_restore_plan(
                last,
                default_initial_equity=DEFAULT_INITIAL_EQUITY,
                default_trade_notional=DEFAULT_TRADE_NOTIONAL,
                default_fee_bps=DEFAULT_FEE_BPS,
                default_slippage_bps=DEFAULT_SLIPPAGE_BPS,
                default_fill_mode=DEFAULT_FILL_MODE,
            )
            self.restoring_session_id = plan.session_id
            self.session_id = plan.session_id
            self._restoring_session_settings = True
            try:
                apply_session_restore_plan(self, plan)
            finally:
                self._restoring_session_settings = False
            self.restore_snapshot_pending = True
            self._log(self.tr("log.session_restore_start").format(session_id=self.session_id))
            QtCore.QTimer.singleShot(100, lambda: self.load_data(restore=True))
        except Exception as e:
            logger.exception("恢复历史会话失败")
            self._log(
                self.tr("log.session_restore_failed").format(
                    error=f"{type(e).__name__}: {e}"
                )
            )
            self.session_id = self._new_id("sess")

    def refresh_replay_performance_sessions(self):
        return apply_refresh_replay_performance_sessions(self)

    def continue_performance_session(self):
        return apply_continue_performance_session(self)

    def persist_session_state(self):
        started = time.perf_counter()
        if not self.session_id:
            return
        try:
            now_iso = bjt_now_iso()
            result = save_session_state(
                self.storage,
                build_session_save_input(
                    self,
                    now_iso=now_iso,
                    app_version=APP_VERSION,
                )
            )
            self._sample_cursor_bar_index = result.sample_cursor_bar_index
        finally:
            _maybe_log_slow_operation(self, "persist_session_state", started)

    def _on_autosave_timer(self):
        now = QtCore.QDateTime.currentMSecsSinceEpoch()
        if not should_autosave(
            is_transaction_active=bool(getattr(self, "_trade_transaction_active", False)),
            is_playing=bool(self.playing),
            now_msec=int(now),
            last_autosave_msec=int(getattr(self, "_last_autosave_msec", 0)),
        ):
            return
        try:
            self.persist_session_state()
            self._last_autosave_msec = now
        except Exception:
            logger.exception("autosave failed")

    def _operation_context(self) -> dict[str, Any]:
        return {
            "cursor": int(getattr(self, "cursor", 0)),
            "df_rows": int(len(getattr(self, "df", []))),
            "playing": bool(getattr(self, "playing", False)),
            "trades": int(len(getattr(self, "trades", []))),
            "events": int(len(getattr(self, "events", []))),
        }

    def _log_slow_operation(self, name: str, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms < 200.0:
            return
        context = self._operation_context()
        message = (
            "slow_operation function=%s elapsed_ms=%.1f cursor=%s df_rows=%s "
            "playing=%s trades=%s events=%s"
        )
        args = (
            name,
            elapsed_ms,
            context["cursor"],
            context["df_rows"],
            context["playing"],
            context["trades"],
            context["events"],
        )
        if elapsed_ms >= 1000.0:
            logger.error(message, *args)
        else:
            logger.warning(message, *args)

    def _should_render_now(self, force: bool = False) -> bool:
        return should_render_now(self, force)

    def _mark_rendered(self) -> None:
        mark_rendered(self)

    def _pause_replay_for_manual_trade(self) -> None:
        pause_replay_for_manual_trade(self)

    def confirm_clear_trade_records(self):
        apply_clear_trade_records(self)

    def confirm_delete_trade_range(self):
        apply_delete_trade_range(self)

    def confirm_delete_selected_trade(self):
        apply_delete_selected_trade(self)

    def confirm_delete_session_trade(self):
        apply_delete_session_trade(self)

    def confirm_delete_performance_session(self):
        apply_delete_performance_session(self)

    def preview_trade_data_range(self):
        return apply_preview_trade_data_range(self)

    def refresh_trade_management_sessions(self):
        return apply_refresh_trade_management_sessions(self)

    def load_trade_management_session_trades(self):
        return apply_load_trade_management_session_trades(self)

    def _new_id(self, prefix: str):
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _chart_render_state(self) -> RenderState:
        state = getattr(self, "render_state", None)
        if state is None:
            state = RenderState()
            self.render_state = state
        return state

    # ---------- Data load ----------
    def _normalized_symbol(self) -> str | None:
        return normalized_symbol(self)

    def _current_market_key(self) -> tuple[str, str, str, str]:
        return current_market_key(self)

    def _is_market_params_dirty(self) -> bool:
        return is_market_params_dirty(self)

    def _accept_loaded_market_key(self, df: pd.DataFrame, successful: bool = True) -> None:
        apply_loaded_market_key(self, df, successful)

    def _show_market_dirty_feedback(self) -> None:
        show_market_dirty_feedback(self)

    def _refresh_multi_timeframe_context(self) -> None:
        refresh_multi_timeframe_context(self)

    def _load_multi_timeframe_context(self) -> None:
        load_multi_timeframe_context(self)

    def on_multi_timeframe_load_failed(self, interval: str, error: str) -> None:
        apply_multi_timeframe_load_failure(self, interval, error)

    def on_interval_changed_for_dynamic_switch(self, new_interval: str) -> None:
        apply_dynamic_interval_change(self, new_interval)

    def on_market_params_changed(self, *_args) -> None:
        apply_market_params_change(self)

    def _clear_timeframe_switch_pending(self) -> None:
        clear_timeframe_switch_pending(self)

    def load_data(
        self,
        restore: bool = False,
        use_cache: bool | None = None,
        dynamic_switch: bool = False,
        preserve_time_anchor: bool = False,
        auto_resume_after_load: bool = False,
        reset_session: bool | None = None,
    ):
        return request_market_data_load(
            self,
            restore=restore,
            use_cache=use_cache,
            dynamic_switch=dynamic_switch,
            preserve_time_anchor=preserve_time_anchor,
            auto_resume_after_load=auto_resume_after_load,
            reset_session=reset_session,
        )

    def on_load_progress(self, message: str):
        apply_load_progress(self, message)

    def on_loaded(self, df: pd.DataFrame, message: str):
        apply_loaded_market_data(self, df, message)

    def _persist_loaded_market_data(self):
        persist_loaded_market_data(self)

    # ---------- Playback ----------
    def load_or_toggle_play(self):
        apply_load_or_toggle_play(self)

    def _update_load_play_button(self):
        update_load_play_button(self)

    def on_speed_changed(self, value: int):
        apply_speed_change(self, value)

    def current_speed(self):
        return replay_current_speed(self)

    def speed_down(self):
        replay_adjust_speed(self, -1)

    def speed_up(self):
        replay_adjust_speed(self, 1)

    def execution_settings(self) -> ExecutionSettings:
        return self.trade_controller.execution_settings(
            self._fill_mode_value(),
            self.feeBpsSpin.value(),
            self.slippageBpsSpin.value(),
            self.tradeNotionalSpin.value(),
        )

    def take_profit_pct_value(self) -> float | None:
        value = self.takeProfitPctSpin.value()
        return float(value) if value is not None and float(value) > 0 else None

    def stop_loss_pct_value(self) -> float | None:
        value = self.stopLossPctSpin.value()
        return float(value) if value is not None and float(value) > 0 else None

    def on_execution_settings_changed(self, *_):
        if bool(getattr(self, "_restoring_session_settings", False)):
            return
        try:
            self.persist_session_state()
            self._sync_equity_curve()
            self._refresh_tables()
        except Exception as e:
            self._log(
                self.tr("log.execution_settings_failed").format(
                    error=f"{type(e).__name__}: {e}"
                )
            )

    def _sync_equity_curve(self):
        from accounting import build_equity_curve

        if not self.session_id:
            return
        rows = build_equity_curve(
            self.trades,
            self.session_id,
            float(self.initialEquitySpin.value()),
            float(self.tradeNotionalSpin.value()),
        )
        self.trade_controller.replace_equity_curve(self.session_id, rows)

    def on_timer(self):
        apply_replay_timer(self)

    def toggle_play(self):
        replay_toggle_play(self)

    def step_once(self):
        replay_step_once(self)

    def jump_to_end(self):
        replay_jump_to_end(self)

    def toggle_follow(self):
        replay_toggle_follow(self)

    def on_user_interaction(self):
        apply_user_chart_interaction(self)

    def reset_view(self):
        reset_replay_view(self)

    def _rebuild_items(self, n=None, visible_range=None):
        rebuild_items(self, n=n, visible_range=visible_range)

    def _render_active_drag_frame(self):
        render_active_drag_frame(self)

    def _current_xrange(self):
        return current_xrange(self)

    def _set_xrange(self, x0: float, x1: float, force: bool = False):
        set_xrange(self, x0, x1, force)

    def _clamp_xrange(self, x0: float, x1: float):
        return clamp_xrange(self, x0, x1)

    def _soft_follow_should_apply(self):
        return soft_follow_should_apply(self)

    def _autoscale_y(self, x0, x1):
        autoscale_y(self, x0, x1)

    def _sync_markers(self, force_reindex: bool | None = None):
        sync_markers(self, force_reindex)

    def _update_header(self):
        update_header(self)

    def _render(self, force=False):
        render_chart(self, force)

    # ---------- Trade / Event ----------
    def current_bar(self):
        return current_trade_bar(self)

    def current_tags_and_note(self):
        return current_trade_tags_and_note(self)

    def _display_interval(self) -> str:
        return display_interval(self)

    def _sample_interval(self) -> str:
        return sample_interval(self)

    def _is_display_interval_same_as_sample_interval(self) -> bool:
        return is_display_interval_same_as_sample_interval(self)

    def _is_trade_recording_allowed(self) -> bool:
        return is_trade_recording_allowed(self)

    def _warn_trade_interval_mismatch(self) -> None:
        warn_trade_interval_mismatch(self)

    def _update_trade_buttons_enabled(self) -> None:
        update_trade_buttons_enabled(self)

    def start_new_session_for_current_display_interval(self) -> None:
        start_trade_sample_session(self)

    def _selected_id_from_table(self, table: QtWidgets.QTableWidget):
        selection = table.selectionModel()
        if selection is None:
            return None
        rows = selection.selectedRows()
        if len(rows) != 1:
            return None
        row = rows[0].row()
        if row < 0 or row >= table.rowCount():
            return None
        item = table.item(row, 0)
        return item.data(ROLE_ID) if item else None

    def _operation_error(self, title: str, exc: Exception):
        message = f"{type(exc).__name__}: {exc}"
        logger.exception("%s：%s", title, exc)
        self._log(f"{title}：{message}")
        QtWidgets.QMessageBox.critical(self, title, message)

    def _trade_use_case(self) -> TradeUseCase:
        return trade_use_case(self)

    @staticmethod
    def _raise_trade_action_error(result: TradeActionResult) -> None:
        raise_trade_action_error(result)

    def _apply_open_trade_result(self, result: TradeActionResult) -> None:
        apply_open_trade_result(self, result)

    def _undo_open_trade_result(self, result: TradeActionResult) -> None:
        undo_open_trade_result(self, result)

    def _apply_close_trade_result(self, result: TradeActionResult, trade: dict[str, Any]) -> None:
        apply_close_trade_result(self, result, trade)

    def _undo_close_trade_result(self, result: TradeActionResult, trade: dict[str, Any]) -> None:
        undo_close_trade_result(self, result, trade)

    def request_open_trade(self, side: str):
        apply_open_trade_request(self, side)

    def request_close_trade(self, expected_side: str):
        apply_close_trade_request(self, expected_side)

    def _apply_tp_sl_triggers(self, from_bar_index: int, to_bar_index: int) -> int:
        return apply_tp_sl_triggers(self, from_bar_index, to_bar_index)

    def selected_open_trade(self, verify_db: bool = False):
        return find_selected_open_trade(self, verify_db)

    def on_open_trade_selected(self):
        trade = self.selected_open_trade()
        if trade:
            self.detailText.setPlainText(
                format_trade_detail(trade, language=self.current_language)
            )
        else:
            self.detailText.setPlainText(self.tr("ui.no_details"))

    def on_closed_trade_selected(self):
        trade_id = self._selected_id_from_table(self.closedTradesTable)
        if not trade_id:
            return
        trade = self._trade_by_id.get(trade_id)
        if trade:
            self.detailText.setPlainText(
                format_trade_detail(trade, language=self.current_language)
            )

    def on_event_selected(self):
        event_id = self._selected_id_from_table(self.eventTable)
        if not event_id:
            return
        event = self._event_by_id.get(event_id)
        if not event:
            self._log(self.tr("log.event_missing_memory").format(event_id=event_id))
            return
        self.detailText.setPlainText(
            format_event_detail(event, language=self.current_language)
        )
        for cb in self.tag_checks:
            cb.setChecked(cb.property("eventTagValue") in event.get("label_tags", []))
        self.noteEdit.setPlainText(event.get("note") or "")

    def apply_labels_to_selected_event(self):
        event_id = self._selected_id_from_table(self.eventTable)
        if not event_id:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialog.no_event_selected_title"),
                self.tr("dialog.no_event_selected_message"),
            )
            return
        event = self._event_by_id.get(event_id)
        if not event:
            self._log(self.tr("log.event_update_missing_memory").format(event_id=event_id))
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialog.event_state_error_title"),
                self.tr("dialog.event_missing_memory"),
            )
            return
        if not self.storage.fetch_event(event_id):
            self._log(self.tr("log.event_update_missing_storage").format(event_id=event_id))
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("dialog.event_state_error_title"),
                self.tr("dialog.event_missing_storage"),
            )
            return
        new_tags, new_note = self.current_tags_and_note()
        old_tags = list(event.get("label_tags", []))
        old_note = event.get("note") or ""
        if old_tags == new_tags and old_note == new_note:
            return

        def do():
            self.storage.update_event_labels(event_id, new_tags, new_note)
            event["label_tags"] = list(new_tags)
            event["note"] = new_note
            self._refresh_tables()
            self._log(self.tr("log.event_updated").format(event_id=event_id))

        def undo():
            self.storage.update_event_labels(event_id, old_tags, old_note)
            event["label_tags"] = list(old_tags)
            event["note"] = old_note
            self._refresh_tables()
            self._log(self.tr("log.event_update_undone").format(event_id=event_id))

        self.execute_command(ActionCommand(name="event_meta_update", do_fn=do, undo_fn=undo))

    # ---------- Undo / redo ----------
    def execute_command(self, command: ActionCommand):
        return execute_trade_command(self, command)

    def undo(self):
        undo_trade_command(self)

    def redo(self):
        redo_trade_command(self)

    # ---------- Tables / selection ----------
    def _refresh_tables(self, include_heavy: bool = True):
        started = time.perf_counter()
        tables = [
            self.openTradesTable,
            self.closedTradesTable,
            self.eventTable,
            self.equityTable,
            self.eventStudyTable,
        ]
        old_signal_state = {table: table.blockSignals(True) for table in tables}
        try:
            for table in tables:
                table.clearSelection()
                table.setCurrentCell(-1, -1)
            self._populate_tables(include_heavy=False)
        finally:
            for table, old_state in old_signal_state.items():
                table.blockSignals(old_state)
            _maybe_log_slow_operation(self, "_refresh_tables", started)
        if include_heavy and hasattr(self, "analysis_refresh_controller"):
            self.analysis_refresh_controller.schedule()

    def _populate_tables(self, include_heavy: bool = True):
        language = str(getattr(self, "current_language", "zh_CN") or "zh_CN")
        populate_trade_tables(
            self.openTradesTable,
            self.closedTradesTable,
            self.trades,
            language=language,
        )
        tag_filter = getattr(self, "eventFilterTag", None)
        if tag_filter is None:
            selected_tag = ""
        elif callable(getattr(tag_filter, "currentData", None)):
            selected_tag = tag_filter.currentData()
        else:
            selected_tag = tag_filter.currentText()
        selected_side = self.eventFilterSide.currentData() if hasattr(self, "eventFilterSide") else ""
        selected_type = self.eventFilterType.currentData() if hasattr(self, "eventFilterType") else ""
        populate_event_table(
            self.eventTable,
            self.events,
            selected_tag=selected_tag,
            selected_side=selected_side,
            selected_type=selected_type,
            language=language,
        )
        if hasattr(self, "recentEventsList"):
            populate_recent_event_list(
                self.recentEventsList,
                getattr(self, "recentEventsEmptyState", None),
                self.events,
                language=language,
            )
        if include_heavy and hasattr(self, "analysis_refresh_controller"):
            self.analysis_refresh_controller.schedule()
        if hasattr(self, "_update_empty_states"):
            self._update_empty_states()

    def _update_empty_states(self) -> None:
        if hasattr(self, "tradeResultsStack"):
            has_trades = self.openTradesTable.rowCount() > 0 or self.closedTradesTable.rowCount() > 0
            self.tradeResultsStack.setCurrentIndex(1 if has_trades else 0)
        if hasattr(self, "equityStack"):
            self.equityStack.setCurrentIndex(1 if self.equityTable.rowCount() > 0 else 0)
        if hasattr(self, "performanceStack"):
            has_closed_trades = self.closedTradesTable.rowCount() > 0
            self.performanceStack.setCurrentIndex(1 if has_closed_trades else 0)
        if hasattr(self, "eventResearchStack"):
            has_research = self.eventStudyTable.rowCount() > 0 or self.eventTable.rowCount() > 0
            self.eventResearchStack.setCurrentIndex(1 if has_research else 0)
        if hasattr(self, "datasetStack"):
            text = self.datasetText.toPlainText().strip() if hasattr(self, "datasetText") else ""
            empty_dataset_texts = {
                i18n_tr("ui.dataset_initial", language)
                for language in ("zh_CN", "en_US")
            }
            has_dataset = bool(text) and text not in empty_dataset_texts
            self.datasetStack.setCurrentIndex(1 if has_dataset else 0)

    def _clear_analysis_views(self) -> None:
        self.equityTable.setRowCount(0)
        self.eventStudyTable.setRowCount(0)
        self.performanceText.clear()
        self.datasetText.clear()
        self._update_empty_states()

    def _analysis_refresh_request(self) -> AnalysisRefreshRequest:
        started = time.perf_counter()
        market_frame = getattr(self, "df", None)
        has_market_frame = isinstance(market_frame, pd.DataFrame) and not market_frame.empty
        trade_notional_spin = getattr(self, "tradeNotionalSpin", None)
        storage = getattr(self, "storage", None)
        values = {
            "db_path": str(getattr(storage, "db_path", "")),
            "session_id": str(getattr(self, "session_id", None) or ""),
            "market_data": (
                PublishedMarketData(
                    generation=int(getattr(self, "_market_data_generation", 0)),
                    frame=market_frame,
                )
                if has_market_frame
                else None
            ),
            "market_cursor": int(self.cursor) if has_market_frame else None,
            "initial_equity": float(self.initialEquitySpin.value()),
            "trade_notional": (
                float(trade_notional_spin.value())
                if trade_notional_spin is not None
                else 1000.0
            ),
            "language": str(getattr(self, "current_language", "zh_CN") or "zh_CN"),
        }
        return AnalysisRefreshRequest(
            **values,
            ui_input_capture_seconds=time.perf_counter() - started,
            ui_thread_id=threading.get_ident(),
        )

    def _on_analysis_refresh_failed(self, error: str) -> None:
        translator = getattr(self, "tr", None)
        template = (
            translator("log.analysis_refresh_failed")
            if callable(translator)
            else i18n_tr(
                "log.analysis_refresh_failed",
                str(getattr(self, "current_language", "en_US") or "en_US"),
            )
        )
        self._log(template.format(error=error))

    def _apply_analysis_refresh_result(self, result: AnalysisRefreshResult) -> None:
        if hasattr(self, "equityTable"):
            populate_equity_table(self.equityTable, result.equity_rows)
        populate_event_study_table(self.eventStudyTable, result.event_study)
        self.datasetText.setPlainText(result.dataset_text)
        if hasattr(self, "performanceText"):
            self.performanceText.setPlainText(result.performance_text)
        if hasattr(self, "_update_empty_states"):
            self._update_empty_states()
        if result.performance_workspace is not None:
            self._analysis_performance_payload = result.performance_workspace
            workspace = getattr(self, "_analysis_workspace", None)
            if workspace is not None:
                workspace.apply_performance_payload(result.performance_workspace)
        for warning in result.warnings:
            self._log(warning)

    def _feature_rows_for_session(self) -> list[dict[str, Any]]:
        if not self.session_id:
            return []
        try:
            return self.storage.fetch_table("event_features", "session_id=?", (self.session_id,))
        except Exception as e:
            self._log(
                self.tr("log.event_features_failed").format(
                    error=f"{type(e).__name__}: {e}"
                )
            )
            return []

    def _event_rows_for_study(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event in self.events:
            row = dict(event)
            if not row.get("label_tags_json"):
                row["label_tags_json"] = json.dumps(row.get("label_tags") or [], ensure_ascii=False)
            rows.append(row)
        return rows

    def _populate_event_study_table(self):
        started = time.perf_counter()

        try:
            summary, warning = build_event_study_summary_frame(
                self._event_rows_for_study(),
                self._feature_rows_for_session(),
                language=self.current_language,
            )
            if warning:
                self._log(warning)
            populate_event_study_table(self.eventStudyTable, summary)
        finally:
            _maybe_log_slow_operation(self, "_populate_event_study_table", started)

    def _refresh_dataset_summary(self):
        started = time.perf_counter()

        try:
            text, warning = build_dataset_summary_text(
                self._feature_rows_for_session(),
                language=self.current_language,
            )
            self.datasetText.setPlainText(text)
            if warning:
                self._log(warning)
        finally:
            _maybe_log_slow_operation(self, "_refresh_dataset_summary", started)

    def jump_to_trade_row(self, item: QtWidgets.QTableWidgetItem):
        trade_id = self.sender().item(item.row(), 0).data(ROLE_ID)
        trade = self._trade_by_id.get(trade_id)
        if not trade:
            return
        idx = trade.get("entry_bar_index") if trade.get("status") == "OPEN" else trade.get("exit_bar_index") or trade.get("entry_bar_index")
        self.jump_to_bar(int(idx))

    def jump_to_event_row(self, item: QtWidgets.QTableWidgetItem):
        event_id = self.eventTable.item(item.row(), 0).data(ROLE_ID)
        event = self._event_by_id.get(event_id)
        if event:
            self.jump_to_bar(int(event["bar_index"]))

    def jump_to_bar(self, bar_index: int):
        if self.df.empty:
            return
        self.cursor = int(clamp(bar_index, 0, len(self.df) - 1))
        self._last_cursor_for_series = int(self.cursor)
        (x0, x1), _ = self.vb_price.viewRange()
        span = max(20.0, x1 - x0 if math.isfinite(x0) and math.isfinite(x1) and x1 > x0 else self.window_bars)
        x0 = max(0.0, self.cursor - span / 2.0)
        x1 = x0 + span
        self.pricePlot.setXRange(x0, x1, padding=0.0)
        self.volPlot.setXRange(x0, x1, padding=0.0)
        MainWindow._chart_render_state(self).mark_cursor_changed()
        MainWindow._chart_render_state(self).mark_visible_range_changed()
        self._render(force=True)

    # ---------- Export ----------
    def _ensure_export_controller(self):
        if self.export_controller is None:
            from export_controller import ExportController
            from exporter import Exporter

            self.exporter = Exporter(self.storage)
            self.export_controller = ExportController(self.exporter)
        return self.export_controller

    def export_session(self):
        lifecycle = getattr(self, "task_lifecycle", None)
        if lifecycle is not None and lifecycle.shutdown_in_progress:
            return
        if not self.session_id:
            return
        target = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("export.select_directory"),
            str(EXPORT_DIR),
        )
        if not target:
            return
        self.start_export_task(Path(target), language=self.current_language)

    def start_export_task(
        self,
        target: Path,
        on_success=None,
        language: str | None = None,
        selected_label: str = "fwd_ret_10_side_adj",
    ):
        lifecycle = getattr(self, "task_lifecycle", None)
        if lifecycle is not None and lifecycle.shutdown_in_progress:
            return False
        if not self.session_id or self.app_state.export.running or self.export_task_controller.is_running:
            return False

        request = build_export_task_request(
            target=target,
            session_id=self.session_id,
            language=language or self.current_language,
            selected_label=selected_label,
        )

        self.app_state.export.running = True
        self.app_state.export.last_error = None
        self._export_success_callback = on_success
        self.btnExport.setEnabled(False)
        self.status.setText(translate_for(self, "export.running"))
        return self.export_task_controller.start(self.storage.db_path, request)

    @QtCore.Slot(str, object, float)
    def _on_export_finished(self, output_dir: str, warnings: list, elapsed: float):
        self.app_state.export.output_dir = output_dir
        self._log(
            self.tr("log.export_completed").format(
                elapsed=elapsed,
                directory=output_dir,
            )
        )
        callback = self._export_success_callback
        self._finish_export_task()
        if callback is not None:
            callback(Path(output_dir))
        QtWidgets.QMessageBox.information(
            self,
            self.tr("export.completed_title"),
            self.tr("export.completed_message").format(directory=output_dir),
        )

    @QtCore.Slot(str, float)
    def _on_export_failed(self, error: str, elapsed: float):
        self.app_state.export.last_error = error
        logger.error("Export failed after %.2fs: %s", elapsed, error)
        self._log(self.tr("log.export_failed").format(error=error))
        self._finish_export_task()
        QtWidgets.QMessageBox.critical(self, self.tr("export.failed_title"), error)

    @QtCore.Slot()
    def _on_export_cancelled(self):
        self._log(self.tr("export.cancelled"))
        self._finish_export_task()

    def _finish_export_task(self):
        self.app_state.export.running = False
        self._export_success_callback = None
        self.btnExport.setEnabled(True)

    # ---------- Premium ----------
    def request_premium_sample(self):
        if self.task_lifecycle.shutdown_in_progress:
            return
        if not self.premium_controller.begin_sample():
            return
        request_stop = getattr(self.premium_worker, "request_stop", None)
        self.task_lifecycle.start(
            "premium_sample",
            request_stop=request_stop if callable(request_stop) else None,
        )
        self.requestPremium.emit()

    @QtCore.Slot()
    def on_premium_cancelled(self) -> None:
        self.premium_controller.inflight = False
        self.task_lifecycle.complete("premium_sample")

    def on_premium_sample(self, row: dict[str, Any]):
        self.premium_controller.complete_sample(row, self.storage)
        if row["sample_status"] == "OK":
            self._set_widget_role(self.premiumStatus, "pillLive")
            self.premiumStatus.setText(
                translate_for(self, "premium.latest_ok").format(
                    time=row["sample_time_bjt"],
                    source=row.get("fx_source") or "-",
                )
            )
            self.premiumStats.setPlainText(
                translate_for(self, "premium.stats").format(
                    buy_price=row["p2p_buy_price_cny"],
                    buy_premium=row["buy_premium_pct"],
                    sell_price=row["p2p_sell_price_cny"],
                    sell_premium=row["sell_premium_pct"],
                    average_price=row["p2p_avg_price_cny"],
                    average_premium=row["avg_premium_pct"],
                    rate=row["usd_cny_rate"],
                )
            )
        else:
            self._set_widget_role(self.premiumStatus, "pillWarning")
            self.premiumStatus.setText(
                translate_for(self, "premium.latest_error").format(time=row["sample_time_bjt"])
            )
            self.premiumStats.setPlainText(
                row.get("error_message") or translate_for(self, "premium_sample_failed")
            )
        self._refresh_premium_plot()
        if row.get("sample_status") == "OK":
            self.task_lifecycle.complete("premium_sample")
        else:
            self.task_lifecycle.fail("premium_sample", row.get("error_message") or "Premium sample failed")

    def _refresh_premium_plot(self):
        refresh_premium_plot(self)

    def _update_current_price_line(self, vx0: float, vx1: float):
        update_current_price_line(self, vx0, vx1)

    # ---------- Utils ----------
    def _log(self, message: str):
        logger.info(message)
        if hasattr(self, "logSummaryLabel"):
            summary = str(message).replace("\n", " ").strip()
            self.logSummaryLabel.setText(
                summary[:180] if summary else self.tr("ui.no_operations")
            )
        self.log.appendPlainText(f"[{bjt_now_iso()}] {message}")


def main():
    bootstrap_runtime_dirs()
    log_path = configure_logging()
    install_exception_hook()
    logger.info("启动 %s v%s，日志文件=%s", APP_NAME, APP_VERSION, log_path)
    try:
        app = QtWidgets.QApplication(sys.argv)
        apply_application_icon(app)
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception:
        logger.exception("程序启动或运行失败")
        raise


if __name__ == "__main__":
    main()
