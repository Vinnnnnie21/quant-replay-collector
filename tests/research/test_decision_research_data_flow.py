from __future__ import annotations

import gc
import os
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")

from analysis_workspace import AnalysisWorkspace
from app_i18n import tr as i18n_tr
import main_app
from main_app import MainWindow
from controllers.research_backfill_controller import ResearchBackfillController
from market_data.types import interval_to_ms, to_api_utc_ms_from_bjt
from storage import StorageManager
from task_lifecycle import BackgroundTaskLifecycle
from workers.research_backfill_worker import ResearchBackfillWorker
from research.setups import (
    CreateSetup,
    DecisionProtocol,
    SetupDirection,
    SetupLibrary,
    SetupVersionSpec,
    TimeframeProfile,
)


def _wait_until(predicate, timeout_seconds: float = 8.0) -> bool:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


@pytest.fixture
def collect_main_window_qt_cycles():
    yield
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    gc.collect()
    app.processEvents()


class _CompletingNetwork:
    def __init__(self) -> None:
        self.requests = []

    def download(
        self,
        symbol,
        interval,
        start_dt_bjt,
        end_dt_bjt,
        progress=None,
        cancelled=None,
    ):
        del progress
        start_ms = to_api_utc_ms_from_bjt(start_dt_bjt)
        end_ms = to_api_utc_ms_from_bjt(end_dt_bjt)
        self.requests.append((symbol, interval, start_ms, end_ms))
        step_ms = interval_to_ms(interval)
        rows = []
        for open_time_ms in range(start_ms, end_ms + 1, step_ms):
            if cancelled is not None and cancelled():
                break
            rows.append(
                [
                    open_time_ms,
                    "100.0",
                    "102.0",
                    "99.0",
                    "101.0",
                    "10.0",
                    open_time_ms + step_ms - 1,
                    "1200.5",
                    42,
                    "3.25",
                    "650.75",
                    "0",
                ]
            )
        return rows


class _Host(QtWidgets.QWidget):
    decisionResearchSourceChanged = QtCore.Signal()
    current_language = "zh_CN"
    session_id = "session_research_data"
    playing = False

    def __init__(self, db_path, network) -> None:
        super().__init__()
        self.storage = StorageManager(db_path)
        self.task_lifecycle = BackgroundTaskLifecycle()
        self.research_backfill_controller = ResearchBackfillController(
            db_path=db_path,
            lifecycle=self.task_lifecycle,
            worker_factory=lambda: ResearchBackfillWorker(
                network_factory=lambda: network
            ),
            parent=self,
        )
        self.symbolBox = QtWidgets.QComboBox(self)
        self.symbolBox.addItem("BTCUSDT")
        self.startDate = QtWidgets.QDateEdit(self)
        self.endDate = QtWidgets.QDateEdit(self)
        selected_date = QtCore.QDate(2026, 1, 1)
        self.startDate.setDate(selected_date)
        self.endDate.setDate(selected_date)


class _HostWithoutResearchController(QtWidgets.QWidget):
    current_language = "zh_CN"
    session_id = "session_research_data"
    playing = False

    def __init__(self, db_path) -> None:
        super().__init__()
        self.storage = StorageManager(db_path)
        self.task_lifecycle = BackgroundTaskLifecycle()
        self.research_backfill_controller = None
        self.symbolBox = QtWidgets.QComboBox(self)
        self.symbolBox.addItem("BTCUSDT")
        self.startDate = QtWidgets.QDateEdit(self)
        self.endDate = QtWidgets.QDateEdit(self)
        selected_date = QtCore.QDate(2026, 1, 1)
        self.startDate.setDate(selected_date)
        self.endDate.setDate(selected_date)


def _start_production_main_window(tmp_path, monkeypatch) -> MainWindow:
    db_path = tmp_path / "main-window-research.db"
    monkeypatch.setattr(
        main_app,
        "StorageManager",
        lambda: StorageManager(db_path),
    )
    monkeypatch.setattr(main_app, "load_app_settings", lambda: {})
    monkeypatch.setattr(main_app, "save_app_settings", lambda _settings: None)
    monkeypatch.setattr(
        main_app.DailyBackupController,
        "schedule",
        lambda _controller: None,
    )
    monkeypatch.setattr(
        MainWindow,
        "request_premium_sample",
        lambda _window: None,
    )
    monkeypatch.setattr(
        MainWindow,
        "_restore_latest_session_if_any",
        lambda _window: None,
    )
    monkeypatch.setattr(
        MainWindow,
        "_save_layout_preferences",
        lambda _window: None,
    )
    window = MainWindow()
    selected_date = QtCore.QDate(2026, 1, 1)
    window.startDate.setDate(selected_date)
    window.endDate.setDate(selected_date)
    return window


