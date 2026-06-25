from __future__ import annotations

import json

import pandas as pd

from quant_collector_app.research.entry_logic_report import (
    build_entry_logic_report,
    render_entry_logic_markdown,
    write_entry_logic_report,
)


def test_empty_data_generates_report_with_warning():
    report = build_entry_logic_report()
    markdown = render_entry_logic_markdown(report)

    assert "学习用户开仓逻辑，不是收益预测" in markdown
    assert "不是交易信号" in markdown
    assert "empty_input" in report["warnings"]
    assert report["annotation_overview"] == {
        "ENTRY": 0,
        "REJECT": 0,
        "UNCERTAIN": 0,
        "UNLABELED": 0,
    }


def _annotations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "uncertain_1", "unlabeled_1"],
            "human_decision": ["ENTRY", "REJECT", "UNCERTAIN", "UNLABELED"],
        }
    )


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "uncertain_1", "unlabeled_1"],
            "symbol": ["BTCUSDT"] * 4,
            "interval": ["5m"] * 4,
            "bar_time": ["2026-01-01T00:00:00Z", "2026-01-01T00:05:00Z", "2026-01-01T00:10:00Z", "2026-01-01T00:15:00Z"],
            "lower_shadow_ratio": [0.8, 0.2, 0.5, 0.7],
            "volume_zscore_20": [2.0, -1.0, 0.5, 1.5],
        }
    )


def _diagnostic_features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": [f"entry_{index}" for index in range(4)] + [f"reject_{index}" for index in range(4)],
            "symbol": ["BTCUSDT"] * 8,
            "interval": ["5m"] * 8,
            "bar_time": [
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "2026-02-02T00:00:00Z",
                "2026-01-01T00:05:00Z",
                "2026-01-02T00:05:00Z",
                "2026-02-01T00:05:00Z",
                "2026-02-02T00:05:00Z",
            ],
            "lower_shadow_ratio": [0.8, 0.9, 8.0, 9.0, 0.1, 0.2, 0.25, 0.3],
            "volume_zscore_20": [2.0, 2.1, 2.4, 2.8, -0.5, -0.2, 0.0, 0.1],
        }
    )


def _diagnostic_annotations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": [f"entry_{index}" for index in range(4)] + [f"reject_{index}" for index in range(4)],
            "human_decision": ["ENTRY"] * 4 + ["REJECT"] * 4,
        }
    )


def _outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": [f"entry_{index}" for index in range(4)] + [f"reject_{index}" for index in range(4)],
            "fwd_ret_5": [0.02, -0.01, 0.04, -0.03, 0.00, 0.01, -0.02, 0.02],
            "mfe_10": [0.06, 0.03, 0.08, 0.04, 0.02, 0.03, 0.01, 0.04],
            "mae_10": [-0.01, -0.03, -0.02, -0.05, -0.02, -0.01, -0.04, -0.02],
        }
    )


def _scores() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["unlabeled_1", "uncertain_1"],
            "human_entry_similarity": [0.82, 0.51],
        }
    )


def _review_queue() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["unlabeled_1"],
            "human_entry_similarity": [0.82],
            "review_reason": ["high_similarity_to_entry_prototype"],
        }
    )


def test_normal_data_generates_markdown_sections():
    report = build_entry_logic_report(
        annotations_df=_annotations(),
        features_df=_features(),
        scores_df=_scores(),
        review_queue_df=_review_queue(),
        split_summary={"method": "walk_forward", "embargo_bars": 2},
        feature_cols=["lower_shadow_ratio", "volume_zscore_20"],
    )
    markdown = render_entry_logic_markdown(report)

    assert "- ENTRY: 1" in markdown
    assert "BTCUSDT" in markdown
    assert "lower_shadow_ratio" in markdown
    assert "human_entry_similarity" in markdown
    assert "unlabeled_1" in markdown
    assert "walk_forward" in markdown


def test_report_contains_enhanced_diagnostics_rule_hypotheses_and_risk_warnings():
    report = build_entry_logic_report(
        annotations_df=_diagnostic_annotations(),
        features_df=_diagnostic_features(),
        outcomes_df=_outcomes(),
        feature_cols=["lower_shadow_ratio", "volume_zscore_20"],
        outcome_cols=["fwd_ret_5", "mfe_10", "mae_10"],
        top_k=3,
    )
    markdown = render_entry_logic_markdown(report)

    assert report["entry_reject_summary"][0]["quantile_diff_entry_minus_reject"]
    assert report["feature_binning"]
    assert report["rule_hypotheses"]
    assert report["posterior_outcome_by_bin"]
    assert report["outcome_time_series_diagnostics"]
    assert all(row["analysis_role"] == "posterior_outcome_analysis_only" for row in report["posterior_outcome_by_bin"])
    assert "fwd_ret_5" not in report["diagnostic_feature_cols"]
    assert any("sample_size_warning" in warning for warning in report["warnings"])
    assert any("heavy_tail_warning" in warning for warning in report["warnings"])
    assert any("drift_warning" in warning for warning in report["warnings"])
    assert "not a trading signal" in markdown
    assert "buy_signal" not in json.dumps(report, ensure_ascii=False)


