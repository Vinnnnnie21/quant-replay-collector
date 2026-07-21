from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


SNAPSHOT_MANIFEST_VERSION = "qrc-research-snapshot-v1"
_ABSOLUTE_PATH = re.compile(
    r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|mnt|var|tmp)(?:/|$))"
)
_MACHINE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


class ResearchSnapshotValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HypothesisStatus(str, Enum):
    BEHAVIOR_PROFILE_ONLY = "BEHAVIOR_PROFILE_ONLY"
    EXPLORATORY_HYPOTHESIS = "EXPLORATORY_HYPOTHESIS"
    AWAITING_FORWARD_VALIDATION = "AWAITING_FORWARD_VALIDATION"

    @property
    def label_zh(self) -> str:
        return {
            self.BEHAVIOR_PROFILE_ONLY: "仅行为画像",
            self.EXPLORATORY_HYPOTHESIS: "探索性策略假设",
            self.AWAITING_FORWARD_VALIDATION: "待前瞻验证",
        }[self]


@dataclass(frozen=True, slots=True)
class HypothesisCard:
    status: HypothesisStatus
    summary_zh: str
    evidence_zh: tuple[str, ...]
    next_evidence_zh: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", HypothesisStatus(self.status))
        text = "\n".join(
            (
                self.summary_zh,
                *self.evidence_zh,
                *self.next_evidence_zh,
            )
        )
        forbidden = (
            "买入信号",
            "卖出信号",
            "交易信号",
            "胜率保证",
            "保证盈利",
            "盈利保证",
            "稳赚",
            "必赚",
            "可交易策略",
        )
        if any(term in text for term in forbidden):
            raise ResearchSnapshotValidationError(
                "HYPOTHESIS_BOUNDARY",
                "策略假设卡不能包含交易信号、胜率保证或可交易策略声明。",
            )


@dataclass(frozen=True, slots=True)
class ResearchSnapshotVersions:
    setup_version_id: str
    direction: str
    timeframes: tuple[str, str, str]
    data_version: str
    label_version: str
    episode_version: str
    formula_version: str
    feature_version: str
    model_version_ids: tuple[str, ...]
    matched_research_ids: tuple[str, ...]
    application_version: str
    random_seed: int
    data_start_utc_ms: int
    data_end_utc_ms: int

    def __post_init__(self) -> None:
        timeframes = tuple(self.timeframes)
        if (
            len(timeframes) != 3
            or len(set(timeframes)) != 3
            or any(not str(value).strip() for value in timeframes)
        ):
            raise ResearchSnapshotValidationError(
                "SNAPSHOT_TIMEFRAMES",
                "研究快照必须冻结三个互不重复的有效周期。",
            )
        if self.direction not in {"LONG", "SHORT"}:
            raise ResearchSnapshotValidationError(
                "SNAPSHOT_DIRECTION",
                "研究快照方向必须是 LONG 或 SHORT。",
            )
        identifiers = (
            self.setup_version_id,
            self.data_version,
            self.label_version,
            self.episode_version,
            self.formula_version,
            self.feature_version,
            self.application_version,
            *self.model_version_ids,
            *self.matched_research_ids,
        )
        if any(not str(value).strip() for value in identifiers):
            raise ResearchSnapshotValidationError(
                "SNAPSHOT_VERSION_ID",
                "研究快照的版本标识不能为空。",
            )
        duplicate_model = len(set(self.model_version_ids)) != len(
            self.model_version_ids
        )
        duplicate_research = len(set(self.matched_research_ids)) != len(
            self.matched_research_ids
        )
        if duplicate_model or duplicate_research:
            raise ResearchSnapshotValidationError(
                "SNAPSHOT_VERSION_ID",
                "研究快照不能重复引用同一模型或匹配研究版本。",
            )
        if self.data_start_utc_ms > self.data_end_utc_ms:
            raise ResearchSnapshotValidationError(
                "SNAPSHOT_DATA_RANGE",
                "研究快照的数据起点不能晚于终点。",
            )
        object.__setattr__(self, "timeframes", timeframes)
        object.__setattr__(
            self,
            "model_version_ids",
            tuple(self.model_version_ids),
        )
        object.__setattr__(
            self,
            "matched_research_ids",
            tuple(self.matched_research_ids),
        )


