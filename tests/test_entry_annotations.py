from __future__ import annotations

import pytest

from research.entry_annotations import (
    DecisionTiming,
    EntryAnnotation,
    EntryReasonTag,
    HumanDecision,
    build_entry_annotation_id,
)


def _annotation_payload(**overrides):
    payload = {
        "annotation_id": "ann_001",
        "observation_id": "obs_001",
        "session_id": "session_1",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "bar_index": 42,
        "bar_time": "2026-06-18T10:42:00+08:00",
        "human_decision": "ENTRY",
        "confidence": 5,
        "reason_tags": ["prior_downtrend", "volume_climax", "long_lower_shadow"],
        "note": "visible setup only",
        "decision_timing": "CURRENT_BAR_CLOSE",
        "created_at": "2026-06-18T02:42:00+00:00",
        "app_version": "test",
    }
    payload.update(overrides)
    return payload


def test_entry_annotation_can_be_created_and_serialized():
    annotation = EntryAnnotation.from_dict(_annotation_payload())

    assert annotation.human_decision is HumanDecision.ENTRY
    assert annotation.decision_timing is DecisionTiming.CURRENT_BAR_CLOSE
    assert annotation.setup_bar_index == 42
    assert annotation.decision_bar_index == 42
    assert annotation.bar_index == 42
    assert annotation.setup_bar_time == "2026-06-18T10:42:00+08:00"
    assert annotation.decision_bar_time == "2026-06-18T10:42:00+08:00"
    assert annotation.bar_time == "2026-06-18T10:42:00+08:00"
    assert annotation.annotation_version == "entry_annotations_v1"
    assert annotation.updated_at == "2026-06-18T02:42:00+00:00"
    assert annotation.is_active is True
    assert annotation.superseded_by is None
    assert annotation.observation_id == "obs_001"


def test_reject_annotation_can_be_created():
    annotation = EntryAnnotation.from_dict(
        _annotation_payload(
            annotation_id="ann_reject",
            human_decision="REJECT",
            confidence=4,
            reason_tags=["insufficient_confirmation"],
        )
    )

    assert annotation.human_decision is HumanDecision.REJECT
    assert annotation.confidence == 4


def test_uncertain_annotation_can_be_created():
    annotation = EntryAnnotation.from_dict(
        _annotation_payload(
            annotation_id="ann_uncertain",
            human_decision="UNCERTAIN",
            confidence=3,
            reason_tags=[],
            note="mixed setup",
        )
    )

    assert annotation.human_decision is HumanDecision.UNCERTAIN
    assert annotation.reason_tags == []


def test_unlabeled_annotation_can_be_created_without_confidence_or_bar_index():
    annotation = EntryAnnotation.from_dict(
        _annotation_payload(
            annotation_id="ann_unlabeled",
            human_decision="UNLABELED",
            confidence=None,
            bar_index=None,
            reason_tags=[],
        )
    )

    assert annotation.human_decision is HumanDecision.UNLABELED
    assert annotation.confidence is None
    assert annotation.bar_index is None
    assert annotation.decision_bar_index is None


def test_current_bar_close_requires_setup_and_decision_to_match():
    annotation = EntryAnnotation.from_dict(_annotation_payload(setup_bar_index=42, decision_bar_index=42))

    assert annotation.setup_bar_index == annotation.decision_bar_index

    with pytest.raises(ValueError, match="CURRENT_BAR_CLOSE"):
        EntryAnnotation.from_dict(_annotation_payload(setup_bar_index=41, decision_bar_index=42))


def test_next_bar_confirmation_uses_setup_then_decision_bar():
    annotation = EntryAnnotation.from_dict(
        _annotation_payload(
            bar_index=43,
            setup_bar_index=42,
            decision_bar_index=43,
            setup_bar_time="2026-06-18T10:42:00+08:00",
            decision_bar_time="2026-06-18T10:43:00+08:00",
            decision_timing="NEXT_BAR_CONFIRMATION",
            reason_tags=["bullish_confirmation"],
        )
    )

    assert annotation.setup_bar_index == 42
    assert annotation.decision_bar_index == 43
    assert annotation.bar_index == 43
    assert annotation.setup_bar_time == "2026-06-18T10:42:00+08:00"
    assert annotation.decision_bar_time == "2026-06-18T10:43:00+08:00"

    with pytest.raises(ValueError, match="NEXT_BAR_CONFIRMATION"):
        EntryAnnotation.from_dict(
            _annotation_payload(
                setup_bar_index=43,
                decision_bar_index=42,
                decision_timing="NEXT_BAR_CONFIRMATION",
            )
        )


