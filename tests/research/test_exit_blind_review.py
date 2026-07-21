from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from research.entry_blind_review import ReviewPhase, ReviewStatus
from research.exit_blind_review import (
    ExitBlindJudgmentInput,
    ExitJudgmentLabel,
    ExitReviewLabelState,
    OptionalRiskLevelStatus,
)
from research.market_episodes import (
    MarketEpisodeService,
    ResearchSampleWindow,
    TimeRange,
)
from research.setups import (
    CreateSetup,
    DecisionProtocol,
    SetupDirection,
    SetupLibrary,
    SetupVersionSpec,
    TimeframeProfile,
)
from services.entry_blind_review import EntryBlindReviewService
from services.exit_blind_review import (
    ExitBlindReviewService,
    PartialExitUnsupportedError,
)
from storage import StorageManager


ENTRY_TIME = datetime(2026, 7, 1, 0, 30, 30, tzinfo=UTC)
EXIT_TIME = datetime(2026, 7, 1, 1, 5, 30, tzinfo=UTC)


def _utc_ms(value: datetime) -> int:
    return int(value.timestamp() * 1_000)


def _setup_version(
    storage: StorageManager,
    direction: SetupDirection = SetupDirection.LONG,
):
    return SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="平仓盲审",
            version=SetupVersionSpec(
                direction=direction,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只按决策截止点及此前信息判断。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version


def _event(
    event_id: str,
    event_type: str,
    action_time: datetime,
    *,
    bar_index: int,
    side: str = "LONG",
    bar_time: datetime | None = None,
) -> dict:
    market_time = bar_time or action_time
    return {
        "event_id": event_id,
        "session_id": "session_exit_review",
        "trade_id": "trade_exit_review",
        "event_type": event_type,
        "side": side,
        "symbol": "BTCUSDT",
        "interval": "1m",
        "bar_index": bar_index,
        "bar_open_time_bjt": market_time.replace(second=0).isoformat(),
        "real_key_time_bjt": action_time.isoformat(),
        "price_proxy": 100.0 if event_type == "OPEN" else 104.0,
        "label_tags": [],
        "note": "",
        "created_at": action_time.isoformat(),
    }


def _closed_trade(
    storage: StorageManager,
    *,
    side: str = "LONG",
    stop_loss_pct: float | None = 1.0,
    stop_loss_price: float | None = 99.0,
    observed_exit_time: datetime | None = None,
) -> None:
    exit_observed = observed_exit_time or EXIT_TIME
    storage.insert_trade(
        {
            "trade_id": "trade_exit_review",
            "session_id": "session_exit_review",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": side,
            "status": "CLOSED",
            "entry_event_id": "event_open_exit_review",
            "exit_event_id": "event_close_exit_review",
            "entry_bar_index": 30,
            "exit_bar_index": 65,
            "entry_bar_time_bjt": ENTRY_TIME.replace(second=0).isoformat(),
            "exit_bar_time_bjt": EXIT_TIME.replace(second=0).isoformat(),
            "entry_real_time_bjt": ENTRY_TIME.isoformat(),
            "exit_real_time_bjt": exit_observed.isoformat(),
            "entry_fill_price": 100.0,
            "entry_price_proxy": 100.0,
            "exit_fill_price": 104.0,
            "notional_quote": 1_000.0,
            "take_profit_pct": None,
            "take_profit_price": None,
            "stop_loss_pct": stop_loss_pct,
            "stop_loss_price": stop_loss_price,
            "net_pnl_quote": 40.0,
            "created_at": ENTRY_TIME.isoformat(),
            "updated_at": exit_observed.isoformat(),
        }
    )
    storage.insert_event(
        _event(
            "event_open_exit_review",
            "OPEN",
            ENTRY_TIME,
            bar_index=30,
            side=side,
            bar_time=ENTRY_TIME,
        )
    )
    storage.insert_event(
        _event(
            "event_close_exit_review",
            "CLOSE",
            exit_observed,
            bar_index=65,
            side=side,
            bar_time=EXIT_TIME,
        )
    )


def _store_klines(storage: StorageManager) -> None:
    start = ENTRY_TIME.replace(second=0, microsecond=0) - timedelta(minutes=25)
    rows = []
    for index in range(70):
        open_time = start + timedelta(minutes=index)
        close_time = open_time + timedelta(minutes=1)
        close = 98.0 + index * 0.1
        rows.append(
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "open_time_utc_ms": _utc_ms(open_time),
                "open_time_bjt": open_time.isoformat(),
                "close_time_utc_ms": _utc_ms(close_time),
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 10.0,
                "source": "test_exchange",
                "downloaded_at": EXIT_TIME.isoformat(),
                "data_quality_status": "ok",
            }
        )
    storage.upsert_klines(rows)


