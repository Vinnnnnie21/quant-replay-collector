from __future__ import annotations

from storage import StorageManager
from strategy_consistency.profile import (
    StrategyProfile,
    strategy_profile_from_storage_row,
    strategy_profile_to_storage_row,
)


def test_strategy_profile_can_be_saved_loaded_and_listed_in_sqlite(tmp_path):
    storage = StorageManager(tmp_path / "profiles.db")
    profile = StrategyProfile(
        strategy_id="breakdown_reclaim",
        name="Breakdown Reclaim",
        description="Declared study profile",
        allowed_sides=["LONG"],
        allowed_symbols=["BTCUSDT"],
        allowed_intervals=["5m"],
        required_entry_tags=["reclaim"],
        expected_entry_features={"pre_ret_20": {"op": "<=", "value": -0.02}},
        stop_loss_pct=1.0,
        take_profit_pct=2.0,
        max_holding_bars=20,
    )
    row = strategy_profile_to_storage_row(
        profile,
        profile_id="profile_1",
        profile_version="1.0",
        selected_label="fwd_ret_10_side_adj",
        created_at="2026-05-27T08:00:00+00:00",
        updated_at="2026-05-27T08:00:00+00:00",
    )

    storage.save_strategy_profile(row)
    loaded_row = storage.load_strategy_profile("profile_1")
    profiles = storage.list_strategy_profiles()
    loaded_profile = strategy_profile_from_storage_row(loaded_row)

    assert loaded_row["profile_version"] == "1.0"
    assert loaded_row["selected_label"] == "fwd_ret_10_side_adj"
    assert [item["profile_id"] for item in profiles] == ["profile_1"]
    assert loaded_profile.strategy_id == "breakdown_reclaim"
    assert loaded_profile.allowed_sides == ["LONG"]
    assert loaded_profile.expected_entry_features == profile.expected_entry_features
    assert loaded_profile.description == profile.description
