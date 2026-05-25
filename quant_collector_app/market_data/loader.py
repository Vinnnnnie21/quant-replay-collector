from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from app_config import CACHE_DIR
from app_logger import get_logger
from .cache import KlineCache
from .client import MarketDataClient, format_request_error
from .quality import DataQualityReport, assess_data_quality
from .transforms import normalize_kline_df
from .types import BINANCE_RAW_COLUMNS, DataLoadCancelled, LoadRequest, normalize_interval, normalize_symbol, validate_date_range


logger = get_logger(__name__)


class KlineLoader:
    def __init__(self, cache_dir: Path | str = CACHE_DIR, client: MarketDataClient | None = None):
        self.cache = KlineCache(cache_dir)
        self.cache_dir = self.cache.cache_dir
        self.client = client or MarketDataClient()

    def cache_path(self, symbol: str, interval: str, start_dt_bjt, end_dt_bjt) -> Path:
        return self.cache.path(symbol, interval, LoadRequest(symbol, interval, start_dt_bjt, end_dt_bjt))

    @staticmethod
    def manifest_path(cache_path: Path) -> Path:
        return KlineCache.manifest_path(cache_path)

    def _finalize(
        self,
        df: pd.DataFrame,
        request: LoadRequest,
        symbol: str,
        interval: str,
        source: str,
        stats: dict[str, int],
    ) -> tuple[pd.DataFrame, DataQualityReport]:
        report = assess_data_quality(
            df,
            symbol,
            interval,
            request.start_dt_bjt,
            request.end_dt_bjt,
            source,
            stats,
        )
        df.attrs["data_quality_report"] = report.to_dict()
        df.attrs["data_source"] = source
        return df, report

    def read_cache(
        self,
        cache_path: Path,
        request: LoadRequest,
        symbol: str,
        interval: str,
    ) -> tuple[pd.DataFrame, DataQualityReport]:
        frame, stats = self.cache.read(cache_path, request, interval)
        return self._finalize(frame, request, symbol, interval, "cache", stats)

    def _write_cache_manifest(
        self,
        cache_path: Path,
        request: LoadRequest,
        symbol: str,
        interval: str,
        report: DataQualityReport,
    ) -> None:
        self.cache.write_manifest(cache_path, request, symbol, interval, report)

    def load(
        self,
        request: LoadRequest,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[pd.DataFrame, str]:
        progress = progress or (lambda _message: None)
        cancelled = cancelled or (lambda: False)
        symbol = normalize_symbol(request.symbol)
        interval = normalize_interval(request.interval)
        start_dt_bjt, end_dt_bjt = validate_date_range(request.start_dt_bjt, request.end_dt_bjt)
        normalized_request = LoadRequest(symbol, interval, start_dt_bjt, end_dt_bjt, request.use_cache)
        cache_path = self.cache.path(symbol, interval, normalized_request)
        progress("Checking cache.")
        if normalized_request.use_cache and cache_path.exists():
            try:
                frame, report = self.read_cache(cache_path, normalized_request, symbol, interval)
                return frame, f"Loaded cache {cache_path.name}; bars={len(frame)}; quality={report.data_quality_status}."
            except Exception as cache_error:
                progress(f"Cache is unusable; downloading online instead: {cache_error}")
        try:
            progress(f"Downloading Binance Futures klines: {symbol} {interval}.")
            raw = self.client.download(symbol, interval, start_dt_bjt, end_dt_bjt, progress, cancelled)
            if cancelled():
                raise DataLoadCancelled("Loading cancelled.")
            if not raw:
                raise ValueError(f"No klines returned for {symbol} {interval}.")
            progress("Parsing and cleaning downloaded klines.")
            raw_df = pd.DataFrame(raw, columns=BINANCE_RAW_COLUMNS)
            frame, stats = normalize_kline_df(raw_df, start_dt_bjt, end_dt_bjt, interval, "Binance download")
            progress("Validating kline data quality.")
            frame, report = self._finalize(frame, normalized_request, symbol, interval, "binance_online", stats)
            try:
                self.cache.write_frame(cache_path, frame)
                self._write_cache_manifest(cache_path, normalized_request, symbol, interval, report)
                cache_message = f"cache={cache_path.name}"
            except Exception as cache_error:
                logger.warning("下载成功但缓存写入失败：%s", cache_error, exc_info=True)
                cache_message = f"cache write failed: {cache_error}"
            return frame, f"Downloaded bars={len(frame)}; quality={report.data_quality_status}; {cache_message}."
        except DataLoadCancelled:
            return pd.DataFrame(), "Loading cancelled."
        except Exception as online_error:
            if cache_path.exists():
                try:
                    frame, report = self.read_cache(cache_path, normalized_request, symbol, interval)
                    return frame, (
                        f"Online load failed; using cache {cache_path.name}; bars={len(frame)}; "
                        f"quality={report.data_quality_status}; reason={format_request_error(online_error)}"
                    )
                except Exception as cache_error:
                    raise RuntimeError(
                        f"Online load failed ({format_request_error(online_error)}); "
                        f"cache fallback failed ({cache_error})."
                    ) from cache_error
            raise RuntimeError(f"Online load failed: {format_request_error(online_error)}") from online_error


__all__ = ["KlineLoader"]