def _grouping(storage: StorageManager):
    samples = (
        ("event_open_exit_review", ENTRY_TIME),
        ("event_close_exit_review", EXIT_TIME),
    )
    return MarketEpisodeService(storage).create_automatic_grouping(
        tuple(
            ResearchSampleWindow(
                sample_id=sample_id,
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    decision_time - timedelta(minutes=20),
                    decision_time,
                ),
                outcome_window=TimeRange(
                    decision_time,
                    decision_time + timedelta(minutes=10),
                ),
            )
            for sample_id, decision_time in samples
        ),
        created_at=EXIT_TIME,
    )


def _manual_grouping(storage: StorageManager, sample_id: str):
    decision_time = ENTRY_TIME + timedelta(minutes=15)
    return MarketEpisodeService(storage).create_automatic_grouping(
        (
            ResearchSampleWindow(
                sample_id="event_open_exit_review",
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    ENTRY_TIME - timedelta(minutes=20),
                    ENTRY_TIME,
                ),
                outcome_window=TimeRange(
                    ENTRY_TIME,
                    ENTRY_TIME + timedelta(minutes=10),
                ),
            ),
            ResearchSampleWindow(
                sample_id=sample_id,
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    decision_time - timedelta(minutes=20),
                    decision_time,
                ),
                outcome_window=TimeRange(
                    decision_time,
                    decision_time + timedelta(minutes=10),
                ),
            ),
        ),
        created_at=EXIT_TIME,
    )


def test_full_close_is_pending_until_one_immutable_blind_exit_judgment_is_saved(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_blind_review.db")
    setup = _setup_version(storage)
    _closed_trade(storage)
    _store_klines(storage)
    grouping = _grouping(storage)
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    service = ExitBlindReviewService(storage)

    receipt = service.enqueue_actual_close(
        trade_event_id="event_close_exit_review",
        grouping_version_id=grouping.grouping_version_id,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )

    assert receipt.status is ReviewStatus.PENDING_CONFIRMATION
    assert item.status is ReviewStatus.PENDING_CONFIRMATION
    assert item.setup_version_id == setup.setup_version_id
    assert item.position.anonymous_position_id.startswith("position_")
    assert item.position.actual_entry_price == 100.0
    assert item.position.entry_atr20 is not None
    assert item.judgment is None
    assert item.label_state is ExitReviewLabelState.UNLABELED

    saved = service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
        judgment=ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.EXIT_NOW,
            reason_tags=("giveback",),
            confidence=4,
            note="只依据截止线前的持仓状态。",
        ),
    )

    assert saved.phase is ReviewPhase.BLIND
    assert saved.label is ExitJudgmentLabel.EXIT_NOW
    assert saved.version_number == 1
    assert saved.eligible_for_primary_research is True
    assert service.list_judgments(receipt.decision_event_id) == (saved,)
    audit = storage.fetch_table(
        "exit_decision_events",
        "decision_event_id=?",
        (receipt.decision_event_id,),
    )[0]
    assert audit["trade_id"] == "trade_exit_review"
    assert audit["entry_event_id"] == "event_open_exit_review"
    judged_item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
    )
    assert judged_item.label_state is ExitReviewLabelState.EXIT_NOW


