from __future__ import annotations

from typing import Any, Iterable


def upsert_klines(conn, rows: Iterable[dict[str, Any]]) -> None:
    payload = list(rows)
    if not payload:
        return
    conn.executemany(
        """
        INSERT INTO klines (
            symbol, interval, open_time_utc_ms, open_time_bjt, close_time_utc_ms,
            open, high, low, close, volume, source, downloaded_at, data_quality_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, interval, open_time_utc_ms) DO UPDATE SET
            open_time_bjt=excluded.open_time_bjt,
            close_time_utc_ms=excluded.close_time_utc_ms,
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            source=excluded.source,
            downloaded_at=excluded.downloaded_at,
            data_quality_status=excluded.data_quality_status
        """,
        [
            (
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
                row.get("source"),
                row.get("downloaded_at"),
                row.get("data_quality_status"),
            )
            for row in payload
        ],
    )


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
