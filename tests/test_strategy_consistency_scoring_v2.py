from __future__ import annotations

import json

import pandas as pd

from strategy_consistency.consistency import analyze_strategy_consistency
from strategy_consistency.profile import StrategyProfile
from strategy_consistency.report import write_strategy_consistency_report


def _data(count: int = 60, side: str = "LONG"):
    events = []
    features = []
    trades = []
    for index in range(count):
        events.append(
            {
                "event_id": f"open_{index}",
                "trade_id": f"trade_{index}",
                "event_type": "OPEN",
                "side": side,
                "label_tags_json": json.dumps(["反转", "放量"], ensure_ascii=False),
                "note": "entry",
            }
        )
        events.append(
            {
                "event_id": f"close_{index}",
                "trade_id": f"trade_{index}",
                "event_type": "CLOSE",
                "side": side,
                "label_tags_json": "[]",
                "note": "exit",
            }
        )
        features.append(
            {
                "event_id": f"open_{index}",
                "pre_ret_5": -0.01,
                "pre_ret_10": -0.02,
                "pre_ret_20": -0.03,
                "event_lower_wick_ratio": 0.5,
                "event_close_position": 0.8,
                "event_volume_ratio_20": 2.0,
            }
        )
        trades.append(
            {
                "trade_id": f"trade_{index}",
                "status": "CLOSED",
                "fee_bps": 4.0,
                "slippage_bps": 1.0,
                "exit_reason": "profile_exit",
            }
        )
    return pd.DataFrame(events), pd.DataFrame(features), pd.DataFrame(trades)


def _long_profile() -> StrategyProfile:
    return StrategyProfile(
        name="Long only",
        allowed_sides=["LONG"],
        required_entry_tags=["反转"],
        risk_model="fixed_stop_take",
        stop_loss_pct=1.0,
        take_profit_pct=2.0,
        max_holding_bars=20,
        allowed_intervals=["1m"],
    )


def test_declared_long_only_does_not_lose_direction_points():
    events, features, trades = _data()
    result = analyze_strategy_consistency(events, features, trades, _long_profile())
    assert result["component_scores"]["direction_discipline"] == 10.0
    assert result["directional_coverage_warning"] is False


def test_leakage_failure_invalidates_score():
    events, features, trades = _data()
    result = analyze_strategy_consistency(events, features, trades, _long_profile(), leakage_audit_status="FAIL")
    assert result["total_score"] is None
    assert result["recommendation"] == "invalid_due_to_leakage"


def test_no_profile_single_direction_receives_only_limited_direction_points():
    events, features, trades = _data()
    result = analyze_strategy_consistency(events, features, trades, profile=None)
    assert result["component_scores"]["direction_discipline"] == 3.0
    assert "direction discipline cannot be fully evaluated without a strategy profile" in result["warnings"]


def test_two_sided_profile_reports_missing_direction_coverage():
    events, features, trades = _data()
    profile = _long_profile()
    profile.allowed_sides = ["LONG", "SHORT"]
    result = analyze_strategy_consistency(events, features, trades, profile)
    assert result["component_scores"]["direction_discipline"] <= 6.0
    assert result["directional_coverage_warning"] is True


def test_report_explains_single_direction_and_behavior_proxy(tmp_path):
    events, features, trades = _data()
    result = analyze_strategy_consistency(events, features, trades, profile=None)
    path = write_strategy_consistency_report(result, tmp_path / "consistency.md")
    text = path.read_text(encoding="utf-8")
    assert "只做多/只做空不是一致性问题" in text
    assert "无 StrategyProfile 时，方向纪律无法充分评价" in text
    assert "行为稳定性近似诊断" in text
    assert "硬性门槛失败项" in text
    assert "no StrategyProfile: cap 65" not in text