def test_historical_full_close_uses_market_cutoff_and_audits_wall_clock(tmp_path):
    storage = StorageManager(tmp_path / "historical-exit-cutoff.db")
    setup = _setup_version(storage)
    observed_exit = datetime(2026, 7, 20, 4, 0, tzinfo=UTC)
    _closed_trade(storage, observed_exit_time=observed_exit)
    _store_klines(storage)
    grouping = _grouping(storage)
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    ExitBlindReviewService(storage).enqueue_actual_close(
        trade_event_id="event_close_exit_review",
        grouping_version_id=grouping.grouping_version_id,
    )

    row = storage.fetch_table("exit_decision_events")[0]
    expected_cutoff = EXIT_TIME.replace(second=0, microsecond=0)
    assert row["decision_cutoff_utc_ms"] == _utc_ms(expected_cutoff)
    assert row["decision_bar_open_time_utc_ms"] == _utc_ms(
        expected_cutoff - timedelta(minutes=1)
    )
    assert row["observed_action_time_utc_ms"] == _utc_ms(observed_exit)
    assert row["timing_approximate"] == 1


def test_manual_position_time_is_pending_and_does_not_infer_hold(tmp_path):
    storage = StorageManager(tmp_path / "manual_exit_seed.db")
    setup = _setup_version(storage)
    _closed_trade(storage)
    _store_klines(storage)
    grouping = _manual_grouping(storage, "manual_exit_position_1")
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    service = ExitBlindReviewService(storage)

    receipt = service.enqueue_manual_position(
        manual_seed_id="manual_exit_position_1",
        trade_id="trade_exit_review",
        grouping_version_id=grouping.grouping_version_id,
        decision_time=ENTRY_TIME + timedelta(minutes=15),
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )

    assert receipt.status is ReviewStatus.PENDING_CONFIRMATION
    assert item.status is ReviewStatus.PENDING_CONFIRMATION
    assert item.judgment is None
    original = storage.fetch_table(
        "exit_original_actions",
        "decision_event_id=?",
        (receipt.decision_event_id,),
    )[0]
    assert original["seed_source"] == "MANUAL_POSITION"
    assert original["original_action"] == "NONE"
    audit = storage.fetch_table(
        "exit_decision_events",
        "decision_event_id=?",
        (receipt.decision_event_id,),
    )[0]
    assert audit["timing_approximate"] == 1


def test_blinded_exit_payload_hides_close_outcome_and_relabel_is_post_outcome(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_reveal.db")
    setup = _setup_version(storage)
    _closed_trade(storage)
    _store_klines(storage)
    grouping = _grouping(storage)
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    service = ExitBlindReviewService(storage)
    service.enqueue_actual_close(
        trade_event_id="event_close_exit_review",
        grouping_version_id=grouping.grouping_version_id,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )

    blinded_keys = str(asdict(item)).lower()
    assert "trade_id" not in blinded_keys
    assert "entry_event_id" not in blinded_keys
    assert "decision_event_id" not in blinded_keys
    assert "seed_source" not in blinded_keys
    assert "original_action" not in blinded_keys
    assert "realized_pnl" not in blinded_keys
    assert "enqueue_reason" not in blinded_keys
    assert all(
        bar.close_time_utc_ms <= item.decision_cutoff_utc_ms
        for chart in item.charts
        for bar in chart.bars
    )

    blind = service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
        judgment=ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.HOLD,
            reason_tags=("trend_intact",),
            confidence=3,
        ),
    )
    revealed = service.reveal(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
    )
    relabel = service.relabel_after_reveal(
        decision_event_id=revealed.decision_event_id,
        judgment=ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.EXIT_NOW,
            reason_tags=("giveback",),
            confidence=5,
        ),
    )

    assert blind.label is ExitJudgmentLabel.HOLD
    assert revealed.original.seed_source.value == "ACTUAL_CLOSE"
    assert revealed.original.original_action.value == "FULL_CLOSE"
    assert revealed.original.realized_pnl_quote == 40.0
    assert any(
        bar.close_time_utc_ms > item.decision_cutoff_utc_ms
        for chart in revealed.future_charts
        for bar in chart.bars
    )
    assert relabel.phase is ReviewPhase.POST_OUTCOME
    assert relabel.previous_judgment_id == blind.judgment_id
    assert relabel.eligible_for_primary_research is False
    assert service.list_judgments(revealed.decision_event_id) == (blind, relabel)


