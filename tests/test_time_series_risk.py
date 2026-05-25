from __future__ import annotations

import pandas as pd

from time_series_analysis.risk import historical_expected_shortfall, historical_var, risk_summary


def test_historical_var_and_es_use_positive_loss_convention():
    returns = pd.Series([-0.10, -0.04, -0.02, 0.01, 0.02])
    var = historical_var(returns, 0.8)
    es = historical_expected_shortfall(returns, 0.8)
    assert var > 0
    assert es >= var
    assert risk_summary(returns)["loss_convention"] == "positive values represent losses"
