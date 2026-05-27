"""Auditable quantitative research pipeline for Quant Replay Collector."""

from .behavior_model import (
    compute_behavior_entropy,
    compute_profile_adherence,
    compute_state_action_table,
    summarize_action_frequency,
    summarize_behavior_model,
)
from .context_features import compute_context_features_for_sample, compute_multi_window_context_features
from .dataset import run_research_pack
from .matched_baseline import (
    MatchedBaselineSpec,
    bootstrap_effect_ci,
    build_match_pool,
    compare_user_vs_controls,
    compute_context_distance,
    permutation_test_effect,
    select_matched_controls,
    summarize_matched_baseline,
)
from .multiple_testing import add_fdr_results, benjamini_hochberg, multiple_testing_warning
from .outcome_labels import compute_multi_horizon_outcome_labels, compute_outcome_labels_for_sample
from .validation import (
    minimum_sample_gate,
    oos_degradation_gate,
    purged_embargo_split,
    summarize_rule_validation,
    validate_candidate_rule,
)

__all__ = [
    "MatchedBaselineSpec",
    "add_fdr_results",
    "benjamini_hochberg",
    "bootstrap_effect_ci",
    "build_match_pool",
    "compare_user_vs_controls",
    "compute_behavior_entropy",
    "compute_context_features_for_sample",
    "compute_context_distance",
    "compute_multi_horizon_outcome_labels",
    "compute_multi_window_context_features",
    "compute_outcome_labels_for_sample",
    "compute_profile_adherence",
    "compute_state_action_table",
    "minimum_sample_gate",
    "multiple_testing_warning",
    "oos_degradation_gate",
    "permutation_test_effect",
    "purged_embargo_split",
    "run_research_pack",
    "select_matched_controls",
    "summarize_action_frequency",
    "summarize_behavior_model",
    "summarize_matched_baseline",
    "summarize_rule_validation",
    "validate_candidate_rule",
]
