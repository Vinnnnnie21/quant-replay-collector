from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

if __package__ and __package__.startswith("quant_collector_app."):
    from quant_collector_app.i18n import tr
else:
    from i18n import tr
from .autocorrelation import acf, white_noise_diagnostic
from .baseline import build_random_bar_baseline, build_random_event_baseline, compare_events_to_baseline
from .diagnostics import descriptive_stats, normality_warning
from .factor_model import correlation_matrix, pca_factor_model
from .liquidity_proxy import compute_liquidity_proxy, summarize_liquidity_proxy
from .microstructure import microstructure_diagnostics
from .regime import build_regime_features, summarize_regime_distribution
from .returns import annualized_log_return, annualized_return, build_return_series, summarize_return_distribution
from .risk import risk_summary
from .volatility import volatility_diagnostics

WARNING_KEYS = {
    "time series return analysis skipped: no usable kline data": "time_series.warning.no_data",
    "return distribution departs from normality or displays heavy-tail behavior": "time_series.warning.non_normal",
    "returns exhibit serial dependence under the Ljung-Box diagnostic": "time_series.warning.serial_dependence",
    "squared or absolute returns indicate volatility clustering": "time_series.warning.volatility_clustering",
    "short-interval K-lines are not tick or order-book observations": "time_series.warning.short_interval",
    "possible bid-ask bounce or high-frequency noise proxy detected; this is not a spread estimate": "time_series.warning.bounce",
    "scipy unavailable; Ljung-Box p-value uses a diagnostic approximation": "time_series.warning.ljung_box_approximation",
    "high zero-return ratio may indicate sparse movement or aggregation effects": "time_series.warning.zero_return",
    "Time series analysis is based on event windows only, not the full session market series.": "time_series.warning.event_windows",
    "Event-window time series is fragmented; returns and autocorrelation do not represent the full market sequence.": "time_series.warning.fragmented",
}
ZH_TEXT = {
    "Statistics are exploratory diagnostics, not investment advice or price predictions.": "统计结果仅用于探索性诊断，不构成投资建议，也不是价格预测。",
    "K-line data cannot reconstruct order-book liquidity, true bid-ask spread or partial fills.": "K 线数据不能还原盘口流动性、真实买卖价差或部分成交。",
    "VaR and Expected Shortfall are loss-risk measures, not return forecasts.": "VaR 和 Expected Shortfall 是损失风险度量，不是收益预测。",
    "Random baseline is a research reference only.": "随机基线仅作为研究参照。",
    "Small samples are not enough for conclusions.": "小样本不足以形成结论。",
    "Time series analysis is based on event windows only, not the full session market series.": "时间序列分析基于事件窗口，而不是完整会话行情序列。",
    "Returns are computed within each event window only; cross-window returns are intentionally disabled.": "收益仅在每个事件窗口内部计算，跨窗口收益已主动禁用。",
    "positive values represent losses": "正数代表损失",
    "VaR may understate losses beyond its threshold; ES complements tail-loss review.": "VaR 可能低估超过阈值后的损失，ES 用于补充尾部损失审查。",
    "This is a squared-return dependence proxy, not a fitted ARCH/GARCH model.": "这是平方收益依赖近似诊断，不是拟合后的 ARCH/GARCH 模型。",
    "Without trade-level bid/ask or order-book data this module reports proxies only, not true spread.": "没有逐笔 bid/ask 或订单簿数据时，本模块只报告近似诊断，不估计真实价差。",
    "negative lag-1 return dependence may reflect bid-ask bounce or high-frequency noise proxy; this is not a measured bid-ask spread": "负的一阶收益依赖可能反映 bid-ask bounce 或高频噪声 proxy；这不是盘口价差估计。",
    "The first component is a common-return factor proxy, not proof of alpha or a complete pricing model.": "第一主成分只是共同收益因子近似，不证明 alpha，也不是完整定价模型。",
    "PCA factor model requires multi-symbol return matrix.": "PCA 因子模型需要多币种收益矩阵，单品种 K 线数据不可用。",
    "PCA factor model requires at least two varying symbol returns.": "PCA 因子模型需要至少两个具有变动的币种收益序列。",
    "insufficient sample": "样本不足。",
    "insufficient sample for Jarque-Bera test": "样本不足，无法进行 Jarque-Bera 诊断。",
}

PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "3m": 365 * 24 * 20,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}
LIQUIDITY_PROXY_DISCLAIMER = (
    "This is an OHLCV-based proxy. It is not order book liquidity, bid-ask spread, "
    "market depth, or a trading signal."
)
LIQUIDITY_PROXY_DISCLAIMER_ZH = (
    "该指标仅基于 OHLCV K线数据构造，是历史流动性冲击代理指标，不代表真实订单簿深度、"
    "bid-ask spread 或盘口流动性，也不构成交易信号。"
)
LIQUIDITY_STATE_LABELS_ZH = [
    "LOW_LIQUIDITY_SHOCK：低量高冲击，疑似薄流动性冲击",
    "EVENT_REPRICING：高量高冲击，疑似事件重定价",
    "ABSORPTION：高量低冲击，疑似承接 / 吸收",
    "QUIET_THIN_MARKET：低量低波动，冷清市场",
    "NORMAL_LIQUIDITY：正常",
    "UNKNOWN：样本不足或数据不可用",
]


def localized_warning(message: str, language: str = "zh_CN") -> str:
    key = WARNING_KEYS.get(str(message))
    return tr(key, language, str(message)) if key else str(message)


def localized_payload(value, language: str = "zh_CN"):
    if language == "en_US":
        return value
    if isinstance(value, dict):
        return {key: localized_payload(item, language) for key, item in value.items()}
    if isinstance(value, list):
        return [localized_payload(item, language) for item in value]
    if isinstance(value, str):
        return ZH_TEXT.get(value, localized_warning(value, language))
    return value


def _log_values(returns_df: pd.DataFrame) -> pd.Series:
    if returns_df is None or returns_df.empty:
        return pd.Series(dtype=float)
    column = "log_return" if "log_return" in returns_df.columns else "simple_return"
    return pd.to_numeric(returns_df.get(column), errors="coerce").dropna()


def _build_liquidity_proxy_diagnostics(kline_df: pd.DataFrame, source: str = "full_session_klines") -> dict:
    if source == "event_windows_only":
        return {
            "enabled": False,
            "reason": "event_windows_only is fragmented; liquidity proxy rolling-state interpretation requires contiguous K-line data",
            "disclaimer": LIQUIDITY_PROXY_DISCLAIMER,
        }
    try:
        result_df = compute_liquidity_proxy(kline_df)
        summary = summarize_liquidity_proxy(result_df)
    except Exception as exc:
        return {
            "enabled": False,
            "reason": str(exc),
            "disclaimer": LIQUIDITY_PROXY_DISCLAIMER,
        }
    return {
        "enabled": True,
        "proxy_name": "Kline Liquidity Impact Proxy",
        "disclaimer": LIQUIDITY_PROXY_DISCLAIMER,
        "summary": summary,
    }


