from __future__ import annotations

import pandas as pd
import pytest

from app_config import APP_VERSION
from event_study import build_event_study_summary
from research.event_study import build_event_study


def test_event_study_includes_distribution_ci_and_warnings():
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "event_type": ["OPEN", "OPEN", "CLOSE"],
            "side": ["LONG", "LONG", "SHORT"],
            "label_tags_json": ['["wick"]', '["wick"]', '["break"]'],
        }
    )
    features = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "fwd_ret_1_side_adj": [0.01, -0.02, 0.03],
        }
    )

    out = build_event_study_summary(events, features)
    wick = out[out["label_tag"] == "wick"].iloc[0]
    assert wick["sample_count"] == 2
    assert "fwd_ret_1_side_adj_std" in out.columns
    assert "fwd_ret_1_side_adj_mean_ci95_low" in out.columns
    assert wick["bootstrap_random_seed"] == 42
    assert wick["bootstrap_simulation_count"] == 1000
    assert wick["bootstrap_confidence"] == 0.95
    assert wick["bootstrap_method_version"]
    assert wick["bootstrap_application_version"] == APP_VERSION
    assert bool(wick["small_sample_warning"]) is True
    assert "exploratory" in wick["multiple_testing_warning"]


def test_research_event_study_propagates_bootstrap_cancellation():
    features = pd.DataFrame(
        {
            "event_id": [f"e{index}" for index in range(30)],
            "event_type": "OPEN",
            "side": "LONG",
        }
    )
    labels = pd.DataFrame(
        {
            "event_id": [f"e{index}" for index in range(30)],
            "fwd_ret_10_side_adj": [index / 100 for index in range(30)],
        }
    )
    cancellation_checks = 0

    def cancelled() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 2

    with pytest.raises(RuntimeError, match="research calculation cancelled") as exc_info:
        build_event_study(
            features,
            labels,
            label="fwd_ret_10_side_adj",
            cancelled=cancelled,
        )

    assert type(exc_info.value).__name__ == "ResearchCancelled"


def test_export_event_study_propagates_bootstrap_cancellation():
    events = pd.DataFrame(
        {
            "event_id": [f"e{index}" for index in range(30)],
            "event_type": "OPEN",
            "side": "LONG",
            "label_tags_json": '["wick"]',
        }
    )
    features = pd.DataFrame(
        {
            "event_id": [f"e{index}" for index in range(30)],
            "fwd_ret_1_side_adj": [index / 100 for index in range(30)],
        }
    )
    cancellation_checks = 0

    def cancelled() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 2

    with pytest.raises(RuntimeError, match="research calculation cancelled") as exc_info:
        build_event_study_summary(events, features, cancelled=cancelled)

    assert type(exc_info.value).__name__ == "ResearchCancelled"