def test_legacy_close_without_entry_setup_is_browsable_but_never_formal(
    tmp_path,
):
    storage = StorageManager(tmp_path / "legacy_exit_review.db")
    setup = _setup_version(storage)
    _closed_trade(storage)
    _store_klines(storage)
    grouping = _grouping(storage)
    service = ExitBlindReviewService(storage)

    receipt = service.enqueue_actual_close(
        trade_event_id="event_close_exit_review",
        grouping_version_id=grouping.grouping_version_id,
        legacy_review_setup_version_id=setup.setup_version_id,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )
    saved = service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
        judgment=ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.UNCERTAIN,
            reason_tags=("data_quality_warning",),
            confidence=2,
        ),
    )

    assert receipt.status is ReviewStatus.PENDING_CONFIRMATION
    assert item.setup_link_status == "LEGACY_UNLINKED"
    assert item.eligible_for_formal_research is False
    assert saved.eligible_for_primary_research is False
    assert service.list_primary_research_judgments(receipt.decision_event_id) == ()


def test_partial_reduction_has_an_explicit_unsupported_domain_state(tmp_path):
    storage = StorageManager(tmp_path / "partial_exit_review.db")
    _closed_trade(storage)
    service = ExitBlindReviewService(storage)

    with pytest.raises(PartialExitUnsupportedError) as captured:
        service.enqueue_actual_close(
            trade_event_id="event_close_exit_review",
            grouping_version_id="unused_for_partial_rejection",
            close_scope="PARTIAL",
        )

    assert captured.value.code == "partial_exit_unsupported"
    assert (
        captured.value.user_message_key
        == "decision_research.exit_review.partial_unsupported"
    )


def test_exit_judgment_requires_at_least_one_explicit_reason():
    with pytest.raises(ValueError, match="reason_tag"):
        ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.UNCERTAIN,
            reason_tags=(),
            confidence=3,
        )
    with pytest.raises(ValueError, match="Unsupported reason_tags"):
        ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.EXIT_NOW,
            reason_tags=("trend_intact",),
            confidence=3,
        )