def _stop_production_main_window(window: MainWindow) -> None:
    controller = window.research_backfill_controller
    window.close()
    assert _wait_until(
        lambda: window._safe_shutdown_coordinator._finalized
        and not window.loader_thread.isRunning()
        and not window.premium_thread.isRunning()
        and not window.analysis_refresh_controller.is_running
        and (
            controller is None
            or not controller.is_running
        )
    )
    app = QtWidgets.QApplication.instance()
    app.processEvents()


def test_main_window_analysis_navigation_clicks_through_to_three_timeframe_audit(
    tmp_path,
    monkeypatch,
    collect_main_window_qt_cycles,
) -> None:
    window = _start_production_main_window(tmp_path, monkeypatch)

    try:
        assert window.research_backfill_controller is None

        window.open_analysis_workspace()
        workspace = window._analysis_workspace
        decision = workspace.decisionResearchWorkspace
        inspected = []
        window.research_backfill_controller.inspected.connect(
            inspected.append
        )
        workspace.tabs.setCurrentWidget(decision)
        decision.btnAuditResearchData.click()

        assert decision.backfillStatusLabel.text() == (
            "正在后台检查三个周期的本地数据…"
        )
        assert decision.btnAuditResearchData.isEnabled() is False
        assert _wait_until(
            lambda: decision.state.completeness == "incomplete"
        )
        assert len(inspected) == 1
        assert tuple(
            item.interval
            for item in inspected[0].report.timeframes
        ) == ("1m", "5m", "15m")
        assert decision.backfillStatusLabel.text() == i18n_tr(
            "decision_research.data.audit_incomplete",
            "zh_CN",
        )
    finally:
        _stop_production_main_window(window)


def test_main_window_formal_research_entry_reuses_controller_and_click_binding(
    tmp_path,
    monkeypatch,
    collect_main_window_qt_cycles,
) -> None:
    window = _start_production_main_window(tmp_path, monkeypatch)

    try:
        window.open_analysis_workspace()
        controller = window.research_backfill_controller
        workspace = window._analysis_workspace

        window.open_decision_research_workspace()
        decision = workspace.decisionResearchWorkspace

        assert controller is not None
        assert window._analysis_workspace is workspace
        assert window.research_backfill_controller is controller
        assert controller.is_running is False
        assert decision.state.completeness == "not_audited"

        window.open_decision_research_workspace()

        assert window.research_backfill_controller is controller
        assert controller.is_running is False

        inspected = []
        rendered = []
        render_completeness = decision.render_completeness

        def record_render(report) -> None:
            rendered.append(report)
            render_completeness(report)

        decision.render_completeness = record_render
        controller.inspected.connect(inspected.append)
        decision.btnAuditResearchData.click()

        assert decision.backfillStatusLabel.text() == (
            "正在后台检查三个周期的本地数据…"
        )
        assert _wait_until(lambda: len(inspected) == 1)
        assert len(inspected[0].report.timeframes) == 3
        assert len(rendered) == 1
    finally:
        _stop_production_main_window(window)


