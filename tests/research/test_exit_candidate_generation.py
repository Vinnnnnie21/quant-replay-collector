from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import asdict, replace
import json

import pytest

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
from research.exit_candidate_generation import (
    ExitCandidateScanCancelled,
    ExitCandidateScanRequest,
    ExitCandidateScanStatus,
)
from research.exit_blind_review import ExitBlindJudgmentInput, ExitJudgmentLabel
from services.entry_blind_review import EntryBlindReviewService
from services.exit_blind_review import ExitBlindReviewService
from services.exit_candidate_generation import ExitCandidateGenerationService
from services.exit_outcome_comparison import ExitOutcomeComparisonService
from storage import StorageManager
from errors import DatabaseError
from controllers.exit_blind_review_controller import ExitBlindReviewController


BASE_TIME = datetime(2026, 7, 1, tzinfo=UTC)


def test_exit_candidate_maturity_gate_reports_exact_exit_now_and_holding_deficits(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_candidate_maturity.db")
    setup = _setup_version(storage)
    grouping = MarketEpisodeService(storage).create_automatic_grouping(
        (
            ResearchSampleWindow(
                sample_id="maturity_anchor",
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    BASE_TIME - timedelta(hours=1),
                    BASE_TIME,
                ),
                outcome_window=TimeRange(
                    BASE_TIME,
                    BASE_TIME + timedelta(minutes=20),
                ),
            ),
        ),
        created_at=BASE_TIME,
    )

    service = ExitCandidateGenerationService(storage)
    result = service.scan(
        ExitCandidateScanRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.status is ExitCandidateScanStatus.NOT_READY
    assert result.maturity.complete_exit_now_count == 0
    assert result.maturity.holding_episode_count == 0
    assert result.maturity.missing_exit_now_count == 10
    assert result.maturity.missing_holding_episode_count == 5
    assert result.candidates == ()


def test_exit_outcome_round_trips_from_revealed_blind_judgments_atomically(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_outcome_round_trip.db")
    setup = _setup_version(storage)
    grouping, _candidate_event_ids = _seed_candidate_universe(storage, setup)
    review = ExitBlindReviewService(storage)

    for row in storage.fetch_table("exit_judgment_versions", "phase='BLIND'"):
        assert storage.insert_exit_review_reveal(
            {
                "decision_event_id": row["decision_event_id"],
                "blind_judgment_id": row["judgment_id"],
                "revealed_at": BASE_TIME.isoformat(),
            }
        )
    hold_batch = review.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    assert len(hold_batch.items) == 2
    for item in hold_batch.items:
        review.save_blind_judgment(
            batch_id=hold_batch.batch_id,
            blind_item_id=item.blind_item_id,
            judgment=ExitBlindJudgmentInput(
                label=ExitJudgmentLabel.HOLD,
                reason_tags=("trend_intact",),
                confidence=3,
            ),
        )
        review.reveal(
            batch_id=hold_batch.batch_id,
            blind_item_id=item.blind_item_id,
        )

    service = ExitOutcomeComparisonService(
        storage,
        clock=lambda: datetime(2026, 7, 20, tzinfo=UTC),
        id_factory=lambda: "exit_outcome_round_trip",
    )
    result = service.run(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        direction="LONG",
        random_seed=17,
    )

    assert len(result.primary.pairs) == 2
    assert len(result.primary.matrix) == 15
    assert service.get_result(result.comparison_id) == result
    assert len(storage.fetch_table("exit_outcome_matches")) == 6
    with pytest.raises(DatabaseError, match="immutable"):
        with storage.connect() as conn:
            conn.execute(
                """
                UPDATE exit_outcome_comparisons
                SET random_seed=1
                WHERE comparison_id=?
                """,
                (result.comparison_id,),
            )

    failed_id = "exit_outcome_forced_transaction_failure"
    with storage.connect() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_exit_outcome_match_insert
            BEFORE INSERT ON exit_outcome_matches
            WHEN NEW.comparison_id='exit_outcome_forced_transaction_failure'
            BEGIN
                SELECT RAISE(ABORT, 'forced exit match insert failure');
            END
            """
        )
    with pytest.raises(DatabaseError, match="forced exit match insert failure"):
        storage.save_exit_outcome_result(
            replace(result, comparison_id=failed_id)
        )
    assert storage.get_exit_outcome_result(failed_id) is None


def test_public_exit_scan_scores_only_explicit_open_position_review_points(tmp_path):
    storage = StorageManager(tmp_path / "exit_candidate_tracer.db")
    setup = _setup_version(storage)
    grouping, candidate_event_ids = _seed_candidate_universe(storage, setup)

    service = ExitCandidateGenerationService(storage)
    result = service.scan(
        ExitCandidateScanRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.status is ExitCandidateScanStatus.COMPLETED
    assert result.maturity.complete_exit_now_count == 10
    assert result.maturity.holding_episode_count == 10
    assert result.candidate_universe_count == 2
    assert {item.decision_event_id for item in result.candidates} == set(
        candidate_event_ids
    )
    assert all(len(item.references) == 3 for item in result.candidates)
    assert all(
        len({reference.holding_episode_id for reference in item.references}) == 3
        for item in result.candidates
    )
    assert service.get_scan(result.scan_id) == result
    assert len(storage.fetch_table("exit_candidate_scans")) == 1
    with pytest.raises(DatabaseError, match="immutable"):
        with storage.connect() as conn:
            conn.execute(
                "UPDATE exit_candidate_scans SET direction='SHORT' WHERE scan_id=?",
                (result.scan_id,),
            )
    payload = json.dumps(asdict(result), ensure_ascii=False).lower()
    assert not any(
        token in payload
        for token in (
            "realized_pnl",
            "future",
            "account_pressure",
            "confidence",
            "reason_tags",
        )
    )
    formal = service.create_blind_review_batch(scan_id=result.scan_id, limit=2)
    assert len(formal.batch.items) == 2
    assert formal.high_similarity_count == 1
    assert formal.diverse_count == 1
    exit_review = ExitBlindReviewService(storage)
    first_item = formal.batch.items[0]
    blinded = exit_review.get_blinded_item(
        batch_id=formal.batch.batch_id,
        blind_item_id=first_item.blind_item_id,
    )
    blind_payload = json.dumps(asdict(blinded), ensure_ascii=False).lower()
    assert not any(
        token in blind_payload
        for token in ("similarity", "reference", "enqueue_reason", "selection_reason")
    )
    batch_row = storage.get_exit_review_batch_item(
        batch_id=formal.batch.batch_id,
        blind_item_id=first_item.blind_item_id,
    )
    assert batch_row is not None
    with pytest.raises(PermissionError, match="blind judgment"):
        exit_review.get_candidate_audit_after_judgment(
            batch_row["decision_event_id"]
        )
    saved = exit_review.save_blind_judgment(
        batch_id=formal.batch.batch_id,
        blind_item_id=first_item.blind_item_id,
        judgment=ExitBlindJudgmentInput(
            label=ExitJudgmentLabel.HOLD,
            reason_tags=("trend_intact",),
            confidence=3,
        ),
    )
    controller = ExitBlindReviewController(exit_review)
    controller.load_existing_batch(formal.batch)
    controller.select_item(0)
    audit = controller.candidate_audit_current()
    assert audit is not None
    assert len(audit.references) == 3
    assert audit.enqueue_reason == "STRUCTURAL_SIMILARITY"
    assert len(audit.group_distances) == 12
    assert audit.position_distance is not None
    assert audit.research_target == "EXIT"

    revealed = controller.reveal_current()
    assert revealed.account_pressure is not None
    assert revealed.candidate_audit == audit


def test_schema_16_upgrade_adds_exit_candidate_audit_tables_and_backup(tmp_path):
    db_path = tmp_path / "schema_16_exit_candidates.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(db_path, backup_dir=backup_dir)
    with legacy.connect() as conn:
        for table in (
            "exit_candidate_exclusions",
            "exit_candidate_batch_items",
            "exit_candidate_batches",
            "exit_candidate_scores",
            "exit_candidate_scans",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version=16")

    upgraded = StorageManager(db_path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.fetch_table("exit_candidate_scans") == []
    with upgraded.connect() as conn:
        indexes = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA index_list('exit_decision_events')"
            ).fetchall()
        }
    assert "idx_exit_decision_events_candidate_context" in indexes
    assert list(
        backup_dir.glob(f"*v16_to_v{StorageManager.SCHEMA_VERSION}*.db")
    )


def test_free_browse_reveal_permanently_excludes_exit_candidate_from_formal_batch(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_candidate_exclusion.db")
    setup = _setup_version(storage)
    grouping, _candidate_event_ids = _seed_candidate_universe(storage, setup)
    service = ExitCandidateGenerationService(storage)
    result = service.scan(
        ExitCandidateScanRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )
    exposed = result.candidates[0]

    revealed = service.reveal_candidate_in_free_browse(
        scan_id=result.scan_id,
        decision_event_id=exposed.decision_event_id,
    )
    formal = service.create_blind_review_batch(scan_id=result.scan_id, limit=2)

    assert revealed == exposed
    assert storage.list_exit_candidate_exclusions() == (
        exposed.decision_event_id,
    )
    assert len(formal.batch.items) == 1
    batch_rows = storage.fetch_table(
        "exit_review_batch_items",
        "batch_id=?",
        (formal.batch.batch_id,),
    )
    assert {row["decision_event_id"] for row in batch_rows} == {
        result.candidates[1].decision_event_id
    }
    with pytest.raises(DatabaseError, match="free-browse"):
        storage.create_exit_candidate_batch(
            batch={
                "batch_id": "forbidden_excluded_batch",
                "scan_id": result.scan_id,
                "setup_version_id": result.setup_version_id,
                "grouping_version_id": result.grouping_version_id,
                "high_similarity_count": 1,
                "diverse_count": 0,
                "created_at": BASE_TIME.isoformat(),
            },
            items=(
                {
                    "blind_item_id": "forbidden_excluded_item",
                    "decision_event_id": exposed.decision_event_id,
                    "display_order": 0,
                    "selection_reason": "HIGH_SIMILARITY",
                },
            ),
        )
    assert storage.fetch_table(
        "exit_review_batches",
        "batch_id=?",
        ("forbidden_excluded_batch",),
    ) == []


def test_free_browse_cannot_reveal_candidate_already_reserved_by_formal_batch(
    tmp_path,
):
    storage = StorageManager(tmp_path / "exit_candidate_exclusion_race.db")
    setup = _setup_version(storage)
    grouping, _candidate_event_ids = _seed_candidate_universe(storage, setup)
    service = ExitCandidateGenerationService(storage)
    scan = service.scan(
        ExitCandidateScanRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )
    formal = service.create_blind_review_batch(scan_id=scan.scan_id, limit=1)
    item = formal.batch.items[0]
    row = storage.get_exit_review_batch_item(
        batch_id=formal.batch.batch_id,
        blind_item_id=item.blind_item_id,
    )
    assert row is not None
    with pytest.raises(PermissionError, match="free browse"):
        service.reveal_candidate_in_free_browse(
            scan_id=scan.scan_id,
            decision_event_id=row["decision_event_id"],
        )

    assert storage.list_exit_candidate_exclusions() == ()


def test_exit_candidate_scan_cancellation_does_not_publish_completed_state(tmp_path):
    storage = StorageManager(tmp_path / "exit_candidate_cancel.db")
    setup = _setup_version(storage)
    grouping, _candidate_event_ids = _seed_candidate_universe(storage, setup)
    cancel_requested = {"value": False}

    with pytest.raises(ExitCandidateScanCancelled):
        ExitCandidateGenerationService(storage).scan(
            ExitCandidateScanRequest(
                setup_version_id=setup.setup_version_id,
                grouping_version_id=grouping.grouping_version_id,
                direction="LONG",
            ),
            cancelled=lambda: cancel_requested["value"],
            progress=lambda done, total: cancel_requested.__setitem__(
                "value",
                done == total,
            ),
        )

    assert storage.fetch_table("exit_candidate_scans") == []


def _setup_version(storage: StorageManager):
    return SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="平仓候选测试",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只使用平仓判断截止点及以前的信息。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version


def _seed_candidate_universe(storage: StorageManager, setup):
    reference_times = tuple(
        BASE_TIME + timedelta(days=index * 2, hours=12)
        for index in range(10)
    )
    candidate_times = (
        BASE_TIME + timedelta(days=22, hours=12),
        BASE_TIME + timedelta(days=24, hours=12),
    )
    sample_windows = []
    for index, decision_time in enumerate(reference_times):
        _insert_position(
            storage,
            identity=f"reference_{index:02d}",
            entry_time=decision_time - timedelta(minutes=30),
            decision_time=decision_time,
            closed=True,
        )
        sample_windows.extend(
            _position_sample_windows(
                f"reference_{index:02d}",
                decision_time,
                closed=True,
            )
        )
        _store_complete_history(storage, decision_time, price_offset=index * 0.1)
    for index, decision_time in enumerate(candidate_times):
        _insert_position(
            storage,
            identity=f"candidate_{index:02d}",
            entry_time=decision_time - timedelta(minutes=30),
            decision_time=decision_time,
            closed=False,
        )
        sample_windows.extend(
            _position_sample_windows(
                f"candidate_{index:02d}",
                decision_time,
                closed=False,
            )
        )
        _store_complete_history(
            storage,
            decision_time,
            price_offset=0.15 + index * 0.05,
        )
    grouping = MarketEpisodeService(storage).create_automatic_grouping(
        tuple(sample_windows),
        created_at=BASE_TIME,
    )
    entry_review = EntryBlindReviewService(storage)
    exit_review = ExitBlindReviewService(storage)
    for index in range(10):
        entry_review.enqueue_actual_open(
            trade_event_id=f"open_reference_{index:02d}",
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
        )
        exit_review.enqueue_actual_close(
            trade_event_id=f"close_reference_{index:02d}",
            grouping_version_id=grouping.grouping_version_id,
        )
    batch = exit_review.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    assert len(batch.items) == 10
    for item in batch.items:
        exit_review.save_blind_judgment(
            batch_id=batch.batch_id,
            blind_item_id=item.blind_item_id,
            judgment=ExitBlindJudgmentInput(
                label=ExitJudgmentLabel.EXIT_NOW,
                reason_tags=("trend_failure",),
                confidence=3,
            ),
        )
    candidate_event_ids = []
    for index, decision_time in enumerate(candidate_times):
        entry_review.enqueue_actual_open(
            trade_event_id=f"open_candidate_{index:02d}",
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
        )
        receipt = exit_review.enqueue_manual_position(
            manual_seed_id=f"manual_candidate_{index:02d}",
            trade_id=f"trade_candidate_{index:02d}",
            grouping_version_id=grouping.grouping_version_id,
            decision_time=decision_time + timedelta(seconds=30),
        )
        candidate_event_ids.append(receipt.decision_event_id)
    return grouping, tuple(candidate_event_ids)


def _insert_position(
    storage: StorageManager,
    *,
    identity: str,
    entry_time: datetime,
    decision_time: datetime,
    closed: bool,
) -> None:
    trade_id = f"trade_{identity}"
    open_event_id = f"open_{identity}"
    close_event_id = f"close_{identity}" if closed else None
    storage.insert_trade(
        {
            "trade_id": trade_id,
            "session_id": f"session_{identity}",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": "LONG",
            "status": "CLOSED" if closed else "OPEN",
            "entry_event_id": open_event_id,
            "exit_event_id": close_event_id,
            "entry_bar_index": 100,
            "exit_bar_index": 130 if closed else None,
            "entry_bar_time_bjt": entry_time.isoformat(),
            "entry_real_time_bjt": (entry_time + timedelta(seconds=30)).isoformat(),
            "exit_bar_time_bjt": decision_time.isoformat() if closed else None,
            "exit_real_time_bjt": (
                (decision_time + timedelta(seconds=30)).isoformat()
                if closed
                else None
            ),
            "entry_fill_price": 100.0,
            "entry_price_proxy": 100.0,
            "exit_fill_price": 101.0 if closed else None,
            "notional_quote": 1_000.0,
            "take_profit_pct": None,
            "take_profit_price": None,
            "stop_loss_pct": None,
            "stop_loss_price": None,
            "net_pnl_quote": 10.0 if closed else None,
            "created_at": entry_time.isoformat(),
            "updated_at": decision_time.isoformat(),
        }
    )
    storage.insert_event(
        _trade_event(
            open_event_id,
            trade_id=trade_id,
            event_type="OPEN",
            action_time=entry_time + timedelta(seconds=30),
            bar_index=100,
        )
    )
    if close_event_id is not None:
        storage.insert_event(
            _trade_event(
                close_event_id,
                trade_id=trade_id,
                event_type="CLOSE",
                action_time=decision_time + timedelta(seconds=30),
                bar_index=130,
            )
        )


def _trade_event(
    event_id: str,
    *,
    trade_id: str,
    event_type: str,
    action_time: datetime,
    bar_index: int,
):
    return {
        "event_id": event_id,
        "session_id": f"session_{trade_id}",
        "trade_id": trade_id,
        "event_type": event_type,
        "side": "LONG",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "bar_index": bar_index,
        "bar_open_time_bjt": action_time.replace(second=0).isoformat(),
        "real_key_time_bjt": action_time.isoformat(),
        "price_proxy": 100.0,
        "label_tags": [],
        "note": "",
        "created_at": action_time.isoformat(),
    }


def _position_sample_windows(
    identity: str,
    decision_time: datetime,
    *,
    closed: bool,
):
    entry_time = decision_time - timedelta(minutes=30)
    identities = [(f"open_{identity}", entry_time)]
    identities.append(
        (
            f"close_{identity}" if closed else f"manual_{identity}",
            decision_time,
        )
    )
    return tuple(
        ResearchSampleWindow(
            sample_id=sample_id,
            symbol="BTCUSDT",
            timeframe="1m",
            feature_window=TimeRange(
                sample_time - timedelta(hours=16),
                sample_time,
            ),
            outcome_window=TimeRange(
                sample_time,
                sample_time + timedelta(minutes=20),
            ),
        )
        for sample_id, sample_time in identities
    )


def _store_complete_history(
    storage: StorageManager,
    cutoff: datetime,
    *,
    price_offset: float,
) -> None:
    rows = []
    for interval, minutes in (("1m", 1), ("5m", 5), ("15m", 15)):
        duration = timedelta(minutes=minutes)
        for index in range(63):
            close_time = cutoff - duration * (62 - index)
            open_time = close_time - duration
            close = 100.0 + price_offset + index * 0.04
            rows.append(
                {
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "open_time_utc_ms": int(open_time.timestamp() * 1_000),
                    "open_time_bjt": open_time.isoformat(),
                    "close_time_utc_ms": int(close_time.timestamp() * 1_000),
                    "open": close - 0.1,
                    "high": close + 0.4,
                    "low": close - 0.5,
                    "close": close,
                    "volume": 10.0 + index,
                    "quote_volume": (10.0 + index) * close,
                    "trade_count": 100 + index,
                    "taker_buy_base_volume": (10.0 + index) * 0.55,
                    "taker_buy_quote_volume": (10.0 + index) * close * 0.55,
                    "source": "test_exchange",
                    "downloaded_at": cutoff.isoformat(),
                    "data_quality_status": "ok",
                }
            )
    storage.upsert_klines(rows)
