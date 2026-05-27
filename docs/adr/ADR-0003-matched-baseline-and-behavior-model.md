# ADR-0003: Matched Baseline and Behavior Model

## Status

Accepted for v1.6.

## Context

The v1.4 observation universe records executed actions and comparable non-action
observations. The v1.5 tables separate information visible at the event time
from post-event outcomes. This allows comparison of user actions with controls
that were in similar observable states.

An unconditional random-bar baseline cannot answer whether user actions differ
from nearby opportunities in the same market context. It also risks attributing
market-regime differences to user behavior.

## Decision

### Matched baseline

`research/matched_baseline.py` selects controls using
`event_context_features` only.

- Required exact filters are `symbol` and `interval`.
- Available regime fields (`volatility_regime`, `trend_regime`,
  `time_session`) are exact matching constraints when present.
- Numeric state distance is computed from pre-event features such as
  `pre_ret_20`, `pre_ret_50`, `realized_vol_20`, and `volume_zscore_20`.
- Preferred controls have `NO_ACTION` or `HOLD` actions, or originate from
  `SCHEDULED_BAR`, `AUTO_CANDIDATE`, or `MATCHED_CONTROL`.
- A user action sample cannot be its own control.
- Outcome fields are joined only after controls have been selected.

The module reports effect size, bootstrap confidence interval, and a paired
permutation p-value. Both resampling methods accept a random seed for
reproducibility. Sparse matches and low sample counts reduce the result to
`insufficient_evidence`.

### Behavior model

`research/behavior_model.py` is descriptive statistics, not a predictive
model. It reports:

- action counts and frequencies;
- Shannon behavior entropy;
- state-to-action frequency tables;
- concentration of actions within available regimes;
- StrategyProfile adherence for explicitly declared entry constraints.

When StrategyProfile is undeclared, adherence is `descriptive_only` and no
discipline score is produced. A long-only profile penalizes an executed
`OPEN_SHORT`; it does not penalize the absence of short actions. Holding-time
discipline is not inferred when no applicable rule or evaluation data exists.

## Statistical Boundary

- Matched baseline results are not trading signals.
- Effect size is more informative than a standalone mean difference.
- Confidence intervals and p-values describe evidence inside the observed
  sample and do not establish future profitability.
- Behavior consistency is not strategy effectiveness.
- `descriptive_only` is not a profile discipline pass.

## Deferred Work

This version does not implement rule validation, false-discovery-rate
correction, purged or embargoed splits, machine-learning models, GUI expansion,
or automated/live trading. These require a later validation layer after the
sample and matching definitions are stable.
