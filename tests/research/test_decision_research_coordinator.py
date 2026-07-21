from __future__ import annotations

from datetime import UTC, datetime

from research.setups import (
    CreateSetup,
    DecisionProtocol,
    SetupDirection,
    SetupLibrary,
    SetupVersionSpec,
    TimeframeProfile,
)
from storage import StorageManager


def _setup(storage: StorageManager):
    return SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="回踩确认",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="收盘确认后判断",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    )


def _observation(sample_id: str, setup_version_id: str, event_time: str):
    return {
        "sample_id": sample_id,
        "session_id": "session-coordinator",
        "profile_id": setup_version_id,
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
        "created_at": "2026-06-01T00:00:00+00:00",
    }


def test_coordinator_idempotently_builds_episode_context_for_public_storage(tmp_path):
    from services.decision_research_coordinator import (
        DecisionResearchCoordinator,
        DecisionResearchRequest,
    )

    storage = StorageManager(tmp_path / "coordinator.db")
    created = _setup(storage)
    version_id = created.version.setup_version_id
    storage.save_observation_sample(
        _observation("sample-a", version_id, "2026-06-01T08:00:00+08:00")
    )
    storage.save_observation_sample(
        _observation("sample-b", version_id, "2026-06-01T08:10:00+08:00")
    )
    request = DecisionResearchRequest(
        session_id="session-coordinator",
        setup_version_id=version_id,
        mode="entry",
        symbol="BTCUSDT",
        timeframes=("1m", "5m", "15m"),
        start_time_utc_ms=0,
        end_time_utc_ms=2_000_000_000_000,
    )
    coordinator = DecisionResearchCoordinator(storage)

    first = coordinator.open(request, now=datetime(2026, 6, 1, tzinfo=UTC))
    second = coordinator.open(request, now=datetime(2026, 6, 2, tzinfo=UTC))

    assert first.status == "ready"
    assert first.grouping_version_id is not None
    assert first.episode_summary is not None
    assert first.episode_summary.sample_count == 2
    assert second.grouping_version_id == first.grouping_version_id
    assert coordinator.is_current(second.revision)
    assert not coordinator.is_current(first.revision)


def test_coordinator_includes_actual_open_events_in_entry_episode_context(tmp_path):
    from services.decision_research_coordinator import (
        DecisionResearchCoordinator,
        DecisionResearchRequest,
    )

    storage = StorageManager(tmp_path / "actual-open.db")
    created = _setup(storage)
    version_id = created.version.setup_version_id
    storage.insert_event(
        {
            "event_id": "actual-open",
            "session_id": "session-coordinator",
            "trade_id": "trade-open",
            "event_type": "OPEN",
            "side": "LONG",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "bar_index": 10,
            "bar_open_time_bjt": "2026-06-01T08:10:00+08:00",
            "real_key_time_bjt": "2026-06-01T08:10:30+08:00",
            "price_proxy": 100.0,
            "label_tags": [],
            "note": "",
            "created_at": "2026-06-01T00:10:30+00:00",
        }
    )
    request = DecisionResearchRequest(
        session_id="session-coordinator",
        setup_version_id=version_id,
        mode="entry",
        symbol="BTCUSDT",
        timeframes=("1m", "5m", "15m"),
        start_time_utc_ms=0,
        end_time_utc_ms=2_000_000_000_000,
    )

    context = DecisionResearchCoordinator(storage).open(
        request,
        now=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert context.status == "ready"
    assert context.sample_count == 1
    assert context.episode_summary is not None
    assert context.episode_summary.composition[0].sample_ids == (
        "actual-open",
    )


def test_coordinator_uses_replay_market_time_for_a_historical_actual_open(tmp_path):
    from services.decision_research_coordinator import (
        DecisionResearchCoordinator,
        DecisionResearchRequest,
    )

    storage = StorageManager(tmp_path / "historical-actual-open.db")
    version_id = _setup(storage).version.setup_version_id
    storage.insert_event(
        {
            "event_id": "historical-open",
            "session_id": "session-coordinator",
            "trade_id": "trade-historical-open",
            "event_type": "OPEN",
            "side": "LONG",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "bar_index": 10,
            "bar_open_time_bjt": "2026-06-01T08:10:00+08:00",
            "real_key_time_bjt": "2026-07-20T12:00:00+08:00",
            "price_proxy": 100.0,
            "label_tags": [],
            "note": "",
            "created_at": "2026-07-20T04:00:00+00:00",
        }
    )
    start = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp() * 1_000)
    end = int(datetime(2026, 6, 2, tzinfo=UTC).timestamp() * 1_000)

    context = DecisionResearchCoordinator(storage).open(
        DecisionResearchRequest(
            session_id="session-coordinator",
            setup_version_id=version_id,
            mode="entry",
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start,
            end_time_utc_ms=end,
        )
    )

    assert context.status == "ready"
    assert context.sample_count == 1
    assert context.episode_summary.composition[0].sample_ids == (
        "historical-open",
    )


