from __future__ import annotations

import json

import pandas as pd
import pytest

from research.factor_library import FeatureFactory
from research.label_registry import LabelFactory
from research.rule_search import search_rules
from test_feature_label_separation import research_input


def test_rule_search_rejects_label_fields():
    windows, events, trades = research_input(60)
    features = FeatureFactory().build(windows, events)
    labels = LabelFactory().build(windows, events, trades)
    with pytest.raises(ValueError):
        search_rules(features, labels, factors=["fwd_ret_10_side_adj"])


def test_rule_search_outputs_train_and_test_metrics():
    windows, events, trades = research_input(120)
    features = FeatureFactory().build(windows, events)
    labels = LabelFactory().build(windows, events, trades)
    result = search_rules(features, labels, factors=["pre_ret_10", "volume_ratio_20"], min_samples=10, max_rules=5)
    assert not result.empty
    assert {"conditions_json", "train_score", "test_score", "warning"} <= set(result.columns)


def test_rule_search_ranks_validated_oos_stable_rules_before_in_sample_winners():
    rows = []
    labels = []
    for i in range(100):
        in_train = i < 60
        pre_ret_high = (in_train and i < 25) or (not in_train and 60 <= i < 75)
        volume_high = (in_train and 25 <= i < 40) or (not in_train and 75 <= i < 90)
        event_id = f"e{i:03d}"
        rows.append(
            {
                "event_id": event_id,
                "event_time_bjt": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=i),
                "pre_ret_10": 1.0 if pre_ret_high else 0.0,
                "volume_ratio_20": 1.0 if volume_high else 0.0,
            }
        )
        if pre_ret_high:
            value = 0.12 if in_train else -0.02
        elif volume_high:
            value = 0.04
        else:
            value = 0.001 if in_train else -0.02
        labels.append({"event_id": event_id, "fwd_ret_10_side_adj": value})
    features = pd.DataFrame(rows)
    label_frame = pd.DataFrame(labels)

    result = search_rules(
        features,
        label_frame,
        factors=["pre_ret_10", "volume_ratio_20"],
        min_samples=5,
        max_depth=1,
        max_rules=4,
        train_ratio=0.6,
        horizon_bars=0,
        fdr_alpha=1.0,
    )

    assert not result.empty
    top = result.iloc[0]
    top_conditions = json.loads(top["conditions_json"])
    assert top["validation_status"] == "validated_candidate"
    assert bool(top["fdr_pass"]) is True
    assert top["degradation_ratio"] <= 0.5
    assert top["test_score"] > 0
    assert top_conditions[0]["column"] == "volume_ratio_20"
    assert "candidate hypothesis only" in top["warning"]