def test_completeness_click_surfaces_missing_controller_in_chinese(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _HostWithoutResearchController(tmp_path / "missing-controller.db")
    workspace = AnalysisWorkspace(host)

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()

        assert decision.backfillStatusLabel.text() == (
            "完整度检查暂不可用，请重新打开决策研究。"
        )
        assert decision.btnAuditResearchData.isEnabled() is True
        assert decision.btnCancelBackfill.isEnabled() is False
    finally:
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_completeness_click_surfaces_shared_lifecycle_busy_state(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "busy-lifecycle.db", _CompletingNetwork())
    workspace = AnalysisWorkspace(host)
    host.task_lifecycle.start("analysis_refresh")

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()

        assert decision.backfillStatusLabel.text() == (
            "当前有后台任务正在运行，请稍后再检查。"
        )
        assert decision.btnAuditResearchData.isEnabled() is True
        assert host.research_backfill_controller.is_running is False
    finally:
        host.task_lifecycle.complete("analysis_refresh")
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_completeness_click_surfaces_safe_shutdown_state(tmp_path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "shutdown-state.db", _CompletingNetwork())
    workspace = AnalysisWorkspace(host)
    host.task_lifecycle.begin_shutdown()

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()

        assert decision.backfillStatusLabel.text() == (
            "应用正在安全退出，无法开始完整度检查。"
        )
        assert decision.btnAuditResearchData.isEnabled() is True
        assert host.research_backfill_controller.is_running is False
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_completeness_click_surfaces_missing_range_context(tmp_path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "missing-range-context.db", _CompletingNetwork())
    workspace = AnalysisWorkspace(host)
    host.symbolBox = None

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()

        assert decision.backfillStatusLabel.text() == (
            "无法检查完整度，请先选择有效的品种和日期范围。"
        )
        assert decision.btnAuditResearchData.isEnabled() is True
        assert host.research_backfill_controller.is_running is False
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_completeness_start_failure_is_stable_chinese_without_exception_type(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _HostWithoutResearchController(tmp_path / "start-failure.db")

    def fail_to_create_thread(_parent):
        raise RuntimeError("internal thread detail")

    controller = ResearchBackfillController(
        db_path=host.storage.db_path,
        lifecycle=host.task_lifecycle,
        thread_factory=fail_to_create_thread,
        parent=host,
    )
    host.research_backfill_controller = controller
    workspace = AnalysisWorkspace(host)

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()

        assert decision.backfillStatusLabel.text() == (
            "完整度检查启动失败，请稍后重试。"
        )
        assert "RuntimeError" not in decision.backfillStatusLabel.text()
        assert controller.is_running is False
        assert decision.btnAuditResearchData.isEnabled() is True
        assert decision.btnRetryBackfill.isEnabled() is False
    finally:
        controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_completeness_runtime_failure_is_chinese_and_not_backfill_retryable(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _HostWithoutResearchController(tmp_path / "valid-host.db")
    invalid_db_path = tmp_path / "database-directory"
    invalid_db_path.mkdir()
    controller = ResearchBackfillController(
        db_path=invalid_db_path,
        lifecycle=host.task_lifecycle,
        parent=host,
    )
    host.research_backfill_controller = controller
    workspace = AnalysisWorkspace(host)

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()

        assert _wait_until(
            lambda: decision.backfillStatusLabel.text()
            == "完整度检查失败，请稍后重试。"
        )
        assert "OperationalError" not in decision.backfillStatusLabel.text()
        assert decision.btnAuditResearchData.isEnabled() is True
        assert decision.btnRetryBackfill.isEnabled() is False
        assert controller.can_retry is False
    finally:
        controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_running_completeness_result_is_discarded_after_symbol_changes(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "stale-symbol.db", _CompletingNetwork())
    host.symbolBox.addItem("ETHUSDT")
    workspace = AnalysisWorkspace(host)
    inspected = []
    host.research_backfill_controller.inspected.connect(inspected.append)

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()
        assert host.research_backfill_controller.is_running is True

        host.symbolBox.setCurrentText("ETHUSDT")

        assert _wait_until(
            lambda: not host.research_backfill_controller.is_running
        )
        assert inspected == []
        assert decision.state.completeness == "not_audited"
        assert all(
            "尚未检查" in label.text()
            for label in decision.timeframeCompletenessLabels
        )
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_running_completeness_result_is_discarded_after_date_changes(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "stale-date.db", _CompletingNetwork())
    workspace = AnalysisWorkspace(host)
    inspected = []
    host.research_backfill_controller.inspected.connect(inspected.append)

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()
        assert host.research_backfill_controller.is_running is True

        host.startDate.setDate(QtCore.QDate(2025, 12, 31))

        assert _wait_until(
            lambda: not host.research_backfill_controller.is_running
        )
        assert inspected == []
        assert decision.state.completeness == "not_audited"
        assert all(
            "尚未检查" in label.text()
            for label in decision.timeframeCompletenessLabels
        )
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_running_completeness_result_is_discarded_after_setup_changes(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "stale-setup.db", _CompletingNetwork())
    library = SetupLibrary(host.storage)
    for name in ("Setup A", "Setup B"):
        library.create_setup(
            CreateSetup(
                display_name=name,
                version=SetupVersionSpec(
                    direction=SetupDirection.LONG,
                    decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                    decision_rules="只使用截止线前信息",
                    timeframes=TimeframeProfile("1m", "5m", "15m"),
                ),
            )
        )
    workspace = AnalysisWorkspace(host)
    inspected = []
    host.research_backfill_controller.inspected.connect(inspected.append)

    try:
        decision = workspace.decisionResearchWorkspace
        assert decision.setupBox.count() == 2
        decision.btnAuditResearchData.click()
        assert host.research_backfill_controller.is_running is True

        decision.setupBox.setCurrentIndex(1)

        assert _wait_until(
            lambda: not host.research_backfill_controller.is_running
        )
        assert inspected == []
        assert decision.state.completeness == "not_audited"
        assert all(
            "尚未检查" in label.text()
            for label in decision.timeframeCompletenessLabels
        )
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_repeated_completeness_click_starts_one_worker_and_restores_button(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "single-flight-audit.db", _CompletingNetwork())
    workspace = AnalysisWorkspace(host)
    tasks = []
    host.research_backfill_controller.requestRun.connect(tasks.append)

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()

        assert len(tasks) == 1
        assert decision.btnAuditResearchData.isEnabled() is False
        assert decision.btnCancelBackfill.isEnabled() is True

        decision.btnAuditResearchData.click()

        assert len(tasks) == 1
        assert _wait_until(
            lambda: decision.state.completeness == "incomplete"
        )
        assert decision.btnAuditResearchData.isEnabled() is True
        assert decision.btnCancelBackfill.isEnabled() is False
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_running_completeness_cancel_restores_audit_controls_without_retry(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "cancel-audit.db", _CompletingNetwork())
    workspace = AnalysisWorkspace(host)

    try:
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()
        decision.btnCancelBackfill.click()

        assert _wait_until(
            lambda: decision.backfillStatusLabel.text()
            == "完整度检查已取消，可重新检查。"
        )
        assert decision.btnAuditResearchData.isEnabled() is True
        assert decision.btnCancelBackfill.isEnabled() is False
        assert decision.btnRetryBackfill.isEnabled() is False
        assert host.research_backfill_controller.can_retry is False
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_unique_decision_research_page_audits_then_backfills_on_explicit_click(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    network = _CompletingNetwork()
    host = _Host(tmp_path / "research.db", network)
    workspace = AnalysisWorkspace(host)

    try:
        workspace.open_decision_research()
        decision = workspace.decisionResearchWorkspace
        decision.btnAuditResearchData.click()

        assert _wait_until(
            lambda: decision.state.completeness == "incomplete"
        )
        assert network.requests == []
        assert decision.btnBackfillResearchRange.isEnabled() is True

        decision.btnBackfillResearchRange.click()

        assert _wait_until(
            lambda: decision.state.completeness == "complete"
        )
        assert network.requests
        assert decision.backfillStatusLabel.text() == (
            "当前研究区间和公式窗口已经补齐。"
        )
    finally:
        host.research_backfill_controller.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_production_analysis_workspace_automatically_composes_episode_context(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "production-composition.db", _CompletingNetwork())
    created = SetupLibrary(host.storage).create_setup(
        CreateSetup(
            display_name="生产装配",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只使用截止线前信息",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    )
    version_id = created.version.setup_version_id
    host.storage.save_observation_sample(
        {
            "sample_id": "production-sample",
            "session_id": host.session_id,
            "profile_id": version_id,
            "source_type": "USER_EVENT",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "bar_index": 1,
            "event_time_bjt": "2026-01-01T08:30:00+08:00",
            "user_action": "NO_ACTION",
            "side": "LONG",
            "linked_trade_id": None,
            "linked_event_id": None,
            "is_user_trade": 0,
            "is_candidate": 1,
            "is_matched_control": 0,
            "created_at": "2026-01-01T00:30:00+00:00",
        }
    )
    workspace = AnalysisWorkspace(host)

    try:
        workspace.open_decision_research()
        decision = workspace.decisionResearchWorkspace
        assert _wait_until(lambda: decision._episode_summary is not None)
        grouping_id = decision._episode_summary.grouping_version_id

        assert workspace.decision_research_coordinator is not None
        assert decision.state.grouping_version_id == grouping_id
        assert decision.entryBlindReviewWorkspace._grouping_version_id == grouping_id
        assert decision.entrySimilarityBrowser._grouping_version_id == grouping_id
        assert decision.entryBehaviorModelWorkspace._grouping_version_id == grouping_id
        assert decision.entryOutcomeComparisonWorkspace._grouping_version_id == grouping_id

        decision.btnAuditResearchData.click()
        assert _wait_until(lambda: decision.state.completeness == "incomplete")
        assert _wait_until(lambda: not host.research_backfill_controller.is_running)
        decision.stepButtons["version_report"].click()
        assert _wait_until(lambda: workspace._research_snapshot_input is not None)
        snapshot_input = workspace._research_snapshot_input
        assert snapshot_input.versions.setup_version_id == version_id
        assert snapshot_input.versions.episode_version == grouping_id
        assert snapshot_input.content.model_summary["status"] == "not_ready"
        assert snapshot_input.content.label_audit["total_labels"] == 0
        assert snapshot_input.content.label_audit["label_counts"] == {}
        assert snapshot_input.content.similarity_summary["status"] == "not_run"
        assert snapshot_input.content.model_summary["dependency_versions"] == {}
        assert len(snapshot_input.content.outcome_rows) == 15
        assert decision.researchSnapshotWorkspace._draft_hash is not None
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_actual_open_signal_refreshes_episode_and_unlocks_pending_blind_batch(
    tmp_path,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "actual-open-refresh.db", _CompletingNetwork())
    created = SetupLibrary(host.storage).create_setup(
        CreateSetup(
            display_name="历史回放入场",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只使用截止线前信息",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    )
    workspace = AnalysisWorkspace(host)

    try:
        workspace.open_decision_research()
        decision = workspace.decisionResearchWorkspace
        assert decision._episode_summary is None
        host.storage.insert_event(
            {
                "event_id": "historical-open",
                "session_id": host.session_id,
                "trade_id": "historical-trade",
                "event_type": "OPEN",
                "side": "LONG",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": 30,
                "bar_open_time_bjt": "2026-01-01T08:30:00+08:00",
                "real_key_time_bjt": "2026-07-20T12:00:00+08:00",
                "price_proxy": 100.0,
                "label_tags": [],
                "note": "",
                "created_at": "2026-07-20T04:00:00+00:00",
            }
        )

        host.decisionResearchSourceChanged.emit()
        app.processEvents()

        assert decision._episode_summary is not None
        assert decision._episode_summary.sample_count == 1
        assert decision.entryBlindReviewWorkspace.loadBatchButton.isEnabled()
        decision.entryBlindReviewWorkspace.loadBatchButton.click()
        app.processEvents()
        assert decision.entryBlindReviewWorkspace.batchList.count() == 1
        assert decision.state.setup_version == created.version.setup_version_id
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()


def test_production_episode_merge_action_selects_new_immutable_version(
    tmp_path,
    monkeypatch,
) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _Host(tmp_path / "production-correction.db", _CompletingNetwork())
    created = SetupLibrary(host.storage).create_setup(
        CreateSetup(
            display_name="生产修正",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只使用截止线前信息",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    )
    version_id = created.version.setup_version_id
    for sample_id, event_time in (
        ("early", "2026-01-01T08:30:00+08:00"),
        ("late", "2026-01-01T18:30:00+08:00"),
    ):
        host.storage.save_observation_sample(
            {
                "sample_id": sample_id,
                "session_id": host.session_id,
                "profile_id": version_id,
                "source_type": "USER_EVENT",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": 1,
                "event_time_bjt": event_time,
                "user_action": "NO_ACTION",
                "side": "LONG",
                "linked_trade_id": None,
                "linked_event_id": None,
                "is_user_trade": 0,
                "is_candidate": 1,
                "is_matched_control": 0,
                "created_at": "2026-01-01T00:30:00+00:00",
            }
        )
    workspace = AnalysisWorkspace(host)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getItem",
        lambda *_args, **_kwargs: ("合并片段", True),
    )
    text_call = {"count": 0}

    def dialog_text(*_args, **kwargs):
        text_call["count"] += 1
        if text_call["count"] == 1:
            return (kwargs.get("text", ""), True)
        return ("人工确认同属一段行情", True)

    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        dialog_text,
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda *_args, **_kwargs: QtWidgets.QMessageBox.Ok,
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QtWidgets.QMessageBox.Ok,
    )

    try:
        workspace.open_decision_research()
        decision = workspace.decisionResearchWorkspace
        assert _wait_until(
            lambda: decision._episode_summary is not None
            and decision._episode_summary.episode_count == 2
        )
        original_id = decision.state.grouping_version_id

        decision.btnCorrectEpisodes.click()

        corrected_id = decision.state.grouping_version_id
        assert corrected_id != original_id
        assert decision._episode_summary.episode_count == 1
        assert host.storage.get_episode_grouping(original_id) is not None
        assert host.storage.get_episode_grouping(corrected_id) is not None
    finally:
        host.research_backfill_controller.shutdown()
        workspace.shutdown()
        workspace.close()
        host.close()
        app.processEvents()
