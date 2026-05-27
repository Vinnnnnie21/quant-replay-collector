from __future__ import annotations

import pandas as pd
import pytest

from research.context_features import compute_context_features_for_sample
from research.outcome_labels import compute_multi_horizon_outcome_labels, compute_outcome_labels_for_sample
from storage import StorageManager


def _klines(total: int = 90) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "bar_index": range(total),
            "open": [100.0 for _ in range(total)],
            "high": [102.0 for _ in range(total)],
            "low": [98.0 for _ in range(total)],
            "close": [100.0 for _ in range(total)],
            "volume": [1000.0 for _ in range(total)],
        }
    )
    df.loc[20, ["high", "low", "close"]] = [1000.0, 1.0, 100.0]
    df.loc[21, ["open", "high", "low", "close"]] = [110.0, 114.0, 106.0, 111.0]
    df.loc[25, ["high", "low", "close"]] = [123.0, 109.0, 121.0]
    return df


def _sample(bar_index: int = 20) -> dict:
    return {
        "sample_id": "obs_outcome",
        "session_id": "session_1",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "bar_index": bar_index,
        "side": "LONG",
        "created_at": "2026-05-27T08:00:00+00:00",
    }


def test_next_open_outcome_is_separate_from_context_and_persists(tmp_path):
    outcome = compute_outcome_labels_for_sample(_klines(), _sample(), 5, label_version="outcome_v1")
    context = compute_context_features_for_sample(_klines(), _sample(), 20, "context_v1")

    assert outcome.iloc[0]["pricing_basis"] == "next_open"
    assert outcome.iloc[0]["fwd_ret"] == pytest.approx(121.0 / 110.0 - 1.0)
    assert {"fwd_ret", "mfe", "mae", "hit_tp", "hit_sl"} <= set(outcome.columns)
    assert not {"fwd_ret", "mfe", "mae", "hit_tp", "hit_sl"} & set(context["feature_name"])

    storage = StorageManager(tmp_path / "outcomes.db")
    storage.save_research_outcome_labels(outcome.to_dict("records"))
    storage.save_research_outcome_labels(outcome.to_dict("records"))
    stored = storage.list_research_outcome_labels(sample_id="obs_outcome")

    assert len(stored) == 1
    assert stored[0]["pricing_basis"] == "next_open"


def test_multi_horizon_outcomes_are_labeled_only_in_outcome_rows():
    outcomes = compute_multi_horizon_outcome_labels(_klines(), _sample(), label_version="outcome_v1")
    context = compute_context_features_for_sample(_klines(), _sample(), 20, "context_v1")

    assert set(outcomes["horizon_bars"]) == {5, 10, 20, 50}
    assert {"fwd_ret", "mfe", "mae", "hit_tp", "hit_sl"} <= set(outcomes.columns)
    assert not {"fwd_ret", "mfe", "mae", "hit_tp", "hit_sl"} & set(context["feature_name"])


def test_outcome_marks_insufficient_future_bars_instead_of_fabricating_values():
    outcome = compute_outcome_labels_for_sample(_klines(30), _sample(20), 20, label_version="outcome_v1")
    row = outcome.iloc[0]

    assert row["insufficient_future_bars"] == 1
    assert pd.isna(row["fwd_ret"])
    assert pd.isna(row["mfe"])
    assert pd.isna(row["mae"])


def test_outcome_rejects_unapproved_horizon():
    with pytest.raises(ValueError):
        compute_outcome_labels_for_sample(_klines(), _sample(), 7, label_version="outcome_v1")
