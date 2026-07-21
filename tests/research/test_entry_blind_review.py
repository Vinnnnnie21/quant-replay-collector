from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import sqlite3

import pytest

from research.entry_blind_review import (
    BlindJudgmentInput,
    EntryJudgmentLabel,
    ReviewPhase,
    ReviewStatus,
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
from storage import StorageManager


DECISION_TIME = datetime(2026, 7, 1, 0, 5, 30, tzinfo=UTC)


def test_service_fails_fast_when_storage_contract_is_incomplete():
    with pytest.raises(TypeError, match="entry blind-review contract"):
        EntryBlindReviewService(object())


def _setup_version(
    storage: StorageManager,
    direction: SetupDirection = SetupDirection.LONG,
):
    return SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="三周期盲审",
            version=SetupVersionSpec(
                direction=direction,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只按决策时点及此前已闭合 K 线判断。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version


def _actual_open(
    storage: StorageManager,
    side: str = "LONG",
    *,
    event_id: str = "event_open_1",
    trade_id: str = "trade_open_1",
    decision_time: datetime = DECISION_TIME,
) -> None:
    storage.insert_trade(
        {
            "trade_id": trade_id,
            "session_id": "session_1",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": side,
            "status": "OPEN",
            "entry_event_id": event_id,
            "entry_real_time_bjt": decision_time.isoformat(),
            "created_at": decision_time.isoformat(),
            "updated_at": decision_time.isoformat(),
        }
    )
    storage.insert_event(
        {
            "event_id": event_id,
            "session_id": "session_1",
            "trade_id": trade_id,
            "event_type": "OPEN",
            "side": side,
            "symbol": "BTCUSDT",
            "interval": "1m",
            "bar_index": 5,
            "bar_open_time_bjt": "2026-07-01T00:05:00+00:00",
            "real_key_time_bjt": decision_time.isoformat(),
            "price_proxy": 100.0,
            "label_tags": [],
            "note": "",
            "created_at": decision_time.isoformat(),
        }
    )


def _utc_ms(value: datetime) -> int:
    return int(value.timestamp() * 1_000)


def _kline(
    interval: str,
    open_time: datetime,
    close_time: datetime,
    close: float,
) -> dict:
    return {
        "symbol": "BTCUSDT",
        "interval": interval,
        "open_time_utc_ms": _utc_ms(open_time),
        "open_time_bjt": open_time.isoformat(),
        "close_time_utc_ms": _utc_ms(close_time),
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 10.0,
        "source": "test_exchange",
        "downloaded_at": DECISION_TIME.isoformat(),
        "data_quality_status": "ok",
    }


def _store_cutoff_fixture(storage: StorageManager) -> None:
    cutoff = DECISION_TIME.replace(second=0, microsecond=0)
    storage.upsert_klines(
        (
            _kline("1m", cutoff - timedelta(minutes=1), cutoff, 100.0),
            _kline("1m", cutoff, cutoff + timedelta(minutes=1), 900.0),
            _kline("5m", cutoff - timedelta(minutes=5), cutoff, 101.0),
            _kline("5m", cutoff, cutoff + timedelta(minutes=5), 901.0),
            _kline("15m", cutoff - timedelta(minutes=20), cutoff - timedelta(minutes=5), 102.0),
            _kline("15m", cutoff - timedelta(minutes=5), cutoff + timedelta(minutes=10), 902.0),
        )
    )


def _episode_grouping(
    storage: StorageManager,
    sample_id: str = "event_open_1",
):
    return MarketEpisodeService(storage).create_automatic_grouping(
        (
            ResearchSampleWindow(
                sample_id=sample_id,
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    DECISION_TIME - timedelta(minutes=20),
                    DECISION_TIME,
                ),
                outcome_window=TimeRange(
                    DECISION_TIME,
                    DECISION_TIME + timedelta(minutes=10),
                ),
            ),
        ),
        created_at=DECISION_TIME,
    )


def _grouping_for_samples(
    storage: StorageManager,
    samples: tuple[tuple[str, datetime], ...],
):
    return MarketEpisodeService(storage).create_automatic_grouping(
        tuple(
            ResearchSampleWindow(
                sample_id=sample_id,
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    decision_time - timedelta(minutes=2),
                    decision_time - timedelta(minutes=1),
                ),
                outcome_window=TimeRange(
                    decision_time,
                    decision_time + timedelta(minutes=1),
                ),
            )
            for sample_id, decision_time in samples
        ),
        created_at=DECISION_TIME,
    )


