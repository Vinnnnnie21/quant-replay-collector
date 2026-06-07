from __future__ import annotations

import datetime as dt
import time
from typing import Callable

import requests

try:
    from app_config import BINANCE_FAPI
except ImportError:  # pragma: no cover - package import path
    from ..app_config import BINANCE_FAPI
from .types import BINANCE_RAW_COLUMNS, DataLoadCancelled, interval_to_ms, to_api_utc_ms_from_bjt


def format_request_error(error: Exception) -> str:
    if isinstance(error, requests.exceptions.Timeout):
        return "网络请求超时，请检查网络或稍后重试。"
    if isinstance(error, requests.exceptions.ConnectionError):
        return "无法连接 Binance Futures API，请检查网络、代理或地区访问限制。"
    if isinstance(error, requests.exceptions.HTTPError):
        response = error.response
        if response is not None:
            body = (response.text or "").strip().replace("\n", " ")[:200]
            return f"Binance API 返回 HTTP {response.status_code}：{body or response.reason}"
        return f"Binance API HTTP 错误：{error}"
    if isinstance(error, requests.exceptions.RequestException):
        return f"网络请求失败：{type(error).__name__}: {error}"
    if isinstance(error, (ValueError, RuntimeError)):
        return str(error)
    return f"{type(error).__name__}: {error}"


class MarketDataClient:
    RETRY_STATUS_CODES = {418, 429, 500, 502, 503, 504}

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = (5.0, 20.0),
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.sleep = sleep

    def _backoff(self, attempt: int, cancelled: Callable[[], bool]) -> None:
        deadline = time.monotonic() + self.backoff_seconds * (2 ** attempt)
        while time.monotonic() < deadline:
            if cancelled():
                raise DataLoadCancelled("Loading cancelled.")
            self.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _request_batch(self, params: dict, cancelled: Callable[[], bool]) -> list:
        for attempt in range(self.max_retries + 1):
            if cancelled():
                raise DataLoadCancelled("Loading cancelled.")
            try:
                response = self.session.get(BINANCE_FAPI, params=params, timeout=self.timeout)
                if response.status_code in self.RETRY_STATUS_CODES and attempt < self.max_retries:
                    self._backoff(attempt, cancelled)
                    continue
                response.raise_for_status()
                batch = response.json()
                if not isinstance(batch, list):
                    raise RuntimeError(f"Binance API returned an invalid response: {str(batch)[:200]}")
                return batch
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt >= self.max_retries:
                    raise
                self._backoff(attempt, cancelled)
        return []

    def download(
        self,
        symbol: str,
        interval: str,
        start_dt_bjt: dt.datetime,
        end_dt_bjt: dt.datetime,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[list]:
        cancelled = cancelled or (lambda: False)
        progress = progress or (lambda _message: None)
        current_ms = to_api_utc_ms_from_bjt(start_dt_bjt)
        end_ms = to_api_utc_ms_from_bjt(end_dt_bjt)
        step_ms = interval_to_ms(interval)
        raw: list[list] = []
        pages = 0
        while current_ms <= end_ms:
            if cancelled():
                raise DataLoadCancelled("Loading cancelled.")
            pages += 1
            if pages > 10000:
                raise RuntimeError("Download exceeded its page safety limit.")
            batch = self._request_batch(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": current_ms,
                    "endTime": end_ms,
                    "limit": 1000,
                },
                cancelled,
            )
            if not batch:
                break
            bad_rows = [row for row in batch if not isinstance(row, list) or len(row) < len(BINANCE_RAW_COLUMNS)]
            if bad_rows:
                raise RuntimeError(f"Binance API returned {len(bad_rows)} incomplete kline rows.")
            raw.extend([row[: len(BINANCE_RAW_COLUMNS)] for row in batch])
            current_ms = int(batch[-1][0]) + step_ms
            progress(f"Downloaded {len(raw)} bars.")
            if len(batch) < 1000:
                break
        return raw


_format_request_error = format_request_error


__all__ = ["MarketDataClient", "_format_request_error", "format_request_error"]
