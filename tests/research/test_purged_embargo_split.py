from __future__ import annotations

import json

import pandas as pd

from research.validation import purged_embargo_split
from research.walk_forward import build_walk_forward_results, walk_forward_splits


def _samples(count: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": [f"e{index}" for index in range(count)],
            "event_time_bjt": pd.date_range("2026-01-01", periods=count, freq="h")[::-1],
        }
    )


def test_purged_embargo_split_is_chronological_and_drops_boundary_rows():
    result = purged_embargo_split(
        _samples(),
        time_col="event_time_bjt",
        train_ratio=0.6,
        purge_bars=2,
        embargo_bars=1,
    )

    train = result["train"]
    test = result["test"]
    assert train["event_id"].tolist() == ["e9", "e8", "e7", "e6"]
    assert result["purged"]["event_id"].tolist() == ["e5", "e4"]
    assert result["embargoed"]["event_id"].tolist() == ["e3"]
    assert test["event_id"].tolist() == ["e2", "e1", "e0"]
    assert train["event_id"].is_unique and test["event_id"].is_unique
    assert set(train["event_id"]).isdisjoint(set(test["event_id"]))
    assert pd.to_datetime(train["event_time_bjt"]).max() < pd.to_datetime(test["event_time_bjt"]).min()


def test_purged_embargo_split_reports_too_little_data():
    result = purged_embargo_split(_samples(3), "event_time_bjt", 0.7, purge_bars=2, embargo_bars=2)

    assert result["warning"] == "insufficient_samples_after_purge_embargo"
    assert result["train"].empty or result["test"].empty


def test_walk_forward_split_applies_purge_and_embargo_without_overlap():
    splits = walk_forward_splits(
        _samples(20),
        n_splits=1,
        train_ratio=0.5,
        time_col="event_time_bjt",
        purge_bars=2,
        embargo_bars=1,
    )

    _period, train, test = splits[0]
    assert len(train) == 8
    assert len(test) == 9
    assert set(train["event_id"]).isdisjoint(set(test["event_id"]))
    assert pd.to_datetime(train["event_time_bjt"]).max() < pd.to_datetime(test["event_time_bjt"]).min()


def test_walk_forward_enforces_purge_at_least_outcome_horizon():
    samples = _samples(80)
    samples["body_pct"] = 1.0
    samples["fwd_ret_10_side_adj"] = 0.01
    rules = pd.DataFrame(
        [{"rule_id": "r1", "conditions_json": '[{"column": "body_pct", "op": ">=", "value": 1}]'}]
    )

    result = build_walk_forward_results(
        samples,
        rules,
        n_splits=1,
        horizon_bars=10,
        purge_bars=2,
        embargo_bars=1,
        min_samples=1,
    )

    assert not result.empty
    assert result.iloc[0]["purge_bars"] == 10
    assert result.iloc[0]["embargo_bars"] == 1
    split_spec = json.loads(result.iloc[0]["split_spec_json"])
    assert split_spec["method"] == "purged_chronological_split"
    assert split_spec["purge_bars"] == 10
