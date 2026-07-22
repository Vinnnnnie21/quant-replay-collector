from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
import zlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    from research.research_snapshot import (
        ResearchSnapshotDraft,
        ResearchSnapshotValidationError,
        calculate_snapshot_content_hash,
        snapshot_manifest_as_dict,
    )
    from research.cancellation import ResearchCancelled
except ImportError:  # pragma: no cover - package import path
    from .research_snapshot import (
        ResearchSnapshotDraft,
        ResearchSnapshotValidationError,
        calculate_snapshot_content_hash,
        snapshot_manifest_as_dict,
    )
    from .cancellation import ResearchCancelled


_MACHINE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_TABLE_SCHEMAS = {
    "samples": ("sample_id", "label", "episode_id", "source", "exclusion_reason"),
    "coefficients": (
        "model_version_id",
        "target",
        "feature_id",
        "coefficient",
        "stability",
    ),
    "validation": ("model_version_id", "target", "status", "metric", "value"),
    "outcomes": (
        "comparison_id",
        "horizon_bars",
        "metric",
        "evidence_status",
        "pair_count",
        "episode_count",
        "median_difference",
        "ci_low",
        "ci_high",
        "p_value",
        "q_value",
    ),
}


class ResearchSnapshotCancelled(ResearchCancelled):
    pass


class ResearchSnapshotIntegrityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _checkpoint(
    cancelled: Callable[[], bool] | None,
    progress: Callable[[str], None] | None,
    message: str,
) -> None:
    if cancelled is not None and cancelled():
        raise ResearchSnapshotCancelled("研究快照发布已取消。")
    if progress is not None:
        progress(message)


def _format_mapping(mapping: Mapping[str, Any]) -> list[str]:
    if not mapping:
        return ["- 无可用记录。"]
    return [
        f"- `{key}`：{json.dumps(value, ensure_ascii=False, default=str)}"
        for key, value in sorted(mapping.items())
    ]


def _outcome_sort_key(row: Mapping[str, Any]) -> tuple[str, int, int]:
    horizon_order = {value: index for index, value in enumerate((1, 3, 5, 10, 20))}
    metric_order = {"close_return": 0, "return": 0, "mfe": 1, "mae": 2}
    return (
        str(row.get("comparison_id") or row.get("comparison_target") or "DECISION"),
        horizon_order.get(int(row.get("horizon_bars", -1)), 99),
        metric_order.get(str(row.get("metric", "")).lower(), 99),
    )


def _markdown_cell(value: Any) -> str:
    if value is None or value == "":
        return "不可用"
    if isinstance(value, float):
        return format(value, ".10g")
    return str(value).replace("|", "\\|").replace("\n", " ")


