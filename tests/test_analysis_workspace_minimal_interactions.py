from __future__ import annotations

import json
from pathlib import Path

import pytest
import pandas as pd
import numpy as np


QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")
QtGui = pytest.importorskip("PySide6.QtGui")
from analysis_workspace import AnalysisWorkspace
from controllers.analysis_controller import AnalysisRefreshController
from services.analysis_refresh import AnalysisRefreshSnapshot, build_analysis_refresh_result
from storage import StorageManager
from task_lifecycle import BackgroundTaskLifecycle
from ui_style import COLORS, LIGHT_THEME
from workers.analysis_refresh_worker import AnalysisRefreshWorker


class Host(QtWidgets.QWidget):
    current_language = "zh_CN"


class PerformanceHost(QtWidgets.QWidget):
    current_language = "zh_CN"
    session_id = "sess_perf"

    def __init__(self) -> None:
        super().__init__()
        self.trades = [
            {
                "trade_id": "trd_win",
                "side": "LONG",
                "status": "CLOSED",
                "net_return_pct": 2.0,
                "net_pnl_quote": 20.0,
                "exit_reason": "TAKE_PROFIT",
                "exit_bar_index": 1,
            },
            {
                "trade_id": "trd_open",
                "side": "LONG",
                "status": "OPEN",
                "entry_fill_price": 100.0,
                "notional_quote": 500.0,
                "entry_bar_index": 1,
            },
        ]
        self.df = pd.DataFrame(
            [
                {"bar_index": 0, "close": 100.0, "open_time_bjt": "2026-01-01T00:00:00+08:00"},
                {"bar_index": 1, "close": 104.0, "open_time_bjt": "2026-01-01T00:01:00+08:00"},
            ]
        )
        self.initialEquitySpin = type("Spin", (), {"value": lambda _self: 1000.0})()
        self.tradeNotionalSpin = type("Spin", (), {"value": lambda _self: 500.0})()

    def _current_equity_rows(self):
        return [
            {"sequence_no": 1, "equity_after": 1000.0, "equity_return_pct": 0.0, "drawdown_pct": 0.0},
            {"sequence_no": 2, "equity_after": 1040.0, "equity_return_pct": 4.0, "drawdown_pct": 0.0},
        ]


def _process_until(predicate, timeout_ms: int = 2_000) -> bool:
    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer()
    timer.setInterval(0)
    timer.timeout.connect(lambda: loop.quit() if predicate() else None)
    timer.start()
    QtCore.QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return bool(predicate())


def _send_wheel(widget: QtWidgets.QWidget) -> None:
    local = QtCore.QPointF(widget.rect().center())
    event = QtGui.QWheelEvent(
        local,
        QtCore.QPointF(widget.mapToGlobal(local.toPoint())),
        QtCore.QPoint(),
        QtCore.QPoint(0, -120),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.ScrollUpdate,
        False,
    )
    QtWidgets.QApplication.sendEvent(widget, event)


def test_analysis_workspace_graphics_shutdown_is_explicit_and_idempotent():
    host = Host()
    workspace = AnalysisWorkspace(host)

    assert workspace.shutdown() is True


def test_analysis_workspace_numeric_inputs_do_not_change_on_wheel():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    workspace = AnalysisWorkspace(host)
    workspace.entryConfidenceSpin.setValue(4)

    _send_wheel(workspace.entryConfidenceSpin)

    assert workspace.entryConfidenceSpin.value() == 4
    workspace.shutdown()
    workspace.close()
    host.close()
    app.processEvents()
    assert workspace.equityCurvePlot.plotItem is None
    assert workspace.performanceHistogramPlot.plotItem is None
    assert workspace.shutdown() is True


def test_chinese_analysis_workspace_has_no_raw_translation_keys():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    workspace = AnalysisWorkspace(host)
    try:
        texts: set[str] = set()
        for widget in (workspace, *workspace.findChildren(QtWidgets.QWidget)):
            if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
                texts.add(widget.text().strip())
            if isinstance(widget, QtWidgets.QGroupBox):
                texts.add(widget.title().strip())
            if isinstance(widget, QtWidgets.QTabWidget):
                texts.update(
                    widget.tabText(index).strip()
                    for index in range(widget.count())
                )
            if isinstance(widget, QtWidgets.QComboBox):
                texts.update(
                    widget.itemText(index).strip()
                    for index in range(widget.count())
                )
            if isinstance(widget, QtWidgets.QTableWidget):
                texts.update(
                    item.text().strip()
                    for index in range(widget.columnCount())
                    if (item := widget.horizontalHeaderItem(index)) is not None
                )
        translation_keys = set(
            json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "quant_collector_app"
                    / "translations"
                    / "zh_CN.json"
                ).read_text(encoding="utf-8")
            )
        )

        assert sorted(texts.intersection(translation_keys)) == []
    finally:
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_english_analysis_workspace_has_no_chinese_interface_text():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    host.current_language = "en_US"
    workspace = AnalysisWorkspace(host)
    try:
        texts: list[str] = []
        for widget in (workspace, *workspace.findChildren(QtWidgets.QWidget)):
            if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
                texts.append(widget.text())
            if isinstance(widget, QtWidgets.QGroupBox):
                texts.append(widget.title())
            if isinstance(widget, QtWidgets.QTabWidget):
                texts.extend(widget.tabText(index) for index in range(widget.count()))
            if isinstance(widget, QtWidgets.QComboBox):
                texts.extend(widget.itemText(index) for index in range(widget.count()))

        assert [
            text
            for text in texts
            if any("\u3400" <= char <= "\u9fff" for char in text)
        ] == []
    finally:
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def _worker_performance_payload(host: PerformanceHost):
    result = build_analysis_refresh_result(
        AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=host.trades,
            equity_rows=[],
            initial_equity=1_000.0,
            market_frame=host.df,
            market_cursor=len(host.df) - 1,
            session_id=host.session_id,
            trade_notional=500.0,
        ),
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda _trades, _equity, _initial: {},
        format_performance_report_fn=lambda _summary: "ok",
    )
    return result.performance_workspace


