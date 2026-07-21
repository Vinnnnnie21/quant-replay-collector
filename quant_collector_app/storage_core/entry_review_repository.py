from __future__ import annotations

import json
from typing import Any, Iterable


def insert_decision_event_with_original_action(
    conn,
    *,
    event: dict[str, Any],
    original_action: dict[str, Any],
) -> bool:
    cursor = conn.execute(
        """
        INSERT INTO entry_decision_events (
            decision_event_id, source_sample_id, setup_version_id,
            grouping_version_id, episode_id, session_id, symbol, direction,
            decision_timeframe, context_timeframe_one,
            context_timeframe_two, decision_cutoff_utc_ms,
            decision_bar_open_time_utc_ms, observed_action_time_utc_ms,
            timing_approximate, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_sample_id, setup_version_id, grouping_version_id)
        DO NOTHING
        """,
        (
            event["decision_event_id"],
            event["source_sample_id"],
            event["setup_version_id"],
            event["grouping_version_id"],
            event["episode_id"],
            event.get("session_id"),
            event["symbol"],
            event["direction"],
            event["decision_timeframe"],
            event["context_timeframe_one"],
            event["context_timeframe_two"],
            event["decision_cutoff_utc_ms"],
            event["decision_bar_open_time_utc_ms"],
            event.get("observed_action_time_utc_ms"),
            int(bool(event.get("timing_approximate"))),
            event["created_at"],
        ),
    )
    if cursor.rowcount == 0:
        existing = conn.execute(
            """
            SELECT decision_event_id
            FROM entry_decision_events
            WHERE source_sample_id=? AND setup_version_id=?
              AND grouping_version_id=?
            """,
            (
                event["source_sample_id"],
                event["setup_version_id"],
                event["grouping_version_id"],
            ),
        ).fetchone()
        if (
            existing is None
            or existing["decision_event_id"] != event["decision_event_id"]
        ):
            raise ValueError(
                "Entry seed identity conflicts with an existing decision event"
            )
        return False
    conn.execute(
        """
        INSERT INTO entry_original_actions (
            decision_event_id, seed_source, original_action,
            source_event_id, action_time_utc_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event["decision_event_id"],
            original_action["seed_source"],
            original_action["original_action"],
            original_action.get("source_event_id"),
            original_action.get("action_time_utc_ms"),
            original_action["created_at"],
        ),
    )
    return True


def get_decision_event_by_source(
    conn,
    *,
    source_sample_id: str,
    setup_version_id: str,
    grouping_version_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM entry_decision_events
        WHERE source_sample_id=? AND setup_version_id=?
          AND grouping_version_id=?
        """,
        (source_sample_id, setup_version_id, grouping_version_id),
    ).fetchone()
    return dict(row) if row else None


