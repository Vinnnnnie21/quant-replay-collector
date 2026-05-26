from __future__ import annotations

from test_strategy_consistency_scoring_v2 import _data, _long_profile

from strategy_consistency.consistency import analyze_strategy_consistency


def test_missing_strategy_profile_disables_discipline_scoring():
    events, features, trades = _data()
    result = analyze_strategy_consistency(events, features, trades, profile=None)
    assert result["profile"] is None
    assert result["profile_status"] == "UNDECLARED"
    assert result["audit_mode"] == "DESCRIPTIVE_ONLY"
    assert result["strategy_consistency_score"] is None
    assert result["total_score"] is None
    assert result["component_scores"] == {}


def test_small_closed_sample_caps_score_at_60():
    events, features, trades = _data(count=20)
    result = analyze_strategy_consistency(events, features, trades, _long_profile())
    assert result["total_score"] <= 60.0
    assert "closed_trades < 30: cap 60" in result["caps_applied"]


def test_missing_labels_caps_score_at_55():
    events, features, trades = _data()
    events.loc[events["event_type"] == "OPEN", "label_tags_json"] = "[]"
    result = analyze_strategy_consistency(events, features, trades, _long_profile())
    assert result["total_score"] <= 55.0
    assert "no labels: cap 55" in result["caps_applied"]