def _rendered_color_pixel_count(widget, color: str) -> int:
    widget.repaint()
    image = widget.grab().toImage().convertToFormat(QtGui.QImage.Format_RGBA8888)
    rows = np.frombuffer(
        image.constBits(),
        dtype=np.uint8,
        count=image.sizeInBytes(),
    ).reshape(image.height(), image.bytesPerLine())
    rgba = rows[:, : image.width() * 4].reshape(image.height(), image.width(), 4)
    target = np.asarray(QtGui.QColor(color).getRgb()[:3], dtype=np.int16)
    distance = np.abs(rgba[:, :, :3].astype(np.int16) - target)
    return int(np.count_nonzero(np.all(distance <= 8, axis=2)))


def test_single_equity_point_is_visibly_rendered_in_equity_and_pnl_modes():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.trades = []
    host.df = host.df.iloc[:1].copy()
    dialog = AnalysisWorkspace(host)
    dialog.resize(900, 700)
    dialog.show()

    dialog.apply_performance_payload(_worker_performance_payload(host))
    app.processEvents()
    equity_pixels = _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["success"],
    )

    dialog.performanceCurveMode.setCurrentIndex(
        dialog.performanceCurveMode.findData("pnl")
    )
    app.processEvents()
    pnl_pixels = _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["success"],
    )

    assert equity_pixels > 0
    assert pnl_pixels > 0

    dialog.close()
    host.close()
    app.processEvents()


def test_single_losing_equity_point_uses_danger_color_in_both_curve_modes():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.df = pd.DataFrame()
    host.trades = [
        {
            "trade_id": "trd_loss_only",
            "side": "LONG",
            "status": "CLOSED",
            "net_pnl_quote": -20.0,
            "updated_at": "2026-01-01T00:01:00+08:00",
        }
    ]
    dialog = AnalysisWorkspace(host)
    dialog.resize(900, 700)
    dialog.show()

    dialog.apply_performance_payload(_worker_performance_payload(host))
    app.processEvents()
    equity_pixels = _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["danger"],
    )

    dialog.performanceCurveMode.setCurrentIndex(
        dialog.performanceCurveMode.findData("pnl")
    )
    app.processEvents()
    pnl_pixels = _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["danger"],
    )

    assert equity_pixels > 0
    assert pnl_pixels > 0

    dialog.close()
    host.close()
    app.processEvents()


def test_two_point_equity_curve_stays_visible_without_per_point_symbols():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)
    dialog.resize(900, 700)
    dialog.show()

    dialog.apply_performance_payload(_worker_performance_payload(host))
    app.processEvents()

    assert _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["success"],
    ) > 0
    assert len(dialog.performanceSinglePoint.points()) == 0
    assert dialog.performanceMetricLabels["total_return"].text() == "4.00%"
    assert {point.data() for point in dialog.performanceTradeMarkers.points()} == {
        "trd_open",
        "trd_win",
    }

    dialog.close()
    host.close()
    app.processEvents()


def test_empty_performance_payload_shows_localized_state_and_clears_old_plot():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)
    dialog.resize(900, 700)
    dialog.show()
    dialog.apply_performance_payload(_worker_performance_payload(host))
    app.processEvents()
    assert _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["success"],
    ) > 0
    assert len(dialog.performanceTradeMarkers.points()) > 0

    host.df = pd.DataFrame()
    host.trades = []
    dialog.apply_performance_payload(_worker_performance_payload(host))
    app.processEvents()

    assert dialog.performanceCurveStateLabel.isVisible()
    assert dialog.performanceCurveStateLabel.text() == "暂无可绘制收益数据"
    assert _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["success"],
    ) == 0
    assert len(dialog.performanceSinglePoint.points()) == 0
    assert len(dialog.performanceTradeMarkers.points()) == 0

    dialog.close()
    host.close()
    app.processEvents()


def test_first_open_during_playback_shows_pause_hint_without_starting_worker():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.playing = True
    scheduled: list[tuple[int, object]] = []
    workers: list[object] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: (_ for _ in ()).throw(
            AssertionError("snapshot must stay deferred while replay is active")
        ),
        is_playing=lambda: host.playing,
        worker_factory=lambda: workers.append(object()),
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )
    host.analysis_refresh_controller = controller

    dialog = AnalysisWorkspace(host)
    dialog.resize(900, 700)
    dialog.show()
    app.processEvents()
    scheduled.pop(0)[1]()

    assert dialog.performanceCurveStateLabel.isVisible()
    assert dialog.performanceCurveStateLabel.text() == "暂停回放后更新收益曲线"
    assert controller.pending is True
    assert controller.is_running is False
    assert workers == []

    controller.shutdown()
    dialog.close()
    host.close()
    app.processEvents()


def test_playback_with_cached_payload_keeps_visible_curve_without_waiting_overlay():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.playing = True
    host._analysis_performance_payload = _worker_performance_payload(host)
    dialog = AnalysisWorkspace(host)
    dialog.resize(900, 700)
    dialog.show()
    app.processEvents()

    assert _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["success"],
    ) > 0
    assert dialog.performanceCurveStateLabel.isHidden()
    assert dialog.equityCurveData == [1_000.0, 1_040.0]

    dialog.close()
    host.close()
    app.processEvents()


