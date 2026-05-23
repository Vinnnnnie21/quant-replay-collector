from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FORBIDDEN_PREFIXES = ("fwd_", "post_")
FORBIDDEN_EXACT = {
    "mfe_10",
    "mae_10",
    "manual_trade_final_return_pct",
    "manual_trade_holding_bars",
}
FORBIDDEN_SUBSTRINGS = ("manual_trade_final", "manual_trade_holding")
LABEL_HINTS = ("fwd_", "mfe", "mae", "manual_trade_final", "manual_trade_holding", "label_")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        out = float(value)
        return out if math.isfinite(out) else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if pd.isna(value):
        return None
    return value


def forbidden_feature_columns(columns: list[str] | pd.Index) -> list[str]:
    out = []
    for col in map(str, columns):
        lower = col.lower()
        if lower.startswith(FORBIDDEN_PREFIXES) or lower in FORBIDDEN_EXACT or any(token in lower for token in FORBIDDEN_SUBSTRINGS):
            out.append(col)
    return out


def _value_counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if df.empty or column not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df[column].fillna("MISSING").value_counts(dropna=False).items()}


def _label_tag_counts(df: pd.DataFrame) -> dict[str, int]:
    if df.empty:
        return {}
    tag_col = "label_tags_json" if "label_tags_json" in df.columns else ("label_tags" if "label_tags" in df.columns else None)
    if not tag_col:
        return {}
    counts: dict[str, int] = {}
    for value in df[tag_col].dropna().tolist():
        tags: list[Any]
        if isinstance(value, list):
            tags = value
        else:
            try:
                parsed = json.loads(str(value))
                tags = parsed if isinstance(parsed, list) else [parsed]
            except Exception:
                tags = [value]
        for tag in tags:
            key = str(tag or "UNTAGGED")
            counts[key] = counts.get(key, 0) + 1
    return counts


def _missing_top(df: pd.DataFrame, limit: int = 20) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows = []
    total = max(len(df), 1)
    for col in df.columns:
        missing = int(df[col].isna().sum())
        rows.append({"column": str(col), "missing_count": missing, "missing_pct": missing / total * 100.0})
    rows.sort(key=lambda r: (-r["missing_pct"], r["column"]))
    return rows[:limit]


