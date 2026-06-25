from __future__ import annotations

import numpy as np
import pandas as pd

from .autocorrelation import acf, ljung_box_test

DEFAULT_QUANTILES = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
MIN_SAMPLE_SIZE = 20
POSTERIOR_ONLY = "posterior_outcome_analysis_only"


def _clean_numeric(values) -> pd.Series:
    return pd.to_numeric(pd.Series(values), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _quantile_key(level: float) -> str:
    return f"q{int(round(float(level) * 100)):02d}"


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")


def _sample_warning(count: int) -> str | None:
    return f"low_sample: {count} < {MIN_SAMPLE_SIZE}" if count < MIN_SAMPLE_SIZE else None


def _iqr_from_stats(stats: dict) -> float | None:
    q25 = stats.get("q25")
    q75 = stats.get("q75")
    return float(q75 - q25) if q25 is not None and q75 is not None else None


def compute_skewness(series) -> float | None:
    clean = _clean_numeric(series)
    if len(clean) < 3:
        return None
    return float(clean.skew())


def compute_excess_kurtosis(series) -> float | None:
    clean = _clean_numeric(series)
    if len(clean) < 4:
        return None
    return float(clean.kurt())


def compute_quantiles(series, q=DEFAULT_QUANTILES) -> dict[str, float | None]:
    clean = _clean_numeric(series)
    levels = tuple(float(level) for level in q)
    if clean.empty:
        return {_quantile_key(level): None for level in levels}
    return {_quantile_key(level): float(clean.quantile(level)) for level in levels}


def tail_concentration(series) -> dict[str, float | bool | int | None]:
    clean = _clean_numeric(series)
    count = int(len(clean))
    if clean.empty:
        return {
            "n": 0,
            "top_5pct_abs_share": None,
            "p99_to_p95_abs_ratio": None,
            "heavy_tail_warning": False,
        }
    absolute = clean.abs()
    total = float(absolute.sum())
    q95 = float(absolute.quantile(0.95))
    q99 = float(absolute.quantile(0.99))
    tail_share = float(absolute[absolute >= q95].sum() / total) if total > 0 else 0.0
    ratio = float(q99 / q95) if q95 > 0 else None
    kurtosis = compute_excess_kurtosis(clean)
    return {
        "n": count,
        "top_5pct_abs_share": tail_share,
        "p99_to_p95_abs_ratio": ratio,
        "heavy_tail_warning": bool((kurtosis is not None and kurtosis > 1.0) or tail_share > 0.25),
    }


def _feature_stats(values) -> dict:
    raw = pd.Series(values)
    clean = _clean_numeric(raw)
    count = int(len(clean))
    tail = tail_concentration(clean)
    return {
        "n": count,
        "missing_count": int(raw.isna().sum()),
        "invalid_count": int(len(raw) - count),
        "mean": float(clean.mean()) if count else None,
        "median": float(clean.median()) if count else None,
        "iqr": float(clean.quantile(0.75) - clean.quantile(0.25)) if count else None,
        "std": float(clean.std(ddof=1)) if count > 1 else (0.0 if count == 1 else None),
        "skewness": compute_skewness(clean),
        "excess_kurtosis": compute_excess_kurtosis(clean),
        **compute_quantiles(clean),
        "top_5pct_abs_share": tail["top_5pct_abs_share"],
        "p99_to_p95_abs_ratio": tail["p99_to_p95_abs_ratio"],
        "heavy_tail_warning": tail["heavy_tail_warning"],
        "sample_warning": _sample_warning(count),
    }


def describe_feature_distribution(df: pd.DataFrame, group_col: str, feature_cols: list[str]) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    _require_columns(df, [group_col, *feature_cols])

    rows: list[dict] = []
    for group_value, group_df in df.groupby(group_col, dropna=False, sort=True):
        for feature in feature_cols:
            raw = group_df[feature]
            rows.append(
                {
                    "group": group_value,
                    "feature": feature,
                    **_feature_stats(raw),
                }
            )
    columns = [
        "group",
        "feature",
        "n",
        "missing_count",
        "invalid_count",
        "mean",
        "median",
        "std",
        "skewness",
        "excess_kurtosis",
        *compute_quantiles([]).keys(),
        "top_5pct_abs_share",
        "p99_to_p95_abs_ratio",
        "heavy_tail_warning",
        "sample_warning",
    ]
    return pd.DataFrame(rows, columns=columns)


def _stats_for_decision(df: pd.DataFrame, decision_col: str, decision: str, feature: str) -> dict:
    subset = df.loc[df[decision_col] == decision, feature]
    return _feature_stats(subset)


def compare_entry_reject_distributions(
    df: pd.DataFrame,
    decision_col: str,
    feature_cols: list[str],
) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    _require_columns(df, [decision_col, *feature_cols])

    rows: list[dict] = []
    for feature in feature_cols:
        entry = _stats_for_decision(df, decision_col, "ENTRY", feature)
        reject = _stats_for_decision(df, decision_col, "REJECT", feature)
        rows.append(
            {
                "feature": feature,
                "entry_n": entry["n"],
                "reject_n": reject["n"],
                "entry_mean": entry["mean"],
                "reject_mean": reject["mean"],
                "mean_diff_entry_minus_reject": (
                    float(entry["mean"] - reject["mean"])
                    if entry["mean"] is not None and reject["mean"] is not None
                    else None
                ),
                "entry_median": entry["median"],
                "reject_median": reject["median"],
                "median_diff_entry_minus_reject": (
                    float(entry["median"] - reject["median"])
                    if entry["median"] is not None and reject["median"] is not None
                    else None
                ),
                "entry_iqr": entry["iqr"],
                "reject_iqr": reject["iqr"],
                "iqr_diff_entry_minus_reject": (
                    float(entry["iqr"] - reject["iqr"])
                    if entry["iqr"] is not None and reject["iqr"] is not None
                    else None
                ),
                "entry_skewness": entry["skewness"],
                "reject_skewness": reject["skewness"],
                "skewness_diff_entry_minus_reject": (
                    float(entry["skewness"] - reject["skewness"])
                    if entry["skewness"] is not None and reject["skewness"] is not None
                    else None
                ),
                "entry_excess_kurtosis": entry["excess_kurtosis"],
                "reject_excess_kurtosis": reject["excess_kurtosis"],
                "excess_kurtosis_diff_entry_minus_reject": (
                    float(entry["excess_kurtosis"] - reject["excess_kurtosis"])
                    if entry["excess_kurtosis"] is not None and reject["excess_kurtosis"] is not None
                    else None
                ),
                "quantile_diff_entry_minus_reject": _quantile_diff(entry, reject),
                "entry_sample_warning": entry["sample_warning"],
                "reject_sample_warning": reject["sample_warning"],
            }
        )
    return pd.DataFrame(rows)


def _quantile_diff(entry: dict, reject: dict) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for key in compute_quantiles([]).keys():
        entry_value = entry.get(key)
        reject_value = reject.get(key)
        result[key] = (
            float(entry_value - reject_value)
            if entry_value is not None and reject_value is not None
            else None
        )
    return result


def _assign_quantile_bins(values: pd.Series, q: int) -> pd.DataFrame:
    numeric = _clean_numeric(values)
    result = pd.DataFrame(index=values.index)
    result["_numeric_value"] = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    result["bin_id"] = pd.NA
    result["bin_left"] = np.nan
    result["bin_right"] = np.nan
    clean = result["_numeric_value"].dropna()
    if clean.empty:
        return result
    bin_count = max(1, min(int(q), int(clean.nunique())))
    if bin_count <= 1:
        mask = result["_numeric_value"].notna()
        result.loc[mask, "bin_id"] = 0
        result.loc[mask, "bin_left"] = float(clean.min())
        result.loc[mask, "bin_right"] = float(clean.max())
        return result
    ranked = clean.rank(method="first")
    bin_ids = pd.qcut(ranked, q=bin_count, labels=False, duplicates="drop")
    clean_positions = bin_ids.index
    result.loc[clean_positions, "bin_id"] = bin_ids.astype(int)
    for bin_id, grouped in result.loc[clean_positions].groupby("bin_id", sort=True):
        values_in_bin = grouped["_numeric_value"].dropna()
        result.loc[grouped.index, "bin_left"] = float(values_in_bin.min())
        result.loc[grouped.index, "bin_right"] = float(values_in_bin.max())
    return result


def quantile_feature_binning(
    df: pd.DataFrame,
    decision_col: str,
    feature_cols: list[str],
    q: int = 4,
) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    _require_columns(df, [decision_col, *feature_cols])
    rows: list[dict] = []
    for feature in feature_cols:
        assigned = _assign_quantile_bins(df[feature], q=q)
        working = df[[decision_col, feature]].copy()
        working["bin_id"] = assigned["bin_id"]
        working["bin_left"] = assigned["bin_left"]
        working["bin_right"] = assigned["bin_right"]
        working = working.dropna(subset=["bin_id"])
        if working.empty:
            continue
        working["bin_id"] = working["bin_id"].astype(int)
        decisions = working[decision_col].astype(str).str.upper()
        for bin_id, bin_df in working.groupby("bin_id", sort=True):
            bin_decisions = decisions.loc[bin_df.index]
            entry_count = int((bin_decisions == "ENTRY").sum())
            reject_count = int((bin_decisions == "REJECT").sum())
            total_count = int(len(bin_df))
            rows.append(
                {
                    "feature": feature,
                    "bin_id": int(bin_id),
                    "bin_left": float(bin_df["bin_left"].iloc[0]),
                    "bin_right": float(bin_df["bin_right"].iloc[0]),
                    "bin_label": f"{feature}[{float(bin_df['bin_left'].iloc[0]):.6g}, {float(bin_df['bin_right'].iloc[0]):.6g}]",
                    "total_count": total_count,
                    "entry_count": entry_count,
                    "reject_count": reject_count,
                    "entry_rate": float(entry_count / (entry_count + reject_count)) if entry_count + reject_count else None,
                    "sample_warning": _sample_warning(total_count),
                }
            )
    return pd.DataFrame(rows)


def feature_bin_outcome_summary(
    features_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    outcomes_df: pd.DataFrame,
    *,
    feature_cols: list[str],
    outcome_cols: list[str],
    q: int = 4,
) -> pd.DataFrame:
    for name, frame in (("features_df", features_df), ("annotations_df", annotations_df), ("outcomes_df", outcomes_df)):
        if not isinstance(frame, pd.DataFrame):
            raise ValueError(f"{name} must be a pandas DataFrame")
    _require_columns(features_df, ["observation_id", *feature_cols])
    _require_columns(annotations_df, ["observation_id", "human_decision"])
    _require_columns(outcomes_df, ["observation_id", *outcome_cols])
    merged = (
        features_df[["observation_id", *feature_cols]]
        .merge(annotations_df[["observation_id", "human_decision"]], on="observation_id", how="inner")
        .merge(outcomes_df[["observation_id", *outcome_cols]], on="observation_id", how="inner")
    )
    rows: list[dict] = []
    for feature in feature_cols:
        assigned = _assign_quantile_bins(merged[feature], q=q)
        working = merged.copy()
        working["bin_id"] = assigned["bin_id"]
        working["bin_left"] = assigned["bin_left"]
        working["bin_right"] = assigned["bin_right"]
        working = working.dropna(subset=["bin_id"])
        if working.empty:
            continue
        working["bin_id"] = working["bin_id"].astype(int)
        for bin_id, bin_df in working.groupby("bin_id", sort=True):
            decisions = bin_df["human_decision"].astype(str).str.upper()
            for outcome_col in outcome_cols:
                stats = _feature_stats(bin_df[outcome_col])
                rows.append(
                    {
                        "analysis_role": POSTERIOR_ONLY,
                        "feature": feature,
                        "bin_id": int(bin_id),
                        "bin_left": float(bin_df["bin_left"].iloc[0]),
                        "bin_right": float(bin_df["bin_right"].iloc[0]),
                        "outcome_col": outcome_col,
                        "n": stats["n"],
                        "entry_count": int((decisions == "ENTRY").sum()),
                        "reject_count": int((decisions == "REJECT").sum()),
                        "median": stats["median"],
                        "iqr": stats["iqr"],
                        "skewness": stats["skewness"],
                        "excess_kurtosis": stats["excess_kurtosis"],
                        "sample_warning": stats["sample_warning"],
                    }
                )
    return pd.DataFrame(rows)


def outcome_time_series_diagnostics(
    outcomes_df: pd.DataFrame,
    *,
    outcome_cols: list[str] | None = None,
    lags: int = 10,
) -> pd.DataFrame:
    if not isinstance(outcomes_df, pd.DataFrame):
        raise ValueError("outcomes_df must be a pandas DataFrame")
    columns = list(outcome_cols or [column for column in outcomes_df.columns if str(column).startswith("fwd_ret_")])
    _require_columns(outcomes_df, columns)
    rows: list[dict] = []
    for outcome_col in columns:
        clean = _clean_numeric(outcomes_df[outcome_col])
        acf_df = acf(clean, max_lag=int(lags))
        return_ljung = ljung_box_test(clean, lags=int(lags))
        absolute_ljung = ljung_box_test(clean.abs(), lags=int(lags))
        squared_ljung = ljung_box_test(clean.pow(2), lags=int(lags))
        warnings = []
        for frame in (return_ljung, absolute_ljung, squared_ljung):
            if not frame.empty:
                warnings.extend(str(value) for value in frame.get("warning", pd.Series(dtype=object)).dropna().unique())
        if len(clean) < max(5, int(lags) + 1):
            warnings.append("insufficient sample for stable ACF/Ljung-Box diagnostic")
        rows.append(
            {
                "analysis_role": "posterior_time_series_diagnostic_only",
                "outcome_col": outcome_col,
                "sample_count": int(len(clean)),
                "acf": acf_df.to_dict("records"),
                "return_ljung_box": return_ljung.to_dict("records"),
                "absolute_return_ljung_box": absolute_ljung.to_dict("records"),
                "squared_return_ljung_box": squared_ljung.to_dict("records"),
                "return_serial_dependence_warning": bool(return_ljung["significant"].any()) if not return_ljung.empty else False,
                "volatility_clustering_warning": bool(
                    (absolute_ljung["significant"].any() if not absolute_ljung.empty else False)
                    or (squared_ljung["significant"].any() if not squared_ljung.empty else False)
                ),
                "warnings": sorted(set(warnings)),
            }
        )
    return pd.DataFrame(rows)


def feature_drift_by_period(
    df: pd.DataFrame,
    time_col: str,
    feature_cols: list[str],
    period: str = "M",
) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    _require_columns(df, [time_col, *feature_cols])

    working = df.copy()
    working["_diagnostic_time"] = pd.to_datetime(working[time_col], errors="coerce", utc=True).dt.tz_convert(None)
    if working["_diagnostic_time"].isna().any():
        raise ValueError(f"{time_col} contains invalid timestamps")
    working["_diagnostic_period"] = working["_diagnostic_time"].dt.to_period(period)
    working = working.sort_values("_diagnostic_time", kind="stable")

    rows: list[dict] = []
    baseline_by_feature: dict[str, dict] = {}
    for period_value, period_df in working.groupby("_diagnostic_period", sort=True):
        for feature in feature_cols:
            raw = period_df[feature]
            stats = _feature_stats(raw)
            if feature not in baseline_by_feature:
                baseline_by_feature[feature] = stats
            baseline = baseline_by_feature[feature]
            baseline_median = baseline.get("median")
            current_median = stats.get("median")
            baseline_iqr = baseline.get("iqr") or 0.0
            threshold = max(0.5, 3.0 * float(baseline_iqr))
            drift_warning = (
                baseline_median is not None
                and current_median is not None
                and abs(float(current_median) - float(baseline_median)) > threshold
            )
            rows.append(
                {
                    "period": str(period_value),
                    "period_start": period_value.start_time,
                    "feature": feature,
                    **stats,
                    "baseline_median": baseline_median,
                    "median_diff_vs_first_period": (
                        float(current_median - baseline_median)
                        if current_median is not None and baseline_median is not None
                        else None
                    ),
                    "drift_warning": bool(drift_warning),
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["period_start", "feature"], kind="stable").reset_index(drop=True)


__all__ = [
    "compare_entry_reject_distributions",
    "compute_excess_kurtosis",
    "compute_quantiles",
    "compute_skewness",
    "describe_feature_distribution",
    "feature_bin_outcome_summary",
    "feature_drift_by_period",
    "outcome_time_series_diagnostics",
    "quantile_feature_binning",
    "tail_concentration",
]
