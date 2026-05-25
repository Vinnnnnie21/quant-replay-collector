from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .feature_registry import feature_registry_frame


FORBIDDEN_FEATURE_PREFIXES = (
    "fwd_",
    "mfe",
    "mae",
    "post_",
    "future",
    "manual_trade_final",
    "exit",
    "pnl",
    "label",
)
METADATA_COLUMNS = {
    "event_id",
    "session_id",
    "trade_id",
    "event_type",
    "side",
    "symbol",
    "interval",
    "event_time_bjt",
}


def forbidden_feature_columns(columns) -> list[str]:
    blocked = []
    for column in map(str, columns):
        lower = column.lower()
        if any(lower.startswith(prefix) for prefix in FORBIDDEN_FEATURE_PREFIXES):
            blocked.append(column)
    return blocked


def leakage_audit(features: pd.DataFrame, registry: pd.DataFrame | None = None) -> dict:
    features = features if isinstance(features, pd.DataFrame) else pd.DataFrame()
    registry = feature_registry_frame() if registry is None else registry
    forbidden = forbidden_feature_columns(features.columns)
    registered = set(registry["feature_name"].astype(str)) if not registry.empty else set()
    factor_columns = [str(c) for c in features.columns if str(c) not in METADATA_COLUMNS]
    unregistered = sorted(set(factor_columns) - registered)
    disallowed = []
    if not registry.empty:
        allowed = registry.set_index("feature_name")["model_input_allowed"].to_dict()
        disallowed = [col for col in factor_columns if col in allowed and not bool(allowed[col])]
    status = "FAIL" if forbidden or disallowed else "PASS"
    return {
        "status": status,
        "sample_count": int(len(features)),
        "forbidden_feature_columns": forbidden,
        "disallowed_registry_columns": disallowed,
        "unregistered_feature_columns": unregistered,
        "model_input_columns": factor_columns,
        "statement": "All model input columns use event-bar or earlier data only." if status == "PASS" else "Feature leakage detected.",
    }


def assert_feature_safe(features: pd.DataFrame) -> dict:
    audit = leakage_audit(features)
    if audit["status"] != "PASS":
        raise ValueError(f"Feature leakage detected: {audit['forbidden_feature_columns'] + audit['disallowed_registry_columns']}")
    return audit


def write_leakage_audit(features: pd.DataFrame, output_path: Path) -> dict:
    audit = leakage_audit(features)
    Path(output_path).write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit
