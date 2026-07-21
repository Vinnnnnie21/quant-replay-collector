from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
import csv
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
import services.research_snapshots as research_snapshot_service_module

from research.research_snapshot import (
    HypothesisCard,
    HypothesisStatus,
    ResearchSnapshotContent,
    ResearchSnapshotInput,
    PublishedResearchSnapshot,
    ResearchSnapshotValidationError,
    ResearchSnapshotVersions,
    build_research_snapshot_draft,
    snapshot_manifest_as_dict,
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
from services.research_snapshots import (
    ResearchSnapshotCancelled,
    ResearchSnapshotIntegrityError,
    ResearchSnapshotReferenceError,
    ResearchSnapshotService,
)
from storage import StorageManager
from export_publish import ExportDirectoryPublisher


def _snapshot_input() -> ResearchSnapshotInput:
    return ResearchSnapshotInput(
        versions=ResearchSnapshotVersions(
            setup_version_id="setup-version-1",
            direction="LONG",
            timeframes=("5m", "15m", "1h"),
            data_version="data-v1",
            label_version="labels-v1",
            episode_version="episodes-v1",
            formula_version="decision-research-v1",
            feature_version="features-v1",
            model_version_ids=("entry-model-v1", "exit-model-v1"),
            matched_research_ids=("entry-comparison-v1", "exit-comparison-v1"),
            application_version="1.6.0",
            random_seed=42,
            data_start_utc_ms=1_700_000_000_000,
            data_end_utc_ms=1_700_086_400_000,
        ),
        content=ResearchSnapshotContent(
            data_quality={"coverage_ratio": 1.0},
            label_audit={"entry_count": 30, "excluded_count": 2},
            similarity_summary={"candidate_count": 18},
            model_summary={"entry_status": "COMPLETED", "exit_status": "FAILED"},
            sample_rows=({"sample_id": "sample-1", "label": "ENTRY"},),
            coefficient_rows=({"feature_id": "range_position", "coefficient": 0.4},),
            validation_rows=({"target": "ENTRY_SELECTION", "recall": 0.82},),
            outcome_rows=tuple(
                {
                    "horizon_bars": horizon,
                    "metric": metric,
                    "evidence_status": "NO_RELIABLE_DIFFERENCE",
                }
                for horizon in (1, 3, 5, 10, 20)
                for metric in ("RETURN", "MFE", "MAE")
            ),
            limitations_zh=("当前证据不包含交易成本与前瞻验证。",),
            audit_notes_zh=("平仓模型失败实验已保留。",),
        ),
        hypothesis_card=HypothesisCard(
            status=HypothesisStatus.EXPLORATORY_HYPOTHESIS,
            summary_zh="当前结果只形成可检验的研究假设。",
            evidence_zh=("完整保留十五项后验结果。",),
            next_evidence_zh=("收集时间上更晚且未参与归纳的数据。",),
        ),
    )


def test_same_snapshot_input_and_seed_has_same_manifest_content_hash():
    first = build_research_snapshot_draft(_snapshot_input())
    second = build_research_snapshot_draft(_snapshot_input())

    assert first.content_hash == second.content_hash
    assert first.manifest["content_hash"] == first.content_hash
    assert first.manifest == second.manifest


def test_manifest_hash_is_stable_when_export_rows_arrive_in_another_order():
    snapshot_input = _snapshot_input()
    rows = (
        {"sample_id": "sample-2", "label": "REJECT"},
        {"sample_id": "sample-1", "label": "ENTRY"},
    )
    first = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(snapshot_input.content, sample_rows=rows),
    )
    second = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(
            snapshot_input.content,
            sample_rows=tuple(reversed(rows)),
        ),
    )

    first_draft = build_research_snapshot_draft(first)
    second_draft = build_research_snapshot_draft(second)

    assert first_draft.content_hash == second_draft.content_hash
    assert first_draft.manifest == second_draft.manifest


def test_snapshot_versions_reject_duplicate_timeframes_before_hashing():
    versions = _snapshot_input().versions

    with pytest.raises(ResearchSnapshotValidationError) as captured:
        dataclasses.replace(versions, timeframes=("5m", "5m", "1h"))

    assert captured.value.code == "SNAPSHOT_TIMEFRAMES"