@dataclass(frozen=True, slots=True)
class ResearchSnapshotContent:
    data_quality: Mapping[str, Any]
    label_audit: Mapping[str, Any]
    similarity_summary: Mapping[str, Any]
    model_summary: Mapping[str, Any]
    sample_rows: tuple[Mapping[str, Any], ...]
    coefficient_rows: tuple[Mapping[str, Any], ...]
    validation_rows: tuple[Mapping[str, Any], ...]
    outcome_rows: tuple[Mapping[str, Any], ...]
    limitations_zh: tuple[str, ...]
    audit_notes_zh: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchSnapshotInput:
    versions: ResearchSnapshotVersions
    content: ResearchSnapshotContent
    hypothesis_card: HypothesisCard


@dataclass(frozen=True, slots=True)
class ResearchSnapshotDraft:
    content_hash: str
    manifest: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublishedResearchSnapshot:
    snapshot_id: str
    content_hash: str
    versions: ResearchSnapshotVersions
    manifest: Mapping[str, Any]
    published_relative_path: str
    created_at: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.published_relative_path)
        if (
            not self.published_relative_path
            or path == PurePosixPath(".")
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in self.published_relative_path
        ):
            raise ValueError("published_relative_path must be a portable relative path")
        if self.manifest.get("content_hash") != self.content_hash:
            raise ValueError("published manifest content hash does not match snapshot identity")
        if calculate_snapshot_content_hash(self.manifest) != self.content_hash:
            raise ValueError("published manifest content hash cannot be reproduced")
        manifest_versions = self.manifest.get("versions")
        if (
            not isinstance(manifest_versions, Mapping)
            or snapshot_manifest_as_dict(manifest_versions)
            != _versions_payload(self.versions)
        ):
            raise ValueError("published manifest versions do not match database columns")
        object.__setattr__(self, "manifest", _deep_freeze(self.manifest))


@dataclass(frozen=True, slots=True)
class ResearchSnapshotPublication:
    snapshot: PublishedResearchSnapshot
    directory: Path
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ResearchSnapshotView:
    snapshot: PublishedResearchSnapshot
    directory: Path
    report_markdown: str