def test_worker_payload_after_pause_replaces_waiting_state_with_visible_curve():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.playing = True
    host.trades = []
    host.df = host.df.iloc[:1].copy()
    dialog = AnalysisWorkspace(host)
    dialog.resize(900, 700)
    dialog.show()
    app.processEvents()
    assert dialog.performanceCurveStateLabel.text() == "暂停回放后更新收益曲线"

    host.playing = False
    dialog.apply_performance_payload(_worker_performance_payload(host))
    app.processEvents()

    assert dialog.performanceCurveStateLabel.isHidden()
    assert _rendered_color_pixel_count(
        dialog.equityCurvePlot,
        COLORS["success"],
    ) > 0

    dialog.close()
    host.close()
    app.processEvents()


def test_empty_curve_state_uses_english_translation():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    host.current_language = "en_US"
    dialog = AnalysisWorkspace(host)
    dialog.show()
    app.processEvents()

    assert dialog.performanceCurveStateLabel.isVisible()
    assert dialog.performanceCurveStateLabel.text() == "No equity data available to plot"

    dialog.close()
    host.close()
    app.processEvents()


def test_analysis_workspace_can_be_embedded_without_dialog_chrome():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = Host()
    host.theme_settings = LIGHT_THEME
    stack = QtWidgets.QStackedWidget()
    workspace = AnalysisWorkspace(host, parent=stack, embedded=True)
    stack.addWidget(workspace)

    try:
        assert workspace.embedded is True
        assert workspace.parentWidget() is stack
        assert workspace.windowType() == QtCore.Qt.Widget
        assert not workspace.isWindow()
        assert workspace.tabs.count() == 8
        assert workspace.equityCurvePlot.backgroundBrush().color().name().upper() == "#FFFFFF"
    finally:
        workspace.close()
        stack.close()
        host.close()
        app.processEvents()


def test_performance_workspace_shows_account_summary_curve_and_trade_pnl():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)

    dialog.apply_performance_payload(_worker_performance_payload(host))

    assert dialog.performanceMetricLabels["total_return"].text() == "4.00%"
    assert dialog.performanceMetricLabels["total_pnl"].text() == "40.00"
    assert dialog.performanceMetricLabels["total_pnl"].styleSheet() == f"color: {COLORS['success']};"
    assert dialog.performanceMetricLabels["total_pnl"].parentWidget().property("role") == "metricBlock"
    assert dialog.performanceTradeFilter.currentData() == "closed"
    assert dialog.tradePnlTable.rowCount() == 1
    assert dialog.tradePnlTable.item(0, 0).data(QtCore.Qt.UserRole) == "trd_win"
    assert dialog.tradePnlTable.item(0, 0).text() == "1"
    assert dialog.tradePnlTable.item(0, 8).text() == "20.00"
    assert dialog.tradePnlTable.item(0, 9).text() == "2.00%"
    assert dialog.equityCurveData == [1000.0, 1040.0]

    dialog.close()
    host.close()
    app.processEvents()


def test_performance_workspace_applies_worker_payload_without_changing_visible_results():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)
    result = build_analysis_refresh_result(
        AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=host.trades,
            equity_rows=[],
            initial_equity=1_000.0,
            market_frame=host.df,
            market_cursor=1,
            session_id=host.session_id,
            trade_notional=500.0,
        ),
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda _trades, _equity, _initial: {},
        format_performance_report_fn=lambda _summary: "ok",
    )

    dialog.apply_performance_payload(result.performance_workspace)

    assert dialog.performanceMetricLabels["total_return"].text() == "4.00%"
    assert dialog.performanceMetricLabels["total_pnl"].text() == "40.00"
    assert dialog.performanceMetricLabels["unrealized_pnl"].text() == "20.00"
    assert dialog.equityCurveData == [1_000.0, 1_040.0]
    assert dialog.tradePnlTable.rowCount() == 1
    assert dialog.tradePnlTable.item(0, 0).text() == "1"
    assert dialog.tradePnlTable.item(0, 8).text() == "20.00"
    assert dialog.tradePnlTable.item(0, 8).foreground().color().name() == COLORS["success"].lower()
    marker_ids = {point.data() for point in dialog.performanceTradeMarkers.points()}
    assert marker_ids == {"trd_open", "trd_win"}

    dialog.close()
    host.close()
    app.processEvents()


def test_invalidating_current_session_performance_clears_stale_payload_until_worker_refreshes():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)
    dialog.show()
    app.processEvents()
    dialog.apply_performance_payload(_worker_performance_payload(host))
    assert dialog.equityCurveData == [1_000.0, 1_040.0]

    dialog.invalidate_performance_sessions([host.session_id])

    assert dialog.equityCurveData == []
    assert dialog.performanceCurveStateLabel.isVisible()
    assert dialog.performanceCurveStateLabel.text() == "暂无可绘制收益数据"

    dialog.close()
    host.close()
    app.processEvents()


