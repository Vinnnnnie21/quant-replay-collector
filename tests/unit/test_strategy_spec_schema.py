from __future__ import annotations

import pytest

from backtesting.strategy_spec import StrategySpec, StrategySpecValidationError


def _valid_strategy_spec_payload() -> dict:
    return {
        "schema_version": "strategy_spec_v1",
        "provenance": {
            "source": "decision_research",
            "setup_version_id": "setup-version-1",
            "research_snapshot_id": "snapshot-abc",
            "decision_mode": "entry_research",
            "formula_version": "decision-research-v1",
            "feature_version": "features-v1",
            "application_version": "1.6.0",
            "random_seed": 42,
            "maturity": "EXPLORATORY_HYPOTHESIS",
            "warnings": ["insufficient forward validation"],
        },
        "market": {
            "symbol": "BTCUSDT",
            "interval": "5m",
            "data_start_utc_ms": 1_700_000_000_000,
            "data_end_utc_ms": 1_700_086_400_000,
        },
        "entry": {
            "rule": {
                "all": [
                    {"feature": "volume_ratio_20", "op": ">=", "value": 1.8},
                    {"feature": "pre_ret_20", "op": "<=", "value": -0.03},
                ]
            }
        },
        "exit": {
            "mode": "tp_sl_timeout",
            "take_profit_pct": 0.03,
            "stop_loss_pct": 0.015,
            "max_holding_bars": 20,
        },
        "position": {
            "direction": "long_only",
            "allow_overlap_positions": False,
            "cooldown_bars": 2,
            "notional_per_trade": 1000.0,
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
        },
    }


def test_strategy_spec_v1_loads_and_preserves_research_provenance():
    spec = StrategySpec.from_dict(_valid_strategy_spec_payload())

    payload = spec.to_dict()

    assert payload["schema_version"] == "strategy_spec_v1"
    assert payload["provenance"]["setup_version_id"] == "setup-version-1"
    assert payload["provenance"]["research_snapshot_id"] == "snapshot-abc"
    assert payload["provenance"]["feature_version"] == "features-v1"
    assert payload["provenance"]["random_seed"] == 42
    assert payload["provenance"]["maturity"] == "EXPLORATORY_HYPOTHESIS"
    assert payload["provenance"]["warnings"] == ["insufficient forward validation"]
    assert payload["position"]["direction"] == "long_only"


@pytest.mark.parametrize(
    "feature_name",
    (
        "future_return_5",
        "outcome_label",
        "mfe_10",
        "mae_10",
        "hit_tp",
        "hit_sl",
        "pnl_after_cost",
        "final_return",
        "realized_pnl",
    ),
)
def test_strategy_spec_rejects_future_and_outcome_fields_in_nested_entry_rules(
    feature_name,
):
    payload = _valid_strategy_spec_payload()
    payload["entry"]["rule"] = {
        "any": [
            {"feature": "volume_ratio_20", "op": ">=", "value": 1.8},
            {"all": [{"feature": feature_name, "op": ">", "value": 0.0}]},
        ]
    }

    with pytest.raises(StrategySpecValidationError, match=feature_name):
        StrategySpec.from_dict(payload)
