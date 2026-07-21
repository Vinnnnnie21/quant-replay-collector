from __future__ import annotations

import json
from typing import Any, Iterable


def list_entry_setup_links(
    conn,
    *,
    source_sample_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM entry_decision_events
        WHERE source_sample_id=?
        ORDER BY created_at, decision_event_id
        """,
        (source_sample_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_decision_event_by_source(
    conn,
    *,
    source_sample_id: str,
    review_setup_version_id: str,
    grouping_version_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM exit_decision_events
        WHERE source_sample_id=? AND review_setup_version_id=?
          AND grouping_version_id=?
        """,
        (
            source_sample_id,
            review_setup_version_id,
            grouping_version_id,
        ),
    ).fetchone()
    return dict(row) if row else None


def insert_decision_event_bundle(
    conn,
    *,
    event: dict[str, Any],
    position: dict[str, Any],
    account_pressure: dict[str, Any],
    original_action: dict[str, Any],
) -> bool:
    cursor = conn.execute(
        """
        INSERT INTO exit_decision_events (
            decision_event_id, source_sample_id, setup_version_id,
            review_setup_version_id, grouping_version_id, episode_id,
            trade_id, entry_event_id, session_id, symbol, direction,
            decision_timeframe, context_timeframe_one,
            context_timeframe_two, decision_cutoff_utc_ms,
            decision_bar_open_time_utc_ms, observed_action_time_utc_ms,
            timing_approximate, setup_link_status,
            eligible_for_formal_research, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(
            source_sample_id, review_setup_version_id, grouping_version_id
        ) DO NOTHING
        """,
        (
            event["decision_event_id"],
            event["source_sample_id"],
            event.get("setup_version_id"),
            event["review_setup_version_id"],
            event["grouping_version_id"],
            event["episode_id"],
            event["trade_id"],
            event.get("entry_event_id"),
            event.get("session_id"),
            event["symbol"],
            event["direction"],
            event["decision_timeframe"],
            event["context_timeframe_one"],
            event["context_timeframe_two"],
            event["decision_cutoff_utc_ms"],
            event["decision_bar_open_time_utc_ms"],
            event.get("observed_action_time_utc_ms"),
            int(bool(event["timing_approximate"])),
            event["setup_link_status"],
            int(bool(event["eligible_for_formal_research"])),
            event["created_at"],
        ),
    )
    if cursor.rowcount == 0:
        existing = get_decision_event_by_source(
            conn,
            source_sample_id=event["source_sample_id"],
            review_setup_version_id=event["review_setup_version_id"],
            grouping_version_id=event["grouping_version_id"],
        )
        if (
            existing is None
            or existing["decision_event_id"] != event["decision_event_id"]
        ):
            raise ValueError(
                "Exit seed identity conflicts with an existing decision event"
            )
        return False

    conn.execute(
        """
        INSERT INTO exit_position_snapshots (
            decision_event_id, actual_entry_price, entry_price_source,
            entry_atr20, entry_atr_status, entry_bar_index,
            decision_bar_index, take_profit_status, take_profit_price,
            stop_loss_status, stop_loss_price, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["decision_event_id"],
            position.get("actual_entry_price"),
            position["entry_price_source"],
            position.get("entry_atr20"),
            position["entry_atr_status"],
            position.get("entry_bar_index"),
            position.get("decision_bar_index"),
            position["take_profit_status"],
            position.get("take_profit_price"),
            position["stop_loss_status"],
            position.get("stop_loss_price"),
            position["created_at"],
        ),
    )
    conn.execute(
        """
        INSERT INTO exit_account_pressure_snapshots (
            decision_event_id, equity_before_decision,
            position_notional_quote, position_equity_ratio,
            total_open_notional_quote, total_exposure_ratio,
            open_position_count, account_drawdown_pct, leverage,
            margin_quote, liquidation_price, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["decision_event_id"],
            account_pressure.get("equity_before_decision"),
            account_pressure.get("position_notional_quote"),
            account_pressure.get("position_equity_ratio"),
            account_pressure.get("total_open_notional_quote"),
            account_pressure.get("total_exposure_ratio"),
            account_pressure["open_position_count"],
            account_pressure.get("account_drawdown_pct"),
            account_pressure.get("leverage"),
            account_pressure.get("margin_quote"),
            account_pressure.get("liquidation_price"),
            account_pressure["created_at"],
        ),
    )
    conn.execute(
        """
        INSERT INTO exit_original_actions (
            decision_event_id, seed_source, original_action,
            source_event_id, action_time_utc_ms, realized_pnl_quote,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["decision_event_id"],
            original_action["seed_source"],
            original_action["original_action"],
            original_action.get("source_event_id"),
            original_action.get("action_time_utc_ms"),
            original_action.get("realized_pnl_quote"),
            original_action["created_at"],
        ),
    )
    return True


def list_pending_decision_events(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        WITH ranked_pending AS (
            SELECT
                event.*,
                ROW_NUMBER() OVER (
                    PARTITION BY event.episode_id
                    ORDER BY
                        CASE action.seed_source
                            WHEN 'ACTUAL_CLOSE' THEN 0 ELSE 1
                        END,
                        event.created_at,
                        event.decision_event_id
                ) AS episode_rank
            FROM exit_decision_events AS event
            JOIN exit_original_actions AS action
              ON action.decision_event_id=event.decision_event_id
            LEFT JOIN exit_judgment_versions AS judgment
              ON judgment.decision_event_id=event.decision_event_id
             AND judgment.phase='BLIND'
            WHERE event.review_setup_version_id=?
              AND event.grouping_version_id=?
              AND judgment.judgment_id IS NULL
        )
        SELECT * FROM ranked_pending
        WHERE episode_rank=1
        ORDER BY created_at, decision_event_id
        LIMIT ?
        """,
        (setup_version_id, grouping_version_id, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def list_actual_close_episode_member_ids(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
    limit: int,
) -> tuple[str, ...]:
    rows = conn.execute(
        """
        WITH ranked_episode_closes AS (
            SELECT
                close_event.event_id,
                close_event.created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY membership.episode_id
                    ORDER BY close_event.created_at, close_event.event_id
                ) AS episode_rank
            FROM market_episode_memberships AS membership
            JOIN trade_events AS close_event
              ON close_event.event_id=membership.sample_id
            JOIN trades AS position
              ON position.trade_id=close_event.trade_id
            LEFT JOIN exit_decision_events AS exit_decision
              ON exit_decision.source_sample_id=close_event.event_id
             AND exit_decision.review_setup_version_id=?
             AND exit_decision.grouping_version_id=membership.grouping_version_id
            WHERE membership.grouping_version_id=?
              AND close_event.event_type='CLOSE'
              AND close_event.side=?
              AND position.status='CLOSED'
              AND position.exit_event_id=close_event.event_id
              AND exit_decision.decision_event_id IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM entry_decision_events AS entry_decision
                  WHERE entry_decision.source_sample_id=position.entry_event_id
                    AND entry_decision.setup_version_id=?
              )
        )
        SELECT event_id
        FROM ranked_episode_closes
        WHERE episode_rank=1
        ORDER BY created_at, event_id
        LIMIT ?
        """,
        (
            setup_version_id,
            grouping_version_id,
            direction,
            setup_version_id,
            int(limit),
        ),
    ).fetchall()
    return tuple(str(row["event_id"]) for row in rows)


def create_batch(
    conn,
    *,
    batch: dict[str, Any],
    items: Iterable[dict[str, Any]],
) -> None:
    conn.execute(
        """
        INSERT INTO exit_review_batches (
            batch_id, setup_version_id, grouping_version_id, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            batch["batch_id"],
            batch["setup_version_id"],
            batch["grouping_version_id"],
            batch["created_at"],
        ),
    )
    conn.executemany(
        """
        INSERT INTO exit_review_batch_items (
            batch_id, blind_item_id, decision_event_id, display_order
        ) VALUES (?, ?, ?, ?)
        """,
        (
            (
                batch["batch_id"],
                item["blind_item_id"],
                item["decision_event_id"],
                item["display_order"],
            )
            for item in items
        ),
    )


def get_batch_item(
    conn,
    *,
    batch_id: str,
    blind_item_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT item.*, event.*,
               position.actual_entry_price,
               position.entry_atr20,
               position.entry_bar_index,
               position.decision_bar_index,
               position.take_profit_status,
               position.take_profit_price,
               position.stop_loss_status,
               position.stop_loss_price,
               pressure.equity_before_decision,
               pressure.position_notional_quote,
               pressure.position_equity_ratio,
               pressure.total_open_notional_quote,
               pressure.total_exposure_ratio,
               pressure.open_position_count,
               pressure.account_drawdown_pct,
               pressure.leverage,
               pressure.margin_quote,
               pressure.liquidation_price
        FROM exit_review_batch_items AS item
        JOIN exit_decision_events AS event
          ON event.decision_event_id=item.decision_event_id
        JOIN exit_position_snapshots AS position
          ON position.decision_event_id=event.decision_event_id
        JOIN exit_account_pressure_snapshots AS pressure
          ON pressure.decision_event_id=event.decision_event_id
        WHERE item.batch_id=? AND item.blind_item_id=?
        """,
        (batch_id, blind_item_id),
    ).fetchone()
    return dict(row) if row else None


def insert_judgment(conn, row: dict[str, Any]) -> bool:
    values = (
        row["judgment_id"],
        row["decision_event_id"],
        row["version_number"],
        row["phase"],
        row["label"],
        json.dumps(row["reason_tags"], ensure_ascii=False),
        row["confidence"],
        row["note"],
        row.get("previous_judgment_id"),
        int(bool(row["eligible_for_primary_research"])),
        row["created_at"],
    )
    if row["phase"] == "BLIND":
        cursor = conn.execute(
            """
            INSERT INTO exit_judgment_versions (
                judgment_id, decision_event_id, version_number, phase,
                label, reason_tags_json, confidence, note,
                previous_judgment_id, eligible_for_primary_research,
                created_at
            )
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM exit_judgment_versions
                WHERE decision_event_id=? AND phase='BLIND'
            )
              AND NOT EXISTS (
                  SELECT 1 FROM exit_candidate_exclusions
                  WHERE decision_event_id=?
              )
            """,
            (
                *values,
                row["decision_event_id"],
                row["decision_event_id"],
            ),
        )
        return cursor.rowcount == 1
    conn.execute(
        """
        INSERT INTO exit_judgment_versions (
            judgment_id, decision_event_id, version_number, phase,
            label, reason_tags_json, confidence, note,
            previous_judgment_id, eligible_for_primary_research,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return True


def list_judgments(conn, decision_event_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM exit_judgment_versions
        WHERE decision_event_id=?
        ORDER BY version_number
        """,
        (decision_event_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["reason_tags"] = tuple(json.loads(item.pop("reason_tags_json")))
        result.append(item)
    return result


def get_reveal(conn, decision_event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM exit_review_reveals WHERE decision_event_id=?",
        (decision_event_id,),
    ).fetchone()
    return dict(row) if row else None


def insert_reveal(conn, row: dict[str, Any]) -> bool:
    cursor = conn.execute(
        """
        INSERT INTO exit_review_reveals (
            decision_event_id, blind_judgment_id, revealed_at
        ) VALUES (?, ?, ?)
        ON CONFLICT(decision_event_id) DO NOTHING
        """,
        (
            row["decision_event_id"],
            row["blind_judgment_id"],
            row["revealed_at"],
        ),
    )
    return cursor.rowcount == 1


def get_original_action(conn, decision_event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM exit_original_actions WHERE decision_event_id=?",
        (decision_event_id,),
    ).fetchone()
    return dict(row) if row else None


__all__ = [
    "create_batch",
    "get_batch_item",
    "get_decision_event_by_source",
    "get_original_action",
    "get_reveal",
    "insert_decision_event_bundle",
    "insert_judgment",
    "insert_reveal",
    "list_entry_setup_links",
    "list_actual_close_episode_member_ids",
    "list_judgments",
    "list_pending_decision_events",
]