def test_snapshot_service_rejects_missing_setup_reference_before_publication(
    tmp_path,
):
    storage = StorageManager(tmp_path / "research.db")
    service = ResearchSnapshotService(
        storage=storage,
        export_root=tmp_path / "reports",
    )
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            model_version_ids=(),
            matched_research_ids=(),
        ),
    )

    with pytest.raises(ResearchSnapshotReferenceError) as captured:
        service.build_draft(snapshot_input)

    assert captured.value.code == "SETUP_VERSION_NOT_FOUND"
    assert not (tmp_path / "reports").exists()


def test_snapshot_service_rejects_context_that_differs_from_setup_version(
    tmp_path,
):
    storage = StorageManager(tmp_path / "research.db")
    created = SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="区间反转",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="收盘确认后复查。",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            setup_version_id=created.version.setup_version_id,
            direction="SHORT",
            model_version_ids=(),
            matched_research_ids=(),
        ),
    )
    service = ResearchSnapshotService(
        storage=storage,
        export_root=tmp_path / "reports",
    )

    with pytest.raises(ResearchSnapshotReferenceError) as captured:
        service.build_draft(snapshot_input)

    assert captured.value.code == "SETUP_CONTEXT_MISMATCH"
    assert not (tmp_path / "reports").exists()


def test_snapshot_service_rejects_missing_episode_grouping_reference(tmp_path):
    storage = StorageManager(tmp_path / "research.db")
    created = SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="趋势回踩",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="回踩后收盘重新站稳。",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            setup_version_id=created.version.setup_version_id,
            model_version_ids=(),
            matched_research_ids=(),
        ),
    )
    service = ResearchSnapshotService(
        storage=storage,
        export_root=tmp_path / "reports",
    )

    with pytest.raises(ResearchSnapshotReferenceError) as captured:
        service.build_draft(snapshot_input)

    assert captured.value.code == "EPISODE_VERSION_NOT_FOUND"


def test_published_snapshot_identity_round_trips_through_public_storage(tmp_path):
    database_path = tmp_path / "research.db"
    storage = StorageManager(database_path)
    created = SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="发布样本",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="使用冻结版本生成报告。",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    grouping = MarketEpisodeService(storage).create_automatic_grouping(
        (
            ResearchSampleWindow(
                sample_id="sample-1",
                symbol="BTCUSDT",
                timeframe="5m",
                feature_window=TimeRange(start, start + timedelta(hours=1)),
                outcome_window=TimeRange(
                    start + timedelta(hours=1),
                    start + timedelta(hours=2),
                ),
            ),
        ),
        created_at=start + timedelta(days=1),
    )
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            setup_version_id=created.version.setup_version_id,
            episode_version=grouping.grouping_version_id,
            model_version_ids=(),
            matched_research_ids=(),
        ),
    )
    draft = build_research_snapshot_draft(snapshot_input)
    record = PublishedResearchSnapshot(
        snapshot_id=f"snapshot-{draft.content_hash[:24]}",
        content_hash=draft.content_hash,
        versions=snapshot_input.versions,
        manifest=draft.manifest,
        published_relative_path=(
            f"research_snapshots/snapshot-{draft.content_hash[:24]}"
        ),
        created_at="2026-01-02T00:00:00+00:00",
    )

    storage.save_research_snapshot(record)
    restored = StorageManager(database_path).get_research_snapshot(
        record.snapshot_id
    )

    assert restored == record
    assert StorageManager(database_path).schema_version() == StorageManager.SCHEMA_VERSION


def test_published_snapshot_database_row_cannot_be_updated_or_deleted(tmp_path):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    publication = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )

    with storage.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE research_snapshots SET created_at=? WHERE snapshot_id=?",
                ("2099-01-01T00:00:00+00:00", publication.snapshot.snapshot_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "DELETE FROM research_snapshots WHERE snapshot_id=?",
                (publication.snapshot.snapshot_id,),
            )

    assert storage.get_research_snapshot(publication.snapshot.snapshot_id) == (
        publication.snapshot
    )