def test_actual_open_starts_pending_and_saves_one_immutable_blind_judgment(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_blind_review.db")
    setup_version = _setup_version(storage)
    _actual_open(storage)
    grouping = _episode_grouping(storage)
    service = EntryBlindReviewService(storage)

    receipt = service.enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    batch = service.create_batch(
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )

    assert receipt.status is ReviewStatus.PENDING_CONFIRMATION
    assert item.status is ReviewStatus.PENDING_CONFIRMATION
    assert item.judgment is None

    saved = service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
        judgment=BlindJudgmentInput(
            label=EntryJudgmentLabel.ENTRY,
            reason_tags=("long_lower_shadow",),
            confidence=4,
            note="只依据截止线前的三周期图表。",
        ),
    )

    assert saved.phase is ReviewPhase.BLIND
    assert saved.version_number == 1
    assert saved.eligible_for_primary_research is True
    assert service.list_judgments(item.decision_event_id) == (saved,)


def test_historical_actual_open_uses_market_cutoff_and_keeps_wall_clock_for_audit(
    tmp_path,
):
    storage = StorageManager(tmp_path / "historical-entry-cutoff.db")
    setup_version = _setup_version(storage)
    observed_time = datetime(2026, 7, 20, 4, 0, tzinfo=UTC)
    _actual_open(storage, decision_time=observed_time)
    _store_cutoff_fixture(storage)
    grouping = _episode_grouping(storage)

    EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    row = storage.fetch_table("entry_decision_events")[0]
    expected_cutoff = DECISION_TIME.replace(second=0, microsecond=0)
    assert row["decision_cutoff_utc_ms"] == _utc_ms(expected_cutoff)
    assert row["decision_bar_open_time_utc_ms"] == _utc_ms(
        expected_cutoff - timedelta(minutes=1)
    )
    assert row["observed_action_time_utc_ms"] == _utc_ms(observed_time)
    assert row["timing_approximate"] == 1


