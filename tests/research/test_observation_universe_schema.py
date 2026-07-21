from __future__ import annotations

import pytest

from research.observation_universe import (
    create_auto_candidate_observation,
    create_no_action_observation,
    create_user_trade_observation,
    validate_source_type,
    validate_user_action,
)
from storage import StorageManager


def test_observation_universe_saves_user_trade_no_action_and_candidate(tmp_path):
    storage = StorageManager(tmp_path / "universe.db")
    common = {
        "session_id": "session_1",
        "profile_id": "profile_1",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "event_time_bjt": "2026-05-27T16:00:00+08:00",
        "created_at": "2026-05-27T08:00:00+00:00",
    }
    rows = [
        create_user_trade_observation(
            **common,
            bar_index=10,
            user_action="OPEN_LONG",
            side="LONG",
            linked_trade_id="trade_1",
            linked_event_id="event_1",
        ),
        create_no_action_observation(**common, bar_index=11),
        create_auto_candidate_observation(**common, bar_index=12),
    ]

    for row in rows:
        storage.save_observation_sample(row)

    stored = storage.list_observation_samples(session_id="session_1")

    assert [row["user_action"] for row in stored] == ["OPEN_LONG", "NO_ACTION", "NO_ACTION"]
    assert [row["source_type"] for row in stored] == ["USER_TRADE", "SCHEDULED_BAR", "AUTO_CANDIDATE"]
    assert stored[0]["is_user_trade"] == 1
    assert stored[2]["is_candidate"] == 1


@pytest.mark.parametrize("value", ["BUY", "OPEN", "WAIT"])
def test_invalid_user_action_is_rejected(value):
    with pytest.raises(ValueError):
        validate_user_action(value)


@pytest.mark.parametrize("value", ["MANUAL", "RANDOM", "ORDER_BOOK"])
def test_invalid_source_type_is_rejected(value):
    with pytest.raises(ValueError):
        validate_source_type(value)
