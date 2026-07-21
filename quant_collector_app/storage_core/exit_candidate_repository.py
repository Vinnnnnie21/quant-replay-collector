from __future__ import annotations

from typing import Any, Iterable

from . import exit_review_repository


def list_confirmed_references(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event.*,
               position.actual_entry_price,
               position.entry_atr20,
               position.take_profit_status,
               position.take_profit_price,
               position.stop_loss_status,
               position.stop_loss_price,
               trade.entry_bar_time_bjt,
               trade.entry_real_time_bjt
        FROM exit_decision_events AS event
        JOIN exit_judgment_versions AS blind
          ON blind.decision_event_id=event.decision_event_id
         AND blind.phase='BLIND'
         AND blind.label='EXIT_NOW'
         AND blind.eligible_for_primary_research=1
        JOIN exit_position_snapshots AS position
          ON position.decision_event_id=event.decision_event_id
        JOIN trades AS trade ON trade.trade_id=event.trade_id
        WHERE event.setup_version_id=?
          AND event.grouping_version_id=?
          AND event.direction=?
          AND event.eligible_for_formal_research=1
          AND NOT EXISTS (
              SELECT 1 FROM exit_judgment_versions AS relabel
              WHERE relabel.decision_event_id=event.decision_event_id
                AND relabel.phase='POST_OUTCOME'
          )
          AND NOT EXISTS (
              SELECT 1 FROM exit_candidate_exclusions AS exclusion
              WHERE exclusion.decision_event_id=event.decision_event_id
          )
        ORDER BY event.decision_cutoff_utc_ms, event.decision_event_id
        """,
        (setup_version_id, grouping_version_id, direction),
    ).fetchall()
    return [dict(row) for row in rows]


def list_open_position_observations(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event.*,
               position.actual_entry_price,
               position.entry_atr20,
               position.take_profit_status,
               position.take_profit_price,
               position.stop_loss_status,
               position.stop_loss_price,
               trade.entry_bar_time_bjt,
               trade.entry_real_time_bjt
        FROM exit_decision_events AS event
        JOIN exit_original_actions AS action
          ON action.decision_event_id=event.decision_event_id
         AND action.seed_source='MANUAL_POSITION'
         AND action.original_action='NONE'
        JOIN exit_position_snapshots AS position
          ON position.decision_event_id=event.decision_event_id
        JOIN trades AS trade ON trade.trade_id=event.trade_id
        WHERE event.setup_version_id=?
          AND event.grouping_version_id=?
          AND event.direction=?
          AND event.eligible_for_formal_research=1
          AND NOT EXISTS (
              SELECT 1 FROM exit_judgment_versions AS judgment
              WHERE judgment.decision_event_id=event.decision_event_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM exit_candidate_exclusions AS exclusion
              WHERE exclusion.decision_event_id=event.decision_event_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM exit_candidate_batch_items AS batch_item
              WHERE batch_item.decision_event_id=event.decision_event_id
          )
        ORDER BY event.decision_cutoff_utc_ms, event.decision_event_id
        LIMIT ?
        """,
        (
            setup_version_id,
            grouping_version_id,
            direction,
            int(limit),
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def save_scan(
    conn,
    *,
    scan: dict[str, Any],
    candidates: Iterable[dict[str, Any]],
) -> None:
    conn.execute(
        """
        INSERT INTO exit_candidate_scans (
            scan_id, setup_version_id, grouping_version_id, direction,
            formula_version, feature_version, status, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan["scan_id"],
            scan["setup_version_id"],
            scan["grouping_version_id"],
            scan["direction"],
            scan["formula_version"],
            scan["feature_version"],
            scan["status"],
            scan["result_json"],
            scan["created_at"],
        ),
    )
    conn.executemany(
        """
        INSERT INTO exit_candidate_scores (
            scan_id, decision_event_id, holding_episode_id, similarity,
            completeness_ratio, references_json, diversity_vector_json,
            enqueue_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                scan["scan_id"],
                row["decision_event_id"],
                row["holding_episode_id"],
                row["similarity"],
                row["completeness_ratio"],
                row["references_json"],
                row["diversity_vector_json"],
                row["enqueue_reason"],
            )
            for row in candidates
        ),
    )


def get_scan(conn, scan_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM exit_candidate_scans WHERE scan_id=?",
        (scan_id,),
    ).fetchone()
    return dict(row) if row else None


def create_batch(
    conn,
    *,
    batch: dict[str, Any],
    items: Iterable[dict[str, Any]],
) -> None:
    payload = tuple(items)
    exit_review_repository.create_batch(
        conn,
        batch=batch,
        items=payload,
    )
    conn.execute(
        """
        INSERT INTO exit_candidate_batches (
            batch_id, scan_id, high_similarity_count, diverse_count, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            batch["batch_id"],
            batch["scan_id"],
            batch["high_similarity_count"],
            batch["diverse_count"],
            batch["created_at"],
        ),
    )
    conn.executemany(
        """
        INSERT INTO exit_candidate_batch_items (
            batch_id, scan_id, decision_event_id, selection_reason
        ) VALUES (?, ?, ?, ?)
        """,
        (
            (
                batch["batch_id"],
                batch["scan_id"],
                item["decision_event_id"],
                item["selection_reason"],
            )
            for item in payload
        ),
    )


def get_audit_for_event(
    conn,
    decision_event_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT score.*, item.selection_reason
        FROM exit_candidate_batch_items AS item
        JOIN exit_candidate_scores AS score
          ON score.scan_id=item.scan_id
         AND score.decision_event_id=item.decision_event_id
        WHERE item.decision_event_id=?
        """,
        (decision_event_id,),
    ).fetchone()
    return dict(row) if row else None


def insert_exclusion(conn, row: dict[str, Any]) -> bool:
    cursor = conn.execute(
        """
        INSERT INTO exit_candidate_exclusions (
            setup_version_id, grouping_version_id, decision_event_id,
            reason, created_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            row["setup_version_id"],
            row["grouping_version_id"],
            row["decision_event_id"],
            row["reason"],
            row["created_at"],
        ),
    )
    return cursor.rowcount == 1


def list_exclusions(conn) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT decision_event_id
        FROM exit_candidate_exclusions
        ORDER BY decision_event_id
        """
    ).fetchall()
    return tuple(str(row["decision_event_id"]) for row in rows)


def list_batched_ids(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT DISTINCT item.decision_event_id
        FROM exit_candidate_batch_items AS item
        JOIN exit_candidate_scans AS scan ON scan.scan_id=item.scan_id
        WHERE scan.setup_version_id=? AND scan.grouping_version_id=?
        ORDER BY item.decision_event_id
        """,
        (setup_version_id, grouping_version_id),
    ).fetchall()
    return tuple(str(row["decision_event_id"]) for row in rows)


__all__ = [
    "create_batch",
    "get_audit_for_event",
    "get_scan",
    "insert_exclusion",
    "list_batched_ids",
    "list_confirmed_references",
    "list_exclusions",
    "list_open_position_observations",
    "save_scan",
]