def _sorted_rows_payload(
    rows: tuple[Mapping[str, Any], ...],
) -> list[dict[str, Any]]:
    payload = [dict(row) for row in rows]
    payload.sort(
        key=lambda row: json.dumps(
            row,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return payload


def _content_payload(content: ResearchSnapshotContent) -> dict[str, Any]:
    return {
        "data_quality": dict(content.data_quality),
        "label_audit": dict(content.label_audit),
        "similarity_summary": dict(content.similarity_summary),
        "model_summary": dict(content.model_summary),
        "sample_rows": _sorted_rows_payload(content.sample_rows),
        "coefficient_rows": _sorted_rows_payload(content.coefficient_rows),
        "validation_rows": _sorted_rows_payload(content.validation_rows),
        "outcome_rows": _sorted_rows_payload(content.outcome_rows),
        "limitations_zh": list(content.limitations_zh),
        "audit_notes_zh": list(content.audit_notes_zh),
    }


def _versions_payload(versions: ResearchSnapshotVersions) -> dict[str, Any]:
    return {
        "setup_version_id": versions.setup_version_id,
        "direction": versions.direction,
        "timeframes": list(versions.timeframes),
        "data_version": versions.data_version,
        "label_version": versions.label_version,
        "episode_version": versions.episode_version,
        "formula_version": versions.formula_version,
        "feature_version": versions.feature_version,
        "model_version_ids": list(versions.model_version_ids),
        "matched_research_ids": list(versions.matched_research_ids),
        "application_version": versions.application_version,
        "random_seed": int(versions.random_seed),
        "data_start_utc_ms": int(versions.data_start_utc_ms),
        "data_end_utc_ms": int(versions.data_end_utc_ms),
    }


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def calculate_snapshot_content_hash(manifest: Mapping[str, Any]) -> str:
    try:
        core = {
            key: manifest[key]
            for key in (
                "manifest_version",
                "versions",
                "content",
                "hypothesis_card",
            )
        }
    except KeyError as exc:
        raise ResearchSnapshotValidationError(
            "MANIFEST_CONTENT",
            f"研究快照 manifest 缺少内容字段：{exc.args[0]}",
        ) from exc
    return hashlib.sha256(
        _canonical_json_bytes(snapshot_manifest_as_dict(core))
    ).hexdigest()


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def snapshot_manifest_as_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    def thaw(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): thaw(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [thaw(child) for child in item]
        return item

    return thaw(value)


def _reject_absolute_paths(value: Any) -> None:
    if isinstance(value, str):
        if _ABSOLUTE_PATH.match(value):
            raise ResearchSnapshotValidationError(
                "ABSOLUTE_PATH",
                "研究快照不能包含本机绝对路径。",
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_absolute_paths(key)
            _reject_absolute_paths(item)
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            _reject_absolute_paths(item)


def _validate_machine_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _MACHINE_KEY.fullmatch(key) is None:
                raise ResearchSnapshotValidationError(
                    "MACHINE_KEY",
                    "JSON manifest 和 CSV 字段必须使用稳定英文 snake_case 键。",
                )
            _validate_machine_keys(item)
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            _validate_machine_keys(item)
        return


def _validate_outcome_matrix(rows: tuple[Mapping[str, Any], ...]) -> None:
    expected = {
        (horizon, metric)
        for horizon in (1, 3, 5, 10, 20)
        for metric in ("CLOSE_RETURN", "MFE", "MAE")
    }
    grouped: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        target = str(
            row.get("comparison_id")
            or row.get("comparison_target")
            or "DECISION"
        )
        try:
            metric = str(row["metric"]).upper()
            if metric == "RETURN":
                metric = "CLOSE_RETURN"
            identity = (int(row["horizon_bars"]), metric)
        except (KeyError, TypeError, ValueError) as exc:
            raise ResearchSnapshotValidationError(
                "INCOMPLETE_OUTCOME_MATRIX",
                "后验结果必须包含固定窗口和指标标识。",
            ) from exc
        grouped.setdefault(target, []).append(identity)
    if not grouped or any(
        len(identities) != 15 or set(identities) != expected
        for identities in grouped.values()
    ):
        raise ResearchSnapshotValidationError(
            "INCOMPLETE_OUTCOME_MATRIX",
            "每个后验比较必须完整包含 5 个窗口乘 3 个指标。",
        )


def build_research_snapshot_draft(
    snapshot_input: ResearchSnapshotInput,
) -> ResearchSnapshotDraft:
    _validate_outcome_matrix(snapshot_input.content.outcome_rows)
    core = {
        "manifest_version": SNAPSHOT_MANIFEST_VERSION,
        "versions": _versions_payload(snapshot_input.versions),
        "content": _content_payload(snapshot_input.content),
        "hypothesis_card": {
            "status": snapshot_input.hypothesis_card.status.value,
            "status_zh": snapshot_input.hypothesis_card.status.label_zh,
            "summary_zh": snapshot_input.hypothesis_card.summary_zh,
            "evidence_zh": list(snapshot_input.hypothesis_card.evidence_zh),
            "next_evidence_zh": list(
                snapshot_input.hypothesis_card.next_evidence_zh
            ),
        },
    }
    _validate_machine_keys(core)
    _reject_absolute_paths(core)
    content_hash = calculate_snapshot_content_hash(core)
    manifest = {**core, "content_hash": content_hash}
    return ResearchSnapshotDraft(
        content_hash=content_hash,
        manifest=_deep_freeze(manifest),
    )


__all__ = [
    "HypothesisCard",
    "HypothesisStatus",
    "PublishedResearchSnapshot",
    "ResearchSnapshotContent",
    "ResearchSnapshotDraft",
    "ResearchSnapshotInput",
    "ResearchSnapshotPublication",
    "ResearchSnapshotValidationError",
    "ResearchSnapshotView",
    "ResearchSnapshotVersions",
    "SNAPSHOT_MANIFEST_VERSION",
    "build_research_snapshot_draft",
    "calculate_snapshot_content_hash",
    "snapshot_manifest_as_dict",
]
