from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    try:
        from research.exit_outcome_comparison import ExitOutcomeComparisonResult
    except ImportError:  # pragma: no cover - package import path
        from ..research.exit_outcome_comparison import ExitOutcomeComparisonResult


def _codec():
    try:
        from research.exit_outcome_comparison import (
            exit_outcome_result_from_json,
            exit_outcome_result_to_json,
        )
    except ImportError:  # pragma: no cover - package import path
        from ..research.exit_outcome_comparison import (
            exit_outcome_result_from_json,
            exit_outcome_result_to_json,
        )
    return exit_outcome_result_from_json, exit_outcome_result_to_json


def list_eligible_events(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event.*,
               blind.judgment_id AS blind_judgment_id,
               blind.label AS blind_label,
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
         AND blind.label IN ('EXIT_NOW', 'HOLD')
         AND blind.eligible_for_primary_research=1
        JOIN exit_review_reveals AS reveal
          ON reveal.decision_event_id=event.decision_event_id
         AND reveal.blind_judgment_id=blind.judgment_id
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


def save_result(conn, result: ExitOutcomeComparisonResult) -> None:
    _from_json, to_json = _codec()
    conn.execute(
        """
        INSERT INTO exit_outcome_comparisons (
            comparison_id, setup_version_id, grouping_version_id, direction,
            formula_version, feature_version, input_feature_fingerprint,
            random_seed, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.comparison_id,
            result.setup_version_id,
            result.grouping_version_id,
            result.direction,
            result.formula_version,
            result.feature_version,
            result.input_feature_fingerprint,
            result.random_seed,
            to_json(result),
            result.created_at,
        ),
    )
    conn.executemany(
        """
        INSERT INTO exit_outcome_matches (
            comparison_id, similarity_threshold,
            exit_now_decision_event_id, hold_decision_event_id,
            exit_now_episode_id, hold_episode_id, symbol,
            decision_timeframe, similarity, context_distance
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                result.comparison_id,
                sensitivity.similarity_threshold,
                pair.exit_now_decision_event_id,
                pair.hold_decision_event_id,
                pair.exit_now_episode_id,
                pair.hold_episode_id,
                pair.symbol,
                pair.decision_timeframe,
                pair.similarity,
                pair.context_distance,
            )
            for sensitivity in result.sensitivities
            for pair in sensitivity.pairs
        ),
    )


def get_result(conn, comparison_id: str) -> ExitOutcomeComparisonResult | None:
    row = conn.execute(
        """
        SELECT result_json
        FROM exit_outcome_comparisons
        WHERE comparison_id=?
        """,
        (comparison_id,),
    ).fetchone()
    if row is None:
        return None
    from_json, _to_json = _codec()
    return from_json(str(row["result_json"]))


__all__ = ["get_result", "list_eligible_events", "save_result"]
