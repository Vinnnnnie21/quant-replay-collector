from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pandas as pd
import pytest

from research.market_episodes import (
    MarketEpisodeService,
    ResearchSampleWindow,
    TimeBoundary,
    TimeRange,
)
from database_backup import run_database_integrity_check
from errors import DatabaseError
from storage import StorageManager
from research.temporal_validation import build_purged_chronological_split
from research.matched_baseline import (
    MatchedBaselineSpec,
    build_match_pool,
    select_matched_controls,
    summarize_matched_baseline,
)


def _at(minute: int) -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC) + timedelta(minutes=minute)


def _sample(
    sample_id: str,
    *,
    symbol: str,
    timeframe: str,
    feature: tuple[int, int],
    outcome: tuple[int, int],
) -> ResearchSampleWindow:
    return ResearchSampleWindow(
        sample_id=sample_id,
        symbol=symbol,
        timeframe=timeframe,
        feature_window=TimeRange(_at(feature[0]), _at(feature[1])),
        outcome_window=TimeRange(_at(outcome[0]), _at(outcome[1])),
    )


def test_public_episode_service_groups_overlapping_market_windows_across_markets(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    grouping = service.create_automatic_grouping(
        (
            _sample(
                "btc_same_symbol",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(0, 10),
                outcome=(10, 20),
            ),
            _sample(
                "btc_same_symbol_overlap",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(18, 24),
                outcome=(24, 30),
            ),
            _sample(
                "eth_cross_symbol",
                symbol="ETHUSDT",
                timeframe="1m",
                feature=(29, 35),
                outcome=(35, 40),
            ),
            _sample(
                "btc_cross_timeframe_touching",
                symbol="BTCUSDT",
                timeframe="5m",
                feature=(40, 45),
                outcome=(45, 50),
            ),
            _sample(
                "fully_separate",
                symbol="SOLUSDT",
                timeframe="15m",
                feature=(60, 65),
                outcome=(65, 70),
            ),
        ),
        created_at=_at(100),
    )

    episode_by_sample = grouping.episode_id_by_sample()

    connected = {
        episode_by_sample["btc_same_symbol"],
        episode_by_sample["btc_same_symbol_overlap"],
        episode_by_sample["eth_cross_symbol"],
        episode_by_sample["btc_cross_timeframe_touching"],
    }
    assert len(connected) == 1
    assert episode_by_sample["fully_separate"] not in connected
    assert grouping.formula_version == "market_episode_interval_overlap_v1"
    assert grouping.input_range == TimeRange(
        _at(0),
        _at(70),
        end_boundary=TimeBoundary.CLOSED,
    )

    restored = service.get_grouping(grouping.grouping_version_id)

    assert restored == grouping


def test_manual_merge_creates_an_audited_version_without_rewriting_history(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    original = service.create_automatic_grouping(
        tuple(
            _sample(
                f"sample_{index}",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(index * 20, index * 20 + 5),
                outcome=(index * 20 + 5, index * 20 + 10),
            )
            for index in range(3)
        ),
        created_at=_at(100),
    )
    first_episode_id, second_episode_id, _ = (
        episode.episode_id for episode in original.episodes
    )

    corrected = service.merge_episodes(
        original.grouping_version_id,
        (first_episode_id, second_episode_id),
        actor="researcher",
        reason="同一轮市场冲击",
        created_at=_at(101),
    )

    assert corrected.grouping_version_id != original.grouping_version_id
    assert corrected.parent_grouping_version_id == original.grouping_version_id
    assert len(corrected.episodes) == 2
    assert service.get_grouping(original.grouping_version_id) == original
    audit = service.list_audit(corrected.grouping_version_id)
    assert len(audit) == 1
    assert audit[0].command_type.value == "MANUAL_MERGE"
    assert audit[0].actor == "researcher"
    assert audit[0].reason == "同一轮市场冲击"


def test_manual_split_creates_new_episode_memberships_and_keeps_the_original(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    original = service.create_automatic_grouping(
        tuple(
            _sample(
                f"sample_{index}",
                symbol="BTCUSDT" if index < 2 else "ETHUSDT",
                timeframe="1m" if index % 2 == 0 else "5m",
                feature=(index * 8, index * 8 + 10),
                outcome=(index * 8 + 10, index * 8 + 18),
            )
            for index in range(4)
        ),
        created_at=_at(100),
    )
    assert len(original.episodes) == 1

    corrected = service.split_episode(
        original.grouping_version_id,
        original.episodes[0].episode_id,
        (("sample_0", "sample_1"), ("sample_2", "sample_3")),
        actor="researcher",
        reason="审计后识别为两段驱动",
        created_at=_at(102),
    )

    assert [
        tuple(member.sample_id for member in episode.members)
        for episode in corrected.episodes
    ] == [("sample_0", "sample_1"), ("sample_2", "sample_3")]
    assert all(episode.source.value == "MANUAL_SPLIT" for episode in corrected.episodes)
    assert len(service.get_grouping(original.grouping_version_id).episodes) == 1
    assert service.list_audit(corrected.grouping_version_id)[0].command_type.value == "MANUAL_SPLIT"


def test_automatic_grouping_is_deterministic_across_input_order_and_timezones(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    utc_samples = (
        _sample(
            "sample_a",
            symbol="BTCUSDT",
            timeframe="1m",
            feature=(0, 10),
            outcome=(10, 20),
        ),
        _sample(
            "sample_b",
            symbol="ETHUSDT",
            timeframe="5m",
            feature=(19, 25),
            outcome=(25, 30),
        ),
    )
    first = service.create_automatic_grouping(utc_samples, created_at=_at(100))
    bjt = timezone(timedelta(hours=8))
    equivalent_reversed = tuple(
        ResearchSampleWindow(
            sample_id=sample.sample_id,
            symbol=sample.symbol,
            timeframe=sample.timeframe,
            feature_window=TimeRange(
                sample.feature_window.start.astimezone(bjt),
                sample.feature_window.end.astimezone(bjt),
            ),
            outcome_window=TimeRange(
                sample.outcome_window.start.astimezone(bjt),
                sample.outcome_window.end.astimezone(bjt),
            ),
        )
        for sample in reversed(utc_samples)
    )

    repeated = service.create_automatic_grouping(
        equivalent_reversed,
        created_at=_at(101),
    )

    assert repeated == first
    assert service.get_grouping(first.grouping_version_id) == first


def test_public_audit_summary_reports_episode_composition_and_source(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    grouping = service.create_automatic_grouping(
        (
            _sample(
                "btc",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(0, 10),
                outcome=(10, 20),
            ),
            _sample(
                "eth",
                symbol="ETHUSDT",
                timeframe="5m",
                feature=(15, 25),
                outcome=(25, 30),
            ),
            _sample(
                "sol",
                symbol="SOLUSDT",
                timeframe="15m",
                feature=(60, 65),
                outcome=(65, 70),
            ),
        ),
        created_at=_at(100),
    )

    summary = service.audit_summary(grouping.grouping_version_id)

    assert summary.episode_count == 2
    assert summary.sample_count == 3
    assert summary.grouping_source.value == "AUTOMATIC"
    assert summary.can_correct is True
    assert summary.composition[0].symbols == ("BTCUSDT", "ETHUSDT")
    assert summary.composition[0].timeframes == ("1m", "5m")
    assert summary.composition[0].source.value == "AUTOMATIC"


def test_schema_integrity_requires_all_episode_audit_tables(tmp_path):
    path = tmp_path / "incomplete_episode_schema.db"
    storage = StorageManager(path)
    with storage.connect() as conn:
        conn.execute("DROP TABLE market_episode_audit")

    report = run_database_integrity_check(
        path,
        expected_schema_version=StorageManager.SCHEMA_VERSION,
    )

    assert report["migration_status"] == "incomplete_schema"
    assert report["missing_required_tables"] == ["market_episode_audit"]


def test_public_resolver_is_the_single_episode_lookup_for_downstream_consumers(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    grouping = service.create_automatic_grouping(
        (
            _sample(
                "sample_a",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(0, 10),
                outcome=(10, 20),
            ),
            _sample(
                "sample_b",
                symbol="ETHUSDT",
                timeframe="5m",
                feature=(15, 25),
                outcome=(25, 30),
            ),
        ),
        created_at=_at(100),
    )

    resolved = service.resolve_episode_ids(
        grouping.grouping_version_id,
        ("sample_b", "sample_a"),
    )

    assert tuple(item.sample_id for item in resolved) == ("sample_b", "sample_a")
    assert len({item.episode_id for item in resolved}) == 1
    assert all(
        item.grouping_version_id == grouping.grouping_version_id
        for item in resolved
    )


def test_training_split_consumes_the_persisted_episode_version(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    samples = tuple(
        _sample(
            f"sample_{index}",
            symbol="BTCUSDT" if index % 2 == 0 else "ETHUSDT",
            timeframe="1m" if index < 3 else "5m",
            feature=(index * 20, index * 20 + 5),
            outcome=(index * 20 + 5, index * 20 + 10),
        )
        for index in range(8)
    )
    grouping = service.create_automatic_grouping(samples, created_at=_at(200))
    frame = pd.DataFrame(
        {
            "observation_id": [sample.sample_id for sample in samples],
            "bar_index": list(range(8)),
        }
    )

    split = build_purged_chronological_split(
        frame,
        train_ratio=0.5,
        validation_ratio=0.25,
        test_ratio=0.25,
        horizon_bars=1,
        episode_service=service,
        episode_grouping_version_id=grouping.grouping_version_id,
    )

    combined = pd.concat([split.train, split.validation, split.test])
    expected = grouping.episode_id_by_sample()
    assert dict(zip(combined["observation_id"], combined["episode_id"])) == {
        sample_id: expected[sample_id]
        for sample_id in combined["observation_id"]
    }
    assert split.summary["episode_grouping_version_id"] == grouping.grouping_version_id


def test_matching_excludes_controls_from_the_same_persisted_episode(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    grouping = service.create_automatic_grouping(
        (
            _sample(
                "user",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(0, 10),
                outcome=(10, 20),
            ),
            _sample(
                "same_episode",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(15, 25),
                outcome=(25, 30),
            ),
            _sample(
                "independent_episode",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(60, 70),
                outcome=(70, 80),
            ),
        ),
        created_at=_at(100),
    )
    observations = pd.DataFrame(
        [
            {
                "sample_id": "user",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "user_action": "OPEN_LONG",
                "source_type": "USER_TRADE",
                "is_user_trade": 1,
            },
            *(
                {
                    "sample_id": sample_id,
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "user_action": "NO_ACTION",
                    "source_type": "SCHEDULED_BAR",
                    "is_user_trade": 0,
                }
                for sample_id in ("same_episode", "independent_episode")
            ),
        ]
    )
    context = pd.DataFrame(
        [
            {
                "sample_id": sample_id,
                "feature_name": "pre_ret_20",
                "feature_value": value,
            }
            for sample_id, value in (
                ("user", 0.10),
                ("same_episode", 0.11),
                ("independent_episode", 0.12),
            )
        ]
    )
    pool = build_match_pool(observations, context)

    matches = select_matched_controls(
        "user",
        pool,
        MatchedBaselineSpec(
            controls_per_sample=2,
            numeric_features=("pre_ret_20",),
        ),
        episode_service=service,
        episode_grouping_version_id=grouping.grouping_version_id,
    )

    assert matches["control_sample_id"].tolist() == ["independent_episode"]
    assert matches["episode_grouping_version_id"].tolist() == [
        grouping.grouping_version_id
    ]


def test_blind_review_batches_take_at_most_one_sample_from_each_episode(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    grouping = service.create_automatic_grouping(
        (
            _sample(
                "episode_a_1",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(0, 10),
                outcome=(10, 20),
            ),
            _sample(
                "episode_a_2",
                symbol="ETHUSDT",
                timeframe="5m",
                feature=(15, 25),
                outcome=(25, 30),
            ),
            _sample(
                "episode_b_1",
                symbol="SOLUSDT",
                timeframe="1m",
                feature=(60, 70),
                outcome=(70, 80),
            ),
            _sample(
                "episode_b_2",
                symbol="BTCUSDT",
                timeframe="15m",
                feature=(75, 85),
                outcome=(85, 90),
            ),
        ),
        created_at=_at(100),
    )

    batches = service.build_isolated_batches(
        grouping.grouping_version_id,
        ("episode_a_1", "episode_a_2", "episode_b_1", "episode_b_2"),
        batch_size=2,
    )

    assert [batch.sample_ids for batch in batches] == [
        ("episode_a_1", "episode_b_1"),
        ("episode_a_2", "episode_b_2"),
    ]
    assert all(batch.grouping_version_id == grouping.grouping_version_id for batch in batches)


def test_matched_baseline_summary_resolves_episode_membership_once(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    grouping = service.create_automatic_grouping(
        tuple(
            _sample(
                sample_id,
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(index * 30, index * 30 + 5),
                outcome=(index * 30 + 5, index * 30 + 10),
            )
            for index, sample_id in enumerate(
                ("user_1", "user_2", "control_1", "control_2")
            )
        ),
        created_at=_at(200),
    )

    class CountingResolver:
        def __init__(self):
            self.call_count = 0

        def resolve_episode_ids(self, grouping_version_id, sample_ids):
            self.call_count += 1
            return service.resolve_episode_ids(grouping_version_id, sample_ids)

    resolver = CountingResolver()
    observations = pd.DataFrame(
        [
            {
                "sample_id": sample_id,
                "symbol": "BTCUSDT",
                "interval": "1m",
                "user_action": "OPEN_LONG" if sample_id.startswith("user") else "NO_ACTION",
                "source_type": "USER_TRADE" if sample_id.startswith("user") else "SCHEDULED_BAR",
                "is_user_trade": int(sample_id.startswith("user")),
            }
            for sample_id in ("user_1", "user_2", "control_1", "control_2")
        ]
    )
    context = pd.DataFrame(
        [
            {
                "sample_id": sample_id,
                "feature_name": "pre_ret_20",
                "feature_value": value,
            }
            for sample_id, value in (
                ("user_1", 0.10),
                ("user_2", 0.11),
                ("control_1", 0.12),
                ("control_2", 0.13),
            )
        ]
    )
    outcomes = pd.DataFrame(
        [
            {"sample_id": sample_id, "fwd_ret": value}
            for sample_id, value in (
                ("user_1", 0.02),
                ("user_2", 0.01),
                ("control_1", -0.01),
                ("control_2", 0.00),
            )
        ]
    )

    summarize_matched_baseline(
        observations,
        context,
        outcomes,
        MatchedBaselineSpec(
            controls_per_sample=2,
            numeric_features=("pre_ret_20",),
        ),
        n_bootstrap=10,
        n_permutations=10,
        episode_service=resolver,
        episode_grouping_version_id=grouping.grouping_version_id,
    )

    assert resolver.call_count == 1


def test_time_boundary_semantics_distinguish_closed_touching_from_open_touching(tmp_path):
    service = MarketEpisodeService(StorageManager(tmp_path / "episodes.db"))
    closed = service.create_automatic_grouping(
        (
            _sample(
                "closed_left",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(0, 10),
                outcome=(10, 20),
            ),
            _sample(
                "closed_right",
                symbol="ETHUSDT",
                timeframe="5m",
                feature=(20, 25),
                outcome=(25, 30),
            ),
        ),
        created_at=_at(100),
    )
    open_touching = service.create_automatic_grouping(
        (
            ResearchSampleWindow(
                sample_id="open_left",
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(_at(0), _at(10)),
                outcome_window=TimeRange(
                    _at(10),
                    _at(20),
                    end_boundary=TimeBoundary.OPEN,
                ),
            ),
            _sample(
                "open_right",
                symbol="ETHUSDT",
                timeframe="5m",
                feature=(20, 25),
                outcome=(25, 30),
            ),
        ),
        created_at=_at(101),
    )

    assert len(closed.episodes) == 1
    assert len(open_touching.episodes) == 2


def test_manual_correction_rolls_back_version_and_audit_together(tmp_path):
    storage = StorageManager(tmp_path / "episodes.db")
    service = MarketEpisodeService(storage)
    grouping = service.create_automatic_grouping(
        (
            _sample(
                "left",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(0, 5),
                outcome=(5, 10),
            ),
            _sample(
                "right",
                symbol="ETHUSDT",
                timeframe="5m",
                feature=(30, 35),
                outcome=(35, 40),
            ),
        ),
        created_at=_at(100),
    )
    with storage.connect() as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_episode_audit
            BEFORE INSERT ON market_episode_audit
            BEGIN
                SELECT RAISE(ABORT, 'audit write failed');
            END
            """
        )

    with pytest.raises(DatabaseError, match="audit write failed"):
        service.merge_episodes(
            grouping.grouping_version_id,
            tuple(episode.episode_id for episode in grouping.episodes),
            actor="researcher",
            reason="transaction test",
            created_at=_at(101),
        )

    with storage.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM episode_grouping_versions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM market_episode_audit").fetchone()[0] == 0


def test_schema_8_upgrades_with_backup_and_preserves_existing_rows(tmp_path):
    path = tmp_path / "schema8.db"
    backup_dir = tmp_path / "backups"
    storage = StorageManager(path, backup_dir=backup_dir)
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO setups (
                setup_id, display_name, is_archived, created_at,
                updated_at, archived_at, creation_token
            ) VALUES ('legacy_setup', 'Legacy', 0, '2026-01-01T00:00:00+00:00',
                      '2026-01-01T00:00:00+00:00', NULL, 'legacy_token')
            """
        )
        conn.execute("DROP TABLE market_episode_audit")
        conn.execute("DROP TABLE market_episode_memberships")
        conn.execute("DROP TABLE market_episodes")
        conn.execute("DROP TABLE episode_grouping_versions")
        conn.execute("PRAGMA user_version=8")

    upgraded = StorageManager(path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.fetch_table("setups", "setup_id=?", ("legacy_setup",))[0]["display_name"] == "Legacy"
    backups = tuple(
        backup_dir.glob(
            "quant_replay_pre_upgrade_"
            f"v8_to_v{StorageManager.SCHEMA_VERSION}_*.db"
        )
    )
    assert len(backups) == 1


def test_time_range_normalizes_machine_boundary_values_and_rejects_unknown_values():
    normalized = TimeRange(
        _at(0),
        _at(1),
        start_boundary="CLOSED",
        end_boundary="OPEN",
    )

    assert normalized.start_boundary is TimeBoundary.CLOSED
    assert normalized.end_boundary is TimeBoundary.OPEN
    with pytest.raises(ValueError):
        TimeRange(_at(0), _at(1), end_boundary="INCLUSIVE")


def test_audit_history_follows_immutable_parent_versions(tmp_path):
    storage = StorageManager(tmp_path / "episodes.db")

    class CountingStorage:
        def __init__(self):
            self.audit_read_count = 0

        def __getattr__(self, name):
            return getattr(storage, name)

        def list_episode_audit(self, grouping_version_id):
            self.audit_read_count += 1
            return storage.list_episode_audit(grouping_version_id)

    counting_storage = CountingStorage()
    service = MarketEpisodeService(counting_storage)
    automatic = service.create_automatic_grouping(
        tuple(
            _sample(
                f"sample_{index}",
                symbol="BTCUSDT",
                timeframe="1m",
                feature=(index * 20, index * 20 + 5),
                outcome=(index * 20 + 5, index * 20 + 10),
            )
            for index in range(3)
        ),
        created_at=_at(100),
    )
    merged = service.merge_episodes(
        automatic.grouping_version_id,
        tuple(episode.episode_id for episode in automatic.episodes[:2]),
        actor="researcher",
        reason="merge",
        created_at=_at(101),
    )
    merged_episode = next(
        episode
        for episode in merged.episodes
        if episode.source.value == "MANUAL_MERGE"
    )
    split = service.split_episode(
        merged.grouping_version_id,
        merged_episode.episode_id,
        (("sample_0",), ("sample_1",)),
        actor="reviewer",
        reason="split",
        created_at=_at(102),
    )

    counting_storage.audit_read_count = 0
    history = service.list_audit(split.grouping_version_id)

    assert [item.command_type.value for item in history] == [
        "MANUAL_MERGE",
        "MANUAL_SPLIT",
    ]
    assert counting_storage.audit_read_count == 1
    assert service.get_grouping(automatic.grouping_version_id) == automatic
