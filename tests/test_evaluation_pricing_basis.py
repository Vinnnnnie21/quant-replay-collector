from __future__ import annotations

import pandas as pd
import pytest

from research.outcome_labels import compute_outcome_labels_for_sample, validate_pricing_basis
from test_research_outcome_labels import _klines, _sample


def test_default_pricing_basis_is_next_open_not_event_bar_midpoint():
    first = compute_outcome_labels_for_sample(_klines(), _sample(), 5, label_version="outcome_v1")
    changed_event_mid = _klines()
    changed_event_mid.loc[20, ["high", "low"]] = [50_000.0, 0.5]
    second = compute_outcome_labels_for_sample(changed_event_mid, _sample(), 5, label_version="outcome_v1")

    assert first.iloc[0]["pricing_basis"] == "next_open"
    assert first.iloc[0]["fwd_ret"] == pytest.approx(second.iloc[0]["fwd_ret"])
    assert first.iloc[0]["fwd_ret"] == pytest.approx(121.0 / 110.0 - 1.0)


def test_legacy_mid_is_available_but_explicitly_not_executable_fill():
    legacy = compute_outcome_labels_for_sample(
        _klines(),
        _sample(),
        5,
        pricing_basis="legacy_mid",
        label_version="outcome_v1",
    ).iloc[0]

    assert legacy["pricing_basis"] == "legacy_mid"
    assert "does not represent executable fill" in legacy["pricing_note"]


def test_event_close_and_next_open_have_different_definitions():
    event_close = compute_outcome_labels_for_sample(
        _klines(), _sample(), 5, pricing_basis="event_close", label_version="outcome_v1"
    ).iloc[0]
    next_open = compute_outcome_labels_for_sample(
        _klines(), _sample(), 5, pricing_basis="next_open", label_version="outcome_v1"
    ).iloc[0]

    assert event_close["fwd_ret"] == pytest.approx(121.0 / 100.0 - 1.0)
    assert next_open["fwd_ret"] == pytest.approx(121.0 / 110.0 - 1.0)
    assert event_close["fwd_ret"] != next_open["fwd_ret"]


def test_invalid_pricing_basis_is_rejected():
    with pytest.raises(ValueError):
        validate_pricing_basis("same_bar_optimistic")