def _valid_snapshot_service_and_input(tmp_path):
    storage = StorageManager(tmp_path / "research.db")
    created = SetupLibrary(storage).create_setup(
        CreateSetup(
            display_name="研究快照",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="冻结全部研究版本后发布。",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )
    start = datetime(2026, 2, 1, tzinfo=UTC)
    grouping = MarketEpisodeService(storage).create_automatic_grouping(
        (
            ResearchSampleWindow(
                sample_id="sample-1",
                symbol="BTCUSDT",
                timeframe="5m",
                feature_window=TimeRange(start, start + timedelta(hours=1)),
                outcome_window=TimeRange(
                    start + timedelta(hours=1),
                    start + timedelta(hours=2),
                ),
            ),
        ),
        created_at=start + timedelta(days=1),
    )
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            setup_version_id=created.version.setup_version_id,
            episode_version=grouping.grouping_version_id,
            model_version_ids=(),
            matched_research_ids=(),
        ),
    )
    return (
        ResearchSnapshotService(
            storage=storage,
            export_root=tmp_path / "reports",
        ),
        snapshot_input,
        storage,
    )


def test_public_snapshot_publish_atomically_creates_package_and_identity(tmp_path):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )

    publication = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )

    assert publication.directory.is_dir()
    assert publication.snapshot == storage.get_research_snapshot(
        publication.snapshot.snapshot_id
    )
    manifest = json.loads(
        (publication.directory / "export_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["content_hash"] == publication.snapshot.content_hash
    assert set(manifest["row_counts"]) == {
        "samples",
        "coefficients",
        "validation",
        "outcomes",
    }
    assert not list((tmp_path / "reports").glob(".*.staging-*"))


def test_published_package_is_complete_portable_and_hash_verifiable(tmp_path):
    service, snapshot_input, _storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    publication = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )
    directory = publication.directory
    manifest_text = (directory / "export_manifest.json").read_text(
        encoding="utf-8"
    )
    manifest = json.loads(manifest_text)

    assert set(manifest["artifact_hashes"]) == {
        "research_report.md",
        "samples.csv",
        "coefficients.csv",
        "validation.csv",
        "outcomes.csv",
        "outcome_matrix.png",
        "strategy_hypothesis_card.json",
    }
    for relative_path, expected_hash in manifest["artifact_hashes"].items():
        assert hashlib.sha256(
            (directory / relative_path).read_bytes()
        ).hexdigest() == expected_hash
    report = (directory / "research_report.md").read_text(encoding="utf-8")
    for heading in (
        "研究对象",
        "数据质量",
        "标签来源与排除项",
        "相似检索",
        "行为模型",
        "完整十五项后验",
        "限制",
        "版本审计",
    ):
        assert heading in report
    assert "FAILED" in report
    assert "| 比较版本 | 窗口（K 线） | 指标 | 证据状态 |" in report
    assert report.count("NO_RELIABLE_DIFFERENCE") == 15
    with (directory / "outcomes.csv").open(encoding="utf-8", newline="") as handle:
        outcomes = list(csv.DictReader(handle))
    assert len(outcomes) == 15
    assert {row["evidence_status"] for row in outcomes} == {
        "NO_RELIABLE_DIFFERENCE"
    }
    assert (directory / "outcome_matrix.png").read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    assert str(tmp_path) not in manifest_text
    assert "D:\\Trading" not in manifest_text


def test_snapshot_service_rejects_missing_model_version_reference(tmp_path):
    service, snapshot_input, _storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    snapshot_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            model_version_ids=("missing-model",),
        ),
    )

    with pytest.raises(ResearchSnapshotReferenceError) as captured:
        service.build_draft(snapshot_input)

    assert captured.value.code == "MODEL_VERSION_NOT_FOUND"


def test_snapshot_service_rejects_missing_matched_research_reference(tmp_path):
    service, snapshot_input, _storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    snapshot_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            matched_research_ids=("missing-comparison",),
        ),
    )

    with pytest.raises(ResearchSnapshotReferenceError) as captured:
        service.build_draft(snapshot_input)

    assert captured.value.code == "MATCHED_RESEARCH_NOT_FOUND"


