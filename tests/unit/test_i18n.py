from __future__ import annotations

import ast
import json
from pathlib import Path

from app_i18n import tr
from project_paths import APP_DIR


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
        "trade_data_management_session_group",
        "trade_data_management_range_group",
        "delete_session_trade_phrase_prompt",
        "delete_session_trade_phrase",
        "delete_performance_session_phrase",
        "delete_performance_session_phrase_prompt",
        "delete_performance_session_title",
        "continue_performance_session",
        "continue_performance_session_busy",
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
    assert tr("delete_session_trade_phrase", "zh_CN") == "DELETE TRADE"
    assert tr("delete_trade_range_phrase", "zh_CN") == "DELETE RANGE"


def test_i18n_missing_key_returns_default():
    assert tr("missing_key", "zh_CN", default="fallback") == "fallback"
    assert tr("missing_key", "zh_CN") == "missing_key"


def test_english_missing_key_never_falls_back_to_chinese(monkeypatch):
    import i18n as resource_i18n

    tables = {
        "zh_CN": {"zh_only": "仅中文"},
        "en_US": {},
    }
    monkeypatch.setattr(
        resource_i18n,
        "load_translations",
        lambda language: tables[language],
    )

    assert resource_i18n.tr("zh_only", "en_US") == "zh_only"


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


def test_primary_ui_modules_do_not_hardcode_user_visible_language_text():
    paths = [
        APP_DIR / "analysis_workspace.py",
        APP_DIR / "app_health.py",
        APP_DIR / "backtest_panel.py",
        APP_DIR / "main_app.py",
        APP_DIR / "premium_monitor.py",
        APP_DIR / "settings_dialog.py",
        APP_DIR / "controllers" / "analysis_controller.py",
        APP_DIR / "controllers" / "daily_backup_controller.py",
        APP_DIR / "controllers" / "export_task_controller.py",
        APP_DIR / "controllers" / "historical_performance_controller.py",
        APP_DIR / "controllers" / "market_data_controller.py",
        APP_DIR / "controllers" / "replay_ui_controller.py",
        APP_DIR / "controllers" / "trade_action_controller.py",
        APP_DIR / "controllers" / "session_resume_controller.py",
        APP_DIR / "controllers" / "trade_record_controller.py",
        APP_DIR / "multi_timeframe_panel.py",
        APP_DIR / "presenters" / "status_presenter.py",
        APP_DIR / "presenters" / "table_presenter.py",
        APP_DIR / "render" / "chart_render_adapter.py",
        APP_DIR / "views" / "date_picker.py",
        APP_DIR / "views" / "main_window_layout.py",
        APP_DIR / "views" / "main_window_connections.py",
        APP_DIR / "views" / "main_window_presentation.py",
        APP_DIR / "views" / "nullable_percent_input.py",
        APP_DIR / "views" / "performance_trade_table.py",
        APP_DIR / "views" / "theme_dialog.py",
        APP_DIR / "views" / "windows_title_bar.py",
        APP_DIR / "strategy_consistency_panel.py",
    ]
    text_methods = {
        "setText",
        "setPlainText",
        "setPlaceholderText",
        "setToolTip",
        "setWindowTitle",
        "setTitle",
        "addRow",
        "_log",
    }
    widget_constructors = {
        "QLabel",
        "QPushButton",
        "QToolButton",
        "QCheckBox",
        "QRadioButton",
        "QGroupBox",
    }
    allowed = {"-", "●", "‹", "›", "▾", "#21b26f"}
    hardcoded: list[tuple[str, int, str]] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            indexes: tuple[int, ...] = ()
            if name in text_methods or name in widget_constructors:
                indexes = (0,)
            elif name in {"addTab", "setTabText"}:
                indexes = (1,)
            elif name in {"getOpenFileName", "getExistingDirectory", "getColor"}:
                indexes = (1,)
            elif name in {"information", "warning", "critical", "question"}:
                indexes = (1, 2)
            for index in indexes:
                if index >= len(node.args):
                    continue
                arg = node.args[index]
                values: list[str] = []
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    values.append(arg.value)
                elif isinstance(arg, ast.JoinedStr):
                    values.extend(
                        part.value
                        for part in ast.walk(arg)
                        if isinstance(part, ast.Constant) and isinstance(part.value, str)
                        and (
                            any("\u4e00" <= char <= "\u9fff" for char in part.value)
                            or part.value.strip().lower() == "sample"
                        )
                    )
                for raw_value in values:
                    value = raw_value.strip()
                    if value in allowed or not value or not any(char.isalpha() for char in value):
                        continue
                    hardcoded.append((str(path.relative_to(APP_DIR)), node.lineno, value))

    assert hardcoded == []


def test_english_translation_values_do_not_contain_chinese_characters():
    translations = json.loads((TRANSLATION_DIR / "en_US.json").read_text(encoding="utf-8"))
    mixed = {
        key: value
        for key, value in translations.items()
        if any("\u4e00" <= char <= "\u9fff" for char in value)
    }

    assert mixed == {}


def test_dynamic_analysis_and_backtest_column_keys_exist_in_both_languages():
    from analysis_workspace import (
        AUDIT_COLUMNS,
        AUDIT_METRICS,
        ENTRY_REVIEW_QUEUE_COLUMNS,
        EVENT_STUDY_COLUMNS,
        FACTOR_BINNING_COLUMNS,
        FACTOR_IC_COLUMNS,
        RULE_COLUMNS,
        WALK_FORWARD_COLUMNS,
    )
    from presenters.backtest_presenter import (
        COMPARISON_COLUMNS,
        EQUITY_COLUMNS,
        TRADE_COLUMNS,
    )

    research_columns = {
        column
        for group in (
            AUDIT_COLUMNS,
            AUDIT_METRICS,
            ENTRY_REVIEW_QUEUE_COLUMNS,
            EVENT_STUDY_COLUMNS,
            FACTOR_BINNING_COLUMNS,
            FACTOR_IC_COLUMNS,
            RULE_COLUMNS,
            WALK_FORWARD_COLUMNS,
        )
        for column in group
    }
    keys = {
        *(f"research.column.{column}" for column in research_columns),
        *(f"backtest.column.{column}" for column in TRADE_COLUMNS),
        *(f"backtest.column.{column}" for column in EQUITY_COLUMNS),
        *(f"backtest.comparison.{column}" for column in COMPARISON_COLUMNS),
    }
    missing = {
        language: sorted(key for key in keys if tr(key, language) == key)
        for language in ("zh_CN", "en_US")
    }

    assert missing == {"zh_CN": [], "en_US": []}
