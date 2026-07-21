from __future__ import annotations

from collections.abc import Callable
from itertools import islice
from typing import Any, Iterable

try:
    from market_data.types import KLINE_ANCILLARY_COLUMNS
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import KLINE_ANCILLARY_COLUMNS


KLINE_READ_BATCH_SIZE = 5_000
KLINE_WRITE_BATCH_SIZE = 5_000
_UPSERT_KLINES_SQL = """
    INSERT INTO klines (
        symbol, interval, open_time_utc_ms, open_time_bjt, close_time_utc_ms,
        open, high, low, close, volume, quote_volume, trade_count,
        taker_buy_base_volume, taker_buy_quote_volume,
        source, downloaded_at, data_quality_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(symbol, interval, open_time_utc_ms) DO UPDATE SET
        open_time_bjt=excluded.open_time_bjt,
        close_time_utc_ms=excluded.close_time_utc_ms,
        open=excluded.open,
        high=excluded.high,
        low=excluded.low,
        close=excluded.close,
        volume=excluded.volume,
        quote_volume=COALESCE(excluded.quote_volume, klines.quote_volume),
        trade_count=COALESCE(excluded.trade_count, klines.trade_count),
        taker_buy_base_volume=COALESCE(
            excluded.taker_buy_base_volume,
            klines.taker_buy_base_volume
        ),
        taker_buy_quote_volume=COALESCE(
            excluded.taker_buy_quote_volume,
            klines.taker_buy_quote_volume
        ),
        source=excluded.source,
        downloaded_at=excluded.downloaded_at,
        data_quality_status=excluded.data_quality_status
"""


def _kline_parameters(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("symbol"),
        row.get("interval"),
        row.get("open_time_utc_ms"),
        row.get("open_time_bjt"),
        row.get("close_time_utc_ms"),
        row.get("open"),
        row.get("high"),
        row.get("low"),
        row.get("close"),
        row.get("volume"),
        row.get("quote_volume"),
        row.get("trade_count"),
        row.get("taker_buy_base_volume"),
        row.get("taker_buy_quote_volume"),
        row.get("source"),
        row.get("downloaded_at"),
        row.get("data_quality_status"),
    )


def upsert_klines(conn, rows: Iterable[dict[str, Any]]) -> None:
    iterator = iter(rows)
    while batch := list(islice(iterator, KLINE_WRITE_BATCH_SIZE)):
        conn.executemany(_UPSERT_KLINES_SQL, map(_kline_parameters, batch))


def fetch_klines_for_range(
    conn,
    *,
    symbol: str,
    interval: str,
    start_time_utc_ms: int,
    end_time_utc_ms: int,
    cancelled: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """
        SELECT
            symbol, interval, open_time_utc_ms, open_time_bjt,
            close_time_utc_ms, open, high, low, close, volume,
            quote_volume, trade_count, taker_buy_base_volume,
            taker_buy_quote_volume, source, downloaded_at,
            data_quality_status
        FROM klines
        WHERE symbol=? AND interval=?
          AND open_time_utc_ms BETWEEN ? AND ?
        ORDER BY open_time_utc_ms ASC
        """,
        (symbol, interval, int(start_time_utc_ms), int(end_time_utc_ms)),
    )
    rows = []
    while True:
        if cancelled is not None and cancelled():
            return []
        batch = cursor.fetchmany(KLINE_READ_BATCH_SIZE)
        if not batch:
            break
        rows.extend(batch)
    return [
        {"bar_index": bar_index, **dict(row)}
        for bar_index, row in enumerate(rows)
    ]


def fetch_kline_ancillary_rows_for_range(
    conn,
    *,
    symbol: str,
    interval: str,
    start_time_utc_ms: int,
    end_time_utc_ms: int,
    cancelled: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """
        SELECT
            open_time_utc_ms,
            quote_volume,
            trade_count,
            taker_buy_base_volume,
            taker_buy_quote_volume
        FROM klines
        WHERE symbol=? AND interval=?
          AND open_time_utc_ms BETWEEN ? AND ?
        ORDER BY open_time_utc_ms ASC
        """,
        (
            symbol,
            interval,
            int(start_time_utc_ms),
            int(end_time_utc_ms),
        ),
    )
    rows = []
    while True:
        if cancelled is not None and cancelled():
            return []
        batch = cursor.fetchmany(KLINE_READ_BATCH_SIZE)
        if not batch:
            break
        rows.extend(dict(row) for row in batch)
    return rows


