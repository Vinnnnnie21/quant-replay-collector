from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    try:
        from research.entry_outcome_comparison import EntryOutcomeComparisonResult
    except ImportError:  # pragma: no cover - package import path
        from ..research.entry_outcome_comparison import EntryOutcomeComparisonResult


def _codec():
    try:
        from research.entry_outcome_comparison import (
            entry_outcome_result_from_json,
            entry_outcome_result_to_json,
        )
    except ImportError:  # pragma: no cover - package import path
        from ..research.entry_outcome_comparison import (
            entry_outcome_result_from_json,
            entry_outcome_result_to_json,
        )
    return entry_outcome_result_from_json, entry_outcome_result_to_json


def list_eligible_events(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            event.decision_event_id,
            event.source_sample_id,
            event.setup_version_id,
            event.grouping_version_id,
            event.episode_id,
            event.symbol,
            event.direction,
            event.decision_timeframe,
            event.context_timeframe_one,
            event.context_timeframe_two,
            event.decision_cutoff_utc_ms,
            blind.judgment_id AS blind_judgment_id,
            blind.label AS blind_label
        FROM entry_decision_events AS event
        JOIN entry_judgment_versions AS blind
          ON blind.decision_event_id=event.decision_event_id
         AND blind.phase='BLIND'
         AND blind.label IN ('ENTRY', 'REJECT')
         AND blind.eligible_for_primary_research=1
        JOIN entry_review_reveals AS reveal
          ON reveal.decision_event_id=event.decision_event_id
         AND reveal.blind_judgment_id=blind.judgment_id
        WHERE event.setup_version_id=?
          AND event.grouping_version_id=?
          AND event.direction=?
          AND NOT EXISTS (
              SELECT 1
              FROM entry_judgment_versions AS relabel
              WHERE relabel.decision_event_id=event.decision_event_id
                AND relabel.phase='POST_OUTCOME'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM entry_candidate_exclusions AS exclusion
              WHERE exclusion.source_sample_id=event.source_sample_id
          )
        ORDER BY event.decision_cutoff_utc_ms, event.decision_event_id
        """,
        (setup_version_id, grouping_version_id, direction),
    ).fetchall()
    return [dict(row) for row in rows]


def save_result(conn, result: EntryOutcomeComparisonResult) -> None:
    _from_json, to_json = _codec()
    conn.execute(
        """
        INSERT INTO entry_outcome_comparisons (
            comparison_id, setup_version_id, grouping_version_id, direction,
            formula_version, feature_version, input_feature_fingerprint,
            random_seed, result_json,
            created_at
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
        INSERT INTO entry_outcome_matches (
            comparison_id, similarity_threshold,
            entry_decision_event_id, reject_decision_event_id,
            entry_episode_id, reject_episode_id, symbol,
            decision_timeframe, similarity, context_distance
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                result.comparison_id,
                sensitivity.similarity_threshold,
                pair.entry_decision_event_id,
                pair.reject_decision_event_id,
                pair.entry_episode_id,
                pair.reject_episode_id,
                pair.symbol,
                pair.decision_timeframe,
                pair.similarity,
                pair.context_distance,
            )
            for sensitivity in result.sensitivities
            for pair in sensitivity.pairs
        ),
    )


def get_result(
    conn,
    comparison_id: str,
) -> EntryOutcomeComparisonResult | None:
    row = conn.execute(
        """
        SELECT result_json
        FROM entry_outcome_comparisons
        WHERE comparison_id=?
        """,
        (comparison_id,),
    ).fetchone()
    if row is None:
        return None
    from_json, _to_json = _codec()
    return from_json(str(row["result_json"]))


__all__ = ["get_result", "list_eligible_events", "save_result"]