def get_decision_event(conn, decision_event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM entry_decision_events WHERE decision_event_id=?",
        (decision_event_id,),
    ).fetchone()
    return dict(row) if row else None


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
                e.*,
                CASE a.seed_source
                    WHEN 'ACTUAL_OPEN' THEN 0 ELSE 1
                END AS seed_priority,
                ROW_NUMBER() OVER (
                    PARTITION BY e.episode_id
                    ORDER BY
                        CASE a.seed_source
                            WHEN 'ACTUAL_OPEN' THEN 0 ELSE 1
                        END,
                        e.created_at,
                        e.decision_event_id
                ) AS episode_rank
            FROM entry_decision_events AS e
            JOIN entry_original_actions AS a
              ON a.decision_event_id=e.decision_event_id
            LEFT JOIN entry_judgment_versions AS j
              ON j.decision_event_id=e.decision_event_id
             AND j.phase='BLIND'
            WHERE e.setup_version_id=? AND e.grouping_version_id=?
              AND j.judgment_id IS NULL
        )
        SELECT *
        FROM ranked_pending
        WHERE episode_rank=1
        ORDER BY
          seed_priority,
          created_at,
          decision_event_id
        LIMIT ?
        """,
        (setup_version_id, grouping_version_id, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def list_actual_open_episode_member_ids(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
    limit: int,
) -> tuple[str, ...]:
    rows = conn.execute(
        """
        WITH ranked_episode_opens AS (
            SELECT
                e.event_id,
                e.created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY m.episode_id
                    ORDER BY e.created_at, e.event_id
                ) AS episode_rank
            FROM market_episode_memberships AS m
            JOIN trade_events AS e ON e.event_id=m.sample_id
            LEFT JOIN entry_decision_events AS d
              ON d.source_sample_id=e.event_id
             AND d.setup_version_id=?
             AND d.grouping_version_id=m.grouping_version_id
            WHERE m.grouping_version_id=?
              AND e.event_type='OPEN'
              AND e.side=?
              AND d.decision_event_id IS NULL
        )
        SELECT event_id
        FROM ranked_episode_opens
        WHERE episode_rank=1
        ORDER BY created_at, event_id
        LIMIT ?
        """,
        (
            setup_version_id,
            grouping_version_id,
            direction,
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
        INSERT INTO entry_review_batches (
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
        INSERT INTO entry_review_batch_items (
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
        SELECT i.*, e.*, b.setup_version_id AS batch_setup_version_id,
               b.grouping_version_id AS batch_grouping_version_id
        FROM entry_review_batch_items AS i
        JOIN entry_review_batches AS b ON b.batch_id=i.batch_id
        JOIN entry_decision_events AS e
          ON e.decision_event_id=i.decision_event_id
        WHERE i.batch_id=? AND i.blind_item_id=?
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
            INSERT INTO entry_judgment_versions (
                judgment_id, decision_event_id, version_number, phase, label,
                reason_tags_json, confidence, note, previous_judgment_id,
                eligible_for_primary_research, created_at
            )
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM entry_judgment_versions
                WHERE decision_event_id=? AND phase='BLIND'
            )
              AND NOT EXISTS (
                  SELECT 1
                  FROM entry_decision_events AS event
                  JOIN entry_candidate_exclusions AS exclusion
                    ON exclusion.source_sample_id=event.source_sample_id
                  WHERE event.decision_event_id=?
              )
            """,
            (*values, row["decision_event_id"], row["decision_event_id"]),
        )
        return cursor.rowcount == 1
    conn.execute(
        """
        INSERT INTO entry_judgment_versions (
            judgment_id, decision_event_id, version_number, phase, label,
            reason_tags_json, confidence, note, previous_judgment_id,
            eligible_for_primary_research, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return True


def list_judgments(conn, decision_event_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM entry_judgment_versions
        WHERE decision_event_id=?
        ORDER BY version_number
        """,
        (decision_event_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["reason_tags"] = tuple(
            json.loads(item.pop("reason_tags_json") or "[]")
        )
        result.append(item)
    return result


def get_reveal(conn, decision_event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM entry_review_reveals WHERE decision_event_id=?",
        (decision_event_id,),
    ).fetchone()
    return dict(row) if row else None


def insert_reveal(conn, row: dict[str, Any]) -> bool:
    cursor = conn.execute(
        """
        INSERT INTO entry_review_reveals (
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
        """
        SELECT a.*, e.timing_approximate
        FROM entry_original_actions AS a
        JOIN entry_decision_events AS e
          ON e.decision_event_id=a.decision_event_id
        WHERE a.decision_event_id=?
        """,
        (decision_event_id,),
    ).fetchone()
    return dict(row) if row else None


def insert_similarity_audit(conn, row: dict[str, Any]) -> bool:
    cursor = conn.execute(
        """
        INSERT INTO entry_similarity_audits (
            result_id, left_decision_event_id, right_decision_event_id,
            setup_version_id, direction, formula_version, feature_version,
            left_feature_fingerprint, right_feature_fingerprint,
            status, similarity, usage, eligible_for_formal_evidence,
            result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(result_id) DO NOTHING
        """,
        (
            row["result_id"],
            row["left_decision_event_id"],
            row["right_decision_event_id"],
            row["setup_version_id"],
            row["direction"],
            row["formula_version"],
            row["feature_version"],
            row["left_feature_fingerprint"],
            row["right_feature_fingerprint"],
            row["status"],
            row.get("similarity"),
            row["usage"],
            int(bool(row["eligible_for_formal_evidence"])),
            row["result_json"],
            row["created_at"],
        ),
    )
    return cursor.rowcount == 1


def get_similarity_audit(conn, result_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM entry_similarity_audits WHERE result_id=?",
        (result_id,),
    ).fetchone()
    return dict(row) if row else None


def list_revealed_decision_events(
    conn,
    *,
    setup_version_id: str,
    direction: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            e.decision_event_id,
            e.symbol,
            e.direction,
            e.decision_cutoff_utc_ms,
            r.revealed_at
        FROM entry_decision_events AS e
        JOIN entry_review_reveals AS r
          ON r.decision_event_id=e.decision_event_id
        WHERE e.setup_version_id=? AND e.direction=?
        ORDER BY e.decision_cutoff_utc_ms, e.decision_event_id
        LIMIT ?
        """,
        (setup_version_id, direction, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def list_confirmed_entry_reference_events(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT e.*
        FROM entry_decision_events AS e
        JOIN entry_judgment_versions AS blind
          ON blind.decision_event_id=e.decision_event_id
         AND blind.phase='BLIND'
         AND blind.label='ENTRY'
         AND blind.eligible_for_primary_research=1
        WHERE e.setup_version_id=?
          AND e.grouping_version_id=?
          AND e.direction=?
          AND NOT EXISTS (
              SELECT 1
              FROM entry_judgment_versions AS relabel
              WHERE relabel.decision_event_id=e.decision_event_id
                AND relabel.phase='POST_OUTCOME'
          )
        ORDER BY e.decision_cutoff_utc_ms, e.decision_event_id
        """,
        (setup_version_id, grouping_version_id, direction),
    ).fetchall()
    return [dict(row) for row in rows]


def save_candidate_scan(
    conn,
    *,
    scan: dict[str, Any],
    candidates: Iterable[dict[str, Any]],
) -> None:
    conn.execute(
        """
        INSERT INTO entry_candidate_scans (
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
        INSERT INTO entry_candidate_scores (
            scan_id, source_sample_id, episode_id, similarity,
            completeness_ratio, references_json, diversity_vector_json,
            enqueue_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                scan["scan_id"],
                item["source_sample_id"],
                item["episode_id"],
                item["similarity"],
                item["completeness_ratio"],
                item["references_json"],
                item["diversity_vector_json"],
                item["enqueue_reason"],
            )
            for item in candidates
        ),
    )


def get_candidate_scan(conn, scan_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM entry_candidate_scans WHERE scan_id=?",
        (scan_id,),
    ).fetchone()
    return dict(row) if row else None


def create_candidate_batch(
    conn,
    *,
    batch: dict[str, Any],
    items: Iterable[dict[str, Any]],
) -> None:
    payload = tuple(items)
    conn.execute(
        """
        INSERT INTO entry_review_batches (
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
    for item in payload:
        event = item["event"]
        conn.execute(
            """
            INSERT INTO entry_decision_events (
                decision_event_id, source_sample_id, setup_version_id,
                grouping_version_id, episode_id, session_id, symbol, direction,
                decision_timeframe, context_timeframe_one,
                context_timeframe_two, decision_cutoff_utc_ms,
                decision_bar_open_time_utc_ms, observed_action_time_utc_ms,
                timing_approximate, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)
            """,
            (
                event["decision_event_id"],
                event["source_sample_id"],
                event["setup_version_id"],
                event["grouping_version_id"],
                event["episode_id"],
                event.get("session_id"),
                event["symbol"],
                event["direction"],
                event["decision_timeframe"],
                event["context_timeframe_one"],
                event["context_timeframe_two"],
                event["decision_cutoff_utc_ms"],
                event["decision_bar_open_time_utc_ms"],
                event["created_at"],
            ),
        )
    conn.executemany(
        """
        INSERT INTO entry_review_batch_items (
            batch_id, blind_item_id, decision_event_id, display_order
        ) VALUES (?, ?, ?, ?)
        """,
        (
            (
                batch["batch_id"], item["blind_item_id"],
                item["event"]["decision_event_id"], item["display_order"],
            )
            for item in payload
        ),
    )
    conn.execute(
        """
        INSERT INTO entry_candidate_batches (
            batch_id, scan_id, high_similarity_count, diverse_count, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            batch["batch_id"], batch["scan_id"],
            batch["high_similarity_count"], batch["diverse_count"],
            batch["created_at"],
        ),
    )
    conn.executemany(
        """
        INSERT INTO entry_candidate_batch_items (
            batch_id, scan_id, source_sample_id, decision_event_id,
            selection_reason
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            (
                batch["batch_id"], batch["scan_id"], item["source_sample_id"],
                item["event"]["decision_event_id"], item["selection_reason"],
            )
            for item in payload
        ),
    )


def get_candidate_audit_for_event(
    conn,
    decision_event_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT s.*, i.selection_reason
        FROM entry_candidate_batch_items AS i
        JOIN entry_candidate_scores AS s
          ON s.scan_id=i.scan_id AND s.source_sample_id=i.source_sample_id
        WHERE i.decision_event_id=?
        """,
        (decision_event_id,),
    ).fetchone()
    return dict(row) if row else None


def insert_candidate_exclusion(conn, row: dict[str, Any]) -> bool:
    cursor = conn.execute(
        """
        INSERT INTO entry_candidate_exclusions (
            setup_version_id, grouping_version_id, source_sample_id,
            reason, created_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            row["setup_version_id"], row["grouping_version_id"],
            row["source_sample_id"], row["reason"], row["created_at"],
        ),
    )
    return cursor.rowcount == 1


def list_candidate_exclusions(
    conn,
) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT source_sample_id
        FROM entry_candidate_exclusions
        ORDER BY source_sample_id
        """
    ).fetchall()
    return tuple(str(row["source_sample_id"]) for row in rows)


def list_batched_candidate_ids(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT DISTINCT item.source_sample_id
        FROM entry_candidate_batch_items AS item
        JOIN entry_candidate_scans AS scan ON scan.scan_id=item.scan_id
        WHERE scan.setup_version_id=? AND scan.grouping_version_id=?
        ORDER BY item.source_sample_id
        """,
        (setup_version_id, grouping_version_id),
    ).fetchall()
    return tuple(str(row["source_sample_id"]) for row in rows)


__all__ = [
    "create_batch",
    "get_batch_item",
    "get_decision_event",
    "get_decision_event_by_source",
    "get_reveal",
    "get_original_action",
    "get_similarity_audit",
    "insert_decision_event_with_original_action",
    "insert_judgment",
    "insert_reveal",
    "insert_similarity_audit",
    "list_judgments",
    "list_actual_open_episode_member_ids",
    "list_pending_decision_events",
    "list_revealed_decision_events",
    "list_confirmed_entry_reference_events",
    "save_candidate_scan",
    "get_candidate_scan",
    "create_candidate_batch",
    "get_candidate_audit_for_event",
    "insert_candidate_exclusion",
    "list_candidate_exclusions",
    "list_batched_candidate_ids",
]
