"""Auditable research APIs with lazy package-level compatibility exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "compute_behavior_entropy": ".behavior_model",
    "compute_profile_adherence": ".behavior_model",
    "compute_state_action_table": ".behavior_model",
    "summarize_action_frequency": ".behavior_model",
    "summarize_behavior_model": ".behavior_model",
    "compute_context_features_for_sample": ".context_features",
    "compute_multi_window_context_features": ".context_features",
    "MatchedBaselineSpec": ".matched_baseline",
    "bootstrap_effect_ci": ".matched_baseline",
    "build_match_pool": ".matched_baseline",
    "compare_user_vs_controls": ".matched_baseline",
    "compute_context_distance": ".matched_baseline",
    "permutation_test_effect": ".matched_baseline",
    "select_matched_controls": ".matched_baseline",
    "summarize_matched_baseline": ".matched_baseline",
    "add_fdr_results": ".multiple_testing",
    "benjamini_hochberg": ".multiple_testing",
    "multiple_testing_warning": ".multiple_testing",
    "compute_multi_horizon_outcome_labels": ".outcome_labels",
    "compute_outcome_labels_for_sample": ".outcome_labels",
    "minimum_sample_gate": ".validation",
    "oos_degradation_gate": ".validation",
    "purged_embargo_split": ".validation",
    "summarize_rule_validation": ".validation",
    "validate_candidate_rule": ".validation",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def run_research_pack(*args, **kwargs):
    """Load the heavy research-pack pipeline only when it is requested."""

    from .dataset import run_research_pack as implementation

    return implementation(*args, **kwargs)


__all__ = [*_EXPORT_MODULES, "run_research_pack"]
