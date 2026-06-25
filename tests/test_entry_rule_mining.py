from __future__ import annotations

import pandas as pd
import pytest

from quant_collector_app.research.entry_rule_mining import (
    build_entry_rule_research_pack,
    mine_single_feature_rule_hypotheses,
)


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": [f"obs_{index}" for index in range(8)],
            "lower_shadow_ratio": [0.1, 0.2, 0.3, 0.4, 0.75, 0.8, 0.85, 0.9],
            "volume_zscore_20": [-1.0, -0.5, 0.0, 0.2, 1.2, 1.6, 2.0, 2.4],
        }
    )


def _annotations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": [f"obs_{index}" for index in range(8)],
            "human_decision": ["REJECT", "REJECT", "REJECT", "REJECT", "ENTRY", "ENTRY", "ENTRY", "ENTRY"],
        }
    )


def _outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": [f"obs_{index}" for index in range(8)],
            "fwd_ret_5": [-0.02, -0.01, 0.00, 0.01, 0.03, 0.04, 0.05, 0.06],
            "mfe_10": [0.01, 0.02, 0.02, 0.03, 0.06, 0.07, 0.08, 0.09],
            "mae_10": [-0.04, -0.03, -0.02, -0.02, -0.01, -0.01, -0.01, -0.01],
        }
    )


def test_mine_single_feature_rule_hypotheses_outputs_hypothesis_not_signal():
    rules = mine_single_feature_rule_hypotheses(
        _features(),
        _annotations(),
        feature_cols=["lower_shadow_ratio", "volume_zscore_20"],
        min_samples=2,
        quantiles=(0.5,),
    )

    assert not rules.empty
    first = rules.iloc[0]
    assert first["rule_type"] == "single_feature_threshold_hypothesis"
    assert "hypothesis" in rules.columns
    assert first["entry_rate"] == pytest.approx(1.0)
    joined = " ".join(rules.columns).lower()
    assert "buy_signal" not in joined
    assert "trade_signal" not in joined


def test_rule_mining_rejects_outcome_fields_as_inputs():
    with pytest.raises(ValueError, match="outcome fields are not allowed"):
        mine_single_feature_rule_hypotheses(
            _features().merge(_outcomes(), on="observation_id"),
            _annotations(),
            feature_cols=["lower_shadow_ratio", "fwd_ret_5"],
        )


def test_entry_rule_research_pack_keeps_outcome_analysis_posterior_only():
    pack = build_entry_rule_research_pack(
        _features(),
        _annotations(),
        outcomes_df=_outcomes(),
        feature_cols=["lower_shadow_ratio"],
        outcome_cols=["fwd_ret_5", "mfe_10", "mae_10"],
        min_samples=2,
    )

    assert not pack["rule_hypotheses"].empty
    assert set(pack["posterior_outcome_by_bin"]["analysis_role"]) == {"posterior_outcome_analysis_only"}
    assert "fwd_ret_5" not in pack["feature_cols"]
    assert "not_trading_signal" in pack["warnings"]
