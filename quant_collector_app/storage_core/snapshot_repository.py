from __future__ import annotations

import json

try:
    from research.research_snapshot import (
        PublishedResearchSnapshot,
        ResearchSnapshotVersions,
        snapshot_manifest_as_dict,
    )
except ImportError:  # pragma: no cover - package import path
    from ..research.research_snapshot import (
        PublishedResearchSnapshot,
        ResearchSnapshotVersions,
        snapshot_manifest_as_dict,
    )


def _decode(row) -> PublishedResearchSnapshot:
    manifest = json.loads(str(row["manifest_json"]))
    versions = ResearchSnapshotVersions(
        setup_version_id=str(row["setup_version_id"]),
        direction=str(row["direction"]),
        timeframes=(
            str(row["decision_timeframe"]),
            str(row["context_timeframe_one"]),
            str(row["context_timeframe_two"]),
        ),
        data_version=str(row["data_version"]),
        label_version=str(row["label_version"]),
        episode_version=str(row["episode_version"]),
        formula_version=str(row["formula_version"]),
        feature_version=str(row["feature_version"]),
        model_version_ids=tuple(
            str(value) for value in json.loads(str(row["model_version_ids_json"]))
        ),
        matched_research_ids=tuple(
            str(value) for value in json.loads(str(row["matched_research_ids_json"]))
        ),
        application_version=str(row["application_version"]),
        random_seed=int(row["random_seed"]),
        data_start_utc_ms=int(row["data_start_utc_ms"]),
        data_end_utc_ms=int(row["data_end_utc_ms"]),
    )
    return PublishedResearchSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        content_hash=str(row["content_hash"]),
        versions=versions,
        manifest=manifest,
        published_relative_path=str(row["published_relative_path"]),
        created_at=str(row["created_at"]),
    )


def save_snapshot(conn, snapshot: PublishedResearchSnapshot) -> None:
    versions = snapshot.versions
    conn.execute(
        """
        INSERT INTO research_snapshots (
            snapshot_id, content_hash, setup_version_id, episode_version,
            direction, decision_timeframe, context_timeframe_one,
            context_timeframe_two, data_version, label_version,
            formula_version, feature_version, model_version_ids_json,
            matched_research_ids_json, application_version, random_seed,
            data_start_utc_ms, data_end_utc_ms, manifest_json,
            published_relative_path, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.snapshot_id,
            snapshot.content_hash,
            versions.setup_version_id,
            versions.episode_version,
            versions.direction,
            versions.timeframes[0],
            versions.timeframes[1],
            versions.timeframes[2],
            versions.data_version,
            versions.label_version,
            versions.formula_version,
            versions.feature_version,
            json.dumps(versions.model_version_ids, ensure_ascii=False),
            json.dumps(versions.matched_research_ids, ensure_ascii=False),
            versions.application_version,
            versions.random_seed,
            versions.data_start_utc_ms,
            versions.data_end_utc_ms,
            json.dumps(
                snapshot_manifest_as_dict(snapshot.manifest),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            snapshot.published_relative_path,
            snapshot.created_at,
        ),
    )


def get_snapshot(conn, snapshot_id: str) -> PublishedResearchSnapshot | None:
    row = conn.execute(
        "SELECT * FROM research_snapshots WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()
    return None if row is None else _decode(row)


def get_snapshot_by_content_hash(
    conn,
    content_hash: str,
) -> PublishedResearchSnapshot | None:
    row = conn.execute(
        "SELECT * FROM research_snapshots WHERE content_hash=?",
        (content_hash,),
    ).fetchone()
    return None if row is None else _decode(row)


def list_snapshots(conn, setup_version_id: str) -> tuple[PublishedResearchSnapshot, ...]:
    rows = conn.execute(
        """
        SELECT * FROM research_snapshots
        WHERE setup_version_id=?
        ORDER BY created_at, snapshot_id
        """,
        (setup_version_id,),
    ).fetchall()
    return tuple(_decode(row) for row in rows)


__all__ = [
    "get_snapshot",
    "get_snapshot_by_content_hash",
    "list_snapshots",
    "save_snapshot",
]
