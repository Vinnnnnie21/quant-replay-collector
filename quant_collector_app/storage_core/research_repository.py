from __future__ import annotations

from typing import Any, Iterable


CONTEXT_FEATURE_COLUMNS = [
    "context_feature_id", "sample_id", "session_id", "feature_version",
    "symbol", "interval", "bar_index", "lookback_bars", "feature_name",
    "feature_value", "created_at",
]
OUTCOME_LABEL_COLUMNS = [
    "outcome_label_id", "sample_id", "session_id", "label_version",
    "symbol", "interval", "bar_index", "horizon_bars", "pricing_basis",
    "fwd_ret", "mfe", "mae", "hit_tp", "hit_sl", "r_multiple",
    "insufficient_future_bars", "pricing_note", "created_at",
]
STRATEGY_PROFILE_COLUMNS = [
    "profile_id", "profile_version", "name", "mode",
    "allowed_sides_json", "allowed_symbols_json", "allowed_intervals_json",
    "entry_setup_rules_json", "entry_filter_rules_json", "risk_rules_json",
    "exit_rules_json", "invalidation_rules_json", "expected_holding_bars",
    "selected_label", "profile_payload_json", "created_at", "updated_at",
]
OBSERVATION_SAMPLE_COLUMNS = [
    "sample_id", "session_id", "profile_id", "source_type", "symbol",
    "interval", "bar_index", "event_time_bjt", "user_action", "side",
    "linked_trade_id", "linked_event_id", "is_user_trade",
    "is_candidate", "is_matched_control", "created_at",
]
STRATEGY_SAMPLE_COLUMNS = [
    "strategy_sample_id", "sample_id", "experiment_id", "profile_id",
    "profile_version", "feature_version", "label_version", "dataset_hash",
    "sample_role", "created_at",
]


def _upsert_rows(conn, table: str, id_column: str, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    payload = list(rows)
    if not payload:
        return
    placeholders = ", ".join(["?"] * len(columns))
    assignments = ", ".join(f"{column}=excluded.{column}" for column in columns if column != id_column)
    conn.executemany(
        f"""
        INSERT INTO {table} ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT({id_column}) DO UPDATE SET {assignments}
        """,
        [tuple(row.get(column) for column in columns) for row in payload],
    )


def save_event_context_features(conn, rows: Iterable[dict[str, Any]]) -> None:
    _upsert_rows(conn, "event_context_features", "context_feature_id", CONTEXT_FEATURE_COLUMNS, rows)


def list_event_context_features(
    conn,
    sample_id: str | None = None,
    session_id: str | None = None,
    feature_version: str | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[Any] = []
    for column, value in (
        ("sample_id", sample_id),
        ("session_id", session_id),
        ("feature_version", feature_version),
    ):
        if value is not None:
            conditions.append(f"{column}=?")
            params.append(value)
    query = "SELECT * FROM event_context_features"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY sample_id, lookback_bars, feature_name"
    return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]


def save_research_outcome_labels(conn, rows: Iterable[dict[str, Any]]) -> None:
    _upsert_rows(conn, "research_outcome_labels", "outcome_label_id", OUTCOME_LABEL_COLUMNS, rows)


def list_research_outcome_labels(
    conn,
    sample_id: str | None = None,
    session_id: str | None = None,
    label_version: str | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[Any] = []
    for column, value in (
        ("sample_id", sample_id),
        ("session_id", session_id),
        ("label_version", label_version),
    ):
        if value is not None:
            conditions.append(f"{column}=?")
            params.append(value)
    query = "SELECT * FROM research_outcome_labels"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY sample_id, horizon_bars, pricing_basis"
    return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]


def save_strategy_profile(conn, row: dict[str, Any]) -> None:
    updated = [column for column in STRATEGY_PROFILE_COLUMNS if column != "profile_id"]
    placeholders = ", ".join(["?"] * len(STRATEGY_PROFILE_COLUMNS))
    assignments = ", ".join(f"{column}=excluded.{column}" for column in updated)
    conn.execute(
        f"""
        INSERT INTO strategy_profiles ({", ".join(STRATEGY_PROFILE_COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT(profile_id) DO UPDATE SET {assignments}
        """,
        tuple(row.get(column) for column in STRATEGY_PROFILE_COLUMNS),
    )


def load_strategy_profile(conn, profile_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM strategy_profiles WHERE profile_id=?",
        (profile_id,),
    ).fetchone()
    return dict(row) if row else None


def list_strategy_profiles(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM strategy_profiles ORDER BY updated_at DESC, profile_id"
    ).fetchall()
    return [dict(row) for row in rows]


def save_observation_sample(conn, row: dict[str, Any]) -> None:
    placeholders = ", ".join(["?"] * len(OBSERVATION_SAMPLE_COLUMNS))
    conn.execute(
        f"INSERT INTO observation_universe ({', '.join(OBSERVATION_SAMPLE_COLUMNS)}) VALUES ({placeholders})",
        tuple(row.get(column) for column in OBSERVATION_SAMPLE_COLUMNS),
    )


def list_observation_samples(
    conn,
    session_id: str | None = None,
    profile_id: str | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[Any] = []
    if session_id is not None:
        conditions.append("session_id=?")
        params.append(session_id)
    if profile_id is not None:
        conditions.append("profile_id=?")
        params.append(profile_id)
    query = "SELECT * FROM observation_universe"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY bar_index, created_at, sample_id"
    return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]


def save_strategy_sample(conn, row: dict[str, Any]) -> None:
    placeholders = ", ".join(["?"] * len(STRATEGY_SAMPLE_COLUMNS))
    conn.execute(
        f"INSERT INTO strategy_samples ({', '.join(STRATEGY_SAMPLE_COLUMNS)}) VALUES ({placeholders})",
        tuple(row.get(column) for column in STRATEGY_SAMPLE_COLUMNS),
    )


def list_strategy_samples_for_experiment(conn, experiment_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM strategy_samples
        WHERE experiment_id=?
        ORDER BY created_at, strategy_sample_id
        """,
        (experiment_id,),
    ).fetchall()
    return [dict(row) for row in rows]