def test_coordinator_includes_actual_close_events_only_in_exit_context(tmp_path):
    from services.decision_research_coordinator import (
        DecisionResearchCoordinator,
        DecisionResearchRequest,
    )

    storage = StorageManager(tmp_path / "actual-close.db")
    version_id = _setup(storage).version.setup_version_id
    storage.insert_event(
        {
            "event_id": "actual-close",
            "session_id": "session-coordinator",
            "trade_id": "trade-close",
            "event_type": "CLOSE",
            "side": "LONG",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "bar_index": 20,
            "bar_open_time_bjt": "2026-06-01T08:20:00+08:00",
            "real_key_time_bjt": "2026-06-01T08:20:30+08:00",
            "price_proxy": 101.0,
            "label_tags": [],
            "note": "",
            "created_at": "2026-06-01T00:20:30+00:00",
        }
    )
    base = {
        "session_id": "session-coordinator",
        "setup_version_id": version_id,
        "symbol": "BTCUSDT",
        "timeframes": ("1m", "5m", "15m"),
        "start_time_utc_ms": 0,
        "end_time_utc_ms": 2_000_000_000_000,
    }
    coordinator = DecisionResearchCoordinator(storage)

    entry = coordinator.open(DecisionResearchRequest(mode="entry", **base))
    exit_context = coordinator.open(DecisionResearchRequest(mode="exit", **base))

    assert entry.status == "empty"
    assert exit_context.status == "ready"
    assert exit_context.episode_summary is not None
    assert exit_context.episode_summary.composition[0].sample_ids == (
        "actual-close",
    )


def test_coordinator_correction_creates_new_immutable_grouping_version(tmp_path):
    from services.decision_research_coordinator import (
        DecisionResearchCoordinator,
        DecisionResearchRequest,
    )

    storage = StorageManager(tmp_path / "correction.db")
    created = _setup(storage)
    version_id = created.version.setup_version_id
    storage.save_observation_sample(
        _observation("early", version_id, "2026-06-01T08:00:00+08:00")
    )
    storage.save_observation_sample(
        _observation("late", version_id, "2026-06-01T12:00:00+08:00")
    )
    request = DecisionResearchRequest(
        session_id="session-coordinator",
        setup_version_id=version_id,
        mode="entry",
        symbol="BTCUSDT",
        timeframes=("1m", "5m", "15m"),
        start_time_utc_ms=0,
        end_time_utc_ms=2_000_000_000_000,
    )
    coordinator = DecisionResearchCoordinator(storage)
    original = coordinator.open(request, now=datetime(2026, 6, 1, tzinfo=UTC))
    episode_ids = tuple(
        item.episode_id for item in original.episode_summary.composition
    )

    corrected = coordinator.merge_episodes(
        original,
        episode_ids,
        actor="user",
        reason="人工确认属于同一行情",
        now=datetime(2026, 6, 2, tzinfo=UTC),
    )

    assert corrected.grouping_version_id != original.grouping_version_id
    assert corrected.episode_summary.episode_count == 1
    assert storage.get_episode_grouping(original.grouping_version_id) is not None
    assert storage.get_episode_grouping(corrected.grouping_version_id) is not None
    assert coordinator.is_current(corrected.revision)