def test_current_session_payload_does_not_start_historical_worker(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.storage = StorageManager(tmp_path / "current.db")
    host.task_lifecycle = BackgroundTaskLifecycle()
    host.storage.upsert_session(
        {
            "session_id": host.session_id,
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
        }
    )
    dialog = AnalysisWorkspace(host)

    try:
        controller = dialog.historical_performance_controller
        assert controller.is_running is False

        dialog.apply_performance_payload(_worker_performance_payload(host))
        app.processEvents()

        assert dialog.equityCurveData == [1_000.0, 1_040.0]
        assert controller.is_running is False
        assert host.task_lifecycle.active_tasks == ()
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_bounded_worker_payload_keeps_marker_for_unsampled_trade_bar():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.df = pd.DataFrame(
        {
            "bar_index": range(3_001),
            "open_time_bjt": pd.date_range(
                "2026-01-01",
                periods=3_001,
                freq="min",
                tz="Asia/Shanghai",
            ),
            "close": 100.0,
        }
    )
    host.trades = [
        {
            "trade_id": "trd_unsampled",
            "side": "LONG",
            "status": "OPEN",
            "entry_fill_price": 100.0,
            "notional_quote": 500.0,
            "entry_bar_index": 1,
        }
    ]
    dialog = AnalysisWorkspace(host)

    dialog.apply_performance_payload(_worker_performance_payload(host))

    assert len(dialog.equityCurveData) == 2_000
    assert {point.data() for point in dialog.performanceTradeMarkers.points()} == {
        "trd_unsampled"
    }
    point = next(iter(dialog.performanceTradeMarkers.points()))
    marker_x = float(point.pos().x())
    marker_y = float(point.pos().y())
    assert marker_x in dialog._performanceCurveX
    display_index = dialog._performanceCurveX.index(marker_x)
    assert marker_y == pytest.approx(
        dialog.equityCurveData[display_index]
    )

    dialog.close()
    host.close()
    app.processEvents()


def test_large_current_session_workspace_refresh_only_requests_background_analysis():
    class TrackedFrame(pd.DataFrame):
        _metadata = ["to_dict_threads"]

        @property
        def _constructor(self):
            return TrackedFrame

        def to_dict(self, *args, **kwargs):
            self.to_dict_threads.append(QtCore.QThread.currentThread())
            return super().to_dict(*args, **kwargs)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    frame = TrackedFrame(
        {
            "bar_index": range(270_000),
            "open_time_bjt": pd.date_range(
                "2025-01-01",
                periods=270_000,
                freq="min",
                tz="Asia/Shanghai",
            ),
            "close": 100.0,
        }
    )
    frame.to_dict_threads = []
    host.df = frame
    host.trades = []
    scheduled: list[str] = []
    sync_summaries: list[str] = []
    host.analysis_refresh_controller = type(
        "Controller",
        (),
        {"schedule": lambda _self: scheduled.append("schedule")},
    )()
    host._refresh_performance_summary = lambda: sync_summaries.append("sync")

    dialog = AnalysisWorkspace(host)

    assert scheduled == ["schedule"]
    assert sync_summaries == []
    assert frame.to_dict_threads == []

    dialog.close()
    host.close()
    app.processEvents()


def test_large_workspace_refresh_keeps_heartbeat_then_applies_worker_result():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main_thread = QtCore.QThread.currentThread()
    loop = QtCore.QEventLoop()
    host = PerformanceHost()
    host.df = pd.DataFrame(
        {
            "bar_index": range(270_000),
            "open_time_bjt": pd.date_range(
                "2025-01-01",
                periods=270_000,
                freq="min",
                tz="Asia/Shanghai",
            ),
            "close": 100.0,
        }
    )
    host.trades = []
    dialog = AnalysisWorkspace(host)
    order: list[str] = []
    calculation_threads: list[object] = []
    result_threads: list[object] = []
    errors: list[str] = []

    def build_performance(_trades, equity, _initial):
        calculation_threads.append(QtCore.QThread.currentThread())
        return {"equity_rows": len(equity)}

    controller = AnalysisRefreshController(
        snapshot_factory=lambda: AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=host.trades,
            equity_rows=[],
            initial_equity=1_000.0,
            market_frame=host.df,
            market_cursor=len(host.df) - 1,
            session_id=host.session_id,
            trade_notional=500.0,
        ),
        is_playing=lambda: False,
        delay_ms=0,
        worker_factory=lambda: AnalysisRefreshWorker(
            build_event_study_fn=lambda _events, _features: pd.DataFrame(),
            build_ml_datasets_fn=lambda _features: {
                "ml_features": pd.DataFrame(),
                "ml_labels": pd.DataFrame(),
                "sample_index": pd.DataFrame(),
            },
            build_performance_summary_fn=build_performance,
            format_performance_report_fn=lambda summary: (
                f"equity={summary['equity_rows']}"
            ),
        ),
    )

    def receive_result(result) -> None:
        result_threads.append(QtCore.QThread.currentThread())
        dialog.apply_performance_payload(result.performance_workspace)
        order.append("result")
        loop.quit()

    controller.resultReady.connect(receive_result)
    controller.failed.connect(lambda error: (errors.append(error), loop.quit()))
    controller.schedule()
    QtCore.QTimer.singleShot(0, lambda: order.append("heartbeat"))
    QtCore.QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    app.processEvents()

    assert errors == []
    assert order == ["heartbeat", "result"]
    assert calculation_threads and calculation_threads[0] is not main_thread
    assert result_threads == [main_thread]
    assert dialog.performanceMetricLabels["total_return"].text() == "0.00%"
    assert dialog.performanceMetricLabels["total_pnl"].text() == "0.00"
    assert len(dialog.equityCurveData) == 2_000
    assert dialog.equityCurveData[0] == 1_000.0
    assert dialog.equityCurveData[-1] == 1_000.0

    controller.shutdown()
    dialog.close()
    host.close()
    app.processEvents()


