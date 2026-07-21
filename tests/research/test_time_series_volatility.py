from __future__ import annotations

import pandas as pd

from time_series_analysis.volatility import ewma_volatility, realized_volatility, volatility_diagnostics


def test_volatility_outputs_are_defined_after_window():
    values = pd.Series([0.0, 0.01, -0.02, 0.03, -0.01] * 10)
    assert realized_volatility(values, 5).dropna().iloc[-1] > 0
    assert ewma_volatility(values).dropna().iloc[-1] > 0
    summary = volatility_diagnostics(values, 5)
    assert summary["regime"] in {"LOW", "MID", "HIGH", "EXTREME"}
    assert "arch_effect_proxy" in summary