def build_time_series_report(
    kline_df: pd.DataFrame,
    event_features: pd.DataFrame | None = None,
    source: str = "full_session_klines",
    returns_df: pd.DataFrame | None = None,
    regime_df: pd.DataFrame | None = None,
    interval: str | None = None,
    multi_symbol_returns: pd.DataFrame | None = None,
) -> dict:
    warnings: list[str] = []
    returns_df = returns_df if returns_df is not None else build_return_series(kline_df)
    if returns_df.empty:
        warnings.append("time series return analysis skipped: no usable kline data")
    regime_df = regime_df if regime_df is not None else build_regime_features(returns_df)
    values = _log_values(returns_df)
    inferred_interval = interval
    if inferred_interval is None and isinstance(kline_df, pd.DataFrame) and "interval" in kline_df.columns and not kline_df.empty:
        inferred_interval = str(kline_df["interval"].iloc[0])
    distribution = descriptive_stats(values)
    normal_warning = normality_warning(values)
    if normal_warning:
        warnings.append(normal_warning)
    white_noise = white_noise_diagnostic(values, lags=min(10, max(1, len(values) // 4))) if len(values) else white_noise_diagnostic(values)
    warnings.extend(white_noise["warnings"])
    ljung_box_methods = {
        item.get("p_value_method")
        for key in ("return_ljung_box", "squared_return_ljung_box", "absolute_return_ljung_box")
        for item in white_noise.get(key, [])
    }
    if "normal_approximation" in ljung_box_methods:
        warnings.append("scipy unavailable; Ljung-Box p-value uses a diagnostic approximation")
    microstructure = microstructure_diagnostics(kline_df if isinstance(kline_df, pd.DataFrame) else pd.DataFrame(), inferred_interval)
    warnings.extend(microstructure["warnings"])
    liquidity_proxy = _build_liquidity_proxy_diagnostics(kline_df, source)
    limitations = [
        "Statistics are exploratory diagnostics, not investment advice or price predictions.",
        "K-line data cannot reconstruct order-book liquidity, true bid-ask spread or partial fills.",
        "VaR and Expected Shortfall are loss-risk measures, not return forecasts.",
        "Random baseline is a research reference only.",
        "Small samples are not enough for conclusions.",
    ]
    if source == "event_windows_only":
        limitations.append("Time series analysis is based on event windows only, not the full session market series.")
        limitations.append("Returns are computed within each event window only; cross-window returns are intentionally disabled.")
        warnings.append("Time series analysis is based on event windows only, not the full session market series.")
        warnings.append("Event-window time series is fragmented; returns and autocorrelation do not represent the full market sequence.")
    result = {
        "source": source,
        "return_definition": "log_return",
        "return_distribution": summarize_return_distribution(returns_df),
        "annualized_returns": {
            "periods_per_year": PERIODS_PER_YEAR.get(str(inferred_interval)),
            "annualized_log_return": annualized_log_return(values, PERIODS_PER_YEAR[str(inferred_interval)])
            if str(inferred_interval) in PERIODS_PER_YEAR
            else None,
            "annualized_return": annualized_return(values, PERIODS_PER_YEAR[str(inferred_interval)])
            if str(inferred_interval) in PERIODS_PER_YEAR
            else None,
        },
        "distribution_diagnostics": distribution,
        "normality_warning": normal_warning,
        "acf": acf(values, min(20, max(0, len(values) - 1))).to_dict("records") if len(values) else [],
        "autocorrelation_diagnostics": white_noise,
        "volatility_diagnostics": volatility_diagnostics(values),
        "risk_metrics": risk_summary(values),
        "microstructure_diagnostics": microstructure,
        "liquidity_proxy_diagnostics": liquidity_proxy,
        "regime_distribution": summarize_regime_distribution(regime_df),
        "factor_model": pca_factor_model(pd.DataFrame()),
        "correlation_matrix": None,
        "random_baseline": None,
        "random_bar_baseline": None,
        "random_baseline_comparison": None,
        "warnings": list(dict.fromkeys(warnings)),
        "limitations": limitations,
    }
    if multi_symbol_returns is not None:
        result["correlation_matrix"] = correlation_matrix(multi_symbol_returns).to_dict()
        result["factor_model"] = pca_factor_model(multi_symbol_returns)
    if event_features is not None and not event_features.empty:
        baseline = build_random_event_baseline(event_features)
        result["random_baseline"] = baseline
        if not baseline.get("skipped"):
            result["random_baseline_comparison"] = compare_events_to_baseline(event_features, baseline)
    if source == "full_session_klines" and kline_df is not None and not kline_df.empty:
        result["random_bar_baseline"] = build_random_bar_baseline(kline_df)
    return result


def _json_block(value, language: str = "zh_CN") -> list[str]:
    return ["```json", json.dumps(localized_payload(value, language), ensure_ascii=False, indent=2, default=str), "```"]


def _liquidity_proxy_report_block(diagnostics: dict, language: str = "zh_CN") -> list[str]:
    enabled = bool(diagnostics.get("enabled"))
    summary = diagnostics.get("summary") or {}
    proxy_name = diagnostics.get("proxy_name") or "Kline Liquidity Impact Proxy"
    if language == "en_US":
        lines = [
            "## Kline Liquidity Impact Proxy",
            "",
            f"- proxy name: {proxy_name}",
            f"- disclaimer: {diagnostics.get('disclaimer') or LIQUIDITY_PROXY_DISCLAIMER}",
            f"- enabled: {enabled}",
        ]
        if not enabled:
            lines.append(f"- reason: {diagnostics.get('reason') or 'unavailable'}")
        else:
            lines.extend(["", *_json_block(summary, language)])
        return lines

    lines = [
        "## K线流动性冲击代理指标",
        "",
        f"- proxy name：{proxy_name}",
        f"- 免责声明：{LIQUIDITY_PROXY_DISCLAIMER_ZH}",
        f"- 可计算：{'是' if enabled else '否'}",
    ]
    if not enabled:
        lines.append(f"- 不可用原因：{diagnostics.get('reason') or '数据不足'}")
    else:
        lines.extend(["- 状态释义：", *[f"  - {label}" for label in LIQUIDITY_STATE_LABELS_ZH], "", *_json_block(summary, language)])
    return lines


def write_time_series_report(result: dict, output_path: Path, language: str = "zh_CN") -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    distribution = result.get("distribution_diagnostics") or {}
    annualized = result.get("annualized_returns") or {}
    autocorrelation = result.get("autocorrelation_diagnostics") or {}
    volatility = result.get("volatility_diagnostics") or {}
    risk = result.get("risk_metrics") or {}
    microstructure = result.get("microstructure_diagnostics") or {}
    liquidity_proxy = result.get("liquidity_proxy_diagnostics") or {
        "enabled": False,
        "reason": "liquidity proxy diagnostics not present",
        "disclaimer": LIQUIDITY_PROXY_DISCLAIMER,
    }
    factor = result.get("factor_model") or {}
    warnings = result.get("warnings") or []
    limitations = result.get("limitations") or []
    if language == "en_US":
        lines = [
            "# Financial Time-Series Diagnostic Report",
            "",
            "This is exploratory financial time-series diagnosis, not a price forecast or trading signal.",
            "",
            "## Return Definition",
            "",
            "- Both simple return and log return are exported; diagnostics below use log return by default.",
            "- annualized_log_return is continuously compounded; annualized_return is exp(annualized_log_return) - 1.",
            f"- Annualized log return / annualized simple return: {annualized.get('annualized_log_return')} / {annualized.get('annualized_return')}",
            "",
            "## Distribution Characteristics",
            "",
            f"- n: {distribution.get('n')}",
            f"- mean / median / std: {distribution.get('mean')} / {distribution.get('median')} / {distribution.get('std')}",
            f"- skewness / excess_kurtosis: {distribution.get('skewness')} / {distribution.get('excess_kurtosis')}",
            f"- JB statistic / p-value / method: {distribution.get('jb_statistic')} / {distribution.get('jb_p_value')} / {distribution.get('jb_p_value_method')}",
            f"- heavy_tail_warning: {distribution.get('heavy_tail_warning')}",
            "",
            "## Autocorrelation and White-Noise Diagnostics",
            "",
            *_json_block(autocorrelation, language),
            "",
            "## Volatility Regime",
            "",
            *_json_block(volatility, language),
            "",
            "## Tail Risk",
            "",
            *_json_block(risk, language),
            "",
            "## High-Frequency Microstructure Warnings",
            "",
            *_json_block(microstructure, language),
            "",
            *_liquidity_proxy_report_block(liquidity_proxy, language),
            "",
            "## Multi-Asset Correlation and Factor",
            "",
            *_json_block(factor or {"status": "not supplied"}, language),
            "",
            "## Research Limitations",
            "",
            *[f"- {item}" for item in limitations],
            *[f"- Warning: {localized_warning(item, language)}" for item in warnings],
        ]
    else:
        lines = [
            "# 金融时间序列诊断报告",
            "",
            "本报告是探索性金融时间序列诊断，不是价格预测，也不是交易信号。",
            "",
            "## 收益率定义",
            "",
            "- 同时输出 simple return 与 log return；下列诊断默认使用 log return。",
            "- 对数收益便于跨期累加和统计诊断，价格水平本身不直接作为相关性结论依据。",
            "- annualized_log_return 表示年化连续复利收益；annualized_return 为 exp(annualized_log_return) - 1 的简单年化收益。",
            f"- 年化连续复利收益 / 简单年化收益：{annualized.get('annualized_log_return')} / {annualized.get('annualized_return')}",
            "",
            "## 分布特征",
            "",
            f"- 样本数：{distribution.get('n')}",
            f"- 均值 / 中位数 / 标准差：{distribution.get('mean')} / {distribution.get('median')} / {distribution.get('std')}",
            f"- 偏度 / 超额峰度：{distribution.get('skewness')} / {distribution.get('excess_kurtosis')}",
            f"- Jarque-Bera 统计量 / p 值 / 方法：{distribution.get('jb_statistic')} / {distribution.get('jb_p_value')} / {distribution.get('jb_p_value_method')}",
            f"- 厚尾警告：{distribution.get('heavy_tail_warning')}",
            "",
            "## 自相关与白噪声诊断",
            "",
            "- scipy 可用时，Ljung-Box p 值使用 chi-square survival function；不可用时使用近似方法，仅供诊断参考。",
            *_json_block(autocorrelation, language),
            "",
            "## 波动率状态",
            "",
            *_json_block(volatility, language),
            "",
            "## 尾部风险",
            "",
            "- VaR / ES 使用损失口径，正数代表损失。",
            *_json_block(risk, language),
            "",
            "## 高频数据与微观结构警告",
            "",
            "- K 线没有逐笔 bid/ask 数据时，只能给出 proxy，不估计真实价差；负一阶自相关触发阈值 -0.15 是经验诊断阈值。",
            *_json_block(microstructure, language),
            "",
            *_liquidity_proxy_report_block(liquidity_proxy, language),
            "",
            "## 多资产相关性与因子",
            "",
            *_json_block(factor or {"状态": "PCA 因子模型需要多币种收益矩阵，单品种 K 线数据不可用。"}, language),
            "",
            "## 研究限制",
            "",
            "- 样本内统计不代表预测能力。",
            "- 高频 K 线不等于逐笔数据；没有盘口数据不能估计真实 bid-ask spread。",
            "- VaR / ES 是风险度量，不是收益预测。",
            *[f"- {localized_payload(item, language)}" for item in limitations],
            *[f"- 警告：{localized_warning(item, language)}" for item in warnings],
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
