# ADR-0004: Rule Validation and Overfitting Controls

## Status

Accepted for v1.7.

## Context

Threshold searches evaluate many candidate rules on the same historical
sample. Ranking the best in-sample rule without correcting this search process
creates false-discovery and overfitting risk. A simple chronological split is
also insufficient when neighbouring observations or forward horizons share
information across the train/test boundary.

## Decision

### Multiple testing

`research/multiple_testing.py` implements Benjamini-Hochberg false-discovery
rate adjustment without external statistical dependencies.

- The original test p-value is retained as `raw_p_value`.
- The adjusted value is returned as `q_value`.
- Missing p-values are `unavailable`; they never pass FDR.
- A large search emits `multiple_testing_warning`.

An unadjusted best p-value is not treated as a reliable conclusion.

### Validation gates

`research/validation.py` defines independent gates:

- `minimum_sample_gate` rejects rules without sufficient train or test
  observations.
- `oos_degradation_gate` rejects rules whose out-of-sample metric falls beyond
  the permitted degradation ratio.
- `validate_candidate_rule` marks a rule `validated_candidate` only after
  sample-size, FDR, and out-of-sample gates pass.
- `summarize_rule_validation` reports status counts for audit use.

Rejected rules remain auditable candidate hypotheses. They are not stable
strategies or trading signals.

### Temporal validation

`purged_embargo_split` and enhanced walk-forward evaluation use ordered time
splits only.

- Rows at the train/test boundary are purged.
- Test observations immediately after the boundary can be embargoed.
- When an outcome horizon is supplied, the effective purge is at least that
  horizon.
- Split output records the applied purge and embargo parameters.

This reduces boundary contamination. It does not prove future profitability.

## Compatibility

Existing rule-search columns and exported candidate rule files are preserved.
v1.7 appends validation fields:

- `raw_p_value`
- `q_value`
- `fdr_pass`
- `validation_status`
- `validation_warnings`
- `n_train`
- `n_test`
- `insample_metric`
- `oos_metric`
- `degradation_ratio`

No schema, execution, GUI, matched-baseline matching, behavior-statistics, or
legacy event-feature changes are introduced.

## Deferred Work

This release does not add indicators, machine-learning models, automated
trading, or live recommendations. Model development and more advanced
validation require a separate scope after the gate outputs are reviewed on
real research samples.
