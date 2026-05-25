from __future__ import annotations

from research.label_registry import label_registry_frame


def test_label_registry_marks_labels_as_not_model_inputs():
    registry = label_registry_frame().set_index("label_name")
    for name in ["fwd_ret_20_side_adj", "mfe_20", "mae_20", "good_reversal", "manual_return"]:
        assert name in registry.index
        assert bool(registry.loc[name, "model_input_allowed"]) is False
