from __future__ import annotations

import ast
import json
from pathlib import Path

from app_i18n import tr


APP_DIR = Path(__file__).resolve().parents[1] / "quant_collector_app"
TRANSLATION_DIR = APP_DIR / "translations"


def test_i18n_major_keys_return_chinese_and_english():
    keys = [
        "market_data",
        "replay_control",
        "trade_actions",
        "event_tags_notes",
        "apply_market",
        "market_params_dirty_hint",
        "apply_market_before_play",
        "bar_time",
        "bar_open",
        "bar_high",
        "bar_low",
        "bar_close",
        "bar_volume",
        "bar_index",
        "current_bar_details",
        "step_next",
        "jump_to_end",
        "follow_latest",
        "reset_view",
        "open_long",
        "open_short",
        "close_long",
        "close_short",
        "clear_trade_records",
        "clear_trade_records_title",
        "clear_trade_records_warning",
        "clear_trade_records_phrase_prompt",
        "clear_trade_records_phrase",
        "clear_trade_records_phrase_mismatch",
        "clear_trade_records_busy",
        "clear_trade_records_done",
        "clear_trade_records_failed",
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
    assert tr("apply_market", "zh_CN") == "应用行情"
    assert tr("apply_market", "en_US") == "Apply Market"
    assert tr("bar_volume", "zh_CN") == "成交量"
    assert tr("bar_volume", "en_US") == "Volume"


def test_i18n_missing_key_returns_default():
    assert tr("missing_key", "zh_CN", default="fallback") == "fallback"
    assert tr("missing_key", "zh_CN") == "missing_key"


def test_app_i18n_is_resource_facade_only():
    import app_i18n

    assert not hasattr(app_i18n, "TRANSLATIONS")
    assert app_i18n.tr("data_analysis", "zh_CN") == "数据分析"


def test_translation_json_has_no_duplicate_keys_and_same_key_set():
    key_sets = {}
    for language in ("zh_CN", "en_US"):
        pairs_seen: set[str] = set()
        duplicates: list[str] = []

        def reject_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in pairs_seen:
                    duplicates.append(key)
                pairs_seen.add(key)
                result[key] = value
            return result

        path = TRANSLATION_DIR / f"{language}.json"
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
        assert duplicates == []
        key_sets[language] = set(payload)
    assert key_sets["zh_CN"] == key_sets["en_US"]


def test_literal_translation_keys_exist_in_resources():
    resources = {
        language: json.loads((TRANSLATION_DIR / f"{language}.json").read_text(encoding="utf-8"))
        for language in ("zh_CN", "en_US")
    }
    missing: list[tuple[str, int, str, str]] = []
    for path in APP_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            is_translation_call = (
                isinstance(func, ast.Name)
                and func.id in {"tr", "_tr"}
                or isinstance(func, ast.Attribute)
                and func.attr in {"tr", "_tr"}
            )
            first_arg = node.args[0]
            if not is_translation_call or not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
                continue
            key = first_arg.value
            for language, table in resources.items():
                if key not in table:
                    missing.append((str(path.relative_to(APP_DIR)), node.lineno, language, key))
    assert missing == []
