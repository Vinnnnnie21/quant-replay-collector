from __future__ import annotations

import json

import pandas as pd

from analysis.llm_context import build_llm_context


class FakeStorage:
    def __init__(self):
        self.tables = {
            "sessions": [
                {
                    "session_id": "sess_1",
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "db_path": "C:/should/not/leak.db",
                    "initial_equity": 10000.0,
                }
            ],
            "trades": [
                {
                    "trade_id": "t1",
                    "status": "CLOSED",
                    "side": "LONG",
                    "net_return_pct": 1.0,
                    "holding_bars": 5,
                }
            ],
            "trade_events": [{"event_id": f"e{i}"} for i in range(3)],
            "account_equity": [{"equity_after": 10010.0, "equity_return_pct": 0.1}],
        }

    def fetch_table(self, table, where="", params=()):
        return self.tables.get(table, [])


def test_llm_context_is_limited_and_safe(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    pd.DataFrame([{"feature": f"f{i}", "sample_count": i} for i in range(5)]).to_csv(
        export_dir / "feature_binning_summary.csv", index=False
    )
    pd.DataFrame([{"rule_text": f"rule_{i}", "sample_count": 30 + i} for i in range(5)]).to_csv(
        export_dir / "candidate_rules.csv", index=False
    )
    (export_dir / "backtest_metrics.json").write_text(
        json.dumps({"total_return_pct": 1.2, "win_rate_pct": 55.0, "secret_path": str(tmp_path)}),
        encoding="utf-8",
    )
    pd.DataFrame([{"params_json": f"p{i}", "sharpe": i} for i in range(5)]).to_csv(
        export_dir / "parameter_scan_results.csv", index=False
    )
    (export_dir / "walk_forward_summary.json").write_text(
        json.dumps(
            {
                "selected_params": {"fast_window": 5},
                "objective": "sharpe",
                "test_result": {"sharpe": 0.4},
                "valid_results": [{"params_json": f"v{i}", "sharpe": i} for i in range(5)],
                "train_results": [{"params_json": f"t{i}", "sharpe": i} for i in range(5)],
                "warnings": ["test once only"],
            }
        ),
        encoding="utf-8",
    )
    (export_dir / "strategy_consistency.json").write_text(
        json.dumps(
            {
                "strategy_consistency_score": 81.0,
                "recommendation": "suitable_for_analysis",
                "sample_count": 40,
                "direction_consistency_pct": 100.0,
                "similar_context_agreement_pct": 85.0,
                "high_untagged_warning": False,
                "possible_random_trading_warning": False,
                "possible_selection_bias_warning": True,
                "gate_failures": ["possible_selection_bias_warning is true"],
                "label_score_detail": {"label_score_pct": 75.0},
                "profile_feature_match_all_pct": 80.0,
            }
        ),
        encoding="utf-8",
    )
    (export_dir / "time_series_summary.json").write_text(
        json.dumps(
            {
                "source": "event_windows_only",
                "return_distribution": {
                    "sample_count": 41,
                    "mean_return": 0.001,
                    "std_return": 0.01,
                    "skewness": 0.2,
                    "kurtosis": 1.5,
                    "autocorr_lag_1": 0.1,
                    "squared_return_autocorr_lag_1": 0.3,
                },
                "regime_distribution": {"trend_regime": {"range": {"count": 41, "pct": 100.0}}},
                "random_baseline": {"baseline_type": "event_label_resampling"},
                "random_baseline_comparison": {"event_mean": 0.002},
                "warnings": [],
                "limitations": ["event window only"],
            }
        ),
        encoding="utf-8",
    )

    context = build_llm_context("sess_1", FakeStorage(), export_dir, max_rows=2)
    payload = json.dumps(context, ensure_ascii=False, default=str)

    assert isinstance(context, dict)
    assert "event_windows_long" not in payload
    assert "time_series_returns" not in payload
    assert "time_series_regimes" not in payload
    assert "backtest_trades" not in payload
    assert "should/not/leak" not in payload
    assert str(tmp_path) not in payload
    assert len(context["feature_binning_top"]) == 2
    assert len(context["candidate_rules_top"]) == 2
    assert len(context["backtest_summary"]["parameter_scan_top"]) == 2
    assert len(context["backtest_summary"]["walk_forward"]["valid_results_top"]) == 2
    assert any("single backtest" in item for item in context["forbidden_interpretations"])
    assert context["strategy_consistency_summary"]["strategy_consistency_score"] == 81.0
    assert context["strategy_consistency_summary"]["gate_failures"] == ["possible_selection_bias_warning is true"]
    assert context["strategy_consistency_summary"]["label_score_detail"]["label_score_pct"] == 75.0
    assert context["strategy_consistency_summary"]["profile_feature_match_all_pct"] == 80.0
    assert context["time_series_summary"]["source"] == "event_windows_only"
    assert context["time_series_summary"]["return_distribution"]["sample_count"] == 41
    assert any("event windows only" in w for w in context["time_series_summary"]["warnings"])
    assert any("low-consistency" in item for item in context["forbidden_interpretations"])
    assert any("gate_failures" in item for item in context["forbidden_interpretations"])
    assert any("time series statistics" in item for item in context["forbidden_interpretations"])
    assert context["forbidden_interpretations"]
