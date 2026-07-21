from __future__ import annotations

import sqlite3

try:
    from research.setups import (
        DecisionProtocol,
        Setup,
        SetupDirection,
        SetupVersion,
        SetupVersionSpec,
        SetupWithVersion,
        SetupErrorCode,
        SetupLookupError,
        SetupValidationError,
        TimeframeProfile,
    )
except ImportError:  # pragma: no cover - package import path
    from ..research.setups import (
        DecisionProtocol,
        Setup,
        SetupDirection,
        SetupVersion,
        SetupVersionSpec,
        SetupWithVersion,
        SetupErrorCode,
        SetupLookupError,
        SetupValidationError,
        TimeframeProfile,
    )


def _setup_from_row(row: sqlite3.Row) -> Setup:
    return Setup(
        setup_id=str(row["setup_id"]),
        display_name=str(row["display_name"]),
        is_archived=bool(row["is_archived"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        archived_at=row["archived_at"],
    )


def _version_from_row(row: sqlite3.Row) -> SetupVersion:
    return SetupVersion(
        setup_version_id=str(row["setup_version_id"]),
        setup_id=str(row["setup_id"]),
        version_number=int(row["version_number"]),
        direction=SetupDirection(str(row["direction"])),
        decision_protocol=DecisionProtocol(str(row["decision_protocol"])),
        decision_rules=str(row["decision_rules"]),
        timeframes=TimeframeProfile(
            str(row["decision_timeframe"]),
            str(row["context_timeframe_one"]),
            str(row["context_timeframe_two"]),
        ),
        created_at=str(row["created_at"]),
        parent_version_id=row["parent_version_id"],
    )


def create_setup_with_version(
    conn: sqlite3.Connection,
    *,
    setup: Setup,
    version: SetupVersion,
    creation_token: str,
    semantic_fingerprint: str,
) -> SetupWithVersion:
    conn.execute("BEGIN IMMEDIATE")
    existing = conn.execute(
        "SELECT * FROM setups WHERE creation_token=?",
        (creation_token,),
    ).fetchone()
    if existing is not None:
        stored_version = conn.execute(
            """
            SELECT * FROM setup_versions
            WHERE setup_id=?
            ORDER BY version_number
            LIMIT 1
            """,
            (existing["setup_id"],),
        ).fetchone()
        if stored_version is None:
            raise RuntimeError(
                "Setup creation token exists without an initial version"
            )
        if (
            str(existing["display_name"]) != setup.display_name
            or str(stored_version["semantic_fingerprint"])
            != semantic_fingerprint
        ):
            raise SetupValidationError(
                SetupErrorCode.IDEMPOTENCY_CONFLICT,
                field="creation_token",
                detail=(
                    "Setup creation token was reused with different content"
                ),
            )
        return SetupWithVersion(
            setup=_setup_from_row(existing),
            version=_version_from_row(stored_version),
        )
    conn.execute(
        """
        INSERT INTO setups (
            setup_id, display_name, is_archived, created_at, updated_at,
            archived_at, creation_token
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            setup.setup_id,
            setup.display_name,
            int(setup.is_archived),
            setup.created_at,
            setup.updated_at,
            setup.archived_at,
            creation_token,
        ),
    )
    conn.execute(
        """
        INSERT INTO setup_versions (
            setup_version_id, setup_id, version_number, parent_version_id,
            direction, decision_protocol, decision_rules,
            decision_timeframe, context_timeframe_one, context_timeframe_two,
            semantic_fingerprint, creation_key, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version.setup_version_id,
            version.setup_id,
            version.version_number,
            version.parent_version_id,
            version.direction.value,
            version.decision_protocol.value,
            version.decision_rules,
            version.timeframes.decision,
            version.timeframes.context_one,
            version.timeframes.context_two,
            semantic_fingerprint,
            f"{setup.setup_id}:initial",
            version.created_at,
        ),
    )
    return SetupWithVersion(setup=setup, version=version)


def get_setup_version(
    conn: sqlite3.Connection,
    setup_version_id: str,
) -> SetupVersion | None:
    row = conn.execute(
        "SELECT * FROM setup_versions WHERE setup_version_id=?",
        (setup_version_id,),
    ).fetchone()
    return _version_from_row(row) if row is not None else None


def create_setup_version(
    conn: sqlite3.Connection,
    *,
    setup_version_id: str,
    setup_id: str,
    based_on_version_id: str,
    spec: SetupVersionSpec,
    semantic_fingerprint: str,
    creation_key: str,
    created_at: str,
) -> SetupVersion:
    conn.execute("BEGIN IMMEDIATE")
    setup_row = conn.execute(
        "SELECT * FROM setups WHERE setup_id=?",
        (setup_id,),
    ).fetchone()
    if setup_row is None:
        raise SetupLookupError(
            SetupErrorCode.SETUP_NOT_FOUND,
            identity=setup_id,
        )
    if bool(setup_row["is_archived"]):
        raise SetupValidationError(
            SetupErrorCode.SETUP_ARCHIVED,
            field="setup_id",
            detail=f"Archived Setup cannot create versions: {setup_id}",
        )
    existing = conn.execute(
        "SELECT * FROM setup_versions WHERE creation_key=?",
        (creation_key,),
    ).fetchone()
    if existing is not None:
        return _version_from_row(existing)
    parent = conn.execute(
        """
        SELECT * FROM setup_versions
        WHERE setup_version_id=? AND setup_id=?
        """,
        (based_on_version_id, setup_id),
    ).fetchone()
    if parent is None:
        raise SetupLookupError(
            SetupErrorCode.VERSION_NOT_FOUND,
            identity=based_on_version_id,
        )
    if str(parent["semantic_fingerprint"]) == semantic_fingerprint:
        raise SetupValidationError(
            SetupErrorCode.NO_SEMANTIC_CHANGE,
            field="version",
            detail=(
                "A new Setup version requires a semantic change"
            ),
        )
    latest = conn.execute(
        """
        SELECT setup_version_id
        FROM setup_versions
        WHERE setup_id=?
        ORDER BY version_number DESC
        LIMIT 1
        """,
        (setup_id,),
    ).fetchone()
    if (
        latest is not None
        and latest["setup_version_id"] != based_on_version_id
    ):
        raise SetupValidationError(
            SetupErrorCode.STALE_VERSION,
            field="based_on_version_id",
            detail=(
                "Setup version changed after the editor was opened; "
                "reload before creating another version"
            ),
        )
    next_number = int(
        conn.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1
            FROM setup_versions
            WHERE setup_id=?
            """,
            (setup_id,),
        ).fetchone()[0]
    )
    conn.execute(
        """
        INSERT INTO setup_versions (
            setup_version_id, setup_id, version_number, parent_version_id,
            direction, decision_protocol, decision_rules,
            decision_timeframe, context_timeframe_one, context_timeframe_two,
            semantic_fingerprint, creation_key, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            setup_version_id,
            setup_id,
            next_number,
            based_on_version_id,
            spec.direction.value,
            spec.decision_protocol.value,
            spec.decision_rules,
            spec.timeframes.decision,
            spec.timeframes.context_one,
            spec.timeframes.context_two,
            semantic_fingerprint,
            creation_key,
            created_at,
        ),
    )
    return _version_from_row(
        conn.execute(
            """
            SELECT * FROM setup_versions
            WHERE setup_version_id=?
            """,
            (setup_version_id,),
        ).fetchone()
    )


def list_setup_versions(
    conn: sqlite3.Connection,
    setup_id: str,
) -> tuple[SetupVersion, ...]:
    rows = conn.execute(
        """
        SELECT * FROM setup_versions
        WHERE setup_id=?
        ORDER BY version_number
        """,
        (setup_id,),
    ).fetchall()
    return tuple(_version_from_row(row) for row in rows)


def get_setup(
    conn: sqlite3.Connection,
    setup_id: str,
) -> Setup | None:
    row = conn.execute(
        "SELECT * FROM setups WHERE setup_id=?",
        (setup_id,),
    ).fetchone()
    return _setup_from_row(row) if row is not None else None


def list_setups(
    conn: sqlite3.Connection,
    *,
    include_archived: bool,
) -> tuple[Setup, ...]:
    query = "SELECT * FROM setups"
    if not include_archived:
        query += " WHERE is_archived=0"
    query += " ORDER BY is_archived, lower(display_name), setup_id"
    return tuple(
        _setup_from_row(row)
        for row in conn.execute(query).fetchall()
    )


def rename_setup(
    conn: sqlite3.Connection,
    setup_id: str,
    display_name: str,
    updated_at: str,
) -> Setup | None:
    conn.execute(
        """
        UPDATE setups
        SET display_name=?, updated_at=?
        WHERE setup_id=? AND display_name<>?
        """,
        (display_name, updated_at, setup_id, display_name),
    )
    return get_setup(conn, setup_id)


def archive_setup(
    conn: sqlite3.Connection,
    setup_id: str,
    archived_at: str,
) -> Setup | None:
    cursor = conn.execute(
        """
        UPDATE setups
        SET is_archived=1,
            archived_at=COALESCE(archived_at, ?),
            updated_at=?
        WHERE setup_id=?
        """,
        (archived_at, archived_at, setup_id),
    )
    return get_setup(conn, setup_id) if cursor.rowcount else None


__all__ = [
    "create_setup_version",
    "create_setup_with_version",
    "archive_setup",
    "get_setup",
    "get_setup_version",
    "list_setups",
    "list_setup_versions",
    "rename_setup",
]
