from __future__ import annotations

from strategy_consistency.profile import (
    StrategyProfile,
    default_reversal_long_profile,
    load_strategy_profile,
    profile_to_dict,
    save_strategy_profile,
)


def test_default_profile_can_be_created():
    profile = default_reversal_long_profile()
    assert profile.strategy_id == "reversal_long_after_drop"
    assert profile.expected_direction == "LONG_ONLY"
    assert profile.required_tags


def test_profile_save_and_load(tmp_path):
    profile = StrategyProfile(
        strategy_id="test",
        name="Test",
        description="desc",
        expected_direction="BOTH",
        expected_market_state="OTHER",
        required_tags=["A"],
        forbidden_tags=["B"],
        expected_entry_features={"pre_ret_20": {"op": "<=", "value": -0.02}},
    )
    path = tmp_path / "profile.json"
    save_strategy_profile(profile, path)
    loaded = load_strategy_profile(path)
    assert loaded.strategy_id == "test"
    assert loaded.required_tags == ["A"]
    assert profile_to_dict(loaded)["expected_entry_features"]["pre_ret_20"]["value"] == -0.02


def test_legacy_profile_direction_maps_to_allowed_sides(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text('{"expected_direction": "BOTH", "required_tags": ["A"]}', encoding="utf-8")
    loaded = load_strategy_profile(path)
    assert loaded.allowed_sides == ["LONG", "SHORT"]
    assert loaded.required_entry_tags == ["A"]


def test_load_profile_missing_file_returns_undeclared(tmp_path):
    loaded = load_strategy_profile(tmp_path / "missing.json")
    assert loaded is None


def test_partial_custom_profile_does_not_inherit_reversal_template(tmp_path):
    path = tmp_path / "custom.json"
    path.write_text('{"strategy_id": "custom", "name": "Custom"}', encoding="utf-8")
    loaded = load_strategy_profile(path)
    assert loaded is not None
    assert loaded.strategy_id == "custom"
    assert loaded.allowed_sides is None
    assert loaded.expected_entry_features == {}