def test_normal_data_writes_markdown_and_json(tmp_path):
    report = build_entry_logic_report(
        annotations_df=_annotations(),
        features_df=_features(),
        scores_df=_scores(),
        review_queue_df=_review_queue(),
        feature_cols=["lower_shadow_ratio", "volume_zscore_20"],
    )

    result = write_entry_logic_report(tmp_path / "entry_logic_report.md", tmp_path / "entry_logic_report.json", report)

    assert result["markdown_path"].endswith("entry_logic_report.md")
    assert result["json_path"].endswith("entry_logic_report.json")
    assert "不是交易信号" in (tmp_path / "entry_logic_report.md").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "entry_logic_report.json").read_text(encoding="utf-8"))
    assert payload["annotation_overview"]["ENTRY"] == 1
    assert payload["similarity_score_summary"]["metric"] == "human_entry_similarity"


def test_leakage_check_lists_forbidden_fields_and_report_omits_buy_signal():
    features = _features().assign(fwd_ret_10=[0.1, 0.2, 0.0, -0.1], buy_signal=[0, 0, 1, 0])

    report = build_entry_logic_report(
        annotations_df=_annotations(),
        features_df=features,
        feature_cols=["lower_shadow_ratio", "fwd_ret_10", "buy_signal"],
    )
    markdown = render_entry_logic_markdown(report)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["leakage_check"]["status"] == "FAIL"
    assert "fwd_ret_10" in report["leakage_check"]["forbidden_input_columns_found"]
    assert "future_return" in report["leakage_check"]["forbidden_fields"]
    assert "MFE" in report["leakage_check"]["forbidden_fields"]
    assert "buy_signal" not in markdown
    assert "buy_signal" not in serialized


def test_missing_review_queue_does_not_crash():
    report = build_entry_logic_report(
        annotations_df=_annotations(),
        features_df=_features(),
        scores_df=_scores(),
        feature_cols=["lower_shadow_ratio"],
    )
    markdown = render_entry_logic_markdown(report)

    assert report["review_queue_top_k"] == []
    assert "未提供 review queue" in markdown


def test_report_documents_training_split_and_feature_timing_semantics():
    features = _features().assign(
        setup_bar_index=[10, 11, 12, 13],
        decision_bar_index=[10, 11, 12, 13],
        feature_cutoff_bar_index=[10, 11, 12, 13],
        feature_timing_policy=["current_bar_close"] * 4,
    )
    features.attrs["feature_quality_report"] = {
        "feature_timing_policy": "current_bar_close",
        "allow_confirmation_bar": False,
        "future_cutoff_violation_count": 0,
    }
    report = build_entry_logic_report(
        annotations_df=_annotations(),
        features_df=features,
        scores_df=_scores(),
        review_queue_df=_review_queue(),
        split_summary={
            "split_method": "purged_chronological",
            "train_count": 2,
            "validation_count": 1,
            "test_count": 1,
            "unlabeled_scored_count": 1,
            "purged_count": 3,
            "embargoed_count": 2,
            "episode_leakage_count": 0,
            "horizon_bars": 10,
            "embargo_bars": 2,
        },
        metadata={
            "model_type": "prototype_similarity",
            "selected_threshold": 0.71,
            "threshold_tuning_metric": "precision_at_k",
            "validation_metrics": {"validation_precision_at_k": 1.0},
            "frozen_test_metrics": {"test_precision_at_k": 0.5},
            "review_queue_config": {"name": "high_similarity", "top_k": 5},
        },
        feature_cols=["lower_shadow_ratio", "volume_zscore_20"],
    )
    markdown = render_entry_logic_markdown(report)

    assert report["dataset_summary"]["UNLABELED"] == 1
    assert report["dataset_summary"]["unlabeled_used_for_training"] is False
    assert report["split_summary"]["split_method"] == "purged_chronological"
    assert report["split_summary"]["purged_count"] == 3
    assert report["split_summary"]["embargoed_count"] == 2
    assert report["split_summary"]["episode_leakage_count"] == 0
    assert report["feature_timing_summary"]["allow_confirmation_bar"] is False
    assert report["model_summary"]["selected_threshold"] == 0.71
    assert report["model_summary"]["threshold_tuning_metric"] == "precision_at_k"
    assert "UNLABELED not used for training" in markdown
    assert "validation tunes threshold" in markdown
    assert "test is frozen evaluation" in markdown
    assert "manual review queue, not a trade list" in markdown
    assert "buy_signal" not in markdown