def test_snapshot_service_accepts_version_consistent_exit_outcome_reference(
    tmp_path,
    monkeypatch,
):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    versions = snapshot_input.versions
    exit_comparison_id = "exit-comparison-v1"
    exit_result = SimpleNamespace(
        setup_version_id=versions.setup_version_id,
        grouping_version_id=versions.episode_version,
        direction=versions.direction,
        formula_version=versions.formula_version,
        feature_version=versions.feature_version,
    )
    monkeypatch.setattr(storage, "get_entry_outcome_result", lambda _id: None)
    monkeypatch.setattr(
        storage,
        "get_exit_outcome_result",
        lambda comparison_id: (
            exit_result if comparison_id == exit_comparison_id else None
        ),
    )
    snapshot_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            versions,
            matched_research_ids=(exit_comparison_id,),
        ),
    )

    draft = service.build_draft(snapshot_input)

    assert draft.manifest["versions"]["matched_research_ids"] == (
        exit_comparison_id,
    )


def test_cancelled_publication_preserves_previous_successful_snapshot(tmp_path):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    first = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )
    first_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first.directory.iterdir()
        if path.is_file()
    }
    next_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            random_seed=43,
        ),
    )

    with pytest.raises(ResearchSnapshotCancelled):
        service.publish(
            next_input,
            created_at="2026-02-03T00:00:00+00:00",
            cancelled=lambda: True,
        )

    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first.directory.iterdir()
        if path.is_file()
    } == first_hashes
    assert storage.list_research_snapshots(
        snapshot_input.versions.setup_version_id
    ) == (first.snapshot,)
    assert not list((tmp_path / "reports").glob(".*.staging-*"))


def test_duplicate_publish_returns_existing_immutable_version(tmp_path):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    first = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )
    manifest_before = (first.directory / "export_manifest.json").read_bytes()

    duplicate = service.publish(
        snapshot_input,
        created_at="2099-12-31T23:59:59+00:00",
    )

    assert duplicate.duplicate is True
    assert duplicate.snapshot == first.snapshot
    assert duplicate.snapshot.created_at == "2026-02-02T00:00:00+00:00"
    assert (duplicate.directory / "export_manifest.json").read_bytes() == (
        manifest_before
    )
    assert storage.list_research_snapshots(
        snapshot_input.versions.setup_version_id
    ) == (first.snapshot,)


def test_duplicate_publish_rejects_a_damaged_existing_version(tmp_path):
    service, snapshot_input, _storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    first = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )
    (first.directory / "research_report.md").write_text(
        "damaged",
        encoding="utf-8",
    )

    with pytest.raises(ResearchSnapshotIntegrityError) as captured:
        service.publish(
            snapshot_input,
            created_at="2026-02-03T00:00:00+00:00",
        )

    assert captured.value.code == "FILE_HASH_MISMATCH"


def test_concurrent_duplicate_publish_resolves_unique_identity_race(tmp_path):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    first = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )

    class StaleReadStorage:
        def __init__(self, delegate):
            self._delegate = delegate
            self._stale_read = True

        def __getattr__(self, name):
            return getattr(self._delegate, name)

        def get_research_snapshot_by_content_hash(self, content_hash):
            if self._stale_read:
                self._stale_read = False
                return None
            return self._delegate.get_research_snapshot_by_content_hash(
                content_hash
            )

        def save_research_snapshot_with_publish(self, snapshot, publish):
            raise sqlite3.IntegrityError("simulated concurrent unique race")

    racing_service = ResearchSnapshotService(
        storage=StaleReadStorage(storage),
        export_root=tmp_path / "reports",
    )

    duplicate = racing_service.publish(
        snapshot_input,
        created_at="2026-02-03T00:00:00+00:00",
    )

    assert duplicate.duplicate is True
    assert duplicate.snapshot == first.snapshot


