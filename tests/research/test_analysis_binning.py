from __future__ import annotations

import pandas as pd

from analysis.binning import bin_feature_vs_label


def test_normal_binning():
    df = pd.DataFrame({"feature": range(100), "label": [1 if i > 50 else -1 for i in range(100)]})
    out = bin_feature_vs_label(df, "feature", "label", n_bins=5)
    assert len(out) == 5
    assert "win_rate_pct" in out.columns


def test_empty_data():
    assert bin_feature_vs_label(pd.DataFrame(), "x", "y").empty


def test_identical_feature_safe():
    df = pd.DataFrame({"feature": [1] * 50, "label": [True] * 50})
    assert bin_feature_vs_label(df, "feature", "label").empty


def test_boolean_label_win_rate():
    df = pd.DataFrame({"feature": range(40), "label": [i % 2 == 0 for i in range(40)]})
    out = bin_feature_vs_label(df, "feature", "label", n_bins=2)
    assert out["win_rate_pct"].between(0, 100).all()

