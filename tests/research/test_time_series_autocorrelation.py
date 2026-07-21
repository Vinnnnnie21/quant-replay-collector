from __future__ import annotations

import numpy as np

from time_series_analysis.autocorrelation import ljung_box_test, white_noise_diagnostic


def test_ljung_box_flags_serial_dependence():
    rng = np.random.default_rng(7)
    serial = []
    value = 0.0
    for shock in rng.normal(size=800):
        value = 0.85 * value + shock
        serial.append(value)
    result = ljung_box_test(serial, 10)
    assert bool(result.iloc[0]["significant"]) is True
    assert result.iloc[0]["p_value_method"] in {"scipy_chi2_sf", "normal_approximation"}


def test_squared_returns_can_flag_volatility_clustering_proxy():
    rng = np.random.default_rng(2)
    values = np.r_[rng.normal(0, 0.002, 400), rng.normal(0, 0.05, 400)]
    result = white_noise_diagnostic(values, 10)
    assert result["volatility_clustering_warning"] is True


def test_ljung_box_falls_back_without_scipy(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def without_scipy(name, *args, **kwargs):
        if name == "scipy" or name.startswith("scipy."):
            raise ImportError("scipy intentionally unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_scipy)
    result = ljung_box_test(np.arange(20, dtype=float), 4)
    assert result.iloc[0]["p_value_method"] == "normal_approximation"
    assert "approximation" in result.iloc[0]["warning"]
