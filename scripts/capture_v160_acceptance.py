from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture v1.6.0 screenshots through the production workspace.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    runtime = args.runtime.resolve()
    output.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    os.environ["QRC_RUNTIME_ROOT"] = str(runtime)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app_dir = Path(__file__).resolve().parents[1] / "quant_collector_app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))

    from PySide6 import QtCore, QtWidgets

    from app_config import APP_VERSION
    from controllers.research_backfill_controller import (
        ResearchBackfillController,
    )
    from errors import DatabaseSchemaTooNewError
    from main_app import MainWindow
    from research.setups import (
        CreateSetup,
        DecisionProtocol,
        SetupDirection,
        SetupLibrary,
        SetupVersionSpec,
        TimeframeProfile,
    )
    from ui_style import DARK_THEME, LIGHT_THEME, ensure_ui_font_support
    from workers.research_backfill_worker import ResearchBackfillWorker

    class FailingNetwork:
        def download(self, *_args, **_kwargs):
            raise RuntimeError("验收模拟：网络暂时不可用")

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ensure_ui_font_support(app)
    MainWindow.request_premium_sample = lambda self: None
    window = MainWindow()
    window.research_backfill_controller = ResearchBackfillController(
        db_path=window.storage.db_path,
        lifecycle=window.task_lifecycle,
        worker_factory=lambda: ResearchBackfillWorker(
            network_factory=FailingNetwork,
        ),
        parent=window,
    )
    selected_date = QtCore.QDate(2026, 7, 1)
    window.startDate.setDate(selected_date)
    window.endDate.setDate(selected_date)
    window.symbolBox.setCurrentText("BTCUSDT")
    session_id = str(window.session_id or "v160-visual-session")
    window.session_id = session_id

    setup = SetupLibrary(window.storage).create_setup(
        CreateSetup(
            display_name="回踩确认",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只使用截止线前已闭合 K 线判断，确认结构后再记录人工结论。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version
    decision_time = datetime(2026, 7, 1, 0, 5, 30, tzinfo=UTC)
    close_time = decision_time + timedelta(hours=4)
    window.storage.insert_trade(
        {
            "trade_id": "v160-trade",
            "session_id": session_id,
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": "LONG",
            "status": "CLOSED",
            "entry_event_id": "v160-open",
            "exit_event_id": "v160-close",
            "entry_real_time_bjt": decision_time.isoformat(),
            "exit_real_time_bjt": close_time.isoformat(),
            "entry_price_proxy": 100.0,
            "exit_price_proxy": 103.0,
            "created_at": decision_time.isoformat(),
            "updated_at": close_time.isoformat(),
        }
    )
    for event_id, event_type, when, price, bar_index in (
        ("v160-open", "OPEN", decision_time, 100.0, 5),
        ("v160-close", "CLOSE", close_time, 103.0, 245),
    ):
        window.storage.insert_event(
            {
                "event_id": event_id,
                "session_id": session_id,
                "trade_id": "v160-trade",
                "event_type": event_type,
                "side": "LONG",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": bar_index,
                "bar_open_time_bjt": when.replace(second=0).isoformat(),
                "real_key_time_bjt": when.isoformat(),
                "price_proxy": price,
                "label_tags": [],
                "note": "",
                "created_at": when.isoformat(),
            }
        )

    def kline(interval: str, opened: datetime, closed: datetime, close: float):
        return {
            "symbol": "BTCUSDT",
            "interval": interval,
            "open_time_utc_ms": int(opened.timestamp() * 1000),
            "open_time_bjt": opened.isoformat(),
            "close_time_utc_ms": int(closed.timestamp() * 1000),
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 10.0,
            "quote_volume": 1000.0,
            "trade_count": 20,
            "taker_buy_base_volume": 4.0,
            "taker_buy_quote_volume": 400.0,
            "source": "acceptance_fixture",
            "downloaded_at": decision_time.isoformat(),
            "data_quality_status": "ok",
        }

    cutoff = decision_time.replace(second=0, microsecond=0)
    window.storage.upsert_klines(
        (
            kline("1m", cutoff - timedelta(minutes=1), cutoff, 100.0),
            kline("1m", cutoff, cutoff + timedelta(minutes=1), 100.5),
            kline("5m", cutoff - timedelta(minutes=5), cutoff, 101.0),
            kline("5m", cutoff, cutoff + timedelta(minutes=5), 101.5),
            kline(
                "15m",
                cutoff - timedelta(minutes=20),
                cutoff - timedelta(minutes=5),
                102.0,
            ),
            kline(
                "15m",
                cutoff - timedelta(minutes=5),
                cutoff + timedelta(minutes=10),
                102.5,
            ),
        )
    )

    window.open_decision_research_workspace()
    window.show()
    decision = window._analysis_workspace.decisionResearchWorkspace
    wait_until(app, lambda: decision._episode_summary is not None)

    def capture(name: str, size: tuple[int, int]) -> None:
        window.resize(*size)
        app.processEvents()
        time.sleep(0.04)
        app.processEvents()
        if not window.grab().save(str(output / name)):
            raise RuntimeError(f"could not save screenshot: {name}")

    def scroll_to(widget) -> None:
        point = widget.mapTo(decision.pageContent, QtCore.QPoint(0, 0))
        decision.pageScroll.verticalScrollBar().setValue(max(0, point.y() - 80))
        app.processEvents()

    window.apply_theme(LIGHT_THEME)
    decision.btnCreateSetup.click()
    capture("01-light-1366x768-setup-editor.png", (1366, 768))
    decision.setupEditorForm.cancelButton.click()

    window.apply_theme(DARK_THEME)
    decision.btnCreateSetup.click()
    capture("02-dark-1366x768-setup-editor.png", (1366, 768))
    decision.setupEditorForm.cancelButton.click()

    window.apply_theme(LIGHT_THEME)
    decision.modeTabs.setCurrentIndex(0)
    wait_until(app, lambda: decision._episode_summary is not None)
    decision.stepButtons["sample_review"].click()
    review = decision.entryBlindReviewWorkspace
    review.loadBatchButton.click()
    wait_until(app, lambda: review.batchList.count() > 0)
    scroll_to(review.batchPanel)
    capture("03-light-1920x1080-pending-seeds.png", (1920, 1080))

    window.apply_theme(DARK_THEME)
    scroll_to(review.formPanel)
    capture("04-dark-1920x1080-manual-judgment.png", (1920, 1080))

    window.apply_theme(LIGHT_THEME)
    decision.pageScroll.verticalScrollBar().setValue(0)
    capture("05-entry-complete-context.png", (1920, 1080))

    decision.modeTabs.setCurrentIndex(1)
    wait_until(app, lambda: decision._episode_summary is not None)
    decision.pageScroll.verticalScrollBar().setValue(0)
    capture("06-exit-complete-context.png", (1920, 1080))

    decision.modeTabs.setCurrentIndex(0)
    decision.stepButtons["version_report"].click()
    wait_until(
        app,
        lambda: decision.researchSnapshotWorkspace._draft_hash is not None,
    )
    scroll_to(decision.researchSnapshotWorkspace)
    capture("09-version-report-draft.png", (1920, 1080))

    missing_data_date = QtCore.QDate(2026, 7, 2)
    window.startDate.setDate(missing_data_date)
    window.endDate.setDate(missing_data_date)
    app.processEvents()
    decision.btnAuditResearchData.click()
    wait_until(app, lambda: decision.state.completeness == "incomplete")
    wait_until(app, lambda: not window.research_backfill_controller.is_running)
    scroll_to(decision.dataAvailabilityPanel)
    capture("07-data-insufficient.png", (1366, 768))

    decision.btnBackfillResearchRange.click()
    wait_until(app, lambda: decision.btnRetryBackfill.isEnabled())
    scroll_to(decision.dataAvailabilityPanel)
    capture("08-research-failure.png", (1366, 768))

    error = DatabaseSchemaTooNewError(
        database_schema_version=20,
        supported_schema_version=19,
        database_path=runtime / "data" / "newer-schema.db",
    )
    box = QtWidgets.QMessageBox()
    box.setIcon(QtWidgets.QMessageBox.Critical)
    box.setWindowTitle("数据库版本不兼容")
    box.setText(error.user_message_zh(APP_VERSION))
    box.setStandardButtons(QtWidgets.QMessageBox.Ok)
    box.show()
    app.processEvents()
    box.resize(box.sizeHint())
    app.processEvents()
    if not box.grab().save(str(output / "10-schema-incompatible-zh.png")):
        raise RuntimeError("could not save schema compatibility screenshot")
    box.close()

    window._analysis_workspace.shutdown()
    window.research_backfill_controller.shutdown()
    window.close()
    app.processEvents()
    print(f"Captured {len(tuple(output.glob('*.png')))} screenshots in {output}")
    return 0


def wait_until(app, predicate, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    app.processEvents()
    if not predicate():
        raise RuntimeError("timed out waiting for production UI state")


if __name__ == "__main__":
    raise SystemExit(main())
