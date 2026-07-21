from __future__ import annotations

import json
from datetime import datetime

try:
    from research.market_episodes import (
        EpisodeGrouping,
        EpisodeAuditRecord,
        EpisodeSource,
        MarketEpisode,
        ResearchSampleWindow,
        TimeBoundary,
        TimeRange,
    )
except ImportError:  # pragma: no cover - package import path
    from ..research.market_episodes import (
        EpisodeGrouping,
        EpisodeAuditRecord,
        EpisodeSource,
        MarketEpisode,
        ResearchSampleWindow,
        TimeBoundary,
        TimeRange,
    )


def save_episode_grouping(conn, grouping: EpisodeGrouping) -> None:
    conn.execute(
        """
        INSERT INTO episode_grouping_versions (
            grouping_version_id, formula_version, source,
            parent_grouping_version_id, input_start_utc, input_end_utc,
            input_start_boundary, input_end_boundary, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(grouping_version_id) DO NOTHING
        """,
        (
            grouping.grouping_version_id,
            grouping.formula_version,
            grouping.source.value,
            grouping.parent_grouping_version_id,
            grouping.input_range.start.isoformat(),
            grouping.input_range.end.isoformat(),
            grouping.input_range.start_boundary.value,
            grouping.input_range.end_boundary.value,
            grouping.created_at.isoformat(),
        ),
    )
    existing = conn.execute(
        "SELECT COUNT(*) FROM market_episode_memberships WHERE grouping_version_id=?",
        (grouping.grouping_version_id,),
    ).fetchone()[0]
    if existing:
        return
    conn.executemany(
        """
        INSERT INTO market_episodes (
            grouping_version_id, episode_id, start_utc, end_utc,
            start_boundary, end_boundary, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                grouping.grouping_version_id,
                episode.episode_id,
                episode.time_range.start.isoformat(),
                episode.time_range.end.isoformat(),
                episode.time_range.start_boundary.value,
                episode.time_range.end_boundary.value,
                episode.source.value,
            )
            for episode in grouping.episodes
        ),
    )
    conn.executemany(
        """
        INSERT INTO market_episode_memberships (
            grouping_version_id, episode_id, sample_id, symbol, timeframe,
            feature_start_utc, feature_end_utc,
            feature_start_boundary, feature_end_boundary,
            outcome_start_utc, outcome_end_utc,
            outcome_start_boundary, outcome_end_boundary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                grouping.grouping_version_id,
                episode.episode_id,
                member.sample_id,
                member.symbol,
                member.timeframe,
                member.feature_window.start.isoformat(),
                member.feature_window.end.isoformat(),
                member.feature_window.start_boundary.value,
                member.feature_window.end_boundary.value,
                member.outcome_window.start.isoformat(),
                member.outcome_window.end.isoformat(),
                member.outcome_window.start_boundary.value,
                member.outcome_window.end_boundary.value,
            )
            for episode in grouping.episodes
            for member in episode.members
        ),
    )


def get_episode_grouping(conn, grouping_version_id: str) -> EpisodeGrouping | None:
    version = conn.execute(
        "SELECT * FROM episode_grouping_versions WHERE grouping_version_id=?",
        (grouping_version_id,),
    ).fetchone()
    if version is None:
        return None
    episode_rows = conn.execute(
        """
        SELECT * FROM market_episodes
        WHERE grouping_version_id=?
        ORDER BY start_utc, episode_id
        """,
        (grouping_version_id,),
    ).fetchall()
    member_rows = conn.execute(
        """
        SELECT * FROM market_episode_memberships
        WHERE grouping_version_id=?
        ORDER BY episode_id, sample_id
        """,
        (grouping_version_id,),
    ).fetchall()
    members_by_episode: dict[str, list] = {}
    for member_row in member_rows:
        members_by_episode.setdefault(member_row["episode_id"], []).append(
            member_row
        )
    episodes = []
    for episode_row in episode_rows:
        episodes.append(
            MarketEpisode(
                episode_id=episode_row["episode_id"],
                time_range=_time_range(
                    episode_row["start_utc"],
                    episode_row["end_utc"],
                    episode_row["start_boundary"],
                    episode_row["end_boundary"],
                ),
                members=tuple(
                    _member(row)
                    for row in members_by_episode.get(
                        episode_row["episode_id"],
                        (),
                    )
                ),
                source=EpisodeSource(episode_row["source"]),
            )
        )
    return EpisodeGrouping(
        grouping_version_id=version["grouping_version_id"],
        formula_version=version["formula_version"],
        input_range=_time_range(
            version["input_start_utc"],
            version["input_end_utc"],
            version["input_start_boundary"],
            version["input_end_boundary"],
        ),
        episodes=tuple(episodes),
        created_at=datetime.fromisoformat(version["created_at"]),
        source=EpisodeSource(version["source"]),
        parent_grouping_version_id=version["parent_grouping_version_id"],
    )