@pytest.mark.parametrize("confidence", [0, 6, "bad"])
def test_confidence_out_of_range_raises(confidence):
    with pytest.raises(ValueError, match="confidence"):
        EntryAnnotation.from_dict(_annotation_payload(confidence=confidence))


def test_labeled_annotation_requires_bar_index():
    with pytest.raises(ValueError, match="bar_index"):
        EntryAnnotation.from_dict(_annotation_payload(bar_index=None))


def test_decision_timing_is_required():
    with pytest.raises(ValueError, match="decision_timing"):
        EntryAnnotation.from_dict(_annotation_payload(decision_timing=None))


def test_reason_tags_must_be_list_of_strings():
    with pytest.raises(ValueError, match="reason_tags"):
        EntryAnnotation.from_dict(_annotation_payload(reason_tags="volume_climax"))

    with pytest.raises(ValueError, match="reason_tags"):
        EntryAnnotation.from_dict(_annotation_payload(reason_tags=["volume_climax", 1]))


def test_reason_tags_must_use_controlled_vocabulary():
    annotation = EntryAnnotation.from_dict(_annotation_payload(reason_tags=[EntryReasonTag.VOLUME_CLIMAX]))

    assert annotation.reason_tags == ["volume_climax"]

    with pytest.raises(ValueError, match="Unsupported reason_tags"):
        EntryAnnotation.from_dict(_annotation_payload(reason_tags=["random_story"]))


def test_trading_signal_naming_is_rejected():
    with pytest.raises(ValueError, match="Trading-signal"):
        EntryAnnotation.from_dict(_annotation_payload(buy_signal=True))

    with pytest.raises(ValueError, match="Trading-signal"):
        EntryAnnotation.from_dict(_annotation_payload(reason_tags=["signal_like_setup"]))


@pytest.mark.parametrize("field_name", ["future_return", "MFE", "MAE", "hit_tp", "hit_sl"])
def test_future_outcome_fields_are_rejected(field_name):
    with pytest.raises(ValueError, match="Future outcome"):
        EntryAnnotation.from_dict(_annotation_payload(**{field_name: 1}))


def test_serialized_fields_are_stable():
    annotation = EntryAnnotation.from_dict(_annotation_payload())

    assert list(annotation.to_dict()) == [
        "annotation_id",
        "observation_id",
        "session_id",
        "symbol",
        "interval",
        "bar_index",
        "bar_time",
        "setup_bar_index",
        "decision_bar_index",
        "setup_bar_time",
        "decision_bar_time",
        "human_decision",
        "confidence",
        "reason_tags",
        "note",
        "decision_timing",
        "annotation_version",
        "created_at",
        "updated_at",
        "is_active",
        "superseded_by",
        "app_version",
    ]


def test_from_dict_round_trip_is_consistent():
    first = EntryAnnotation.from_dict(_annotation_payload())
    restored = EntryAnnotation.from_dict(first.to_dict())

    assert restored == first


def test_annotation_id_builder_does_not_depend_on_human_decision():
    entry_id = build_entry_annotation_id(
        session_id="session_1",
        symbol="BTCUSDT",
        interval="1m",
        decision_bar_index=42,
        observation_id="obs_001",
    )
    changed_decision_id = build_entry_annotation_id(
        session_id="session_1",
        symbol="BTCUSDT",
        interval="1m",
        decision_bar_index=42,
        observation_id="obs_001",
    )

    assert entry_id == changed_decision_id
    assert "ENTRY" not in entry_id
    assert "REJECT" not in entry_id