from __future__ import annotations

from research.factor_library import FeatureFactory
from research.label_registry import LabelFactory
from research.rule_search import search_rules
from research.validation import minimum_sample_gate, summarize_rule_validation, validate_candidate_rule
from test_feature_label_separation import research_input


def test_minimum_sample_gate_rejects_small_rules_and_passes_sufficient_rules():
    rejected = minimum_sample_gate(9, 10)
    passed = minimum_sample_gate(10, 10)

    assert rejected["passed"] is False
    assert rejected["status"] == "rejected_low_sample"
    assert passed["passed"] is True


def test_low_sample_candidate_cannot_be_validated():
    result = validate_candidate_rule(
        n_train=9,
        n_test=8,
        insample_metric=0.02,
        oos_metric=0.02,
        fdr_pass=True,
        q_value=0.01,
        min_samples=10,
        max_degradation_ratio=0.25,
    )

    assert result["validation_status"] == "rejected_low_sample"
    assert result["validation_status"] != "validated_candidate"


def test_rule_search_retains_auditable_low_sample_status_and_new_fields():
    windows, events, trades = research_input(60)
    features = FeatureFactory().build(windows, events)
    labels = LabelFactory().build(windows, events, trades)

    result = search_rules(
        features,
        labels,
        factors=["pre_ret_10"],
        min_samples=100,
        max_rules=3,
    )

    assert not result.empty
    assert {
        "raw_p_value",
        "q_value",
        "fdr_pass",
        "validation_status",
        "validation_warnings",
        "n_train",
        "n_test",
        "insample_metric",
        "oos_metric",
        "degradation_ratio",
    } <= set(result.columns)
    assert set(result["validation_status"]) == {"rejected_low_sample"}
    assert "validated_candidate" not in set(result["validation_status"])


def test_only_rules_passing_sample_fdr_and_oos_gates_are_validated():
    passed = validate_candidate_rule(
        n_train=40,
        n_test=40,
        insample_metric=0.02,
        oos_metric=0.018,
        fdr_pass=True,
        q_value=0.04,
        min_samples=30,
        max_degradation_ratio=0.25,
    )
    fdr_rejected = validate_candidate_rule(
        n_train=40,
        n_test=40,
        insample_metric=0.02,
        oos_metric=0.018,
        fdr_pass=False,
        q_value=0.30,
        min_samples=30,
        max_degradation_ratio=0.25,
    )
    oos_rejected = validate_candidate_rule(
        n_train=40,
        n_test=40,
        insample_metric=0.02,
        oos_metric=0.005,
        fdr_pass=True,
        q_value=0.04,
        min_samples=30,
        max_degradation_ratio=0.25,
    )
    summary = summarize_rule_validation([passed, fdr_rejected, oos_rejected])

    assert passed["validation_status"] == "validated_candidate"
    assert fdr_rejected["validation_status"] == "rejected_fdr"
    assert oos_rejected["validation_status"] == "rejected_oos_degradation"
    assert summary["validated_candidate_count"] == 1
    assert summary["status_counts"]["rejected_fdr"] == 1