@pytest.mark.parametrize(
    "private_path",
    (
        r"D:\Trading\quant_collector_app\data\private.db",
        "/home/researcher/private.db",
        "/Users/researcher/private.db",
    ),
)
def test_snapshot_manifest_rejects_local_absolute_paths(private_path):
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(
            snapshot_input.content,
            data_quality={"source_path": private_path},
        ),
    )

    with pytest.raises(ResearchSnapshotValidationError) as captured:
        build_research_snapshot_draft(snapshot_input)

    assert captured.value.code == "ABSOLUTE_PATH"


def test_snapshot_manifest_rejects_absolute_paths_nested_in_export_rows():
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(
            snapshot_input.content,
            sample_rows=(
                {"sample_id": "sample-1", "source_path": r"D:\private\sample.json"},
            ),
        ),
    )

    with pytest.raises(ResearchSnapshotValidationError) as captured:
        build_research_snapshot_draft(snapshot_input)

    assert captured.value.code == "ABSOLUTE_PATH"


@pytest.mark.parametrize(
    "forbidden_claim",
    (
        "买入信号",
        "卖出信号",
        "交易信号",
        "胜率保证",
        "保证盈利",
        "稳赚",
        "可交易策略",
    ),
)
def test_hypothesis_card_rejects_trading_claims(forbidden_claim):
    snapshot_input = _snapshot_input()

    with pytest.raises(ResearchSnapshotValidationError) as captured:
        dataclasses.replace(
            snapshot_input.hypothesis_card,
            summary_zh=f"该结果已经形成{forbidden_claim}。",
        )

    assert captured.value.code == "HYPOTHESIS_BOUNDARY"


def test_snapshot_rejects_incomplete_fifteen_outcome_matrix():
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(
            snapshot_input.content,
            outcome_rows=snapshot_input.content.outcome_rows[:-1],
        ),
    )

    with pytest.raises(ResearchSnapshotValidationError) as captured:
        build_research_snapshot_draft(snapshot_input)

    assert captured.value.code == "INCOMPLETE_OUTCOME_MATRIX"


def test_snapshot_accepts_authoritative_close_return_metric_name():
    snapshot_input = _snapshot_input()
    rows = tuple(
        {
            **row,
            "metric": "close_return" if row["metric"] == "RETURN" else row["metric"].lower(),
        }
        for row in snapshot_input.content.outcome_rows
    )
    snapshot_input = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(snapshot_input.content, outcome_rows=rows),
    )

    draft = build_research_snapshot_draft(snapshot_input)

    assert draft.manifest["content"]["outcome_rows"][0]["metric"] == "close_return"


def test_snapshot_accepts_one_complete_matrix_per_matched_comparison():
    snapshot_input = _snapshot_input()
    rows = tuple(
        {**row, "comparison_id": comparison_id}
        for comparison_id in ("entry-comparison-v1", "exit-comparison-v1")
        for row in snapshot_input.content.outcome_rows
    )
    snapshot_input = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(snapshot_input.content, outcome_rows=rows),
    )

    draft = build_research_snapshot_draft(snapshot_input)

    assert len(draft.manifest["content"]["outcome_rows"]) == 30


def test_directory_publish_failure_rolls_back_new_snapshot_identity(tmp_path):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    first = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )
    changed_input = dataclasses.replace(
        snapshot_input,
        versions=dataclasses.replace(
            snapshot_input.versions,
            random_seed=99,
        ),
    )

    class FailingPublisher:
        def __init__(self, export_root, final_name):
            self._delegate = ExportDirectoryPublisher(export_root, final_name)

        def prepare(self):
            return self._delegate.prepare()

        def publish(self):
            raise OSError("simulated atomic rename failure")

        def abort(self):
            self._delegate.abort()

    failing_service = ResearchSnapshotService(
        storage=storage,
        export_root=tmp_path / "reports",
        publisher_factory=FailingPublisher,
    )

    with pytest.raises(OSError, match="simulated atomic rename failure"):
        failing_service.publish(
            changed_input,
            created_at="2026-02-03T00:00:00+00:00",
        )

    assert storage.list_research_snapshots(
        snapshot_input.versions.setup_version_id
    ) == (first.snapshot,)
    assert first.directory.is_dir()
    assert not list((tmp_path / "reports").glob(".*.staging-*"))


