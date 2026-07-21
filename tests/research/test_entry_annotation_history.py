from __future__ import annotations

import json

import pytest

from research.entry_annotations import DecisionTiming, EntryAnnotation, HumanDecision
from storage import StorageManager


def _annotation(
    annotation_id: str,
    *,
    note: str = "first",
    decision: HumanDecision = HumanDecision.ENTRY,
    confidence: int = 5,
    observation_id: str = "obs_42",
    decision_bar_index: int = 42,
) -> dict:
    return EntryAnnotation(
        annotation_id=annotation_id,
        observation_id=observation_id,
        session_id="session_1",
        symbol="BTCUSDT",
        interval="5m",
        bar_index=decision_bar_index,
        bar_time=f"2026-01-01T00:{decision_bar_index:02d}:00Z",
        setup_bar_index=decision_bar_index,
        decision_bar_index=decision_bar_index,
        setup_bar_time=f"2026-01-01T00:{decision_bar_index:02d}:00Z",
        decision_bar_time=f"2026-01-01T00:{decision_bar_index:02d}:00Z",
        human_decision=decision,
        confidence=confidence,
        reason_tags=["lower_shadow"],
        note=note,
        decision_timing=DecisionTiming.CURRENT_BAR_CLOSE,
        annotation_version="entry_annotations_v1",
        created_at="2026-01-01T00:01:00Z",
        updated_at="2026-01-01T00:01:00Z",
        app_version="test",
    ).to_dict()


def test_annotation_update_preserves_previous_version_in_history(tmp_path):
    storage = StorageManager(tmp_path / "history.db")

    storage.save_entry_annotation(_annotation("ann_1", note="first"))
    storage.save_entry_annotation(_annotation("ann_1", note="second"))

    active = storage.list_entry_annotations(annotation_id="ann_1")
    history = storage.list_entry_annotation_history(annotation_id="ann_1")

    assert active[0]["note"] == "second"
    assert active[0]["annotation_version"] == "entry_annotations_v2"
    assert len(history) == 1
    assert history[0]["note"] == "first"
    assert history[0]["operation"] == "UPDATE"
    assert history[0]["previous_payload"]["note"] == "first"
    assert history[0]["new_payload"]["note"] == "second"


def test_decision_change_chain_keeps_one_active_annotation_and_full_history(tmp_path):
    storage = StorageManager(tmp_path / "decision_chain.db")

    storage.save_entry_annotation(_annotation("ann_1", decision=HumanDecision.ENTRY, note="entry"))
    storage.save_entry_annotation(_annotation("ann_reject", decision=HumanDecision.REJECT, confidence=2, note="reject"))
    storage.save_entry_annotation(
        _annotation("ann_uncertain", decision=HumanDecision.UNCERTAIN, confidence=3, note="uncertain")
    )

    active = storage.list_entry_annotations(session_id="session_1")
    history = storage.list_entry_annotation_history(annotation_id="ann_1")

    assert len(active) == 1
    assert active[0]["annotation_id"] == "ann_1"
    assert active[0]["human_decision"] == "UNCERTAIN"
    assert active[0]["annotation_version"] == "entry_annotations_v3"
    assert [row["previous_payload"]["human_decision"] for row in history] == ["ENTRY", "REJECT"]
    assert history[-1]["new_payload"]["human_decision"] == "UNCERTAIN"


def test_corrupt_duplicate_active_annotation_for_same_observation_is_rejected(tmp_path):
    storage = StorageManager(tmp_path / "duplicate_active.db")

    first = _annotation("ann_1", decision_bar_index=42)
    duplicate = _annotation("ann_2", decision_bar_index=42)
    storage.save_entry_annotation(first)
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO entry_annotations (
                annotation_id, observation_id, session_id, symbol, interval,
                bar_index, bar_time, setup_bar_index, decision_bar_index,
                setup_bar_time, decision_bar_time, human_decision, confidence,
                reason_tags_json, note, decision_timing, annotation_version,
                created_at, updated_at, is_active, superseded_by, app_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                duplicate["annotation_id"], duplicate["observation_id"], duplicate["session_id"],
                duplicate["symbol"], duplicate["interval"], duplicate["bar_index"], duplicate["bar_time"],
                duplicate["setup_bar_index"], duplicate["decision_bar_index"], duplicate["setup_bar_time"],
                duplicate["decision_bar_time"], duplicate["human_decision"], duplicate["confidence"],
                json.dumps(duplicate["reason_tags"]), duplicate["note"], duplicate["decision_timing"],
                duplicate["annotation_version"], duplicate["created_at"], duplicate["updated_at"],
                1, duplicate["superseded_by"], duplicate["app_version"],
            ),
        )

    with pytest.raises(ValueError, match="multiple active entry annotations"):
        storage.get_active_annotation_for_observation(
            session_id="session_1",
            symbol="BTCUSDT",
            interval="5m",
            decision_bar_index=42,
            observation_id="obs_42",
        )


def test_soft_deleted_annotation_releases_active_slot_but_keeps_history(tmp_path):
    storage = StorageManager(tmp_path / "soft_delete_history.db")

    storage.save_entry_annotation(_annotation("ann_1", decision_bar_index=42))
    deleted = storage.soft_delete_annotation("ann_1", reason="user changed mind")
    storage.save_entry_annotation(_annotation("ann_2", decision_bar_index=42, note="replacement"))

    active = storage.list_entry_annotations(session_id="session_1")
    inactive = storage.list_entry_annotations(session_id="session_1", include_inactive=True)
    history = storage.list_entry_annotation_history(annotation_id="ann_1")

    assert deleted == 1
    assert [row["annotation_id"] for row in active] == ["ann_2"]
    assert {row["annotation_id"] for row in inactive} == {"ann_1", "ann_2"}
    assert inactive[0]["is_active"] == 0
    assert history[-1]["operation"] == "SOFT_DELETE"
    assert history[-1]["change_reason"] == "user changed mind"