def audit_kline_ancillary_completeness(
    conn,
    *,
    symbol: str,
    interval: str,
    start_time_utc_ms: int,
    end_time_utc_ms: int,
) -> dict[str, Any]:
    aggregates = []
    for field_name in KLINE_ANCILLARY_COLUMNS:
        aggregates.extend(
            (
                f"COALESCE(SUM({field_name} IS NOT NULL), 0) "
                f"AS {field_name}_covered",
                f"COALESCE(SUM({field_name} IS NULL), 0) "
                f"AS {field_name}_missing",
                f"COALESCE(SUM({field_name} = 0), 0) "
                f"AS {field_name}_zero",
            )
        )
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total_rows,
            MIN(open_time_utc_ms) AS first_open_time_utc_ms,
            MAX(open_time_utc_ms) AS last_open_time_utc_ms,
            {", ".join(aggregates)}
        FROM klines
        WHERE symbol=? AND interval=?
          AND open_time_utc_ms BETWEEN ? AND ?
        """,
        (
            symbol,
            interval,
            int(start_time_utc_ms),
            int(end_time_utc_ms),
        ),
    ).fetchone()
    total_rows = int(row["total_rows"])
    fields = {}
    for field_name in KLINE_ANCILLARY_COLUMNS:
        covered_rows = int(row[f"{field_name}_covered"])
        fields[field_name] = {
            "covered_rows": covered_rows,
            "missing_rows": int(row[f"{field_name}_missing"]),
            "zero_rows": int(row[f"{field_name}_zero"]),
            "coverage_ratio": (
                covered_rows / total_rows if total_rows else 0.0
            ),
        }
    return {
        "symbol": symbol,
        "interval": interval,
        "requested_start_time_utc_ms": int(start_time_utc_ms),
        "requested_end_time_utc_ms": int(end_time_utc_ms),
        "first_open_time_utc_ms": row["first_open_time_utc_ms"],
        "last_open_time_utc_ms": row["last_open_time_utc_ms"],
        "total_rows": total_rows,
        "fields": fields,
    }


def list_kline_series_ranges(
    conn,
    *,
    ancillary_incomplete_only: bool = False,
) -> list[dict[str, Any]]:
    incomplete_expression = " OR ".join(
        f"{field_name} IS NULL"
        for field_name in KLINE_ANCILLARY_COLUMNS
    )
    rows = conn.execute(
        f"""
        SELECT
            symbol,
            interval,
            MIN(open_time_utc_ms) AS start_time_utc_ms,
            MAX(open_time_utc_ms) AS end_time_utc_ms,
            SUM({incomplete_expression}) AS incomplete_rows
        FROM klines
        GROUP BY symbol, interval
        {
            "HAVING SUM(" + incomplete_expression + ") > 0"
            if ancillary_incomplete_only
            else ""
        }
        ORDER BY symbol ASC, interval ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def save_data_quality_report(conn, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO data_quality_reports (
            report_id, symbol, interval, start_time_bjt, end_time_bjt,
            expected_bars, actual_bars, missing_bars, duplicated_bars,
            invalid_rows, first_open_time_bjt, last_open_time_bjt,
            created_at, report_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(report_id) DO UPDATE SET
            symbol=excluded.symbol,
            interval=excluded.interval,
            start_time_bjt=excluded.start_time_bjt,
            end_time_bjt=excluded.end_time_bjt,
            expected_bars=excluded.expected_bars,
            actual_bars=excluded.actual_bars,
            missing_bars=excluded.missing_bars,
            duplicated_bars=excluded.duplicated_bars,
            invalid_rows=excluded.invalid_rows,
            first_open_time_bjt=excluded.first_open_time_bjt,
            last_open_time_bjt=excluded.last_open_time_bjt,
            created_at=excluded.created_at,
            report_json=excluded.report_json
        """,
        (
            row.get("report_id"),
            row.get("symbol"),
            row.get("interval"),
            row.get("start_time_bjt"),
            row.get("end_time_bjt"),
            row.get("expected_bars"),
            row.get("actual_bars"),
            row.get("missing_bars"),
            row.get("duplicated_bars"),
            row.get("invalid_rows"),
            row.get("first_open_time_bjt"),
            row.get("last_open_time_bjt"),
            row.get("created_at"),
            row.get("report_json"),
        ),
    )
