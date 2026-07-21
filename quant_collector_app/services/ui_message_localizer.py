"""Translate stable worker progress messages before they reach Qt widgets."""

from __future__ import annotations

import re
from collections.abc import Callable


Translator = Callable[[str], str]


_INTERNAL_ERROR_PREFIX = re.compile(
    r"^(?:(?:[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))|"
    r"(?:[A-Z][A-Z0-9_]{2,}))\s*:\s*(.*)$"
)


_EXACT_KEYS = {
    "Checking cache.": "worker.market.checking_cache",
    "Exact-name cache is incomplete for the requested time range; checking coverage index.": "worker.market.checking_coverage",
    "Parsing and cleaning downloaded klines.": "worker.market.parsing",
    "Validating kline data quality.": "worker.market.validating",
    "Loading cancelled.": "worker.market.cancelled",
    "Preparing export...": "worker.export.preparing",
    "Reading export source data...": "worker.export.reading",
    "Validating and preparing export data...": "worker.export.validating",
    "Building research tables...": "worker.export.building_tables",
    "Writing export files...": "worker.export.writing_files",
    "Generating export reports...": "worker.export.generating_reports",
    "Generating reproducible research pack...": "worker.export.generating_pack",
    "Finalizing export manifest...": "worker.export.finalizing_manifest",
    "Writing success manifest...": "worker.export.writing_manifest",
    "Preparing to publish export results...": "worker.export.preparing_publish",
    "正在安全发布导出结果": "worker.export.publishing",
    "导出已完成，旧临时目录稍后清理": "worker.export.cleanup_later",
    "Backing up local database in background...": "worker.backup.running",
    "No HTF bars returned.": "worker.market.no_higher_timeframe_data",
}


def localize_worker_message(message: str, translator: Translator) -> str:
    """Return localized UI copy while preserving unknown diagnostic details."""

    text = str(message or "").strip()
    key = _EXACT_KEYS.get(text)
    if key is not None:
        return translator(key)

    match = re.fullmatch(r"Downloaded (\d+) bars\.", text)
    if match:
        return translator("worker.market.downloaded").format(count=match.group(1))
    match = re.match(r"Loaded cache .+; bars=(\d+);", text)
    if match:
        return translator("worker.market.loaded_cache_count").format(count=match.group(1))
    match = re.match(r"Loaded covered cache; files=\d+; bars=(\d+);", text)
    if match:
        return translator("worker.market.loaded_cache_count").format(count=match.group(1))
    match = re.match(r"(?:Filled cache gaps|Downloaded) bars=(\d+);", text)
    if match:
        return translator("worker.market.loaded_online_count").format(count=match.group(1))
    match = re.match(r"Online load failed; using cache .+; bars=(\d+);", text)
    if match:
        return translator("worker.market.fallback_cache_count").format(count=match.group(1))
    match = re.fullmatch(r"Backing up local database in background\.\.\. (\d+)%", text)
    if match:
        return translator("worker.backup.progress").format(percent=match.group(1))
    match = re.fullmatch(r"Cache partially covers request; downloading (\d+) missing range\(s\)\.", text)
    if match:
        return translator("worker.market.partial_cache").format(count=match.group(1))
    chunk = re.fullmatch(r"Writing export table: (.+) \(chunk (\d+)/(\d+)\)", text)
    if chunk:
        return translator("worker.export.writing_chunk").format(
            table=chunk.group(1),
            current=chunk.group(2),
            total=chunk.group(3),
        )

    prefixes = (
        ("Cache is unusable; downloading online instead: ", "worker.market.cache_unusable", "error"),
        ("Downloading Binance Futures klines: ", "worker.market.downloading", "detail"),
        ("Writing export table: ", "worker.export.writing_table", "table"),
        ("Writing optional Parquet table: ", "worker.export.writing_parquet", "table"),
        ("Finished export table: ", "worker.export.finished_table", "table"),
        ("加载失败：", "worker.market.failed", "error"),
    )
    for prefix, translation_key, field in prefixes:
        if text.startswith(prefix):
            value = text[len(prefix):]
            if field == "error":
                value = _localize_error_detail(value, translator)
            return translator(translation_key).format(**{field: value})

    return text


def sanitize_worker_error_detail(message: str) -> str:
    """Hide implementation exception types and stable internal error codes."""

    detail = str(message or "").strip()
    for _unused in range(3):
        match = _INTERNAL_ERROR_PREFIX.fullmatch(detail)
        if match is None:
            break
        detail = match.group(1).strip()
    return detail or "—"


def _localize_error_detail(value: str, translator: Translator) -> str:
    exact_keys = {
        "网络请求超时，请检查网络或稍后重试。": "worker.market.error.timeout",
        "无法连接 Binance Futures API，请检查网络、代理或地区访问限制。": "worker.market.error.connection",
    }
    key = exact_keys.get(value)
    if key is not None:
        return translator(key)
    return value


__all__ = ["localize_worker_message", "sanitize_worker_error_detail"]