def test_performance_workspace_exposes_funds_management_controls():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)

    try:
        assert {
            "current_equity",
            "total_pnl",
            "total_return",
            "unrealized_pnl",
            "realized_pnl",
            "win_rate",
            "payoff",
            "sharpe",
            "max_drawdown",
            "trade_count",
        }.issubset(dialog.performanceMetricLabels)
        assert dialog.performanceCurveMode.count() == 2
        assert dialog.equityCurvePlot.minimumHeight() >= 280
        assert dialog.tradePnlTable.columnCount() == 14
        assert dialog.tradePnlTable.horizontalHeaderItem(0).text() == "交易编号"
        assert dialog.tradePnlTable.minimumHeight() >= 240
        assert dialog.performanceTradeFilter.count() >= 6
        assert dialog.performanceSideFilter.count() >= 3
        assert dialog.performanceDistributionLabels
        assert set(dialog.performanceMetricCards) == set(dialog.performanceMetricLabels)
        assert set(dialog.performanceDistributionCards) == set(dialog.performanceDistributionLabels)
        assert dialog.performanceDistributionLabels["win_count"].property("role") == "distributionValue"
        assert dialog.performanceHistogram is not None
        assert "交易编号" in dialog.performanceHistogramDefinition.text()
        assert "每笔已实现盈亏" in dialog.performanceHistogramDefinition.text()
        assert not hasattr(dialog, "performanceTabs")
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_performance_trade_pnl_and_return_cells_use_signed_colors():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.trades.append(
        {
            "trade_id": "trd_loss",
            "side": "SHORT",
            "status": "CLOSED",
            "net_return_pct": -1.5,
            "net_pnl_quote": -7.5,
            "exit_reason": "STOP_LOSS",
            "exit_bar_index": 1,
        }
    )
    dialog = AnalysisWorkspace(host)

    try:
        dialog.apply_performance_payload(_worker_performance_payload(host))
        rows = {
            dialog.tradePnlTable.item(row, 0).data(QtCore.Qt.UserRole): row
            for row in range(dialog.tradePnlTable.rowCount())
        }
        win_row = rows["trd_win"]
        loss_row = rows["trd_loss"]

        assert dialog.tradePnlTable.item(win_row, 0).text() == "1"
        assert dialog.tradePnlTable.item(loss_row, 0).text() == "2"
        assert dialog.tradePnlTable.item(loss_row, 0).sort_value == 2
        for column in (8, 9):
            assert dialog.tradePnlTable.item(win_row, column).foreground().color().name() == COLORS["success"].lower()
            assert dialog.tradePnlTable.item(loss_row, column).foreground().color().name() == COLORS["danger"].lower()
        assert list(dialog.performanceHistogram.opts["x"]) == [1.0, 2.0]
        assert list(dialog.performanceHistogram.opts["height"]) == [20.0, -7.5]
        assert dialog.performanceDistributionLabels["average_win"].styleSheet() == f"color: {COLORS['success']};"
        assert dialog.performanceDistributionLabels["average_loss"].styleSheet() == f"color: {COLORS['danger']};"
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_performance_trade_fallback_uses_payload_notional_after_spinbox_changes():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.trades = [
        {
            "trade_id": "trd_payload_notional",
            "side": "LONG",
            "status": "CLOSED",
            "net_return_pct": 10.0,
            "exit_bar_index": 1,
        }
    ]
    dialog = AnalysisWorkspace(host)

    try:
        dialog.apply_performance_payload(_worker_performance_payload(host))
        host.tradeNotionalSpin = type(
            "Spin", (), {"value": lambda _self: 2_000.0}
        )()
        dialog.performanceTradeFilter.setCurrentIndex(
            dialog.performanceTradeFilter.findData("profit")
        )

        assert dialog.tradePnlTable.rowCount() == 1
        assert dialog.tradePnlTable.item(0, 6).text() == "500.00"
        assert dialog.tradePnlTable.item(0, 8).text() == "50.00"
        assert dialog.tradePnlTable.item(0, 9).text() == "10.00%"
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_performance_curve_trade_marker_selects_matching_trade_row():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)

    try:
        dialog.apply_performance_payload(_worker_performance_payload(host))
        point = next(point for point in dialog.performanceTradeMarkers.points() if point.data() == "trd_win")

        dialog.performanceTradeMarkers.sigClicked.emit(dialog.performanceTradeMarkers, [point], None)
        app.processEvents()

        selected = dialog.tradePnlTable.selectedItems()
        assert selected
        assert dialog.tradePnlTable.item(selected[0].row(), 0).data(QtCore.Qt.UserRole) == "trd_win"
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_performance_curve_hover_exposes_equity_and_pnl_breakdown():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    dialog = AnalysisWorkspace(host)

    try:
        dialog.apply_performance_payload(_worker_performance_payload(host))
        dialog._update_performance_hover(1)

        text = dialog.performanceHoverLabel.text()
        assert "1040.00" in text
        assert "40.00" in text
        assert "20.00" in text
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_performance_trade_filters_reuse_payload_without_redrawing_curve_or_rescheduling():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.trades.append(
        {
            "trade_id": "trd_loss",
            "side": "SHORT",
            "status": "CLOSED",
            "net_return_pct": -1.5,
            "net_pnl_quote": -7.5,
            "exit_reason": "STOP_LOSS",
            "exit_bar_index": 1,
        }
    )
    dialog = AnalysisWorkspace(host)
    dialog.apply_performance_payload(_worker_performance_payload(host))
    scheduled: list[str] = []
    host.analysis_refresh_controller = type(
        "Controller",
        (),
        {"schedule": lambda _self: scheduled.append("schedule")},
    )()
    initial_curve_items = tuple(dialog.performanceCurveItems)
    initial_total_return = dialog.performanceMetricLabels["total_return"].text()

    dialog.performanceTradeFilter.setCurrentIndex(
        dialog.performanceTradeFilter.findData("profit")
    )

    assert dialog.tradePnlTable.rowCount() == 1
    assert dialog.tradePnlTable.item(0, 0).data(QtCore.Qt.UserRole) == "trd_win"
    assert tuple(dialog.performanceCurveItems) == initial_curve_items
    assert dialog.performanceMetricLabels["total_return"].text() == initial_total_return
    assert scheduled == []

    dialog.performanceTradeFilter.setCurrentIndex(
        dialog.performanceTradeFilter.findData("loss")
    )
    dialog.performanceSideFilter.setCurrentIndex(
        dialog.performanceSideFilter.findData("SHORT")
    )

    assert dialog.tradePnlTable.rowCount() == 1
    assert dialog.tradePnlTable.item(0, 0).data(QtCore.Qt.UserRole) == "trd_loss"
    assert tuple(dialog.performanceCurveItems) == initial_curve_items
    assert scheduled == []

    dialog.close()
    host.close()
    app.processEvents()


