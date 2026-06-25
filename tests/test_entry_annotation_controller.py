from __future__ import annotations

import pytest

from quant_collector_app.controllers.entry_annotation_controller import (
    EntryAnnotationController,
    entry_review_shortcut_action,
)
from quant_collector_app.services.entry_research_service import EntryResearchService


class FakeRepository:
    def __init__(self) -> None:
        self.saved_rows: list[dict] = []
        self.fail_next = False

    def save_or_update_annotation(self, row: dict) -> dict:
        if self.fail_next:
            raise RuntimeError("storage unavailable")
        self.saved_rows.append(dict(row))
        return dict(row)

    def save_entry_annotation(self, row: dict) -> None:
        raise AssertionError("controller must call save_or_update_annotation")


def _queue() -> list[dict]:
    return [
        {
            "observation_id": "obs_1",
            "session_id": "sess_1",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "setup_bar_index": 9,
            "decision_bar_index": 10,
            "bar_time": "2026-01-01T00:10:00Z",
            "decision_timing": "NEXT_BAR_CONFIRMATION",
            "lower_shadow_ratio": 0.82,
            "volume_zscore_20": 2.4,
        },
        {
            "observation_id": "obs_2",
            "session_id": "sess_1",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "setup_bar_index": 12,
            "decision_bar_index": 12,
            "bar_time": "2026-01-01T00:12:00Z",
            "decision_timing": "CURRENT_BAR_CLOSE",
            "lower_shadow_ratio": 0.31,
            "volume_zscore_20": -0.4,
        },
    ]


def test_save_entry_annotation_calls_save_or_update_and_marks_completed():
    repository = FakeRepository()
    controller = EntryAnnotationController(EntryResearchService(repository=repository))
    controller.load_review_queue(_queue())

    result = controller.save_current_annotation(
        human_decision="ENTRY",
        confidence=4,
        reason_tags=["long_lower_shadow", "volume_spike"],
        note="setup accepted",
    )

    assert result.ok is True
    assert len(repository.saved_rows) == 1
    saved = repository.saved_rows[0]
    assert saved["human_decision"] == "ENTRY"
    assert saved["confidence"] == 4
    assert saved["decision_bar_index"] == 10
    assert saved["setup_bar_index"] == 9
    assert saved["is_active"] is True
    assert controller.current_candidate()["observation_id"] == "obs_2"


def test_already_labeled_candidate_removed_from_queue():
    repository = FakeRepository()
    controller = EntryAnnotationController(EntryResearchService(repository=repository))
    controller.load_review_queue(_queue())

    controller.save_current_annotation("REJECT", confidence=3, reason_tags=["weak_volume"])

    assert [row["observation_id"] for row in controller.review_queue] == ["obs_2"]
    assert repository.saved_rows[0]["human_decision"] == "REJECT"


def test_jump_target_uses_decision_bar_index():
    controller = EntryAnnotationController(EntryResearchService(repository=FakeRepository()))
    controller.load_review_queue(_queue())

    assert controller.current_jump_bar_index() == 10


def test_next_bar_confirmation_exposes_setup_bar_index():
    controller = EntryAnnotationController(EntryResearchService(repository=FakeRepository()))
    controller.load_review_queue(_queue())

    detail = controller.current_candidate_detail()

    assert detail["setup_bar_index"] == 9
    assert detail["decision_bar_index"] == 10
    assert detail["decision_timing"] == "NEXT_BAR_CONFIRMATION"
    assert detail["context_features"]["lower_shadow_ratio"] == 0.82


def test_shortcut_mapping_is_entry_review_local_only():
    assert entry_review_shortcut_action("E") == ("decision", "ENTRY")
    assert entry_review_shortcut_action("R") == ("decision", "REJECT")
    assert entry_review_shortcut_action("U") == ("decision", "UNCERTAIN")
    assert entry_review_shortcut_action("N") == ("navigate", "next")
    assert entry_review_shortcut_action("B") == ("navigate", "previous")
    assert entry_review_shortcut_action("5") == ("confidence", 5)
    assert entry_review_shortcut_action("Ctrl+B") is None
    assert entry_review_shortcut_action("Space") is None


def test_annotation_failure_returns_error_without_dropping_candidate():
    repository = FakeRepository()
    repository.fail_next = True
    controller = EntryAnnotationController(EntryResearchService(repository=repository))
    controller.load_review_queue(_queue())

    result = controller.save_current_annotation("UNCERTAIN", confidence=2, reason_tags=["mixed_setup"])

    assert result.ok is False
    assert "storage unavailable" in result.message
    assert controller.current_candidate()["observation_id"] == "obs_1"
    assert repository.saved_rows == []


def test_empty_queue_has_clear_state():
    controller = EntryAnnotationController(EntryResearchService(repository=FakeRepository()))
    controller.load_review_queue([])

    assert controller.current_candidate() is None
    assert controller.current_jump_bar_index() is None
    with pytest.raises(ValueError, match="No review candidate"):
        controller.save_current_annotation("ENTRY", confidence=5, reason_tags=["manual_review"])
