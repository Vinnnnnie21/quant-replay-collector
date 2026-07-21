from __future__ import annotations

import json

import pandas as pd

from quant_collector_app.research.weekly_research_report import (
    build_weekly_research_report,
    render_weekly_research_markdown,
    write_weekly_research_report,
)


WEEK_START = "2026-06-08T00:00:00Z"
WEEK_END = "2026-06-15T00:00:00Z"


def test_empty_week_data_generates_warning_report():
    report = build_weekly_research_report(week_start=WEEK_START, week_end=WEEK_END)
    markdown = render_weekly_research_markdown(report)

    assert report["warnings"]
    assert "empty_week_data" in report["warnings"]
    assert "不是交易信号" in markdown
    assert "buy_signal" not in markdown


def _annotations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "uncertain_1", "old_entry"],
            "human_decision": ["ENTRY", "REJECT", "UNCERTAIN", "ENTRY"],
            "created_at": [
                "2026-06-10T10:00:00Z",
                "2026-06-11T10:00:00Z",
                "2026-06-12T10:00:00Z",
                "2026-06-03T10:00:00Z",
            ],
            "updated_at": [
                "2026-06-10T10:00:00Z",
                "2026-06-11T10:00:00Z",
                "2026-06-12T10:00:00Z",
                "2026-06-03T10:00:00Z",
            ],
            "reason_tags": [
                ["long_lower_shadow", "volume_spike"],
                ["weak_reclaim"],
                ["long_lower_shadow"],
                ["volume_spike"],
            ],
        }
    )


def _annotation_history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "annotation_id": ["ann_entry_1", "ann_reject_1", "ann_old"],
            "operation": ["UPDATE", "SOFT_DELETE", "UPDATE"],
            "changed_at": [
                "2026-06-10T12:00:00Z",
                "2026-06-11T12:00:00Z",
                "2026-06-04T12:00:00Z",
            ],
        }
    )


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "uncertain_1", "old_entry"],
            "bar_time": [
                "2026-06-10T10:00:00Z",
                "2026-06-11T10:00:00Z",
                "2026-06-12T10:00:00Z",
                "2026-06-03T10:00:00Z",
            ],
            "lower_shadow_ratio": [0.82, 0.22, 0.51, 0.61],
            "volume_zscore_20": [2.4, -0.4, 0.7, 1.1],
        }
    )


def _previous_features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["old_entry", "old_reject"],
            "bar_time": ["2026-06-03T10:00:00Z", "2026-06-04T10:00:00Z"],
            "lower_shadow_ratio": [0.20, 0.18],
            "volume_zscore_20": [0.1, 0.2],
        }
    )


def _outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "uncertain_1"],
            "fwd_ret_5": [0.04, -0.03, 0.01],
            "mfe_10": [0.08, 0.01, 0.03],
            "mae_10": [-0.02, -0.05, -0.01],
        }
    )


def _scores() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "uncertain_1"],
            "human_entry_similarity": [0.20, 0.91, 0.52],
            "scored_at": [
                "2026-06-10T10:30:00Z",
                "2026-06-11T10:30:00Z",
                "2026-06-12T10:30:00Z",
            ],
        }
    )


def _previous_scores() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["old_entry", "old_reject"],
            "human_entry_similarity": [0.66, 0.34],
            "scored_at": ["2026-06-03T10:30:00Z", "2026-06-04T10:30:00Z"],
        }
    )


def _review_queue() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "pending_1", "reject_1"],
            "queue_status": ["completed", "pending", "completed"],
            "human_entry_similarity": [0.20, 0.54, 0.91],
        }
    )


def test_weekly_report_counts_tags_drift_outcomes_and_review_samples():
    report = build_weekly_research_report(
        week_start=WEEK_START,
        week_end=WEEK_END,
        annotations_df=_annotations(),
        annotation_history_df=_annotation_history(),
        features_df=_features(),
        previous_features_df=_previous_features(),
        outcomes_df=_outcomes(),
        scores_df=_scores(),
        previous_scores_df=_previous_scores(),
        review_queue_df=_review_queue(),
        feature_cols=["lower_shadow_ratio", "volume_zscore_20"],
        outcome_cols=["fwd_ret_5", "mfe_10", "mae_10"],
    )
    markdown = render_weekly_research_markdown(report)
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["weekly_annotation_summary"]["new_annotation_count"] == 3
    assert report["weekly_annotation_summary"]["decision_counts"]["ENTRY"] == 1
    assert report["weekly_annotation_summary"]["decision_counts"]["REJECT"] == 1
    assert report["weekly_annotation_summary"]["decision_counts"]["UNCERTAIN"] == 1
    assert report["weekly_annotation_summary"]["modification_count"] == 2
    assert report["reason_tag_summary"][0]["reason_tag"] == "long_lower_shadow"
    assert report["review_queue_summary"]["completion_rate"] == 2 / 3
    assert report["posterior_outcome_risk_summary"]
    assert all(item["analysis_role"] == "posterior_only_not_model_input" for item in report["posterior_outcome_risk_summary"])
    assert report["manual_review_samples"]["high_similarity_reject"][0]["observation_id"] == "reject_1"
    assert report["manual_review_samples"]["low_similarity_entry"][0]["observation_id"] == "entry_1"
    assert "后验结果不代表未来收益" in markdown
    assert "buy_signal" not in markdown
    assert "buy_signal" not in serialized
    assert any("drift" in warning for warning in report["warnings"])


def test_weekly_report_warns_when_drift_sample_is_too_small():
    report = build_weekly_research_report(
        week_start=WEEK_START,
        week_end=WEEK_END,
        annotations_df=_annotations().iloc[:1],
        features_df=_features().iloc[:1],
        previous_features_df=pd.DataFrame(),
        feature_cols=["lower_shadow_ratio"],
    )

    assert any("drift_sample_insufficient" in warning for warning in report["warnings"])


def test_weekly_report_can_be_saved_to_reports_or_experiments_directory(tmp_path):
    report = build_weekly_research_report(
        week_start=WEEK_START,
        week_end=WEEK_END,
        annotations_df=_annotations(),
        features_df=_features(),
        scores_df=_scores(),
        feature_cols=["lower_shadow_ratio"],
    )

    result = write_weekly_research_report(tmp_path / "reports", report)

    markdown_path = tmp_path / "reports" / "weekly_research_report.md"
    json_path = tmp_path / "reports" / "weekly_research_report.json"
    assert result["markdown_path"] == str(markdown_path)
    assert result["json_path"] == str(json_path)
    assert markdown_path.exists()
    assert json_path.exists()
    assert "不是交易信号" in markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["weekly_annotation_summary"]["new_annotation_count"] == 3