def test_analysis_performance_sessions_use_the_shared_narrow_session_catalog(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    storage = StorageManager(tmp_path / "catalog.db")
    storage.upsert_session(
        {
            "session_id": "session_history",
            "symbol": "BTCUSDT",
            "interval": "5m",
            "start_date_bjt": "2026-04-01",
            "end_date_bjt": "2026-05-01",
            "last_saved_at": "2026-07-01T00:00:00+08:00",
        }
    )
    storage.fetch_table = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("analysis session catalog must not SELECT *")
    )
    host.storage = storage
    host.task_lifecycle = BackgroundTaskLifecycle()
    dialog = AnalysisWorkspace(host)

    try:
        index = dialog.performanceSessionBox.findData("session_history")
        assert index >= 0
        assert dialog.performanceSessionBox.itemText(index) == (
            "BTCUSDT · 5m · 2026-04-01—2026-05-01"
        )
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_analysis_performance_session_catalog_removes_deleted_session_and_compacts_names(
    tmp_path,
):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    storage = StorageManager(tmp_path / "delete_catalog.db")
    common = {
        "symbol": "BTCUSDT",
        "interval": "5m",
        "start_date_bjt": "2026-04-01",
        "end_date_bjt": "2026-05-01",
    }
    for session_id, saved_day in (
        ("session_first", "03"),
        ("session_middle", "02"),
        ("session_last", "01"),
    ):
        storage.upsert_session(
            {
                **common,
                "session_id": session_id,
                "last_saved_at": f"2026-07-{saved_day}T00:00:00+08:00",
            }
        )
    host.storage = storage
    host.task_lifecycle = BackgroundTaskLifecycle()
    dialog = AnalysisWorkspace(host)

    try:
        assert dialog.performanceSessionBox.itemText(
            dialog.performanceSessionBox.findData("session_middle")
        ).endswith("#2")
        assert dialog.performanceSessionBox.itemText(
            dialog.performanceSessionBox.findData("session_last")
        ).endswith("#3")

        storage.delete_performance_session("session_middle")
        dialog.refresh_performance_session_catalog()

        assert dialog.performanceSessionBox.findData("session_middle") == -1
        last_index = dialog.performanceSessionBox.findData("session_last")
        assert last_index >= 0
        assert dialog.performanceSessionBox.itemText(last_index).endswith("#2")
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_historical_performance_selection_reads_and_computes_off_ui_thread(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    storage = StorageManager(tmp_path / "history.db")
    for session_id, equity in ((host.session_id, 1_000.0), ("session_history", 1_010.0)):
        storage.upsert_session(
            {
                "session_id": session_id,
                "symbol": "BTCUSDT",
                "interval": "1m",
                "start_date_bjt": "2026-01-01",
                "end_date_bjt": "2026-01-01",
                "initial_equity": 1_000.0,
                "trade_notional": 500.0,
                "last_saved_at": f"2026-01-01T00:0{1 if session_id == host.session_id else 2}:00+08:00",
            }
        )
        storage.replace_equity_curve(
            session_id,
            [
                {
                    "session_id": session_id,
                    "sequence_no": 1,
                    "equity_before": 1_000.0,
                    "realized_net_pnl": equity - 1_000.0,
                    "equity_after": equity,
                    "equity_return_pct": equity / 1_000.0 - 1.0,
                    "drawdown_pct": 0.0,
                    "created_at": "2026-01-01T00:01:00+08:00",
                }
            ],
        )
    storage.insert_trade(
        {
            "trade_id": "trade_history_off_ui",
            "session_id": "session_history",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": "LONG",
            "status": "CLOSED",
            "entry_bar_index": 0,
            "exit_bar_index": 0,
            "entry_fill_price": 100.0,
            "notional_quote": 500.0,
            "net_pnl_quote": 10.0,
            "created_at": "2026-01-01T00:00:00+08:00",
            "updated_at": "2026-01-01T00:01:00+08:00",
        }
    )
    storage.upsert_klines(
        [
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "open_time_utc_ms": 1_767_196_800_000,
                "open_time_bjt": "2026-01-01T00:00:00+08:00",
                "close_time_utc_ms": 1_767_196_859_999,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
            }
        ]
    )
    host.storage = storage
    host.task_lifecycle = BackgroundTaskLifecycle()
    sync_reads: list[str] = []
    storage.load_session_snapshot = lambda session_id: sync_reads.append(session_id)
    dialog = AnalysisWorkspace(host)
    order: list[str] = []
    loop = QtCore.QEventLoop()

    try:
        controller = dialog.historical_performance_controller
        controller.resultReady.connect(
            lambda _result: (order.append("result"), loop.quit())
        )
        history_index = dialog.performanceSessionBox.findData("session_history")
        assert history_index >= 0
        dialog.performanceSessionBox.setCurrentIndex(history_index)
        QtCore.QTimer.singleShot(0, lambda: order.append("heartbeat"))
        QtCore.QTimer.singleShot(3_000, loop.quit)
        loop.exec()
        app.processEvents()

        assert order == ["heartbeat", "result"]
        assert sync_reads == []
        assert dialog.performanceMetricLabels["current_equity"].text() == "1010.00"
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_historical_session_builds_curve_from_csv_cache_without_player_data(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.df = pd.DataFrame()
    host.cursor = 37
    host.playing = True
    host.symbolBox = QtWidgets.QComboBox()
    host.symbolBox.addItem("ETHUSDT")
    host.intervalBox = QtWidgets.QComboBox()
    host.intervalBox.addItem("5m")
    host.startDate = QtWidgets.QDateEdit(QtCore.QDate(2025, 12, 1))
    host.endDate = QtWidgets.QDateEdit(QtCore.QDate(2025, 12, 2))
    storage = StorageManager(tmp_path / "history.db")
    storage.upsert_session(
        {
            "session_id": host.session_id,
            "symbol": "ETHUSDT",
            "interval": "5m",
            "start_date_bjt": "2025-12-01",
            "end_date_bjt": "2025-12-02",
            "last_saved_at": "2025-12-02T00:00:00+08:00",
        }
    )
    storage.upsert_session(
        {
            "session_id": "session_history",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
            "initial_equity": 1_000.0,
            "trade_notional": 500.0,
            "last_saved_at": "2026-01-02T00:00:00+08:00",
        }
    )
    storage.insert_trade(
        {
            "trade_id": "trade_history",
            "session_id": "session_history",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": "LONG",
            "status": "CLOSED",
            "entry_bar_index": 1,
            "exit_bar_index": 2,
            "entry_fill_price": 100.0,
            "notional_quote": 500.0,
            "net_pnl_quote": 10.0,
            "created_at": "2026-01-01T00:01:00+08:00",
            "updated_at": "2026-01-01T00:02:00+08:00",
        }
    )
    history_times = [
        "2026-01-01T00:00:00+08:00",
        "2026-01-01T00:01:00+08:00",
        "2026-01-01T00:02:00+08:00",
    ]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    pd.DataFrame(
        [
            {
                "open_time_ms": 1_767_196_800_000 + index * 60_000,
                "open_time_bjt": None if index == 1 else open_time,
                "close": close,
            }
            for index, (open_time, close) in enumerate(
                zip(history_times, (100.0, 101.0, 102.0), strict=True)
            )
        ]
    ).to_csv(
        cache_dir / "BTCUSDT_1m_20260101_20260101_bjt.csv",
        index=False,
    )
    assert storage.fetch_table("klines") == []
    host.storage = storage
    host.task_lifecycle = BackgroundTaskLifecycle()
    original_df = host.df
    original_state = (
        host.cursor,
        host.symbolBox.currentText(),
        host.intervalBox.currentText(),
        host.startDate.date(),
        host.endDate.date(),
        host.playing,
        host.session_id,
    )
    dialog = AnalysisWorkspace(host)
    results: list[object] = []
    errors: list[str] = []

    try:
        controller = dialog.historical_performance_controller
        controller.resultReady.connect(results.append)
        controller.failed.connect(errors.append)
        history_index = dialog.performanceSessionBox.findData("session_history")
        assert history_index >= 0

        dialog.performanceSessionBox.setCurrentIndex(history_index)

        assert _process_until(lambda: bool(results) or bool(errors), timeout_ms=3_000)
        app.processEvents()
        assert errors == []
        assert len(results[0].payload.equity_rows) == 3
        assert [row["time"] for row in results[0].payload.equity_rows] == history_times
        assert dialog.equityCurveData == [1_000.0, 1_005.0, 1_010.0]
        assert host.df is original_df
        assert (
            host.cursor,
            host.symbolBox.currentText(),
            host.intervalBox.currentText(),
            host.startDate.date(),
            host.endDate.date(),
            host.playing,
            host.session_id,
        ) == original_state
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_historical_session_without_klines_shows_missing_data_state_not_player_curve(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host._analysis_performance_payload = _worker_performance_payload(host)
    storage = StorageManager(tmp_path / "history.db")
    storage.upsert_session(
        {
            "session_id": host.session_id,
            "symbol": "ETHUSDT",
            "interval": "5m",
            "start_date_bjt": "2025-12-01",
            "end_date_bjt": "2025-12-02",
            "last_saved_at": "2025-12-02T00:00:00+08:00",
        }
    )
    storage.upsert_session(
        {
            "session_id": "session_without_klines",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
            "initial_equity": 1_000.0,
            "trade_notional": 500.0,
            "last_saved_at": "2026-01-02T00:00:00+08:00",
        }
    )
    storage.replace_equity_curve(
        "session_without_klines",
        [
            {
                "session_id": "session_without_klines",
                "sequence_no": 1,
                "equity_before": 1_000.0,
                "realized_net_pnl": 25.0,
                "equity_after": 1_025.0,
                "equity_return_pct": 2.5,
                "drawdown_pct": 0.0,
                "created_at": "2026-01-01T00:01:00+08:00",
            }
        ],
    )
    host.storage = storage
    host.task_lifecycle = BackgroundTaskLifecycle()
    original_df = host.df
    dialog = AnalysisWorkspace(host)
    dialog.show()
    app.processEvents()
    results: list[object] = []

    try:
        assert dialog.equityCurveData == [1_000.0, 1_040.0]
        controller = dialog.historical_performance_controller
        controller.resultReady.connect(results.append)
        history_index = dialog.performanceSessionBox.findData("session_without_klines")
        assert history_index >= 0

        dialog.performanceSessionBox.setCurrentIndex(history_index)

        assert _process_until(lambda: bool(results), timeout_ms=3_000)
        app.processEvents()
        assert results[0].payload is None
        assert dialog.equityCurveData == []
        assert dialog.performanceCurveStateLabel.isVisible()
        assert dialog.performanceCurveStateLabel.text() == (
            "缺少该会话的行情数据，需要重新加载/恢复该会话"
        )
        assert host.df is original_df
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_historical_session_fast_switch_keeps_latest_b_visible_and_completes_lifecycle(
    tmp_path,
    monkeypatch,
):
    import threading

    import workers.historical_performance_worker as historical_worker_module
    from task_lifecycle import TaskState

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    storage = StorageManager(tmp_path / "history.db")
    for session_id, saved_at in (
        (host.session_id, "2026-01-01T00:00:00+08:00"),
        ("session_a", "2026-01-02T00:00:00+08:00"),
        ("session_b", "2026-01-03T00:00:00+08:00"),
    ):
        storage.upsert_session(
            {
                "session_id": session_id,
                "symbol": "BTCUSDT",
                "interval": "1m",
                "start_date_bjt": "2026-01-01",
                "end_date_bjt": "2026-01-01",
                "initial_equity": 1_000.0,
                "trade_notional": 500.0,
                "last_saved_at": saved_at,
            }
        )
    host.storage = storage
    host.task_lifecycle = BackgroundTaskLifecycle()
    session_a_started = threading.Event()
    release_session_a = threading.Event()

    class StorageBoundary:
        def load_session_snapshot(self, session_id):
            if session_id == "session_a":
                session_a_started.set()
                assert release_session_a.wait(2.0)
            return (
                {
                    "session_id": session_id,
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "start_date_bjt": "2026-01-01",
                    "end_date_bjt": "2026-01-01",
                    "initial_equity": 1_000.0 if session_id == "session_a" else 2_000.0,
                    "trade_notional": 500.0,
                },
                [],
                [],
            )

        def fetch_klines_for_range(self, **_kwargs):
            return [
                {
                    "bar_index": index,
                    "open_time_bjt": f"2026-01-01T00:0{index}:00+08:00",
                    "open_time_utc_ms": 1_767_196_800_000 + index * 60_000,
                    "close": 100.0,
                }
                for index in range(2)
            ]

    monkeypatch.setattr(
        historical_worker_module,
        "StorageManager",
        lambda _db_path: StorageBoundary(),
    )
    dialog = AnalysisWorkspace(host)

    try:
        index_a = dialog.performanceSessionBox.findData("session_a")
        index_b = dialog.performanceSessionBox.findData("session_b")
        assert index_a >= 0 and index_b >= 0

        dialog.performanceSessionBox.setCurrentIndex(index_a)
        assert session_a_started.wait(2.0)
        dialog.performanceSessionBox.setCurrentIndex(index_b)
        release_session_a.set()

        assert _process_until(
            lambda: (
                not dialog.historical_performance_controller.is_running
                and dialog.equityCurveData == [2_000.0, 2_000.0]
            ),
            timeout_ms=3_000,
        )
        app.processEvents()
        assert dialog.performanceSessionBox.currentData() == "session_b"
        assert dialog.performanceMetricLabels["current_equity"].text() == "2000.00"
        assert host.task_lifecycle.state("historical_performance") is TaskState.COMPLETED
    finally:
        release_session_a.set()
        dialog.close()
        host.close()
        app.processEvents()


def test_large_trade_history_uses_bounded_table_model_pages():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = PerformanceHost()
    host.trades = [
        {
            "trade_id": f"trade_{index:04d}",
            "side": "LONG" if index % 2 == 0 else "SHORT",
            "status": "CLOSED",
            "net_pnl_quote": float(index - 500),
            "net_return_pct": float(index - 500) / 5.0,
            "exit_bar_time_bjt": f"2026-01-{(index % 28) + 1:02d}T00:00:00+08:00",
        }
        for index in range(1_000)
    ]
    dialog = AnalysisWorkspace(host)

    try:
        dialog.apply_performance_payload(_worker_performance_payload(host))
        model = dialog.tradePnlTable.model()

        assert isinstance(model, QtCore.QAbstractTableModel)
        assert not isinstance(dialog.tradePnlTable, QtWidgets.QTableWidget)
        assert model.total_rows == 1_000
        assert model.rowCount() <= model.page_size
        first_page_id = model.index(0, 0).data(QtCore.Qt.UserRole)

        model.next_page()

        assert model.current_page == 1
        assert model.index(0, 0).data(QtCore.Qt.UserRole) != first_page_id
    finally:
        dialog.close()
        host.close()
        app.processEvents()


def test_research_controls_sorting_and_single_symbol_pca_hint():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    dialog = AnalysisWorkspace(Host())

    assert dialog.selectedLabelBox.currentText() == "fwd_ret_10_side_adj"
    assert dialog.selectedLabelBox.findText("hit_tp_1pct_before_sl_1pct") >= 0
    assert dialog.researchEventTable.isSortingEnabled()
    assert dialog.factorIcTable.isSortingEnabled()
    assert dialog.ruleTable.isSortingEnabled()

    dialog.last_time_series_summary = {"factor_model": {"available": False}}
    dialog._populate_time_series_views()
    assert "PCA 因子模型需要多币种收益矩阵" in dialog.tsFactorTable.item(0, 1).text()
    assert dialog.btnRunTimeSeries.text() == "运行时间序列诊断"
    dialog.close()
    app.processEvents()