def test_manual_position_uses_the_same_pending_review_path_without_an_open_action(
    tmp_path,
):
    storage = StorageManager(tmp_path / "manual_entry_seed.db")
    setup_version = _setup_version(storage)
    grouping = _episode_grouping(storage, "manual_seed_1")
    service = EntryBlindReviewService(storage)

    receipt = service.enqueue_manual_position(
        manual_seed_id="manual_seed_1",
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction="LONG",
        decision_time=DECISION_TIME,
    )
    batch = service.create_batch(
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    assert receipt.status is ReviewStatus.PENDING_CONFIRMATION
    assert len(batch.items) == 1
    original = storage.fetch_table(
        "entry_original_actions",
        "decision_event_id=?",
        (receipt.decision_event_id,),
    )[0]
    assert original["seed_source"] == "MANUAL_POSITION"
    assert original["original_action"] == "NONE"


def test_intrabar_open_maps_to_last_closed_decision_bar_and_payload_has_no_future_or_source(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_cutoff.db")
    setup_version = _setup_version(storage)
    _actual_open(storage)
    _store_cutoff_fixture(storage)
    grouping = _episode_grouping(storage)
    service = EntryBlindReviewService(storage)

    receipt = service.enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    batch = service.create_batch(
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )

    cutoff = DECISION_TIME.replace(second=0, microsecond=0)
    stored_event = storage.fetch_table(
        "entry_decision_events",
        "decision_event_id=?",
        (receipt.decision_event_id,),
    )[0]
    assert stored_event["decision_bar_open_time_utc_ms"] == _utc_ms(
        cutoff - timedelta(minutes=1)
    )
    assert stored_event["timing_approximate"] == 1
    assert [chart.interval for chart in item.charts] == ["1m", "5m", "15m"]
    assert all(
        bar.close_time_utc_ms <= item.decision_cutoff_utc_ms
        for chart in item.charts
        for bar in chart.bars
    )
    assert [chart.bars[-1].close for chart in item.charts] == [100.0, 101.0, 102.0]

    serialized = json.dumps(asdict(item), ensure_ascii=False).lower()
    for forbidden in (
        "event_open_1",
        "test_exchange",
        "seed_source",
        "original_action",
        "actual_action",
        "future",
        "outcome",
        "score",
        "queue_reason",
    ):
        assert forbidden not in serialized


def test_open_one_millisecond_after_a_closed_bar_is_marked_as_approximate(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_cutoff_one_ms.db")
    setup = _setup_version(storage)
    cutoff = DECISION_TIME.replace(second=0, microsecond=0)
    _actual_open(
        storage,
        decision_time=cutoff + timedelta(milliseconds=1),
    )
    _store_cutoff_fixture(storage)
    grouping = _episode_grouping(storage)

    receipt = EntryBlindReviewService(storage).enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    stored_event = storage.fetch_table(
        "entry_decision_events",
        "decision_event_id=?",
        (receipt.decision_event_id,),
    )[0]
    assert stored_event["decision_cutoff_utc_ms"] == _utc_ms(cutoff)
    assert stored_event["timing_approximate"] == 1


def test_batch_caps_at_twenty_and_does_not_drop_a_real_seed_behind_manual_seeds(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_batch_priority.db")
    setup_version = _setup_version(storage)
    _actual_open(storage)
    manual_samples = tuple(
        (
            f"manual_{index:02d}",
            DECISION_TIME + timedelta(hours=1, minutes=index * 5),
        )
        for index in range(20)
    )
    grouping = _grouping_for_samples(
        storage,
        (("event_open_1", DECISION_TIME), *manual_samples),
    )
    service = EntryBlindReviewService(storage)

    for sample_id, decision_time in manual_samples:
        service.enqueue_manual_position(
            manual_seed_id=sample_id,
            setup_version_id=setup_version.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            symbol="BTCUSDT",
            direction="LONG",
            decision_time=decision_time,
        )
    actual = service.enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    batch = service.create_batch(
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    assert len(batch.items) == 20
    selected_event_ids = {
        row["decision_event_id"]
        for row in storage.fetch_table(
            "entry_review_batch_items",
            "batch_id=?",
            (batch.batch_id,),
        )
    }
    assert actual.decision_event_id in selected_event_ids
    selected_episodes = {
        row["episode_id"]
        for row in storage.fetch_table("entry_decision_events")
        if row["decision_event_id"] in selected_event_ids
    }
    assert len(selected_episodes) == 20


def test_reveal_is_explicit_and_post_outcome_relabel_never_overwrites_blind_version(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_reveal.db")
    setup_version = _setup_version(storage)
    _actual_open(storage)
    _store_cutoff_fixture(storage)
    grouping = _episode_grouping(storage)
    service = EntryBlindReviewService(storage)
    receipt = service.enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    batch = service.create_batch(
        setup_version_id=setup_version.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    blind_item_id = batch.items[0].blind_item_id
    blind = service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=blind_item_id,
        judgment=BlindJudgmentInput(
            label="REJECT",
            reason_tags=("insufficient_confirmation",),
            confidence=3,
            note="盲态原始判断",
        ),
    )

    revealed = service.reveal(
        batch_id=batch.batch_id,
        blind_item_id=blind_item_id,
    )

    assert revealed.status is ReviewStatus.REVEALED
    assert revealed.original.seed_source.value == "ACTUAL_OPEN"
    assert revealed.original.original_action.value == "OPEN_LONG"
    assert revealed.original.timing_approximate is True
    assert revealed.future_charts[0].bars[0].close == 900.0

    relabel = service.relabel_after_reveal(
        decision_event_id=receipt.decision_event_id,
        judgment=BlindJudgmentInput(
            label="ENTRY",
            reason_tags=("bullish_confirmation",),
            confidence=5,
            note="看到结果后的复标",
        ),
    )

    assert relabel.phase is ReviewPhase.POST_OUTCOME
    assert relabel.version_number == 2
    assert relabel.previous_judgment_id == blind.judgment_id
    assert relabel.eligible_for_primary_research is False
    versions = service.list_judgments(receipt.decision_event_id)
    assert versions[0] == blind
    assert versions[0].label is EntryJudgmentLabel.REJECT
    assert service.list_primary_research_judgments(
        receipt.decision_event_id
    ) == (blind,)


def test_concurrent_reveal_is_idempotent_and_keeps_one_audit_record(tmp_path):
    storage = StorageManager(tmp_path / "entry_reveal_concurrent.db")
    setup = _setup_version(storage)
    grouping = _episode_grouping(storage, "manual_reveal_concurrent")
    service = EntryBlindReviewService(storage)
    service.enqueue_manual_position(
        manual_seed_id="manual_reveal_concurrent",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction="LONG",
        decision_time=DECISION_TIME,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    blind_item_id = batch.items[0].blind_item_id
    service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=blind_item_id,
        judgment=BlindJudgmentInput(
            label="UNCERTAIN",
            reason_tags=("mixed_setup",),
            confidence=3,
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        revealed = tuple(
            executor.map(
                lambda _index: service.reveal(
                    batch_id=batch.batch_id,
                    blind_item_id=blind_item_id,
                ),
                range(2),
            )
        )

    assert revealed[0].revealed_at == revealed[1].revealed_at
    assert len(storage.fetch_table("entry_review_reveals")) == 1


def test_duplicate_blind_save_is_rejected_without_mutating_the_first_version(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_duplicate_save.db")
    setup = _setup_version(storage)
    grouping = _episode_grouping(storage, "manual_duplicate")
    service = EntryBlindReviewService(storage)
    service.enqueue_manual_position(
        manual_seed_id="manual_duplicate",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction="LONG",
        decision_time=DECISION_TIME,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    judgment = BlindJudgmentInput(
        label="UNCERTAIN",
        reason_tags=("mixed_setup",),
        confidence=2,
        note="first and only blind save",
    )
    first = service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
        judgment=judgment,
    )

    with pytest.raises(ValueError, match="already been saved"):
        service.save_blind_judgment(
            batch_id=batch.batch_id,
            blind_item_id=batch.items[0].blind_item_id,
            judgment=BlindJudgmentInput(
                label="ENTRY",
                reason_tags=("manual_review",),
                confidence=5,
                note="must not overwrite",
            ),
        )

    assert service.list_judgments(first.decision_event_id) == (first,)


def test_concurrent_duplicate_blind_save_returns_one_domain_rejection(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_duplicate_save_concurrent.db")
    setup = _setup_version(storage)
    grouping = _episode_grouping(storage, "manual_concurrent_save")
    service = EntryBlindReviewService(storage)
    service.enqueue_manual_position(
        manual_seed_id="manual_concurrent_save",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction="LONG",
        decision_time=DECISION_TIME,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    blind_item_id = batch.items[0].blind_item_id

    def save_once():
        try:
            return service.save_blind_judgment(
                batch_id=batch.batch_id,
                blind_item_id=blind_item_id,
                judgment=BlindJudgmentInput(
                    label="UNCERTAIN",
                    reason_tags=("mixed_setup",),
                    confidence=3,
                ),
            )
        except Exception as exc:  # assert the public error below
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: save_once(), range(2)))

    assert sum(not isinstance(result, Exception) for result in results) == 1
    rejected = tuple(
        result for result in results if isinstance(result, Exception)
    )
    assert len(rejected) == 1
    assert type(rejected[0]) is ValueError
    assert "already been saved" in str(rejected[0])
    saved = next(
        result for result in results if not isinstance(result, Exception)
    )
    assert len(service.list_judgments(saved.decision_event_id)) == 1


def test_batch_contains_at_most_one_seed_from_each_episode(tmp_path):
    storage = StorageManager(tmp_path / "entry_episode_isolation.db")
    setup = _setup_version(storage)
    grouping = _grouping_for_samples(
        storage,
        (
            ("overlap_a", DECISION_TIME),
            ("overlap_b", DECISION_TIME),
            ("separate", DECISION_TIME + timedelta(hours=1)),
        ),
    )
    service = EntryBlindReviewService(storage)
    for sample_id, decision_time in (
        ("overlap_a", DECISION_TIME),
        ("overlap_b", DECISION_TIME),
        ("separate", DECISION_TIME + timedelta(hours=1)),
    ):
        service.enqueue_manual_position(
            manual_seed_id=sample_id,
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            symbol="BTCUSDT",
            direction="LONG",
            decision_time=decision_time,
        )

    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    selected_ids = {
        row["decision_event_id"]
        for row in storage.fetch_table(
            "entry_review_batch_items",
            "batch_id=?",
            (batch.batch_id,),
        )
    }
    selected_episodes = [
        row["episode_id"]
        for row in storage.fetch_table("entry_decision_events")
        if row["decision_event_id"] in selected_ids
    ]

    assert len(batch.items) == 2
    assert len(selected_episodes) == len(set(selected_episodes))


def test_empty_market_data_remains_reviewable_and_does_not_invent_bars(tmp_path):
    storage = StorageManager(tmp_path / "entry_empty_charts.db")
    setup = _setup_version(storage)
    grouping = _episode_grouping(storage, "manual_empty")
    service = EntryBlindReviewService(storage)
    service.enqueue_manual_position(
        manual_seed_id="manual_empty",
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        symbol="BTCUSDT",
        direction="LONG",
        decision_time=DECISION_TIME,
    )
    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )

    assert [chart.bars for chart in item.charts] == [(), (), ()]
    saved = service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
        judgment=BlindJudgmentInput(
            label="UNCERTAIN",
            reason_tags=("data_quality_warning",),
            confidence=1,
            note="无 K 线，保留不确定判断",
        ),
    )
    assert saved.label is EntryJudgmentLabel.UNCERTAIN


def test_short_actual_open_preserves_short_direction_without_auto_label(tmp_path):
    storage = StorageManager(tmp_path / "entry_short.db")
    setup = _setup_version(storage, SetupDirection.SHORT)
    _actual_open(storage, "SHORT")
    grouping = _episode_grouping(storage)
    service = EntryBlindReviewService(storage)
    service.enqueue_actual_open(
        trade_event_id="event_open_1",
        setup_version_id=setup.setup_version_id,
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

    assert item.direction == "SHORT"
    assert item.judgment is None
    service.save_blind_judgment(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
        judgment=BlindJudgmentInput(
            label="REJECT",
            reason_tags=("risk_too_wide",),
            confidence=4,
        ),
    )
    revealed = service.reveal(
        batch_id=batch.batch_id,
        blind_item_id=item.blind_item_id,
    )
    assert revealed.original.original_action.value == "OPEN_SHORT"


def test_schema_nine_upgrades_with_backup_and_keeps_existing_rows(tmp_path):
    path = tmp_path / "schema_nine_entry_review.db"
    backup_dir = tmp_path / "backups"
    storage = StorageManager(path, backup_dir=backup_dir)
    storage.upsert_session(
        {
            "session_id": "legacy_session",
            "symbol": "ETHUSDT",
            "interval": "5m",
        }
    )
    with storage.connect() as conn:
        for table in (
            "entry_review_reveals",
            "entry_judgment_versions",
            "entry_review_batch_items",
            "entry_review_batches",
            "entry_original_actions",
            "entry_decision_events",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("PRAGMA user_version=9")

    migrated = StorageManager(path, backup_dir=backup_dir)

    assert migrated.schema_version() == StorageManager.SCHEMA_VERSION
    assert migrated.get_session("legacy_session")["symbol"] == "ETHUSDT"
    assert migrated.fetch_table("entry_decision_events") == []
    backups = list(
        backup_dir.glob(
            "quant_replay_pre_upgrade_"
            f"v9_to_v{StorageManager.SCHEMA_VERSION}_*.db"
        )
    )
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
        assert conn.execute(
            "SELECT symbol FROM sessions WHERE session_id='legacy_session'"
        ).fetchone()[0] == "ETHUSDT"


def test_concurrent_duplicate_manual_seed_creation_is_idempotent(tmp_path):
    storage = StorageManager(tmp_path / "entry_seed_concurrency.db")
    setup = _setup_version(storage)
    grouping = _episode_grouping(storage, "manual_concurrent")
    service = EntryBlindReviewService(storage)

    def enqueue():
        return service.enqueue_manual_position(
            manual_seed_id="manual_concurrent",
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            symbol="BTCUSDT",
            direction="LONG",
            decision_time=DECISION_TIME,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = tuple(executor.map(lambda _index: enqueue(), range(2)))

    assert receipts[0].decision_event_id == receipts[1].decision_event_id
    assert len(storage.fetch_table("entry_decision_events")) == 1
    assert len(storage.fetch_table("entry_original_actions")) == 1


def test_loading_a_batch_discovers_actual_open_episode_members_as_pending_seeds(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_actual_discovery.db")
    setup = _setup_version(storage)
    _actual_open(storage)
    grouping = _episode_grouping(storage)
    service = EntryBlindReviewService(storage)

    batch = service.create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
    )

    assert len(batch.items) == 1
    item = service.get_blinded_item(
        batch_id=batch.batch_id,
        blind_item_id=batch.items[0].blind_item_id,
    )
    assert item.status is ReviewStatus.PENDING_CONFIRMATION
    assert item.judgment is None


def test_actual_open_discovery_fills_from_distinct_episodes_before_batching(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_actual_distinct_episodes.db")
    setup = _setup_version(storage)
    second_episode_time = DECISION_TIME + timedelta(hours=1)
    _actual_open(storage)
    _actual_open(
        storage,
        event_id="event_open_2",
        trade_id="trade_open_2",
        decision_time=DECISION_TIME + timedelta(seconds=1),
    )
    _actual_open(
        storage,
        event_id="event_open_3",
        trade_id="trade_open_3",
        decision_time=second_episode_time,
    )
    grouping = _grouping_for_samples(
        storage,
        (
            ("event_open_1", DECISION_TIME),
            ("event_open_2", DECISION_TIME),
            ("event_open_3", second_episode_time),
        ),
    )

    batch = EntryBlindReviewService(storage).create_batch(
        setup_version_id=setup.setup_version_id,
        grouping_version_id=grouping.grouping_version_id,
        limit=2,
    )

    assert len(batch.items) == 2
