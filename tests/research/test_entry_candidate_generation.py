from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import json

import pytest

from research.market_episodes import (
    MarketEpisodeService,
    ResearchSampleWindow,
    TimeRange,
)
from research.observation_universe import create_auto_candidate_observation
from research.setups import (
    CreateSetup,
    DecisionProtocol,
    SetupDirection,
    SetupLibrary,
    SetupVersionSpec,
    TimeframeProfile,
)
from services.entry_blind_review import EntryBlindReviewService
from services.entry_candidate_generation import (
    CandidateScanRequest,
    CandidateScanStatus,
    EntryCandidateGenerationService,
)
from research.entry_candidate_generation import (
    CandidateReference,
    CandidateScanCancelled,
    CandidateSimilarityDistribution,
    EntryCandidateScore,
    candidate_similarity_distribution,
    select_formal_candidate_batch,
)
from storage import StorageManager
from errors import DatabaseError


BASE_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def test_public_scan_scores_only_deterministic_observation_candidates_without_outcomes(
    tmp_path,
):
    storage = StorageManager(tmp_path / "entry_candidates.db")
    setup = _setup_version(storage)
    reference_times = tuple(BASE_TIME + timedelta(days=index * 2) for index in range(10))
    candidate_times = (
        BASE_TIME + timedelta(days=22),
        BASE_TIME + timedelta(days=24),
    )
    candidates = tuple(
        create_auto_candidate_observation(
            session_id="candidate_session",
            profile_id=setup.setup_version_id,
            symbol="BTCUSDT",
            interval="1m",
            bar_index=10_000 + index,
            event_time_bjt=(cutoff - timedelta(minutes=1)).isoformat(),
            created_at=cutoff.isoformat(),
        )
        for index, cutoff in enumerate(candidate_times)
    )
    for row in candidates:
        storage.save_observation_sample(row)

    grouping = _grouping(
        storage,
        tuple(
            (f"reference_{index}", cutoff)
            for index, cutoff in enumerate(reference_times)
        )
        + tuple(
            (str(row["sample_id"]), cutoff)
            for row, cutoff in zip(candidates, candidate_times, strict=True)
        ),
    )
    _confirm_entry_references(
        storage,
        setup.setup_version_id,
        grouping.grouping_version_id,
        reference_times,
    )
    for index, cutoff in enumerate((*reference_times, *candidate_times)):
        _store_complete_history(storage, cutoff, price_offset=float(index % 2))

    # A persisted outcome for a candidate must stay outside the candidate service.
    storage.save_research_outcome_label(
        {
            "outcome_label_id": "forbidden_outcome",
            "sample_id": candidates[0]["sample_id"],
            "session_id": "candidate_session",
            "label_version": "outcome_v1",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "bar_index": candidates[0]["bar_index"],
            "horizon_bars": 5,
            "pricing_basis": "next_open",
            "fwd_ret": 999.0,
            "mfe": 999.0,
            "mae": -999.0,
            "hit_tp": 1,
            "hit_sl": 0,
            "r_multiple": 999.0,
            "insufficient_future_bars": 0,
            "pricing_note": "must never enter candidate retrieval",
            "created_at": BASE_TIME.isoformat(),
        }
    )

    service = EntryCandidateGenerationService(storage)
    result = service.scan(
        CandidateScanRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.status is CandidateScanStatus.COMPLETED
    assert {item.source_sample_id for item in result.candidates} == {
        str(row["sample_id"]) for row in candidates
    }
    assert all(len(item.references) == 3 for item in result.candidates)
    assert all(item.similarity is not None for item in result.candidates)
    assert service.get_scan(result.scan_id) == result
    cancel_at_last_progress = {"requested": False}
    with pytest.raises(CandidateScanCancelled):
        service.scan(
            CandidateScanRequest(
                setup_version_id=setup.setup_version_id,
                grouping_version_id=grouping.grouping_version_id,
                direction="LONG",
            ),
            cancelled=lambda: cancel_at_last_progress["requested"],
            progress=lambda done, total: cancel_at_last_progress.__setitem__(
                "requested",
                done == total,
            ),
        )
    assert len(storage.fetch_table("entry_candidate_scans")) == 1
    formal = service.create_blind_review_batch(scan_id=result.scan_id, limit=1)
    assert formal.high_similarity_count == 1
    assert formal.diverse_count == 0
    assert len(formal.batch.items) == 1
    with pytest.raises(DatabaseError, match="immutable"):
        with storage.connect() as conn:
            conn.execute(
                """
                UPDATE entry_candidate_batch_items
                SET selection_reason='STRUCTURAL_DIVERSITY'
                WHERE batch_id=?
                """,
                (formal.batch.batch_id,),
            )
    blind_review = EntryBlindReviewService(storage)
    blind_item = blind_review.get_blinded_item(
        batch_id=formal.batch.batch_id,
        blind_item_id=formal.batch.items[0].blind_item_id,
    )
    expected_cutoff_by_sample = {
        str(candidate["sample_id"]): cutoff
        for candidate, cutoff in zip(candidates, candidate_times, strict=True)
    }
    assert blind_item.decision_cutoff_utc_ms == int(
        expected_cutoff_by_sample[
            result.candidates[0].source_sample_id
        ].timestamp()
        * 1_000
    )
    blind_payload = json.dumps(asdict(blind_item), ensure_ascii=False).lower()
    assert not any(
        token in blind_payload
        for token in ("similarity", "reference", "enqueue_reason", "candidate_source")
    )
    from research.entry_blind_review import BlindJudgmentInput, EntryJudgmentLabel

    with pytest.raises(PermissionError, match="blind judgment"):
        blind_review.get_candidate_audit_after_judgment(
            blind_item.decision_event_id
        )

    saved_judgment = blind_review.save_blind_judgment(
        batch_id=formal.batch.batch_id,
        blind_item_id=formal.batch.items[0].blind_item_id,
        judgment=BlindJudgmentInput(
            label=EntryJudgmentLabel.REJECT,
            reason_tags=("long_lower_shadow",),
            confidence=3,
        ),
    )
    assert saved_judgment.eligible_for_primary_research is True
    unlocked = blind_review.get_candidate_audit_after_judgment(
        blind_item.decision_event_id
    )
    assert unlocked is not None
    assert len(unlocked.group_distances) == 12
    assert len(unlocked.references) == 3
    assert unlocked.enqueue_reason == "STRUCTURAL_SIMILARITY"
    assert unlocked.selection_reason == "HIGH_SIMILARITY"
    revealed = blind_review.reveal(
        batch_id=formal.batch.batch_id,
        blind_item_id=formal.batch.items[0].blind_item_id,
    )
    assert revealed.candidate_audit is not None
    assert len(revealed.candidate_audit.references) == 3
    assert revealed.candidate_audit.enqueue_reason == "STRUCTURAL_SIMILARITY"

    exposed_batch = service.create_blind_review_batch(
        scan_id=result.scan_id,
        limit=1,
    )
    exposed_item = blind_review.get_blinded_item(
        batch_id=exposed_batch.batch.batch_id,
        blind_item_id=exposed_batch.batch.items[0].blind_item_id,
    )
    exposed = service.reveal_candidate_in_free_browse(
        scan_id=result.scan_id,
        source_sample_id=result.candidates[1].source_sample_id,
    )
    assert exposed.source_sample_id == result.candidates[1].source_sample_id
    with pytest.raises(PermissionError, match="revealed in free browse"):
        blind_review.save_blind_judgment(
            batch_id=exposed_batch.batch.batch_id,
            blind_item_id=exposed_batch.batch.items[0].blind_item_id,
            judgment=BlindJudgmentInput(
                label=EntryJudgmentLabel.REJECT,
                reason_tags=("long_lower_shadow",),
                confidence=3,
            ),
        )
    assert blind_review.list_primary_research_judgments(
        exposed_item.decision_event_id
    ) == ()
    with pytest.raises(ValueError, match="no eligible candidates"):
        service.create_blind_review_batch(scan_id=result.scan_id, limit=2)
    payload = json.dumps(asdict(result), ensure_ascii=False).lower()
    assert "999.0" not in payload
    assert not any(
        token in payload
        for token in ("fwd_ret", "mfe", "mae", "hit_tp", "hit_sl", "pricing_note")
    )


def test_maturity_gate_reports_exact_entry_and_episode_deficits(tmp_path):
    storage = StorageManager(tmp_path / "entry_candidate_maturity.db")
    setup = _setup_version(storage)
    candidate = create_auto_candidate_observation(
        session_id="candidate_session",
        profile_id=setup.setup_version_id,
        symbol="BTCUSDT",
        interval="1m",
        bar_index=1,
        event_time_bjt=BASE_TIME.isoformat(),
        created_at=BASE_TIME.isoformat(),
    )
    storage.save_observation_sample(candidate)
    grouping = _grouping(storage, ((str(candidate["sample_id"]), BASE_TIME),))

    result = EntryCandidateGenerationService(storage).scan(
        CandidateScanRequest(
            setup_version_id=setup.setup_version_id,
            grouping_version_id=grouping.grouping_version_id,
            direction="LONG",
        )
    )

    assert result.status is CandidateScanStatus.NOT_READY
    assert result.maturity.missing_entry_count == 10
    assert result.maturity.missing_episode_count == 5
    assert result.candidate_universe_count == 1
    assert result.candidates == ()


def test_pre_behavior_batch_is_deterministic_seventy_thirty_and_episode_isolated():
    reference = CandidateReference("entry_ref", "reference_episode", 80.0)
    candidates = tuple(
        EntryCandidateScore(
            source_sample_id=f"candidate_{index:02d}",
            episode_id=f"episode_{index:02d}",
            similarity=90.0 - index,
            references=(reference, reference, reference),
            completeness_ratio=1.0,
            diversity_vector=(float(index % 5), float(index // 5)),
        )
        for index in range(25)
    )

    first = select_formal_candidate_batch(candidates, limit=20)
    second = select_formal_candidate_batch(tuple(reversed(candidates)), limit=20)

    assert first == second
    assert len(first) == 20
    assert sum(item.selection_reason == "HIGH_SIMILARITY" for item in first) == 14
    assert sum(item.selection_reason == "STRUCTURAL_DIVERSITY" for item in first) == 6
    assert len({item.candidate.episode_id for item in first}) == 20
    assert [item.selection_reason for item in first] != (
        ["HIGH_SIMILARITY"] * 14 + ["STRUCTURAL_DIVERSITY"] * 6
    )


def test_batch_selection_ties_and_empty_results_are_deterministic():
    reference = CandidateReference("entry_ref", "reference_episode", 80.0)
    tied = tuple(
        EntryCandidateScore(
            source_sample_id=sample_id,
            episode_id=f"episode_{sample_id}",
            similarity=75.0,
            references=(reference, reference, reference),
            completeness_ratio=1.0,
            diversity_vector=(1.0, 2.0),
        )
        for sample_id in ("c", "a", "b")
    )

    selected = select_formal_candidate_batch(tied, limit=3)

    assert [item.candidate.source_sample_id for item in selected[:3]] == [
        "a",
        "b",
        "c",
    ]
    assert select_formal_candidate_batch((), limit=20) == ()


def test_aggregate_score_distribution_has_stable_boundary_bins():
    reference = CandidateReference("ref", "ref_episode", 90.0)

    def candidate(identity: str, score: float) -> EntryCandidateScore:
        return EntryCandidateScore(
            source_sample_id=identity,
            episode_id=f"episode_{identity}",
            similarity=score,
            references=(reference,) * 3,
            completeness_ratio=1.0,
            diversity_vector=(0.1,) * 12,
        )

    distribution = candidate_similarity_distribution(
        (
            candidate("at_80", 80.0),
            candidate("at_60", 60.0),
            candidate("below_60", 59.999),
        )
    )

    assert distribution == CandidateSimilarityDistribution(
        score_80_to_100=1,
        score_60_to_under_80=1,
        score_0_to_under_60=1,
    )


def test_schema_11_upgrade_adds_candidate_audit_tables_and_backup(tmp_path):
    db_path = tmp_path / "schema_11_candidates.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(db_path, backup_dir=backup_dir)
    with legacy.connect() as conn:
        conn.executescript(
            """
            DROP TABLE entry_candidate_exclusions;
            DROP TABLE entry_candidate_batch_items;
            DROP TABLE entry_candidate_batches;
            DROP TABLE entry_candidate_scores;
            DROP TABLE entry_candidate_scans;
            PRAGMA user_version=11;
            """
        )

    upgraded = StorageManager(db_path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.fetch_table("entry_candidate_scans") == []
    assert list(
        backup_dir.glob(f"*v11_to_v{StorageManager.SCHEMA_VERSION}*.db")
    )


def _setup_version(storage: StorageManager):
    return SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="正式候选测试",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="只比较决策截止点及以前的结构。",
                timeframes=TimeframeProfile("1m", "5m", "15m"),
            ),
        )
    ).version


def _grouping(storage: StorageManager, samples: tuple[tuple[str, datetime], ...]):
    return MarketEpisodeService(storage).create_automatic_grouping(
        tuple(
            ResearchSampleWindow(
                sample_id=sample_id,
                symbol="BTCUSDT",
                timeframe="1m",
                feature_window=TimeRange(
                    cutoff - timedelta(hours=16),
                    cutoff,
                ),
                outcome_window=TimeRange(
                    cutoff,
                    cutoff + timedelta(minutes=20),
                ),
            )
            for sample_id, cutoff in samples
        ),
        created_at=BASE_TIME,
    )


def _confirm_entry_references(
    storage: StorageManager,
    setup_version_id: str,
    grouping_version_id: str,
    reference_times: tuple[datetime, ...],
) -> None:
    review = EntryBlindReviewService(storage)
    for index, cutoff in enumerate(reference_times):
        review.enqueue_manual_position(
            manual_seed_id=f"reference_{index}",
            setup_version_id=setup_version_id,
            grouping_version_id=grouping_version_id,
            symbol="BTCUSDT",
            direction="LONG",
            decision_time=cutoff,
        )
    batch = review.create_batch(
        setup_version_id=setup_version_id,
        grouping_version_id=grouping_version_id,
    )
    from research.entry_blind_review import BlindJudgmentInput, EntryJudgmentLabel

    for item in batch.items:
        review.save_blind_judgment(
            batch_id=batch.batch_id,
            blind_item_id=item.blind_item_id,
            judgment=BlindJudgmentInput(
                label=EntryJudgmentLabel.ENTRY,
                reason_tags=("long_lower_shadow",),
                confidence=3,
            ),
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
        for index in range(62):
            close_time = cutoff - duration * (61 - index)
            open_time = close_time - duration
            close = 100.0 + price_offset + index * 0.05
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