def _outcome_markdown_table(
    rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    lines = [
        "| 比较版本 | 窗口（K 线） | 指标 | 证据状态 | 配对数 | episode 数 | 中位差 | 95% 区间 | p | q |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in sorted(rows, key=_outcome_sort_key):
        comparison_id = (
            row.get("comparison_id")
            or row.get("comparison_target")
            or "DECISION"
        )
        interval = (
            f"[{_markdown_cell(row.get('ci_low'))}, "
            f"{_markdown_cell(row.get('ci_high'))}]"
        )
        values = (
            comparison_id,
            row.get("horizon_bars"),
            row.get("metric"),
            row.get("evidence_status"),
            row.get("pair_count"),
            row.get("episode_count"),
            row.get("median_difference"),
            interval,
            row.get("p_value"),
            row.get("q_value"),
        )
        lines.append("| " + " | ".join(_markdown_cell(value) for value in values) + " |")
    return lines


def _report_markdown(draft: ResearchSnapshotDraft) -> str:
    manifest = draft.manifest
    versions = manifest["versions"]
    content = manifest["content"]
    card = manifest["hypothesis_card"]
    model_lines = _format_mapping(content["model_summary"])
    if not model_lines:
        model_lines = ["- 本次没有可发布模型版本。"]
    lines = [
        "# QRC 决策研究快照报告",
        "",
        "## 1. 研究对象",
        "",
        f"- Setup 版本：`{versions['setup_version_id']}`",
        f"- 方向：`{versions['direction']}`",
        f"- 三周期：{' / '.join(versions['timeframes'])}",
        f"- 数据区间：`{versions['data_start_utc_ms']}`—`{versions['data_end_utc_ms']}`",
        "",
        "## 2. 数据质量",
        "",
        *_format_mapping(content["data_quality"]),
        "",
        "## 3. 标签来源与排除项",
        "",
        *_format_mapping(content["label_audit"]),
        "",
        "## 4. 相似检索",
        "",
        *_format_mapping(content["similarity_summary"]),
        "",
        "## 5. 行为模型",
        "",
        *model_lines,
        "",
        "失败实验、证据不足和未发现稳定指标均按原结果保留。",
        "",
        "## 6. 完整十五项后验",
        "",
        f"- 已导出结果行数：{len(content['outcome_rows'])}",
        "- 固定观察窗口：1、3、5、10、20 根 K 线。",
        "- 固定指标：方向调整收益、MFE、MAE。非显著项不会省略。",
        "",
        *_outcome_markdown_table(content["outcome_rows"]),
        "",
        "## 7. 策略假设卡",
        "",
        f"- 状态：{card['status_zh']}",
        f"- 摘要：{card['summary_zh']}",
        *[f"- 证据：{item}" for item in card["evidence_zh"]],
        *[f"- 下一步证据：{item}" for item in card["next_evidence_zh"]],
        "",
        "## 8. 限制",
        "",
        *([f"- {item}" for item in content["limitations_zh"]] or ["- 暂无补充限制。"]),
        "- 本报告描述行为与当前样本中的后验差异，不构成自动下单依据，也不证明未来收益。",
        "",
        "## 9. 版本审计",
        "",
        f"- 内容哈希：`{draft.content_hash}`",
        f"- 数据版本：`{versions['data_version']}`",
        f"- 标签版本：`{versions['label_version']}`",
        f"- episode 版本：`{versions['episode_version']}`",
        f"- 公式版本：`{versions['formula_version']}`",
        f"- 特征版本：`{versions['feature_version']}`",
        f"- 模型版本：{', '.join(versions['model_version_ids']) or '无'}",
        f"- 匹配研究：{', '.join(versions['matched_research_ids']) or '无'}",
        f"- 应用版本：`{versions['application_version']}`",
        f"- 随机种子：`{versions['random_seed']}`",
        *[f"- 审计备注：{item}" for item in content["audit_notes_zh"]],
        "",
    ]
    return "\n".join(lines)


def _columns_for(
    table_name: str,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    discovered = {str(key) for row in rows for key in row}
    invalid = sorted(key for key in discovered if _MACHINE_KEY.fullmatch(key) is None)
    if invalid:
        raise ValueError(
            f"snapshot CSV keys must be stable English identifiers: {', '.join(invalid)}"
        )
    required = _TABLE_SCHEMAS[table_name]
    return (*required, *sorted(discovered.difference(required)))


def _write_csv(
    path: Path,
    table_name: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    columns = _columns_for(table_name, rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for index, row in enumerate(rows):
            if index % 256 == 0:
                _checkpoint(cancelled, None, "")
            writer.writerow({column: row.get(column) for column in columns})


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _outcome_matrix_png(rows: Sequence[Mapping[str, Any]]) -> bytes:
    width, height = 300, 180
    colors = {
        "DIFFERENCE_EVIDENCE": (65, 105, 225),
        "NO_RELIABLE_DIFFERENCE": (112, 128, 144),
        "INSUFFICIENT": (205, 133, 63),
    }
    ordered_rows = sorted(rows, key=_outcome_sort_key)
    cells = [
        colors.get(str(row.get("evidence_status")), (90, 90, 90))
        for row in ordered_rows[:15]
    ]
    while len(cells) < 15:
        cells.append((70, 70, 70))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        row_index = min(y // 36, 4)
        for x in range(width):
            column_index = min(x // 100, 2)
            color = cells[row_index * 3 + column_index]
            border = x % 100 in {0, 99} or y % 36 in {0, 35}
            raw.extend((35, 35, 35) if border else color)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
            ),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=9)),
            _png_chunk(b"IEND", b""),
        )
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _strategy_spec_for_publish(
    draft: ResearchSnapshotDraft,
    *,
    snapshot_id: str,
) -> dict[str, Any] | None:
    if "strategy_spec" not in draft.manifest:
        return None
    payload = snapshot_manifest_as_dict(draft.manifest["strategy_spec"])
    provenance = dict(payload["provenance"])
    provenance["research_snapshot_id"] = snapshot_id
    return {**payload, "provenance": provenance}


def verify_research_snapshot_package(
    directory: Path,
    *,
    snapshot_id: str,
    content_hash: str,
    expected_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_path = directory / "export_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchSnapshotIntegrityError(
            "MANIFEST_INVALID",
            "研究快照 manifest 缺失或无法读取。",
        ) from exc
    if not isinstance(manifest, dict):
        raise ResearchSnapshotIntegrityError(
            "MANIFEST_INVALID",
            "研究快照 manifest 顶层必须是 JSON 对象。",
        )
    if (
        manifest.get("snapshot_id") != snapshot_id
        or manifest.get("content_hash") != content_hash
    ):
        raise ResearchSnapshotIntegrityError(
            "IDENTITY_MISMATCH",
            "研究快照 manifest 与数据库身份不一致。",
        )
    try:
        calculated_content_hash = calculate_snapshot_content_hash(manifest)
    except (ResearchSnapshotValidationError, TypeError, ValueError) as exc:
        raise ResearchSnapshotIntegrityError(
            "MANIFEST_INVALID",
            "研究快照 manifest 内容无法复算。",
        ) from exc
    if calculated_content_hash != content_hash:
        raise ResearchSnapshotIntegrityError(
            "CONTENT_HASH_MISMATCH",
            "研究快照 manifest 内容哈希不一致。",
        )
    if (
        expected_manifest is not None
        and manifest != snapshot_manifest_as_dict(expected_manifest)
    ):
        raise ResearchSnapshotIntegrityError(
            "MANIFEST_MISMATCH",
            "研究快照 manifest 与数据库冻结版本不一致。",
        )
    artifact_hashes = manifest.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise ResearchSnapshotIntegrityError(
            "MANIFEST_INVALID",
            "研究快照 manifest 缺少文件哈希。",
        )
    root = directory.resolve()
    for relative_path, expected_hash in artifact_hashes.items():
        path = (directory / str(relative_path)).resolve()
        if not path.is_relative_to(root):
            raise ResearchSnapshotIntegrityError(
                "PATH_NOT_PORTABLE",
                "研究快照 manifest 包含目录外路径。",
            )
        if not path.is_file():
            raise ResearchSnapshotIntegrityError(
                "FILE_MISSING",
                f"研究快照文件缺失：{relative_path}",
            )
        if _sha256(path) != expected_hash:
            raise ResearchSnapshotIntegrityError(
                "FILE_HASH_MISMATCH",
                f"研究快照文件哈希不一致：{relative_path}",
            )
    return manifest


def write_research_snapshot_package(
    directory: Path,
    draft: ResearchSnapshotDraft,
    *,
    snapshot_id: str,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    content = draft.manifest["content"]
    strategy_spec = _strategy_spec_for_publish(draft, snapshot_id=snapshot_id)
    _checkpoint(cancelled, progress, "正在生成中文研究报告")
    (directory / "research_report.md").write_text(
        _report_markdown(draft),
        encoding="utf-8",
    )
    if strategy_spec is not None:
        _checkpoint(cancelled, progress, "Writing structured StrategySpec")
        (directory / "strategy_spec_v1.json").write_text(
            json.dumps(
                strategy_spec,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    table_rows = {
        "samples": content["sample_rows"],
        "coefficients": content["coefficient_rows"],
        "validation": content["validation_rows"],
        "outcomes": content["outcome_rows"],
    }
    for table_name, rows in table_rows.items():
        _checkpoint(cancelled, progress, f"正在写入 {table_name}.csv")
        _write_csv(
            directory / f"{table_name}.csv",
            table_name,
            rows,
            cancelled=cancelled,
        )
    _checkpoint(cancelled, progress, "正在生成后验矩阵图")
    (directory / "outcome_matrix.png").write_bytes(
        _outcome_matrix_png(table_rows["outcomes"])
    )
    card = dict(draft.manifest["hypothesis_card"])
    (directory / "strategy_hypothesis_card.json").write_text(
        json.dumps(
            card,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    files = {
        "research_report": {"markdown": "research_report.md"},
        **{
            name: {"csv": f"{name}.csv"}
            for name in table_rows
        },
        "outcome_matrix": {"png": "outcome_matrix.png"},
        "strategy_hypothesis_card": {
            "json": "strategy_hypothesis_card.json"
        },
        "export_manifest": {"json": "export_manifest.json"},
    }
    if strategy_spec is not None:
        files["strategy_spec"] = {"json": "strategy_spec_v1.json"}
    artifact_names = [
        "research_report.md",
        "samples.csv",
        "coefficients.csv",
        "validation.csv",
        "outcomes.csv",
        "outcome_matrix.png",
        "strategy_hypothesis_card.json",
    ]
    if strategy_spec is not None:
        artifact_names.append("strategy_spec_v1.json")
    artifact_hashes = {
        name: _sha256(directory / name) for name in artifact_names
    }
    manifest = {
        **snapshot_manifest_as_dict(draft.manifest),
        **({"strategy_spec": strategy_spec} if strategy_spec is not None else {}),
        "snapshot_id": snapshot_id,
        "row_counts": {
            name: len(rows) for name, rows in table_rows.items()
        },
        "files": files,
        "artifact_hashes": artifact_hashes,
    }
    _checkpoint(cancelled, progress, "正在校验研究快照")
    (directory / "export_manifest.json").write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


__all__ = [
    "ResearchSnapshotCancelled",
    "ResearchSnapshotIntegrityError",
    "verify_research_snapshot_package",
    "write_research_snapshot_package",
]
