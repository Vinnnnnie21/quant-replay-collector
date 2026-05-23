from __future__ import annotations

import json

import pandas as pd
import pytest

from strategy_consistency.consistency import analyze_strategy_consistency
from strategy_consistency.profile import StrategyProfile, default_reversal_long_profile


def _events(
    n=40,
    mixed=False,
    long_ratio: float | None = None,
    tags: list[str] | None = None,
    untagged=False,
    missing_note=False,
    include_close=True,
):
    rows = []
    tag_values = [] if untagged else (tags if tags is not None else ["长下影", "放量"])
    for i in range(n):
        if long_ratio is not None:
            side = "LONG" if i < int(n * long_ratio) else "SHORT"
        else:
            side = "SHORT" if mixed and i % 2 else "LONG"
        rows.append(
            {
                "event_id": f"e{i}",
                "trade_id": f"t{i}",
                "event_type": "OPEN",
                "side": side,
                "label_tags_json": json.dumps(tag_values, ensure_ascii=False),
                "note": "" if missing_note else f"note {i}",
            }
        )
    if include_close:
        for i in range(max(1, n // 2)):
            rows.append(
                {
                    "event_id": f"c{i}",
                    "trade_id": f"t{i}",
                    "event_type": "CLOSE",
                    "side": "LONG",
                    "label_tags_json": json.dumps(tag_values, ensure_ascii=False),
                    "note": f"close {i}",
                }
            )
    return pd.DataFrame(rows)


def _features(n=40, one_condition_only=False, conflict=False):
    rows = []
    for i in range(n):
        group = i // 2 if conflict else i
        lower_wick = 0.1 if one_condition_only else 0.45
        rows.append(
            {
                "event_id": f"e{i}",
                "pre_ret_20": -0.04 + (group % 5) * 0.001,
                "pre_max_drawdown_20": -0.08 + (group % 4) * 0.001,
                "pre_volatility_20": 0.02 + (group % 3) * 0.001,
                "event_lower_wick_ratio": lower_wick,
                "event_close_position": 0.8,
                "event_volume_ratio_20": 2.0,
                "event_body_ratio": 0.3,
                "capitulation_score": 0.7,
            }
        )
    return pd.DataFrame(rows)


def test_empty_data_safe():
    out = analyze_strategy_consistency(pd.DataFrame(), pd.DataFrame())
    assert out["sample_count"] == 0
    assert out["low_sample_warning"] is True
    assert out["gate_failures"]


def test_long_only_direction_consistency_high():
    out = analyze_strategy_consistency(_events(), _features(), profile=default_reversal_long_profile())
    assert out["direction_consistency_pct"] == 100.0
    assert out["mixed_direction_warning"] is False


def test_long_only_mixed_direction_not_suitable():
    out = analyze_strategy_consistency(_events(mixed=True), _features(), profile=default_reversal_long_profile())
    assert out["direction_consistency_pct"] == 50.0
    assert out["recommendation"] == "not_suitable_for_rule_mining"
    assert any("direction_consistency_pct" in item for item in out["gate_failures"])


def test_long_only_direction_below_70_hard_rejects():
    out = analyze_strategy_consistency(_events(long_ratio=0.65), _features(), profile=default_reversal_long_profile())
    assert out["direction_consistency_pct"] == 65.0
    assert out["recommendation"] == "not_suitable_for_rule_mining"


def test_all_untagged_not_suitable_for_analysis():
    out = analyze_strategy_consistency(_events(untagged=True), _features(), profile=default_reversal_long_profile())
    assert out["high_untagged_warning"] is True
    assert out["recommendation"] != "suitable_for_analysis"
    assert any("untagged_pct" in item for item in out["gate_failures"])


def test_missing_note_above_profile_limit_not_suitable_for_analysis():
    out = analyze_strategy_consistency(_events(missing_note=True), _features(), profile=default_reversal_long_profile())
    assert out["high_missing_note_warning"] is True
    assert out["recommendation"] != "suitable_for_analysis"
    assert any("missing_note_pct" in item for item in out["gate_failures"])


def test_selection_bias_downgrades_suitable_result():
    out = analyze_strategy_consistency(_events(include_close=False), _features(), profile=default_reversal_long_profile())
    assert out["possible_selection_bias_warning"] is True
    assert out["recommendation"] != "suitable_for_analysis"
    assert any("possible_selection_bias_warning" in item for item in out["gate_failures"])


def test_profile_all_match_lower_than_any_when_only_one_condition_matches():
    out = analyze_strategy_consistency(
        _events(),
        _features(one_condition_only=True),
        profile=default_reversal_long_profile(),
    )
    assert out["profile_feature_match_any_pct"] > out["profile_feature_match_all_pct"]
    assert out["profile_feature_match_all_pct"] == 0.0


def test_forbidden_tag_hit_triggers_gate_failure():
    profile = default_reversal_long_profile()
    profile.forbidden_tags = ["追涨"]
    out = analyze_strategy_consistency(_events(tags=["长下影", "追涨"]), _features(), profile=profile)
    assert out["forbidden_tag_hit_count"] > 0
    assert any("forbidden_tag_hit_count" in item for item in out["gate_failures"])


def test_similar_features_but_different_actions_lower_agreement():
    out = analyze_strategy_consistency(
        _events(mixed=True),
        _features(conflict=True),
        profile=default_reversal_long_profile(),
    )
    assert out["similar_context_agreement_pct"] is not None
    assert out["similar_context_agreement_pct"] < 100.0
    assert out["conflict_examples"]


def test_low_sample_warning():
    out = analyze_strategy_consistency(_events(n=5), _features(n=5), profile=default_reversal_long_profile())
    assert out["low_sample_warning"] is True
    assert out["recommendation"] != "suitable_for_analysis"


def test_forbidden_profile_field_raises():
    profile = StrategyProfile(
        strategy_id="bad",
        name="bad",
        description="bad",
        expected_direction="LONG_ONLY",
        expected_market_state="OTHER",
        required_tags=[],
        forbidden_tags=[],
        expected_entry_features={"fwd_ret_10": {"op": ">", "value": 0}},
    )
    with pytest.raises(ValueError):
        analyze_strategy_consistency(_events(), _features(), profile=profile)


def test_forbidden_result_columns_are_not_used_even_if_present():
    profile = StrategyProfile(
        strategy_id="bad",
        name="bad",
        description="bad",
        expected_direction="LONG_ONLY",
        expected_market_state="OTHER",
        required_tags=[],
        forbidden_tags=[],
        expected_entry_features={"mfe_10": {"op": ">", "value": 0}},
    )
    features = _features()
    features["mfe_10"] = 1.0
    features["mae_10"] = -0.01
    features["manual_trade_final_return_pct"] = 1.0
    with pytest.raises(ValueError):
        analyze_strategy_consistency(_events(), features, profile=profile)
