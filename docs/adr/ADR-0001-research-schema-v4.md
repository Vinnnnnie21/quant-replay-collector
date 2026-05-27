# ADR-0001: Research Schema v4 Sample Universe Scaffold

- Status: Accepted
- Date: 2026-05-27
- Scope: v1.4 research persistence scaffold

## Context

Quant Replay Collector records discretionary trading research samples. Before
schema v4, persisted samples are centered on trades the user already made:
`trades`, `trade_events`, `event_windows`, and legacy `event_features`.

That data supports replay review and event study, but it does not represent
the decision universe. A study cannot compare user actions with similar
moments where the user did nothing unless those non-action observations exist.

The legacy `event_features` table also contains both state fields and outcome
fields such as forward returns, MFE, MAE, and manual trade results. It remains
useful for compatibility and audit exports, but it is not a safe canonical
model-input Interface.

## Decision

Schema version 4 adds three tables and manifest metadata only.

### `observation_universe`

This table records research observations independently of whether a trade was
executed. It supports user trades, explicit non-actions, and automatically
identified candidates without treating a candidate as an order or signal.

Allowed actions are:

- `OPEN_LONG`
- `OPEN_SHORT`
- `CLOSE_LONG`
- `CLOSE_SHORT`
- `HOLD`
- `NO_ACTION`

Allowed sources are:

- `USER_TRADE`
- `USER_EVENT`
- `AUTO_CANDIDATE`
- `SCHEDULED_BAR`
- `MATCHED_CONTROL`

### `strategy_samples`

This table binds selected observations to a reproducible research experiment.
It records `experiment_id`, Profile identity and version, feature and label
versions, and `dataset_hash`. It does not calculate factors, outcomes, or
statistics.

### `strategy_profiles`

StrategyProfile must be persisted because a report needs to identify the
declared strategy rules used when its sample set was formed. JSON file
compatibility remains supported. The SQLite row contains queryable rule
groups plus `profile_payload_json` to preserve existing serialized fields
during this gradual migration.

### Research manifest extension

The existing JSON research manifest remains the experiment record for v1.4.
It now accepts:

- `profile_id`
- `profile_version`
- `feature_version`
- `label_version`
- `dataset_hash`
- `baseline_spec_json`
- `split_spec_json`

No `research_experiments` SQLite table is introduced in this scaffold because
the manifest already provides the minimum compatible experiment record.

## Compatibility

`event_features` is retained unchanged for legacy exports and historical
review. It is not the canonical research input table. Existing `FeatureFactory`,
`LabelFactory`, and leakage audit remain the safe research Interface until
separate persisted factor and outcome tables are implemented.

No GUI workflow, trade execution behavior, Binance loading logic, or automatic
order behavior is changed by schema v4.

## Deferred Work

The following are intentionally excluded from v1.4:

- `event_context_features` and multi-window context persistence
- `research_outcome_labels`
- matched or regime-aware baseline
- behavior model statistics
- rule-validation enhancements
- GUI controls for populating or selecting the new sample universe

Those changes require separate definitions for observation timing, outcome
pricing, matching rules, and leakage controls. Adding empty tables now would
create an Interface without validated semantics.

## Consequences

The storage layer can now preserve a future decision-universe dataset and bind
it to a declared StrategyProfile and experiment metadata. The application does
not yet populate that universe through the GUI; callers must use the new
research construction and storage Interfaces explicitly.
