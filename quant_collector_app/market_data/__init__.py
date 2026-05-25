"""Market-data public facade with dependency-specific lazy exports."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "BINANCE_RAW_COLUMNS": ("market_data.types", "BINANCE_RAW_COLUMNS"),
    "PRICE_COLUMNS": ("market_data.types", "PRICE_COLUMNS"),
    "VALID_INTERVALS": ("market_data.types", "VALID_INTERVALS"),
    "DataLoadCancelled": ("market_data.types", "DataLoadCancelled"),
    "LoadRequest": ("market_data.types", "LoadRequest"),
    "bjt_now_iso": ("market_data.types", "bjt_now_iso"),
    "clamp": ("market_data.types", "clamp"),
    "interval_to_ms": ("market_data.types", "interval_to_ms"),
    "make_bjt": ("market_data.types", "make_bjt"),
    "normalize_interval": ("market_data.types", "normalize_interval"),
    "normalize_symbol": ("market_data.types", "normalize_symbol"),
    "to_api_utc_ms_from_bjt": ("market_data.types", "to_api_utc_ms_from_bjt"),
    "utc_ms_to_bjt": ("market_data.types", "utc_ms_to_bjt"),
    "validate_date_range": ("market_data.types", "validate_date_range"),
    "MarketDataClient": ("market_data.client", "MarketDataClient"),
    "_format_request_error": ("market_data.client", "_format_request_error"),
    "format_request_error": ("market_data.client", "format_request_error"),
    "KlineLoader": ("market_data.loader", "KlineLoader"),
    "DataQualityReport": ("market_data.quality", "DataQualityReport"),
    "assess_data_quality": ("market_data.quality", "assess_data_quality"),
    "_normalize_kline_df": ("market_data.transforms", "_normalize_kline_df"),
    "normalize_kline_df": ("market_data.transforms", "normalize_kline_df"),
    "build_feature_row": ("market_data.features", "build_feature_row"),
    "build_window_rows": ("market_data.features", "build_window_rows"),
    "compute_price_proxy": ("market_data.features", "compute_price_proxy"),
    "CandlestickItem": ("views.candlestick_item", "CandlestickItem"),
    "IndexTimeAxis": ("views.chart_axis", "IndexTimeAxis"),
    "KViewBox": ("views.k_view_box", "KViewBox"),
    "LoaderWorker": ("workers.loader_worker", "LoaderWorker"),
    "VolumeItem": ("views.volume_item", "VolumeItem"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, export_name = _EXPORTS[name]
    value = getattr(import_module(module_name), export_name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
