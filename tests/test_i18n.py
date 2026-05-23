from __future__ import annotations

from app_i18n import tr


def test_i18n_major_keys_return_chinese_and_english():
    keys = [
        "market_data",
        "replay_control",
        "trade_actions",
        "event_tags_notes",
        "load_klines",
        "step_next",
        "jump_to_end",
        "follow_latest",
        "reset_view",
        "open_long",
        "open_short",
        "close_long",
        "close_short",
        "undo",
        "redo",
        "current_positions",
        "events",
        "details",
        "export_session",
        "data_analysis",
        "settings",
        "run_consistency_audit",
        "export_consistency_report",
        "refresh",
        "no_session_data",
        "settings_center",
        "appearance_settings",
        "language_settings",
        "execution_cost_settings",
        "ai_api_settings",
        "save_and_apply",
        "cancel",
        "consistency_audit_title",
        "consistency_not_run_hint",
        "consistency_score",
        "recommendation",
        "sample_count",
        "direction_consistency_pct",
        "untagged_pct",
        "missing_note_pct",
        "similar_context_agreement_pct",
        "profile_feature_match_all_pct",
        "feature_source",
        "gate_failures",
        "warnings",
        "none",
        "consistency_disclaimer",
        "consistency_audit_failed",
        "select_consistency_export_dir",
        "consistency_exported",
        "consistency_export_failed",
        "warning_low_sample_count",
        "warning_mixed_direction",
        "warning_high_untagged",
        "warning_high_missing_note",
        "warning_low_similar_context_agreement",
        "warning_possible_selection_bias",
        "warning_forbidden_tags",
    ]
    for key in keys:
        assert tr(key, "zh_CN") != key
        assert tr(key, "en_US") != key
    assert tr("data_analysis", "zh_CN") == "数据分析"
    assert tr("data_analysis", "en_US") == "Data Analysis"


def test_i18n_missing_key_returns_default():
    assert tr("missing_key", "zh_CN", default="fallback") == "fallback"
    assert tr("missing_key", "zh_CN") == "missing_key"