def test_database_commit_failure_removes_newly_published_snapshot_directory(tmp_path):
    _service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )

    class CommitFailingStorage:
        def __getattr__(self, name):
            return getattr(storage, name)

        def save_research_snapshot_with_publish(self, _snapshot, publish):
            publish()
            raise sqlite3.OperationalError("simulated database commit failure")

    failing_service = ResearchSnapshotService(
        storage=CommitFailingStorage(),
        export_root=tmp_path / "reports",
    )

    with pytest.raises(sqlite3.OperationalError, match="commit failure"):
        failing_service.publish(
            snapshot_input,
            created_at="2026-02-02T00:00:00+00:00",
        )

    assert storage.list_research_snapshots(
        snapshot_input.versions.setup_version_id
    ) == ()
    assert list((tmp_path / "reports").iterdir()) == []


def test_publication_verifies_staged_artifact_hashes_before_atomic_publish(
    tmp_path,
    monkeypatch,
):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    original_writer = (
        research_snapshot_service_module.write_research_snapshot_package
    )

    def corrupting_writer(*args, **kwargs):
        manifest = original_writer(*args, **kwargs)
        directory = args[0]
        (directory / "research_report.md").write_text(
            "corrupted after package creation",
            encoding="utf-8",
        )
        return manifest

    monkeypatch.setattr(
        research_snapshot_service_module,
        "write_research_snapshot_package",
        corrupting_writer,
    )

    with pytest.raises(ResearchSnapshotIntegrityError) as captured:
        service.publish(
            snapshot_input,
            created_at="2026-02-02T00:00:00+00:00",
        )

    assert captured.value.code == "FILE_HASH_MISMATCH"
    assert storage.list_research_snapshots(
        snapshot_input.versions.setup_version_id
    ) == ()
    assert not list((tmp_path / "reports").glob("snapshot-*"))


def test_schema_17_database_upgrades_with_backup_and_preserves_references(
    tmp_path,
):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    setup_version_id = snapshot_input.versions.setup_version_id
    episode_version = snapshot_input.versions.episode_version
    with storage.connect() as conn:
        conn.execute("DROP TABLE research_snapshots")
        conn.execute("PRAGMA user_version=17")
    backup_dir = tmp_path / "upgrade_backups"

    upgraded = StorageManager(
        tmp_path / "research.db",
        backup_dir=backup_dir,
    )

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.get_setup_version(setup_version_id) is not None
    assert upgraded.get_episode_grouping(episode_version) is not None
    assert upgraded.fetch_table("research_snapshots") == []
    assert list(
        backup_dir.glob(f"*v17_to_v{StorageManager.SCHEMA_VERSION}*.db")
    )


def test_snapshot_manifest_is_deeply_immutable_after_hashing():
    draft = build_research_snapshot_draft(_snapshot_input())

    with pytest.raises(TypeError):
        draft.manifest["content"]["data_quality"]["coverage_ratio"] = 0.5


def test_published_snapshot_identity_recomputes_stored_manifest_hash():
    snapshot_input = _snapshot_input()
    draft = build_research_snapshot_draft(snapshot_input)
    tampered_manifest = snapshot_manifest_as_dict(draft.manifest)
    tampered_manifest["content"]["data_quality"]["coverage_ratio"] = 0.5

    with pytest.raises(ValueError, match="content hash"):
        PublishedResearchSnapshot(
            snapshot_id="snapshot-tampered",
            content_hash=draft.content_hash,
            versions=snapshot_input.versions,
            manifest=tampered_manifest,
            published_relative_path="snapshot-tampered",
            created_at="2026-02-02T00:00:00+00:00",
        )


def test_published_snapshot_rejects_columns_that_disagree_with_manifest_versions():
    snapshot_input = _snapshot_input()
    draft = build_research_snapshot_draft(snapshot_input)
    mismatched_versions = dataclasses.replace(
        snapshot_input.versions,
        random_seed=99,
    )

    with pytest.raises(ValueError, match="versions"):
        PublishedResearchSnapshot(
            snapshot_id="snapshot-mismatched-versions",
            content_hash=draft.content_hash,
            versions=mismatched_versions,
            manifest=draft.manifest,
            published_relative_path="snapshot-mismatched-versions",
            created_at="2026-02-02T00:00:00+00:00",
        )


