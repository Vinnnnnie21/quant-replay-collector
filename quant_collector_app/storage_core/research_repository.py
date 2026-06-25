from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Iterable

try:
    from research.entry_annotations import DEFAULT_ANNOTATION_VERSION, build_entry_annotation_id
except ImportError:  # pragma: no cover - package import path
    from ..research.entry_annotations import DEFAULT_ANNOTATION_VERSION, build_entry_annotation_id


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
ENTRY_ANNOTATION_COLUMNS = [
    "annotation_id", "observation_id", "session_id", "symbol", "interval", "bar_index",
    "bar_time", "setup_bar_index", "decision_bar_index", "setup_bar_time",
    "decision_bar_time", "human_decision", "confidence", "reason_tags_json",
    "note", "decision_timing", "annotation_version", "created_at",
    "updated_at", "is_active", "superseded_by", "app_version",
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


def _table_columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn, table: str, column: str, column_type: str) -> None:
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def ensure_entry_annotation_storage(conn) -> None:
    """Idempotently add entry annotation columns introduced after schema v6.

    The base migration remains compatible with older databases. This repository
    helper safely adds the long-term annotation fields whenever storage opens a
    database or entry annotations are read/written.
    """
    _ensure_column(conn, "entry_annotations", "observation_id", "TEXT")
    for column, column_type in {
        "observation_id": "TEXT",
        "previous_payload_json": "TEXT",
        "new_payload_json": "TEXT",
        "change_reason": "TEXT",
    }.items():
        _ensure_column(conn, "entry_annotation_history", column, column_type)
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_entry_annotations_active_observation
            ON entry_annotations(observation_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_entry_annotation_history_observation
            ON entry_annotation_history(observation_id, changed_at);
        """
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _entry_annotation_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = {column: row.get(column) for column in ENTRY_ANNOTATION_COLUMNS}
    decision_bar_index = payload.get("decision_bar_index")
    if decision_bar_index is None:
        decision_bar_index = row.get("bar_index")
    payload["decision_bar_index"] = decision_bar_index
    payload["bar_index"] = decision_bar_index if payload.get("bar_index") is None else payload.get("bar_index")
    decision_bar_time = payload.get("decision_bar_time")
    if decision_bar_time is None:
        decision_bar_time = row.get("bar_time")
    payload["decision_bar_time"] = decision_bar_time
    payload["bar_time"] = decision_bar_time if payload.get("bar_time") is None else payload.get("bar_time")
    if payload.get("setup_bar_index") is None:
        if payload.get("decision_timing") == "NEXT_BAR_CONFIRMATION" and decision_bar_index is not None:
            payload["setup_bar_index"] = int(decision_bar_index) - 1
        else:
            payload["setup_bar_index"] = decision_bar_index
    if payload.get("setup_bar_time") is None and payload.get("decision_timing") == "CURRENT_BAR_CLOSE":
        payload["setup_bar_time"] = decision_bar_time
    if payload.get("human_decision") is not None:
        payload["human_decision"] = str(payload.get("human_decision")).upper()
    payload["annotation_version"] = payload.get("annotation_version") or DEFAULT_ANNOTATION_VERSION
    payload["created_at"] = payload.get("created_at") or _now_iso()
    payload["updated_at"] = payload.get("updated_at") or payload.get("created_at")
    payload["is_active"] = 1 if _is_active(payload.get("is_active", 1)) else 0
    if payload.get("reason_tags_json") is None:
        payload["reason_tags_json"] = json.dumps(row.get("reason_tags", []), ensure_ascii=False)
    if not payload.get("annotation_id"):
        payload["annotation_id"] = build_entry_annotation_id(
            session_id=str(payload.get("session_id") or ""),
            symbol=str(payload.get("symbol") or ""),
            interval=str(payload.get("interval") or ""),
            decision_bar_index=payload.get("decision_bar_index"),
            observation_id=payload.get("observation_id"),
            created_at=payload.get("created_at"),
        )
    return payload


def _decode_entry_annotation(row) -> dict[str, Any]:
    out = dict(row)
    out.setdefault("observation_id", None)
    if out.get("decision_bar_index") is None:
        out["decision_bar_index"] = out.get("bar_index")
    if out.get("bar_index") is None:
        out["bar_index"] = out.get("decision_bar_index")
    if out.get("setup_bar_index") is None:
        out["setup_bar_index"] = out.get("decision_bar_index")
    if out.get("decision_bar_time") is None:
        out["decision_bar_time"] = out.get("bar_time")
    if out.get("bar_time") is None:
        out["bar_time"] = out.get("decision_bar_time")
    if out.get("setup_bar_time") is None and out.get("decision_timing") == "CURRENT_BAR_CLOSE":
        out["setup_bar_time"] = out.get("decision_bar_time")
    out["annotation_version"] = out.get("annotation_version") or DEFAULT_ANNOTATION_VERSION
    out["updated_at"] = out.get("updated_at") or out.get("created_at")
    out["is_active"] = 1 if _is_active(out.get("is_active", 1)) else 0
    if isinstance(out.get("reason_tags"), list):
        return out
    try:
        parsed = json.loads(out.get("reason_tags_json") or "[]")
        out["reason_tags"] = parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        out["reason_tags"] = []
    return out


def _next_annotation_version(version: Any) -> str:
    text = str(version or DEFAULT_ANNOTATION_VERSION)
    prefix = "entry_annotations_v"
    if text.startswith(prefix):
        suffix = text[len(prefix):]
        if suffix.isdigit():
            return f"{prefix}{int(suffix) + 1}"
    return f"{text}_v2"


def _is_active(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "inactive"}
    return bool(1 if value is None else value)


def _active_rows_for_observation(
    conn,
    *,
    session_id: str | None,
    symbol: str | None,
    interval: str | None,
    decision_bar_index: int | None,
    observation_id: str | None = None,
) -> list:
    ensure_entry_annotation_storage(conn)
    if observation_id:
        rows = conn.execute(
            """
            SELECT * FROM entry_annotations
            WHERE observation_id=? AND COALESCE(is_active, 1)=1
            ORDER BY updated_at, annotation_id
            """,
            (observation_id,),
        ).fetchall()
        if rows:
            return rows
    keys = (session_id, symbol, interval, decision_bar_index)
    if any(value is None or value == "" for value in keys):
        return []
    return conn.execute(
        """
        SELECT * FROM entry_annotations
        WHERE session_id=? AND symbol=? AND interval=? AND decision_bar_index=?
          AND COALESCE(is_active, 1)=1
        ORDER BY updated_at, annotation_id
        """,
        keys,
    ).fetchall()


def get_active_annotation_for_observation(
    conn,
    *,
    session_id: str | None,
    symbol: str | None,
    interval: str | None,
    decision_bar_index: int | None,
    observation_id: str | None = None,
) -> dict[str, Any] | None:
    rows = _active_rows_for_observation(
        conn,
        session_id=session_id,
        symbol=symbol,
        interval=interval,
        decision_bar_index=decision_bar_index,
        observation_id=observation_id,
    )
    if len(rows) > 1:
        raise ValueError("multiple active entry annotations exist for observation")
    return _decode_entry_annotation(rows[0]) if rows else None


def _insert_entry_annotation_row(conn, payload: dict[str, Any]) -> None:
    placeholders = ", ".join(["?"] * len(ENTRY_ANNOTATION_COLUMNS))
    conn.execute(
        f"INSERT INTO entry_annotations ({', '.join(ENTRY_ANNOTATION_COLUMNS)}) VALUES ({placeholders})",
        tuple(payload.get(column) for column in ENTRY_ANNOTATION_COLUMNS),
    )


def _update_entry_annotation_row(conn, payload: dict[str, Any]) -> None:
    assignments = ", ".join(f"{column}=?" for column in ENTRY_ANNOTATION_COLUMNS if column != "annotation_id")
    conn.execute(
        f"UPDATE entry_annotations SET {assignments} WHERE annotation_id=?",
        tuple(payload.get(column) for column in ENTRY_ANNOTATION_COLUMNS if column != "annotation_id")
        + (payload.get("annotation_id"),),
    )


def save_or_update_entry_annotation(
    conn,
    row: dict[str, Any],
    *,
    change_reason: str | None = None,
) -> dict[str, Any]:
    """Save one annotation using update-in-place semantics for active rows.

    The observation key is observation_id when present, otherwise
    session_id/symbol/interval/decision_bar_index. If an active annotation for
    that observation exists, this function updates that row, increments
    annotation_version, preserves created_at and records previous/new payloads in
    entry_annotation_history. It never inserts a second active annotation for the
    same observation.
    """
    ensure_entry_annotation_storage(conn)
    payload = _entry_annotation_row(row)
    if _is_active(payload.get("is_active", 1)):
        existing = get_active_annotation_for_observation(
            conn,
            session_id=payload.get("session_id"),
            symbol=payload.get("symbol"),
            interval=payload.get("interval"),
            decision_bar_index=payload.get("decision_bar_index"),
            observation_id=payload.get("observation_id"),
        )
        if existing is not None:
            previous = dict(existing)
            current = dict(payload)
            current["annotation_id"] = previous.get("annotation_id")
            current["created_at"] = previous.get("created_at") or current.get("created_at")
            current["observation_id"] = current.get("observation_id") or previous.get("observation_id")
            current["annotation_version"] = _next_annotation_version(previous.get("annotation_version"))
            current["updated_at"] = current.get("updated_at") or _now_iso()
            current["is_active"] = 1
            _update_entry_annotation_row(conn, current)
            new_row = conn.execute(
                "SELECT * FROM entry_annotations WHERE annotation_id=?",
                (current.get("annotation_id"),),
            ).fetchone()
            new_payload = _decode_entry_annotation(new_row)
            _insert_entry_annotation_history(
                conn,
                previous,
                new_payload=new_payload,
                operation="UPDATE",
                changed_at=current.get("updated_at"),
                superseded_by=current.get("superseded_by"),
                change_reason=change_reason,
            )
            return new_payload
    existing_by_id = conn.execute(
        "SELECT * FROM entry_annotations WHERE annotation_id=?",
        (payload.get("annotation_id"),),
    ).fetchone()
    if existing_by_id is not None:
        previous = _decode_entry_annotation(existing_by_id)
        payload["annotation_version"] = _next_annotation_version(previous.get("annotation_version"))
        payload["created_at"] = previous.get("created_at") or payload.get("created_at")
        _update_entry_annotation_row(conn, payload)
        new_row = conn.execute(
            "SELECT * FROM entry_annotations WHERE annotation_id=?",
            (payload.get("annotation_id"),),
        ).fetchone()
        new_payload = _decode_entry_annotation(new_row)
        _insert_entry_annotation_history(
            conn,
            previous,
            new_payload=new_payload,
            operation="UPDATE",
            changed_at=payload.get("updated_at"),
            superseded_by=payload.get("superseded_by"),
            change_reason=change_reason,
        )
        return new_payload
    _insert_entry_annotation_row(conn, payload)
    return _decode_entry_annotation(payload)


def save_entry_annotations(conn, rows: Iterable[dict[str, Any]]) -> None:
    for row in rows:
        save_or_update_entry_annotation(conn, row)


def list_entry_annotations(
    conn,
    annotation_id: str | None = None,
    session_id: str | None = None,
    human_decision: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    ensure_entry_annotation_storage(conn)
    conditions = []
    params: list[Any] = []
    for column, value in (
        ("annotation_id", annotation_id),
        ("session_id", session_id),
        ("human_decision", human_decision),
    ):
        if value is not None:
            conditions.append(f"{column}=?")
            params.append(value)
    if not include_inactive:
        conditions.append("COALESCE(is_active, 1)=1")
    query = "SELECT * FROM entry_annotations"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY COALESCE(is_active, 1), decision_bar_index, updated_at, annotation_id"
    return [_decode_entry_annotation(row) for row in conn.execute(query, tuple(params)).fetchall()]


def update_active_annotation_for_observation(
    conn,
    *,
    session_id: str,
    symbol: str,
    interval: str,
    decision_bar_index: int,
    observation_id: str | None = None,
    human_decision: str,
    confidence: int | None,
    reason_tags: list[str] | None = None,
    note: str = "",
    updated_at: str | None = None,
    change_reason: str | None = None,
) -> dict[str, Any]:
    existing = get_active_annotation_for_observation(
        conn,
        session_id=session_id,
        symbol=symbol,
        interval=interval,
        decision_bar_index=decision_bar_index,
        observation_id=observation_id,
    )
    if existing is None:
        raise ValueError("active entry annotation does not exist for observation")
    payload = dict(existing)
    payload.update(
        {
            "human_decision": human_decision,
            "confidence": confidence,
            "reason_tags": list(reason_tags or []),
            "reason_tags_json": json.dumps(list(reason_tags or []), ensure_ascii=False),
            "note": note,
            "updated_at": updated_at or _now_iso(),
        }
    )
    return save_or_update_entry_annotation(conn, payload, change_reason=change_reason or "manual_update")


def delete_entry_annotation(conn, annotation_id: str) -> int:
    return soft_delete_annotation(conn, annotation_id)


def soft_delete_annotation(conn, annotation_id: str, reason: str | None = None) -> int:
    ensure_entry_annotation_storage(conn)
    existing = conn.execute(
        "SELECT * FROM entry_annotations WHERE annotation_id=? AND COALESCE(is_active, 1)=1",
        (annotation_id,),
    ).fetchone()
    if existing is None:
        return 0
    previous = _decode_entry_annotation(existing)
    changed_at = _now_iso()
    new_payload = dict(previous)
    new_payload["is_active"] = 0
    new_payload["updated_at"] = changed_at
    new_payload["superseded_by"] = None
    _insert_entry_annotation_history(
        conn,
        previous,
        new_payload=new_payload,
        operation="SOFT_DELETE",
        changed_at=changed_at,
        change_reason=reason,
    )
    cursor = conn.execute(
        """
        UPDATE entry_annotations
        SET is_active=0, updated_at=?, superseded_by=NULL
        WHERE annotation_id=? AND COALESCE(is_active, 1)=1
        """,
        (changed_at, annotation_id),
    )
    return int(cursor.rowcount)


def list_entry_annotation_history(
    conn,
    annotation_id: str | None = None,
    session_id: str | None = None,
    observation_id: str | None = None,
) -> list[dict[str, Any]]:
    ensure_entry_annotation_storage(conn)
    conditions = []
    params: list[Any] = []
    if annotation_id is not None:
        conditions.append("annotation_id=?")
        params.append(annotation_id)
    if session_id is not None:
        conditions.append("session_id=?")
        params.append(session_id)
    if observation_id is not None:
        conditions.append("observation_id=?")
        params.append(observation_id)
    query = "SELECT * FROM entry_annotation_history"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY annotation_id, revision_no, history_id"
    rows = []
    for row in conn.execute(query, tuple(params)).fetchall():
        item = dict(row)
        previous_payload = _json_payload(item.get("previous_payload_json") or item.get("snapshot_json"))
        new_payload = _json_payload(item.get("new_payload_json"))
        item["previous_payload"] = previous_payload
        item["new_payload"] = new_payload
        if previous_payload:
            item.update(_decode_entry_annotation(previous_payload))
        rows.append(item)
    return rows


def _json_payload(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _insert_entry_annotation_history(
    conn,
    previous_payload: dict[str, Any],
    *,
    new_payload: dict[str, Any] | None = None,
    operation: str,
    changed_at: str | None,
    superseded_by: str | None = None,
    change_reason: str | None = None,
) -> None:
    ensure_entry_annotation_storage(conn)
    snapshot = _decode_entry_annotation(previous_payload)
    new_snapshot = _decode_entry_annotation(new_payload) if new_payload is not None else {}
    revision_no = int(
        conn.execute(
            "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM entry_annotation_history WHERE annotation_id=?",
            (snapshot.get("annotation_id"),),
        ).fetchone()[0]
    )
    conn.execute(
        """
        INSERT INTO entry_annotation_history (
            annotation_id, observation_id, revision_no, operation, session_id, symbol, interval,
            decision_bar_index, changed_at, superseded_by, snapshot_json,
            previous_payload_json, new_payload_json, change_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.get("annotation_id"),
            snapshot.get("observation_id"),
            revision_no,
            operation,
            snapshot.get("session_id"),
            snapshot.get("symbol"),
            snapshot.get("interval"),
            snapshot.get("decision_bar_index"),
            changed_at or snapshot.get("updated_at") or snapshot.get("created_at"),
            superseded_by,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            json.dumps(new_snapshot, ensure_ascii=False, sort_keys=True) if new_snapshot else None,
            change_reason,
        ),
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