def test_account_pressure_keeps_independent_positions_and_ignores_future_equity(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_account_pressure.db")
    setup = _setup_version(storage)
    _closed_trade(storage)
    storage.upsert_session(
        {
            "session_id": "session_exit_review",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "initial_equity": 10_000.0,
        }
    )
    storage.insert_trade(
        {
            "trade_id": "trade_independent_position",
            "session_id": "session_exit_review",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": "LONG",
            "status": "OPEN",
            "entry_event_id": "event_independent_open",
            "entry_bar_index": 50,
            "entry_fill_price": 250.0,
            "entry_price_proxy": 250.0,
            "notional_quote": 2_000.0,
            "created_at": ENTRY_TIME.isoformat(),
            "updated_at": ENTRY_TIME.isoformat(),
        }
    )
    storage.replace_equity_curve(
        "session_exit_review",
        (
            {
                "session_id": "session_exit_review",
                "sequence_no": 1,
                "trade_id": "earlier_trade",
                "event_id": "earlier_close",
                "equity_before": 10_000.0,
                "equity_after": 10_000.0,
                "created_at": ENTRY_TIME.isoformat(),
            },
            {
                "session_id": "session_exit_review",
                "sequence_no": 2,
                "trade_id": "trade_exit_review",
                "event_id": "event_close_exit_review",
                "equity_before": 9_500.0,
                "equity_after": 9_540.0,
                "created_at": EXIT_TIME.isoformat(),
            },
            {
                "session_id": "session_exit_review",
                "sequence_no": 3,
                "trade_id": "future_trade",
                "event_id": "future_close",
                "equity_before": 9_540.0,
                "equity_after": 20_000.0,
                "created_at": (EXIT_TIME + timedelta(hours=1)).isoformat(),
            },
        ),
    )
    _store_klines(storage)
    grouping = _grouping(storage)
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    service = ExitBlindReviewService(storage)
    receipt = service.enqueue_actual_close(
        trade_event_id="event_close_exit_review",
        grouping_version_id=grouping.grouping_version_id,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )

    audit = storage.fetch_table(
        "exit_decision_events",
        "decision_event_id=?",
        (receipt.decision_event_id,),
    )[0]
    assert audit["trade_id"] == "trade_exit_review"
    assert item.position.actual_entry_price == 100.0
    assert item.position.take_profit_status is OptionalRiskLevelStatus.NOT_SET
    assert item.position.take_profit_price is None
    assert item.position.stop_loss_status is OptionalRiskLevelStatus.SET
    assert item.position.stop_loss_price == 99.0
    assert item.account_pressure.open_position_count == 2
    assert item.account_pressure.position_notional_quote == 1_000.0
    assert item.account_pressure.total_open_notional_quote == 3_000.0
    assert item.account_pressure.position_equity_ratio == pytest.approx(
        1_000.0 / 9_500.0
    )
    assert item.account_pressure.total_exposure_ratio == pytest.approx(
        3_000.0 / 9_500.0
    )
    assert item.account_pressure.account_drawdown_pct == pytest.approx(-5.0)
    assert item.account_pressure.leverage is None
    assert item.account_pressure.margin_quote is None
    assert item.account_pressure.liquidation_price is None


def test_loading_a_batch_discovers_full_close_members_as_pending_seeds(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_actual_discovery.db")
    setup = _setup_version(storage)
    _closed_trade(storage)
    _store_klines(storage)
    grouping = _grouping(storage)
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    batch = ExitBlindReviewService(storage).create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    assert len(batch.items) == 1
    discovered = storage.fetch_table("exit_decision_events")
    assert discovered[0]["source_sample_id"] == "event_close_exit_review"
    assert discovered[0]["trade_id"] == "trade_exit_review"


def test_original_close_and_blind_judgment_are_database_immutable(tmp_path):
    storage = StorageManager(tmp_path / "exit_review_immutable.db")
    setup = _setup_version(storage)
    _closed_trade(storage)
    _store_klines(storage)
    grouping = _grouping(storage)
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    service = ExitBlindReviewService(storage)
    receipt = service.enqueue_actual_close(
        trade_event_id="event_close_exit_review",
        grouping_version_id=grouping.grouping_version_id,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )
    service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
        judgment=ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.EXIT_NOW,
            reason_tags=("trend_failure",),
            confidence=4,
        ),
    )

    with storage.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                """
                UPDATE exit_original_actions
                SET realized_pnl_quote=999
                WHERE decision_event_id=?
                """,
                (receipt.decision_event_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                """
                UPDATE exit_judgment_versions
                SET label='HOLD'
                WHERE decision_event_id=?
                """,
                (receipt.decision_event_id,),
            )


def test_short_close_with_missing_entry_atr_and_unset_risk_levels_stays_nonformal(
    tmp_path,
):
    storage = StorageManager(tmp_path / "short_exit_missing_atr.db")
    setup = _setup_version(storage, SetupDirection.SHORT)
    _closed_trade(
        storage,
        side="SHORT",
        stop_loss_pct=None,
        stop_loss_price=None,
    )
    grouping = _grouping(storage)
    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_exit_review",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    service = ExitBlindReviewService(storage)
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )
    saved = service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
        judgment=ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.EXIT_NOW,
            reason_tags=("trend_failure",),
            confidence=2,
        ),
    )

    assert item.direction == "SHORT"
    assert item.position.entry_atr20 is None
    assert item.position.take_profit_status is OptionalRiskLevelStatus.NOT_SET
    assert item.position.stop_loss_status is OptionalRiskLevelStatus.NOT_SET
    assert item.eligible_for_formal_research is False
    assert saved.eligible_for_primary_research is False
