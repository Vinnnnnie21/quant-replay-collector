from __future__ import annotations

import numpy as np
import pandas as pd


def _return_matrix(data: pd.DataFrame) -> pd.DataFrame:
    if data is None or data.empty:
        return pd.DataFrame()
    return data.apply(pd.to_numeric, errors="coerce").dropna(how="all")


def correlation_matrix(return_matrix: pd.DataFrame) -> pd.DataFrame:
    return _return_matrix(return_matrix).corr()


def rolling_correlation(return_matrix: pd.DataFrame, symbol_a: str, symbol_b: str, window: int = 20) -> pd.Series:
    matrix = _return_matrix(return_matrix)
    if symbol_a not in matrix.columns or symbol_b not in matrix.columns:
        return pd.Series(dtype=float)
    return matrix[symbol_a].rolling(max(2, int(window)), min_periods=2).corr(matrix[symbol_b])


def pca_factor_model(return_matrix: pd.DataFrame) -> dict:
    matrix = _return_matrix(return_matrix).dropna()
    if matrix.empty or len(matrix.columns) < 2 or len(matrix) < 2:
        return {
            "available": False,
            "symbols": list(matrix.columns),
            "explained_variance_ratio": [],
            "symbol_beta_to_first_pc": {},
            "reason": "PCA factor model requires multi-symbol return matrix.",
            "reason_zh_CN": "PCA 因子模型需要多币种收益矩阵，单品种 K 线数据不可用。",
        }
    standardized = (matrix - matrix.mean()) / matrix.std(ddof=0).replace(0, np.nan)
    standardized = standardized.dropna(axis=1).dropna()
    if len(standardized.columns) < 2 or standardized.empty:
        return {
            "available": False,
            "symbols": list(standardized.columns),
            "explained_variance_ratio": [],
            "symbol_beta_to_first_pc": {},
            "reason": "PCA factor model requires at least two varying symbol returns.",
            "reason_zh_CN": "PCA 因子模型需要至少两个具有变动的币种收益序列。",
        }
    covariance = np.cov(standardized.to_numpy(), rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    ratio = eigenvalues / eigenvalues.sum() if eigenvalues.sum() else np.zeros_like(eigenvalues)
    first_factor = standardized.to_numpy() @ eigenvectors[:, 0]
    factor_variance = float(np.var(first_factor))
    beta = {
        symbol: float(np.cov(standardized[symbol].to_numpy(), first_factor, ddof=0)[0, 1] / factor_variance)
        if factor_variance > 0
        else None
        for symbol in standardized.columns
    }
    return {
        "available": True,
        "symbols": list(standardized.columns),
        "explained_variance_ratio": [float(value) for value in ratio],
        "first_pc_market_factor": [float(value) for value in first_factor],
        "symbol_beta_to_first_pc": beta,
        "warning": "The first component is a common-return factor proxy, not proof of alpha or a complete pricing model.",
    }
