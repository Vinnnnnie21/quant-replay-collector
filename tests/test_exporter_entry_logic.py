from __future__ import annotations

import json

import pandas as pd

from exporter import Exporter
from test_exporter_basic import insert_complete_trade, insert_session, make_storage
from test_storage_trade_flow import INTERVAL, SESSION_ID, SYMBOL


def _entry_logic_payload(session_id: str) -> dict[str, object]:
    assert session_id == SESSION_ID
    return {
        "entry_annotations": pd.DataFrame(
            [
                {
                    "annotation_id": "ann_1",
                    "session_id": SESSION_ID,
                    "observation_id": "obs_10",
                    "symbol": SYMBOL,
                    "interval": INTERVAL,
                    "bar_index": 10,
                    "bar_time": "2026-01-01T00:50:00Z",
                    "human_decision": "ENTRY",
                    "confidence": 5,
                    "reason_tags": "lower_shadow,volume_spike",
                    "note": "manual review",
                    "decision_timing": "CURRENT_BAR_CLOSE",
                    "created_at": "2026-01-02T00:00:00Z",
                    "app_version": "test",
                }
            ]
        ),
        "entry_observation_universe": pd.DataFrame(
            [
                {
                    "observation_id": "obs_10",
                    "symbol": SYMBOL,
                    "interval": INTERVAL,
                    "bar_index": 10,
                    "bar_time": "2026-01-01T00:50:00Z",
                    "eligible_for_review": True,
                    "candidate_reason": "loose_reversal_candidate",
                    "decision_timing": "CURRENT_BAR_CLOSE",
                    "source": "test",
                }
            ]
        ),
        "entry_context_features": pd.DataFrame(
            [
                {
                    "observation_id": "obs_10",
                    "symbol": SYMBOL,
                    "interval": INTERVAL,
                    "bar_index": 10,
                    "bar_time": "2026-01-01T00:50:00Z",
                    "setup_bar_index": 10,
                    "decision_bar_index": 10,
                    "feature_cutoff_bar_index": 10,
                    "feature_timing_policy": "current_bar_close",
                    "prior_ret_5": -0.04,
                    "lower_shadow_ratio": 0.72,
                    "volume_zscore_20": 2.4,
                    "fwd_ret_10": 0.15,
                    "mfe_10": 0.2,
                    "buy_signal": 1,
                }
            ]
        ),
        "entry_outcome_labels": pd.DataFrame(
            [
                {
                    "observation_id": "obs_10",
                    "fwd_ret_5": 0.03,
                    "mfe_10": 0.06,
                    "mae_10": -0.02,
                    "hit_tp_10": True,
                    "hit_sl_10": False,
                }
            ]
        ),
        "entry_logic_scores": pd.DataFrame(
            [
                {
                    "observation_id": "obs_10",
                    "human_entry_similarity": 0.86,
                    "setup_confidence": 0.82,
                    "nearest_entry_pattern": "",
                    "explanation_features": "lower_shadow_ratio,volume_zscore_20",
                }
            ]
        ),
        "entry_review_queue": pd.DataFrame(
            [
                {
                    "observation_id": "obs_10",
                    "human_entry_similarity": 0.86,
                    "setup_confidence": 0.82,
                    "review_reason": "high_similarity",
                    "review_mode": "high_similarity",
                }
            ]
        ),
        "split_summary": {"method": "walk_forward", "embargo_bars": 2},
    }


def _export_with_storage(tmp_path, provider=None):
    storage = make_storage(tmp_path)
    insert_session(storage)
    insert_complete_trade(storage)
    exporter = Exporter(storage, entry_logic_provider=provider) if provider else Exporter(storage)
    return exporter.export_session(SESSION_ID, tmp_path / "exports")


def test_export_session_writes_optional_entry_logic_files(tmp_path):
    export_dir = _export_with_storage(tmp_path, _entry_logic_payload)

    expected = [
        "entry_annotations.csv",
        "entry_observation_universe.csv",
        "entry_context_features.csv",
        "entry_outcome_labels.csv",
        "entry_logic_scores.csv",
        "entry_review_queue.csv",
        "entry_logic_report.md",
        "entry_logic_report.json",
    ]
    for filename in expected:
        assert (export_dir / filename).exists(), filename

    context = pd.read_csv(export_dir / "entry_context_features.csv")
    forbidden_context = [
        column
        for column in context.columns
        if column.startswith(("fwd_", "future"))
        or column.lower() in {"future_return", "mfe_10", "mae_10", "hit_tp_10", "hit_sl_10", "buy_signal", "sell_signal"}
    ]
    assert forbidden_context == []

    outcomes = pd.read_csv(export_dir / "entry_outcome_labels.csv")
    assert "fwd_ret_5" in outcomes.columns
    assert "mfe_10" in outcomes.columns

    dictionary = (export_dir / "data_dictionary.md").read_text(encoding="utf-8")
    assert "entry_context_features" in dictionary
    assert "model input candidate" in dictionary
    assert "entry_outcome_labels" in dictionary
    assert "must not be used as model input" in dictionary
    assert "decision-time input candidate" in dictionary
    assert "post-event labels" in dictionary
    assert "human-entry similarity" in dictionary
    assert "manual review queue" in dictionary
    assert "not a trade list" in dictionary
    lowered_dictionary = dictionary.lower()
    assert "buy_signal" not in lowered_dictionary
    assert "trade_signal" not in lowered_dictionary

    manifest = json.loads((export_dir / "export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"]["entry_annotations"] == 1
    assert manifest["files"]["entry_logic_report"]["markdown"] == "entry_logic_report.md"
    assert manifest["files"]["entry_logic_report"]["json"] == "entry_logic_report.json"

    report = json.loads((export_dir / "entry_logic_report.json").read_text(encoding="utf-8"))
    assert any(str(warning).startswith("feature_quality:") for warning in report["warnings"])


def test_export_session_without_entry_logic_data_exports_empty_optional_tables(tmp_path):
    export_dir = _export_with_storage(tmp_path)

    manifest = json.loads((export_dir / "export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"]["entry_annotations"] == 0
    assert manifest["row_counts"]["entry_context_features"] == 0
    assert (export_dir / "entry_annotations.csv").exists()
    assert (export_dir / "entry_logic_report.md").exists()


def test_entry_logic_parquet_failure_keeps_csv_exports(tmp_path, monkeypatch):
    def fail_to_parquet(self, *args, **kwargs):
        raise RuntimeError("parquet engine failed")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_to_parquet)

    export_dir = _export_with_storage(tmp_path, _entry_logic_payload)

    assert (export_dir / "entry_annotations.csv").exists()
    assert (export_dir / "entry_context_features.csv").exists()
    manifest = json.loads((export_dir / "export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["entry_annotations"]["parquet_status"] == "failed"
    assert "parquet" not in manifest["files"]["entry_annotations"]
