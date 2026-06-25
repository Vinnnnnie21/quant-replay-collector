from __future__ import annotations

import math

import pandas as pd

from research.entry_context_features import FEATURE_COLUMNS
from research.entry_outcome_labels import LabelSpec, OUTCOME_COLUMNS, build_entry_outcome_labels


def _klines(count: int = 30) -> pd.DataFrame:
    rows = []
    for index in range(count):
        close = 100.0 + index
        rows.append(
            {
                "bar_index": index,
                "open_time": f"2026-06-18T10:{index:02d}:00+08:00",
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 100.0,
            }
        )
    return pd.DataFrame(rows)


def _observations(*bar_indexes: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_id": f"obs_{bar_index}",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": bar_index,
                "bar_time": f"2026-06-18T10:{bar_index:02d}:00+08:00",
            }
            for bar_index in bar_indexes
        ]
    )


def test_fwd_ret_5_is_computed_from_future_close():
    result = build_entry_outcome_labels(_klines(), _observations(10), horizons=(3, 5, 10, 20))

    assert list(result.columns) == OUTCOME_COLUMNS
    row = result.iloc[0]
    assert row["observation_id"] == "obs_10"
    assert row["label_version"] == "entry_outcome_labels_v1"
    assert math.isclose(row["fwd_ret_5"], 115.0 / 110.0 - 1.0)


def test_label_spec_is_serializable_and_supports_dynamic_horizons():
    spec = LabelSpec(
        label_version="entry_outcome_labels_test_v2",
        horizons=(5, 10, 15, 30),
        take_profit_pct=0.02,
        stop_loss_pct=0.01,
        fee_bps=1.0,
        slippage_bps=2.0,
        same_bar_policy="stop_loss_first",
        insufficient_horizon_policy="nan",
    )

    restored = LabelSpec.from_dict(spec.to_dict())
    result = build_entry_outcome_labels(_klines(50), _observations(10), label_spec=restored)

    assert restored == spec
    assert "fwd_ret_15" in result.columns
    assert "fwd_ret_30" in result.columns
    assert result.iloc[0]["label_version"] == "entry_outcome_labels_test_v2"


def test_mfe_and_mae_are_computed_from_future_high_low_path():
    klines = _klines()
    klines.loc[11:20, "high"] = [112.0, 114.0, 119.0, 116.0, 113.0, 112.0, 111.0, 110.0, 109.0, 108.0]
    klines.loc[11:20, "low"] = [109.0, 106.0, 105.0, 104.0, 107.0, 108.0, 109.0, 109.0, 109.0, 109.0]

    result = build_entry_outcome_labels(_klines_with_updates(klines), _observations(10), horizons=(10,))

    row = result.iloc[0]
    assert math.isclose(row["mfe_10"], 119.0 / 110.0 - 1.0)
    assert math.isclose(row["mae_10"], 104.0 / 110.0 - 1.0)
    assert row["max_favorable_excursion_10"] == row["mfe_10"]
    assert row["max_adverse_excursion_10"] == row["mae_10"]


def test_hit_tp_before_sl_uses_first_hit_order():
    klines = _klines()
    klines.loc[11, ["high", "low"]] = [112.5, 109.5]
    klines.loc[12, ["high", "low"]] = [113.5, 106.0]

    result = build_entry_outcome_labels(
        klines,
        _observations(10),
        horizons=(10,),
        take_profit_pct=0.02,
        stop_loss_pct=0.01,
    )

    row = result.iloc[0]
    assert row["hit_tp_10"] == 1
    assert row["hit_sl_10"] == 1
    assert row["hit_tp_before_sl_10"] == 1


def test_same_bar_tp_sl_collision_defaults_to_stop_loss_first():
    klines = _klines()
    klines.loc[11, ["high", "low"]] = [113.0, 108.0]

    result = build_entry_outcome_labels(
        klines,
        _observations(10),
        horizons=(10,),
        take_profit_pct=0.02,
        stop_loss_pct=0.01,
    )

    row = result.iloc[0]
    assert row["hit_tp_10"] == 1
    assert row["hit_sl_10"] == 1
    assert row["hit_tp_before_sl_10"] == 0


def test_insufficient_horizon_at_sample_end_can_return_nan_or_drop():
    observations = _observations(27)

    kept = build_entry_outcome_labels(_klines(), observations, horizons=(3, 5, 10, 20), insufficient_policy="nan")
    dropped = build_entry_outcome_labels(_klines(), observations, horizons=(3, 5, 10, 20), insufficient_policy="drop")

    assert len(kept) == 1
    assert math.isnan(kept.iloc[0]["fwd_ret_5"])
    assert dropped.empty
    assert list(dropped.columns) == OUTCOME_COLUMNS


def test_outcome_fields_are_labels_and_do_not_overlap_context_features():
    assert set(OUTCOME_COLUMNS).isdisjoint(set(FEATURE_COLUMNS) - {"observation_id"})
    assert all(
        any(token in column for token in ("fwd_ret", "mfe", "mae", "hit_tp", "hit_sl", "excursion"))
        or column in {"observation_id", "label_version"}
        for column in OUTCOME_COLUMNS
    )


def test_docstring_states_outcomes_must_not_be_model_inputs():
    text = build_entry_outcome_labels.__doc__ or ""

    assert "must not be used as entry logic model input" in text


def _klines_with_updates(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy()