def save_episode_revision(
    conn,
    grouping: EpisodeGrouping,
    audit: EpisodeAuditRecord,
) -> None:
    save_episode_grouping(conn, grouping)
    conn.execute(
        """
        INSERT INTO market_episode_audit (
            audit_id, base_grouping_version_id, result_grouping_version_id,
            command_type, actor, reason, command_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(audit_id) DO NOTHING
        """,
        (
            audit.audit_id,
            audit.base_grouping_version_id,
            audit.result_grouping_version_id,
            audit.command_type.value,
            audit.actor,
            audit.reason,
            json.dumps(
                {
                    "episode_ids": audit.episode_ids,
                    "sample_groups": audit.sample_groups,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            audit.created_at.isoformat(),
        ),
    )


def list_episode_audit(conn, grouping_version_id: str) -> tuple[EpisodeAuditRecord, ...]:
    rows = conn.execute(
        """
        WITH RECURSIVE audit_history AS (
            SELECT
                audit_id, base_grouping_version_id,
                result_grouping_version_id, command_type,
                actor, reason, command_json, created_at,
                0 AS depth,
                '|' || result_grouping_version_id || '|' AS visited
            FROM market_episode_audit
            WHERE result_grouping_version_id=?

            UNION ALL

            SELECT
                parent.audit_id, parent.base_grouping_version_id,
                parent.result_grouping_version_id, parent.command_type,
                parent.actor, parent.reason, parent.command_json,
                parent.created_at, child.depth + 1,
                child.visited || parent.result_grouping_version_id || '|'
            FROM market_episode_audit AS parent
            JOIN audit_history AS child
              ON parent.result_grouping_version_id = child.base_grouping_version_id
            WHERE instr(
                child.visited,
                '|' || parent.result_grouping_version_id || '|'
            ) = 0
        )
        SELECT * FROM audit_history
        ORDER BY depth DESC
        """,
        (grouping_version_id,),
    ).fetchall()
    records = []
    for row in rows:
        command = json.loads(row["command_json"])
        records.append(
            EpisodeAuditRecord(
                audit_id=row["audit_id"],
                base_grouping_version_id=row["base_grouping_version_id"],
                result_grouping_version_id=row["result_grouping_version_id"],
                command_type=EpisodeSource(row["command_type"]),
                episode_ids=tuple(command.get("episode_ids", ())),
                sample_groups=tuple(tuple(group) for group in command.get("sample_groups", ())),
                actor=row["actor"],
                reason=row["reason"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        )
    return tuple(records)


def _member(row) -> ResearchSampleWindow:
    return ResearchSampleWindow(
        sample_id=row["sample_id"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        feature_window=_time_range(
            row["feature_start_utc"],
            row["feature_end_utc"],
            row["feature_start_boundary"],
            row["feature_end_boundary"],
        ),
        outcome_window=_time_range(
            row["outcome_start_utc"],
            row["outcome_end_utc"],
            row["outcome_start_boundary"],
            row["outcome_end_boundary"],
        ),
    )


def _time_range(start: str, end: str, start_boundary: str, end_boundary: str) -> TimeRange:
    return TimeRange(
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        TimeBoundary(start_boundary),
        TimeBoundary(end_boundary),
    )
