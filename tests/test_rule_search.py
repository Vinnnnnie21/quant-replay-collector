from __future__ import annotations

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
