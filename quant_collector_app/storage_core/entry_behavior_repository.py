from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    try:
        from research.entry_behavior_model import (
            BehaviorModelTarget,
            EntryBehaviorModelVersion,
            EntryBehaviorTrainingResult,
        )
    except ImportError:  # pragma: no cover - package import path
        from ..research.entry_behavior_model import (
            BehaviorModelTarget,
            EntryBehaviorModelVersion,
            EntryBehaviorTrainingResult,
        )


def _codec():
    try:
        from research.entry_behavior_codec import (
            entry_behavior_model_from_json,
            entry_behavior_model_to_json,
            entry_behavior_result_from_json,
            entry_behavior_result_to_json,
        )
    except ImportError:  # pragma: no cover - package import path
        from ..research.entry_behavior_codec import (
            entry_behavior_model_from_json,
            entry_behavior_model_to_json,
            entry_behavior_result_from_json,
            entry_behavior_result_to_json,
        )
    return (
        entry_behavior_model_from_json,
        entry_behavior_model_to_json,
        entry_behavior_result_from_json,
        entry_behavior_result_to_json,
    )


def list_training_events(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
    target: BehaviorModelTarget | str = "ENTRY_SELECTION",
) -> list[dict[str, Any]]:
    if _target_value(target) == "EXIT_SELECTION":
        rows = conn.execute(
            """
            SELECT
                event.decision_event_id,
                event.source_sample_id,
                event.episode_id,
                event.trade_id AS holding_episode_id,
                event.symbol,
                event.direction,
                event.decision_cutoff_utc_ms,
                event.decision_timeframe,
                event.context_timeframe_one,
                event.context_timeframe_two,
                blind.judgment_id AS blind_judgment_id,
                blind.label AS blind_label,
                position.actual_entry_price,
                position.entry_atr20,
                position.entry_atr_status,
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
            JOIN exit_position_snapshots AS position
              ON position.decision_event_id=event.decision_event_id
            JOIN trades AS trade ON trade.trade_id=event.trade_id
            WHERE event.setup_version_id=?
              AND event.grouping_version_id=?
              AND event.direction=?
              AND event.eligible_for_formal_research=1
              AND NOT EXISTS (
                  SELECT 1
                  FROM exit_judgment_versions AS relabel
                  WHERE relabel.decision_event_id=event.decision_event_id
                    AND relabel.phase='POST_OUTCOME'
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM exit_candidate_exclusions AS exclusion
                  WHERE exclusion.decision_event_id=event.decision_event_id
              )
            ORDER BY event.decision_cutoff_utc_ms, event.decision_event_id
            """,
            (setup_version_id, grouping_version_id, direction),
        ).fetchall()
        return [dict(row) for row in rows]
    rows = conn.execute(
        """
        SELECT
            event.decision_event_id,
            event.source_sample_id,
            event.episode_id,
            event.symbol,
            event.direction,
            event.decision_cutoff_utc_ms,
            blind.judgment_id AS blind_judgment_id,
            blind.label AS blind_label
        FROM entry_decision_events AS event
        JOIN entry_judgment_versions AS blind
          ON blind.decision_event_id=event.decision_event_id
         AND blind.phase='BLIND'
         AND blind.label IN ('ENTRY', 'REJECT')
         AND blind.eligible_for_primary_research=1
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


def save_training_result(
    conn,
    result: EntryBehaviorTrainingResult,
) -> None:
    experiments_table, models_table = _tables_for_target(result.target)
    (
        _model_from_json,
        model_to_json,
        _result_from_json,
        result_to_json,
    ) = _codec()
    payload = result_to_json(result)
    conn.execute(
        f"""
        INSERT INTO {experiments_table} (
            experiment_id, setup_version_id, grouping_version_id, direction,
            status, failure_code, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.experiment_id,
            result.setup_version_id,
            result.grouping_version_id,
            result.direction,
            result.status.value,
            None if result.failure is None else result.failure.code,
            payload,
            result.created_at,
        ),
    )
    model = result.model
    if model is None:
        return
    conn.execute(
        f"""
        INSERT INTO {models_table} (
            model_version_id, experiment_id, setup_version_id,
            grouping_version_id, direction, maturity,
            training_cutoff_utc_ms, label_fingerprint, model_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            model.model_version_id,
            model.experiment_id,
            model.setup_version_id,
            model.grouping_version_id,
            model.direction,
            model.maturity.value,
            model.manifest.data_end_utc_ms,
            model.manifest.label_fingerprint,
            model_to_json(model),
            model.created_at,
        ),
    )


def get_training_result(
    conn,
    experiment_id: str,
    *,
    target: BehaviorModelTarget | str = "ENTRY_SELECTION",
) -> EntryBehaviorTrainingResult | None:
    experiments_table, _models_table = _tables_for_target(target)
    row = conn.execute(
        f"""
        SELECT result_json
        FROM {experiments_table}
        WHERE experiment_id=?
        """,
        (experiment_id,),
    ).fetchone()
    if row is None:
        return None
    _model_from_json, _model_to_json, result_from_json, _result_to_json = _codec()
    return result_from_json(str(row["result_json"]))


def get_model_version(
    conn,
    model_version_id: str,
    *,
    target: BehaviorModelTarget | str = "ENTRY_SELECTION",
) -> EntryBehaviorModelVersion | None:
    _experiments_table, models_table = _tables_for_target(target)
    row = conn.execute(
        f"""
        SELECT model_json
        FROM {models_table}
        WHERE model_version_id=?
        """,
        (model_version_id,),
    ).fetchone()
    if row is None:
        return None
    model_from_json, _model_to_json, _result_from_json, _result_to_json = _codec()
    return model_from_json(str(row["model_json"]))


def list_model_versions(
    conn,
    *,
    setup_version_id: str,
    grouping_version_id: str,
    direction: str,
    target: BehaviorModelTarget | str = "ENTRY_SELECTION",
) -> tuple[EntryBehaviorModelVersion, ...]:
    _experiments_table, models_table = _tables_for_target(target)
    rows = conn.execute(
        f"""
        SELECT model_json
        FROM {models_table}
        WHERE setup_version_id=? AND grouping_version_id=? AND direction=?
        ORDER BY created_at, model_version_id
        """,
        (setup_version_id, grouping_version_id, direction),
    ).fetchall()
    model_from_json, _model_to_json, _result_from_json, _result_to_json = _codec()
    return tuple(model_from_json(str(row["model_json"])) for row in rows)


def _tables_for_target(
    target: BehaviorModelTarget | str,
) -> tuple[str, str]:
    normalized = _target_value(target)
    if normalized == "ENTRY_SELECTION":
        return "entry_behavior_experiments", "entry_behavior_model_versions"
    if normalized == "EXIT_SELECTION":
        return "exit_behavior_experiments", "exit_behavior_model_versions"
    raise ValueError(f"unsupported behavior model target: {normalized}")


def _target_value(target: BehaviorModelTarget | str) -> str:
    return str(getattr(target, "value", target)).upper()

__all__ = [
    "get_model_version",
    "get_training_result",
    "list_model_versions",
    "list_training_events",
    "save_training_result",
]
