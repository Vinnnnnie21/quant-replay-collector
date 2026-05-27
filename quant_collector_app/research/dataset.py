from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from i18n import tr
from .event_study import build_event_study
from .experiment_tracker import create_manifest
from .factor_audit import leakage_audit
from .factor_binning import build_factor_binning_summary
from .factor_ic import build_factor_ic_summary
from .factor_library import FeatureFactory, METADATA_COLUMNS
from .feature_registry import feature_registry_frame
from .label_registry import LabelFactory, label_registry_frame
from .report import write_research_report
from .rule_search import search_rules
from .walk_forward import build_walk_forward_results


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if pd.isna(value):
        return None
    return value


def _counts(data: pd.DataFrame, column: str) -> dict[str, int]:
    if column not in data.columns:
        return {}
    return {str(key): int(value) for key, value in data[column].fillna("MISSING").value_counts().items()}


def _tag_distribution(events: pd.DataFrame) -> dict[str, int]:
    if events.empty or "label_tags_json" not in events.columns:
        return {}
    counts: dict[str, int] = {}
    for raw in events["label_tags_json"].dropna():
        try:
            tags = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            tags = [raw]
        for tag in tags if isinstance(tags, list) else [tags]:
            counts[str(tag)] = counts.get(str(tag), 0) + 1
    return counts


def sample_size_warning(count: int, language: str = "zh_CN") -> str:
    if count < 30:
        return tr("research.sample.severe", language)
    if count < 100:
        return tr("research.sample.exploratory", language)
    if count < 500:
        return tr("research.sample.initial", language)
    return tr("research.sample.stable", language)


def build_data_audit(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    samples: pd.DataFrame,
    events: pd.DataFrame,
    selected_label: str,
    leakage: dict,
    language: str = "zh_CN",
) -> dict:
    label_values = pd.to_numeric(labels.get(selected_label), errors="coerce") if selected_label in labels.columns else pd.Series(dtype=float)
    valid = int(label_values.notna().sum())
    factor_columns = [column for column in features.columns if column not in METADATA_COLUMNS]
    label_columns = [column for column in labels.columns if column != "event_id"]
    times = pd.to_datetime(features.get("event_time_bjt"), errors="coerce") if "event_time_bjt" in features.columns else pd.Series(dtype="datetime64[ns]")
    duplicates = int(features["event_id"].duplicated().sum()) if "event_id" in features.columns else 0
    return {
        "sample_count": int(len(features)),
        "valid_sample_count": valid,
        "invalid_sample_count": int(len(features) - valid),
        "missing_feature_count": int(features[factor_columns].isna().sum().sum()) if factor_columns else 0,
        "missing_label_count": int(labels[label_columns].isna().sum().sum()) if label_columns else 0,
        "duplicate_event_id_count": duplicates,
        "symbol_distribution": _counts(features, "symbol"),
        "interval_distribution": _counts(features, "interval"),
        "label_tag_distribution": _tag_distribution(events),
        "side_distribution": _counts(features, "side"),
        "event_type_distribution": _counts(features, "event_type"),
        "time_range": {
            "start": str(times.min()) if times.notna().any() else None,
            "end": str(times.max()) if times.notna().any() else None,
        },
        "leakage_audit_status": leakage.get("status"),
        "small_sample_warning": sample_size_warning(int(len(features)), language),
    }