def _numeric_bad_values(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for col in df.columns:
        series = pd.to_numeric(df[col], errors="coerce")
        if series.notna().sum() == 0:
            continue
        values = series.to_numpy(dtype=float)
        rows.append(
            {
                "column": str(col),
                "nan_count": int(np.isnan(values).sum()),
                "pos_inf_count": int(np.isposinf(values).sum()),
                "neg_inf_count": int(np.isneginf(values).sum()),
            }
        )
    return rows


def _sample_warning(sample_count: int) -> str:
    if sample_count < 30:
        return "strong_warning"
    if sample_count < 100:
        return "weak_warning"
    return "usable_for_exploration"


def audit_event_features(features: pd.DataFrame) -> dict[str, Any]:
    features = features.copy() if isinstance(features, pd.DataFrame) else pd.DataFrame()
    event_id_unique = True
    duplicate_event_ids: list[str] = []
    if "event_id" in features.columns:
        duplicated = features["event_id"][features["event_id"].duplicated()].dropna().astype(str).unique().tolist()
        duplicate_event_ids = duplicated[:50]
        event_id_unique = len(duplicated) == 0
    return {
        "row_count": int(len(features)),
        "is_empty": bool(features.empty),
        "event_id_unique": event_id_unique,
        "duplicate_event_ids": duplicate_event_ids,
        "event_type_counts": _value_counts(features, "event_type"),
        "side_counts": _value_counts(features, "side"),
        "symbol_counts": _value_counts(features, "symbol"),
        "interval_counts": _value_counts(features, "interval"),
        "label_tag_counts": _label_tag_counts(features),
        "missing_top_20": _missing_top(features),
        "numeric_bad_values": _numeric_bad_values(features),
        "sample_warning": _sample_warning(len(features)),
    }


def audit_ml_dataset(features: pd.DataFrame, labels: pd.DataFrame, sample_index: pd.DataFrame) -> dict[str, Any]:
    features = features.copy() if isinstance(features, pd.DataFrame) else pd.DataFrame()
    labels = labels.copy() if isinstance(labels, pd.DataFrame) else pd.DataFrame()
    sample_index = sample_index.copy() if isinstance(sample_index, pd.DataFrame) else pd.DataFrame()
    leakage_columns = forbidden_feature_columns(features.columns)
    label_columns = [c for c in labels.columns if any(str(c).lower().startswith(prefix) for prefix in LABEL_HINTS) or str(c).lower() in FORBIDDEN_EXACT]
    can_join = False
    missing_in_labels: list[str] = []
    missing_in_index: list[str] = []
    if "event_id" in features.columns:
        feature_ids = set(features["event_id"].dropna().astype(str))
        if "event_id" in labels.columns:
            label_ids = set(labels["event_id"].dropna().astype(str))
            missing_in_labels = sorted(feature_ids - label_ids)[:50]
        if "event_id" in sample_index.columns:
            index_ids = set(sample_index["event_id"].dropna().astype(str))
            missing_in_index = sorted(feature_ids - index_ids)[:50]
        can_join = "event_id" in labels.columns and "event_id" in sample_index.columns and not missing_in_labels and not missing_in_index
    return {
        "ml_features_rows": int(len(features)),
        "ml_labels_rows": int(len(labels)),
        "sample_index_rows": int(len(sample_index)),
        "leakage_columns": leakage_columns,
        "has_leakage": bool(leakage_columns),
        "label_columns": list(map(str, label_columns)),
        "has_label": bool(label_columns),
        "sample_index_join_ok": bool(can_join),
        "missing_feature_ids_in_labels": missing_in_labels,
        "missing_feature_ids_in_sample_index": missing_in_index,
        "sample_warning": _sample_warning(len(features)),
    }


def audit_export_tables(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    tables = tables or {}
    features = tables.get("event_features_full")
    if features is None or features.empty:
        features = tables.get("event_features", pd.DataFrame())
    ml_features = tables.get("ml_features", pd.DataFrame())
    ml_labels = tables.get("ml_labels", tables.get("event_labels", pd.DataFrame()))
    sample_index = tables.get("sample_index", pd.DataFrame())
    events = tables.get("trade_events", pd.DataFrame())
    audit = {
        "table_row_counts": {name: int(len(df)) for name, df in tables.items()},
        "event_features": audit_event_features(features),
        "ml_dataset": audit_ml_dataset(ml_features, ml_labels, sample_index),
        "trade_events": {
            "row_count": int(len(events)),
            "event_type_counts": _value_counts(events, "event_type"),
            "side_counts": _value_counts(events, "side"),
            "symbol_counts": _value_counts(events, "symbol"),
            "interval_counts": _value_counts(events, "interval"),
            "label_tag_counts": _label_tag_counts(events),
        },
    }
    warnings = []
    if audit["event_features"]["is_empty"]:
        warnings.append("event_features is empty")
    if not audit["event_features"]["event_id_unique"]:
        warnings.append("event_features contains duplicate event_id")
    if audit["ml_dataset"]["has_leakage"]:
        warnings.append("ml_features contains future/label leakage columns")
    if not audit["ml_dataset"]["has_label"]:
        warnings.append("ml_labels does not contain label columns")
    audit["warnings"] = warnings
    audit["sample_warning"] = _sample_warning(int(audit["event_features"]["row_count"]))
    return audit


def write_audit_report(audit: dict[str, Any], output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_audit = _json_safe(audit)
    (output_dir / "analysis_audit.json").write_text(json.dumps(safe_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Analysis Audit",
        "",
        "本报告用于检查导出样本的数据质量和未来函数隔离状态。",
        "",
        f"- 样本量状态：{audit.get('sample_warning')}",
        f"- 警告数量：{len(audit.get('warnings', []))}",
        "",
        "## Warnings",
        "",
    ]
    warnings = audit.get("warnings", [])
    lines.extend([f"- {w}" for w in warnings] or ["- 无"])
    ef = audit.get("event_features", {})
    ml = audit.get("ml_dataset", {})
    lines.extend(
        [
            "",
            "## Event Features",
            "",
            f"- 行数：{ef.get('row_count', 0)}",
            f"- event_id 唯一：{ef.get('event_id_unique')}",
            f"- 样本量状态：{ef.get('sample_warning')}",
            "",
            "## ML Dataset",
            "",
            f"- 特征行数：{ml.get('ml_features_rows', 0)}",
            f"- 标签行数：{ml.get('ml_labels_rows', 0)}",
            f"- 样本索引行数：{ml.get('sample_index_rows', 0)}",
            f"- 泄漏字段：{', '.join(ml.get('leakage_columns', [])) or '无'}",
            f"- 有标签字段：{ml.get('has_label')}",
            f"- event_id 可连接：{ml.get('sample_index_join_ok')}",
            "",
            "## Missing Top 20",
            "",
        ]
    )
    for item in ef.get("missing_top_20", []):
        lines.append(f"- {item['column']}: {item['missing_pct']:.2f}% ({item['missing_count']})")
    (output_dir / "analysis_audit.md").write_text("\n".join(lines), encoding="utf-8")

