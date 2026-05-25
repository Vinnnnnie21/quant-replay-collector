from __future__ import annotations

import numpy as np
import pandas as pd

from time_series_analysis.factor_model import correlation_matrix, pca_factor_model


def test_single_symbol_pca_reports_unavailable():
    result = pca_factor_model(pd.DataFrame({"BTCUSDT": [0.01, -0.02, 0.03]}))
    assert result["available"] is False
    assert result["reason"] == "PCA factor model requires multi-symbol return matrix."
    assert "多币种收益矩阵" in result["reason_zh_CN"]


def test_pca_first_component_outputs_explained_variance():
    rng = np.random.default_rng(9)
    market = rng.normal(size=300)
    returns = pd.DataFrame(
        {
            "BTCUSDT": market + rng.normal(scale=0.1, size=300),
            "ETHUSDT": 0.9 * market + rng.normal(scale=0.1, size=300),
            "SOLUSDT": 1.1 * market + rng.normal(scale=0.2, size=300),
        }
    )
    result = pca_factor_model(returns)
    assert result["available"] is True
    assert result["explained_variance_ratio"][0] > 0.8
    assert set(result["symbol_beta_to_first_pc"]) == set(returns.columns)
    assert correlation_matrix(returns).shape == (3, 3)