def _label_distribution(labels: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in labels.columns:
        if column == "event_id":
            continue
        values = pd.to_numeric(labels[column], errors="coerce").dropna()
        rows.append(
            {
                "label": column,
                "sample_count": int(len(values)),
                "missing_count": int(labels[column].isna().sum()),
                "mean": float(values.mean()) if len(values) else math.nan,
                "median": float(values.median()) if len(values) else math.nan,
                "positive_rate": float((values > 0).mean() * 100.0) if len(values) else math.nan,
            }
        )
    return pd.DataFrame(rows)


def _write_frame(output_dir: Path, filename: str, frame: pd.DataFrame, files: list[str], json_copy: bool = False) -> None:
    frame.to_csv(output_dir / filename, index=False)
    files.append(filename)
    if json_copy:
        json_name = str(Path(filename).with_suffix(".json"))
        records = frame.where(pd.notna(frame), None).to_dict("records") if not frame.empty else []
        (output_dir / json_name).write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        files.append(json_name)


def _write_audit_markdown(output_dir: Path, audit: dict, language: str) -> None:
    if language == "en_US":
        lines = [
            "# Data Audit",
            "",
            f"- sample_count: {audit['sample_count']}",
            f"- valid_sample_count: {audit['valid_sample_count']}",
            f"- invalid_sample_count: {audit['invalid_sample_count']}",
            f"- duplicate_event_id_count: {audit['duplicate_event_id_count']}",
            f"- leakage_audit_status: {audit['leakage_audit_status']}",
            f"- small_sample_warning: {audit['small_sample_warning']}",
        ]
    else:
        lines = [
            "# 数据审计",
            "",
            f"- 样本数：{audit['sample_count']}",
            f"- 有效样本数：{audit['valid_sample_count']}",
            f"- 无效样本数：{audit['invalid_sample_count']}",
            f"- 重复事件 ID 数：{audit['duplicate_event_id_count']}",
            f"- 未来函数审计状态：{audit['leakage_audit_status']}",
            f"- 小样本警告：{audit['small_sample_warning']}",
        ]
    (output_dir / "data_audit.md").write_text("\n".join(lines), encoding="utf-8")


def run_research_pack(
    output_dir: Path | str,
    event_windows: pd.DataFrame,
    trade_events: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    premium_history: pd.DataFrame | None = None,
    selected_label: str = "fwd_ret_10_side_adj",
    language: str = "zh_CN",
    profile_id: str | None = None,
    profile_version: str | None = None,
    baseline_spec: dict | str | None = None,
    split_spec: dict | str | None = None,
) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    features = FeatureFactory().build(event_windows, trade_events, premium_history)
    labels = LabelFactory().build(event_windows, trade_events, trades)
    leakage = leakage_audit(features)
    if leakage["status"] != "PASS":
        raise ValueError(f"Research feature leakage audit failed: {leakage['forbidden_feature_columns']}")
    samples = features.merge(labels, on="event_id", how="left")
    events_for_sample = trade_events[[column for column in ["event_id", "label_tags_json"] if column in trade_events.columns]]
    if not events_for_sample.empty:
        samples = samples.merge(events_for_sample, on="event_id", how="left")
    audit = build_data_audit(features, labels, samples, trade_events, selected_label, leakage, language)
    label_distribution = _label_distribution(labels)
    event_summary = build_event_study(features, labels, trade_events, selected_label)
    binning = build_factor_binning_summary(features, labels, selected_label)
    ic_summary = build_factor_ic_summary(features, labels, selected_label)
    candidate_rules = search_rules(features, labels, selected_label)
    walk_forward_samples = features.merge(labels[["event_id", selected_label]], on="event_id", how="inner") if selected_label in labels.columns else pd.DataFrame()
    walk_forward = build_walk_forward_results(walk_forward_samples, candidate_rules, selected_label)
    files: list[str] = []
    _write_frame(output_dir, "feature_registry.csv", feature_registry_frame(), files)
    _write_frame(output_dir, "label_registry.csv", label_registry_frame(), files)
    _write_frame(output_dir, "research_samples.csv", samples, files)
    _write_frame(output_dir, "factor_values.csv", features, files)
    _write_frame(output_dir, "label_values.csv", labels, files)
    _write_frame(output_dir, "label_distribution.csv", label_distribution, files, json_copy=True)
    _write_frame(output_dir, "event_study_summary.csv", event_summary, files, json_copy=True)
    _write_frame(output_dir, "factor_binning_summary.csv", binning, files, json_copy=True)
    _write_frame(output_dir, "factor_ic_summary.csv", ic_summary, files, json_copy=True)
    _write_frame(output_dir, "candidate_rules.csv", candidate_rules, files, json_copy=True)
    _write_frame(output_dir, "walk_forward_results.csv", walk_forward, files, json_copy=True)
    (output_dir / "data_audit.json").write_text(json.dumps(_safe_json(audit), ensure_ascii=False, indent=2), encoding="utf-8")
    _write_audit_markdown(output_dir, audit, language)
    (output_dir / "leakage_audit.json").write_text(json.dumps(_safe_json(leakage), ensure_ascii=False, indent=2), encoding="utf-8")
    files.extend(["data_audit.json", "data_audit.md", "leakage_audit.json"])
    manifest = create_manifest(
        samples,
        selected_label,
        [*files, "research_report.md", "research_manifest.json"],
        profile_id=profile_id,
        profile_version=profile_version,
        baseline_spec=baseline_spec,
        split_spec=split_spec,
    )
    write_research_report(
        output_dir / "research_report.md",
        manifest,
        audit,
        leakage,
        label_distribution,
        event_summary,
        binning,
        ic_summary,
        candidate_rules,
        walk_forward,
        language=language,
    )
    (output_dir / "research_manifest.json").write_text(
        json.dumps(_safe_json(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "output_dir": output_dir,
        "manifest": manifest,
        "audit": audit,
        "leakage_audit": leakage,
        "features": features,
        "labels": labels,
        "event_study": event_summary,
        "factor_binning": binning,
        "factor_ic": ic_summary,
        "candidate_rules": candidate_rules,
        "walk_forward": walk_forward,
    }