def test_reading_published_version_verifies_artifact_hashes(tmp_path):
    service, snapshot_input, _storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    publication = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )

    restored = service.read(publication.snapshot.snapshot_id)
    assert restored.snapshot == publication.snapshot
    assert restored.report_markdown.startswith("# QRC 决策研究快照报告")

    (publication.directory / "research_report.md").write_text(
        "tampered",
        encoding="utf-8",
    )
    with pytest.raises(ResearchSnapshotIntegrityError) as captured:
        service.read(publication.snapshot.snapshot_id)

    assert captured.value.code == "FILE_HASH_MISMATCH"


def test_cancellation_after_validation_still_prevents_atomic_publish(tmp_path):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    cancel_requested = False

    def progress(message: str) -> None:
        nonlocal cancel_requested
        if message == "正在校验研究快照":
            cancel_requested = True

    with pytest.raises(ResearchSnapshotCancelled):
        service.publish(
            snapshot_input,
            created_at="2026-02-02T00:00:00+00:00",
            cancelled=lambda: cancel_requested,
            progress=progress,
        )

    assert storage.list_research_snapshots(
        snapshot_input.versions.setup_version_id
    ) == ()
    assert not list((tmp_path / "reports").glob("snapshot-*"))


def test_large_csv_export_checks_cancellation_at_bounded_row_intervals(tmp_path):
    service, snapshot_input, storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    snapshot_input = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(
            snapshot_input.content,
            sample_rows=tuple(
                {"sample_id": f"sample-{index}", "label": "ENTRY"}
                for index in range(2_048)
            ),
        ),
    )
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 10

    with pytest.raises(ResearchSnapshotCancelled):
        service.publish(
            snapshot_input,
            created_at="2026-02-02T00:00:00+00:00",
            cancelled=cancelled,
        )

    assert storage.list_research_snapshots(
        snapshot_input.versions.setup_version_id
    ) == ()
    assert not list((tmp_path / "reports").glob("snapshot-*"))


def test_snapshot_machine_keys_do_not_change_with_interface_language():
    snapshot_input = _snapshot_input()
    snapshot_input = dataclasses.replace(
        snapshot_input,
        content=dataclasses.replace(
            snapshot_input.content,
            data_quality={"覆盖率": 1.0},
        ),
    )

    with pytest.raises(ResearchSnapshotValidationError) as captured:
        build_research_snapshot_draft(snapshot_input)

    assert captured.value.code == "MACHINE_KEY"


def test_reading_published_version_recomputes_manifest_content_hash(tmp_path):
    service, snapshot_input, _storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    publication = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )
    manifest_path = publication.directory / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["content"]["data_quality"]["coverage_ratio"] = 0.25
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(ResearchSnapshotIntegrityError) as captured:
        service.read(publication.snapshot.snapshot_id)

    assert captured.value.code == "CONTENT_HASH_MISMATCH"


def test_reading_published_version_compares_full_manifest_with_database(
    tmp_path,
):
    service, snapshot_input, _storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    publication = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )
    manifest_path = publication.directory / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["row_counts"]["samples"] = 99
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(ResearchSnapshotIntegrityError) as captured:
        service.read(publication.snapshot.snapshot_id)

    assert captured.value.code == "MANIFEST_MISMATCH"


def test_reading_published_version_reports_non_object_manifest_as_invalid(
    tmp_path,
):
    service, snapshot_input, _storage = _valid_snapshot_service_and_input(
        tmp_path
    )
    publication = service.publish(
        snapshot_input,
        created_at="2026-02-02T00:00:00+00:00",
    )
    (publication.directory / "export_manifest.json").write_text(
        "[]",
        encoding="utf-8",
    )

    with pytest.raises(ResearchSnapshotIntegrityError) as captured:
        service.read(publication.snapshot.snapshot_id)

    assert captured.value.code == "MANIFEST_INVALID"
