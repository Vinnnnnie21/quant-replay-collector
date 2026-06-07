from __future__ import annotations

from typing import Any


def insert_premium_sample(conn, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO usdt_premium_history (
            sample_time_bjt, p2p_buy_price_cny, p2p_sell_price_cny,
            p2p_avg_price_cny, usd_cny_rate,
            buy_premium_pct, sell_premium_pct, avg_premium_pct,
            premium_pct, fx_source, sample_status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("sample_time_bjt"), row.get("p2p_buy_price_cny"), row.get("p2p_sell_price_cny"),
            row.get("p2p_avg_price_cny"), row.get("usd_cny_rate"),
            row.get("buy_premium_pct"), row.get("sell_premium_pct"), row.get("avg_premium_pct"),
            row.get("premium_pct"), row.get("fx_source"), row.get("sample_status"), row.get("error_message"),
        ),
    )


def fetch_recent_premium_samples(conn, limit: int = 240) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM (
            SELECT * FROM usdt_premium_history
            ORDER BY sample_time_bjt DESC, id DESC
            LIMIT ?
        )
        ORDER BY sample_time_bjt ASC, id ASC
        """,
        (max(1, int(limit)),),
    ).fetchall()
    return [dict(row) for row in rows]
