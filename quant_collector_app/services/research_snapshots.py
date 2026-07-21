from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from research.research_snapshot import (
        ResearchSnapshotDraft,
        ResearchSnapshotInput,
        PublishedResearchSnapshot,
        ResearchSnapshotPublication,
        ResearchSnapshotView,
        build_research_snapshot_draft,
    )
except ImportError:  # pragma: no cover - package import path
    from ..research.research_snapshot import (
        ResearchSnapshotDraft,
        ResearchSnapshotInput,
        PublishedResearchSnapshot,
        ResearchSnapshotPublication,
        ResearchSnapshotView,
        build_research_snapshot_draft,
    )

try:
    from export_publish import ExportDirectoryPublisher
    from research.research_snapshot_report import (
        ResearchSnapshotCancelled,
        ResearchSnapshotIntegrityError,
        verify_research_snapshot_package,
        write_research_snapshot_package,
    )
except ImportError:  # pragma: no cover - package import path
    from ..export_publish import ExportDirectoryPublisher
    from ..research.research_snapshot_report import (
        ResearchSnapshotCancelled,
        ResearchSnapshotIntegrityError,
        verify_research_snapshot_package,
        write_research_snapshot_package,
    )

try:
    from research.entry_behavior_model import BehaviorModelTarget
except ImportError:  # pragma: no cover - package import path
    from ..research.entry_behavior_model import BehaviorModelTarget


class ResearchSnapshotReferenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_REQUIRED_STORAGE_METHODS = (
    "get_setup_version",
    "get_episode_grouping",
    "get_behavior_model_version",
    "get_entry_outcome_result",
    "get_exit_outcome_result",
    "get_research_snapshot_by_content_hash",
    "save_research_snapshot_with_publish",
    "get_research_snapshot",
    "list_research_snapshots",
)


def supports_research_snapshot_storage(storage: Any) -> bool:
    return storage is not None and all(
        callable(getattr(storage, method, None))
        for method in _REQUIRED_STORAGE_METHODS
    )


