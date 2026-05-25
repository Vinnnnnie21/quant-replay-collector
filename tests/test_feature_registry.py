from __future__ import annotations

from research.feature_registry import feature_registry_frame, model_input_features


def test_feature_registry_contains_required_auditable_fields():
    registry = feature_registry_frame().set_index("feature_name")
    for name in ["body_pct", "atr_14", "realized_vol_50", "volume_absorption_score", "panic_drop_score", "premium_avg_pct"]:
        assert name in registry.index
        assert bool(registry.loc[name, "model_input_allowed"]) is True
        assert bool(registry.loc[name, "uses_future_data"]) is False
    assert "fwd_ret_10" not in model_input_features()