class ResearchSnapshotService:
    """Validate, freeze, publish, and reload decision-research snapshots."""

    def __init__(
        self,
        *,
        storage: Any,
        export_root: str | Path,
        publisher_factory: Callable[..., Any] = ExportDirectoryPublisher,
    ) -> None:
        self.storage = storage
        self.export_root = Path(export_root)
        self._publisher_factory = publisher_factory

    def build_draft(
        self,
        snapshot_input: ResearchSnapshotInput,
    ) -> ResearchSnapshotDraft:
        setup_version = self.storage.get_setup_version(
            snapshot_input.versions.setup_version_id
        )
        if setup_version is None:
            raise ResearchSnapshotReferenceError(
                "SETUP_VERSION_NOT_FOUND",
                "引用的 Setup 版本不存在。",
            )
        versions = snapshot_input.versions
        if (
            setup_version.direction.value != versions.direction
            or setup_version.timeframes.as_tuple() != versions.timeframes
        ):
            raise ResearchSnapshotReferenceError(
                "SETUP_CONTEXT_MISMATCH",
                "快照方向或三周期与引用的 Setup 版本不一致。",
            )
        if self.storage.get_episode_grouping(versions.episode_version) is None:
            raise ResearchSnapshotReferenceError(
                "EPISODE_VERSION_NOT_FOUND",
                "引用的独立行情片段分组版本不存在。",
            )
        for model_version_id in versions.model_version_ids:
            model = None
            for target in BehaviorModelTarget:
                model = self.storage.get_behavior_model_version(
                    model_version_id,
                    target=target,
                )
                if model is not None:
                    break
            if model is None:
                raise ResearchSnapshotReferenceError(
                    "MODEL_VERSION_NOT_FOUND",
                    f"引用的行为模型版本不存在：{model_version_id}",
                )
            if (
                model.setup_version_id != versions.setup_version_id
                or model.grouping_version_id != versions.episode_version
                or model.direction != versions.direction
            ):
                raise ResearchSnapshotReferenceError(
                    "MODEL_CONTEXT_MISMATCH",
                    f"行为模型版本与快照上下文不一致：{model_version_id}",
                )
        for comparison_id in versions.matched_research_ids:
            result = self.storage.get_entry_outcome_result(comparison_id)
            if result is None:
                result = self.storage.get_exit_outcome_result(comparison_id)
            if result is None:
                raise ResearchSnapshotReferenceError(
                    "MATCHED_RESEARCH_NOT_FOUND",
                    f"引用的匹配后验研究不存在：{comparison_id}",
                )
            if (
                result.setup_version_id != versions.setup_version_id
                or result.grouping_version_id != versions.episode_version
                or result.direction != versions.direction
                or result.formula_version != versions.formula_version
                or result.feature_version != versions.feature_version
            ):
                raise ResearchSnapshotReferenceError(
                    "MATCHED_RESEARCH_CONTEXT_MISMATCH",
                    f"匹配后验研究与快照版本不一致：{comparison_id}",
                )
        return build_research_snapshot_draft(snapshot_input)

    def publish(
        self,
        snapshot_input: ResearchSnapshotInput,
        *,
        created_at: str,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> ResearchSnapshotPublication:
        draft = self.build_draft(snapshot_input)
        existing = self.storage.get_research_snapshot_by_content_hash(
            draft.content_hash
        )
        if existing is not None:
            verified = self.read(existing.snapshot_id)
            return ResearchSnapshotPublication(
                snapshot=verified.snapshot,
                directory=verified.directory,
                duplicate=True,
            )
        snapshot_id = f"snapshot-{draft.content_hash[:24]}"
        publisher = self._publisher_factory(self.export_root, snapshot_id)
        staging = publisher.prepare()
        try:
            manifest = write_research_snapshot_package(
                staging,
                draft,
                snapshot_id=snapshot_id,
                cancelled=cancelled,
                progress=progress,
            )
            verify_research_snapshot_package(
                staging,
                snapshot_id=snapshot_id,
                content_hash=draft.content_hash,
                expected_manifest=manifest,
            )
            if cancelled is not None and cancelled():
                raise ResearchSnapshotCancelled("研究快照发布已取消。")
            if progress is not None:
                progress("正在原子发布研究快照")
            if cancelled is not None and cancelled():
                raise ResearchSnapshotCancelled("研究快照发布已取消。")
            snapshot = PublishedResearchSnapshot(
                snapshot_id=snapshot_id,
                content_hash=draft.content_hash,
                versions=snapshot_input.versions,
                manifest=manifest,
                published_relative_path=snapshot_id,
                created_at=created_at,
            )
            directory = self.storage.save_research_snapshot_with_publish(
                snapshot,
                publisher.publish,
            )
        except sqlite3.IntegrityError:
            _abort_publication(publisher)
            existing = self.storage.get_research_snapshot_by_content_hash(
                draft.content_hash
            )
            if existing is None:
                raise
            verified = self.read(existing.snapshot_id)
            return ResearchSnapshotPublication(
                snapshot=verified.snapshot,
                directory=verified.directory,
                duplicate=True,
            )
        except Exception:
            _abort_publication(publisher)
            raise
        return ResearchSnapshotPublication(
            snapshot=snapshot,
            directory=directory,
            duplicate=False,
        )

    def read(self, snapshot_id: str) -> ResearchSnapshotView:
        snapshot = self.storage.get_research_snapshot(snapshot_id)
        if snapshot is None:
            raise ResearchSnapshotReferenceError(
                "SNAPSHOT_NOT_FOUND",
                "引用的研究快照不存在。",
            )
        directory = self.export_root / snapshot.published_relative_path
        verify_research_snapshot_package(
            directory,
            snapshot_id=snapshot.snapshot_id,
            content_hash=snapshot.content_hash,
            expected_manifest=snapshot.manifest,
        )
        return ResearchSnapshotView(
            snapshot=snapshot,
            directory=directory,
            report_markdown=(directory / "research_report.md").read_text(
                encoding="utf-8"
            ),
        )


def _abort_publication(publisher: Any) -> None:
    rollback = getattr(publisher, "rollback_new_publication", None)
    try:
        if callable(rollback):
            rollback()
    finally:
        publisher.abort()


__all__ = [
    "ResearchSnapshotReferenceError",
    "ResearchSnapshotCancelled",
    "ResearchSnapshotIntegrityError",
    "ResearchSnapshotService",
    "supports_research_snapshot_storage",
]
