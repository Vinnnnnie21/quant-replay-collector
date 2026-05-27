# ADR-0002: Context Features and Outcome Labels Are Separate Tables

- Status: Accepted
- Date: 2026-05-27
- Scope: v1.5 research feature and outcome persistence

## Context

Schema v4 established `observation_universe` and `strategy_samples`, so a
research experiment can identify both acted and non-acted observations.
The next problem is temporal correctness.

The legacy `event_features` table predates this separation. It contains useful
review data together with forward returns, MFE, MAE, and manual result fields.
It must remain readable for existing exports, but it cannot be the canonical
input Interface for new research.

## Decision

Schema version 5 adds two long tables:

- `event_context_features`
- `research_outcome_labels`

### `event_context_features`

This is the canonical v1.5 input table for observation context. Every row is a
single numeric feature value for one sample and one lookback window.

Allowed lookback windows are `20`, `50`, and `100` bars. A context computation
first truncates OHLCV rows to `bar_index <= sample.bar_index`. It then uses at
most the selected trailing window, including the event bar because that bar is
assumed visible when the observation is recorded.

If fewer bars are available than requested, the result records
`available_bars` and `insufficient_history=1`; it does not calculate
full-window metrics from invented padding.

Names containing future or result terms are rejected by both the Python
Interface and the SQLite `CHECK` constraint:

- `fwd`
- `post`
- `future`
- `mfe`
- `mae`
- `hit_tp`
- `hit_sl`
- `pnl`
- `exit`
- `label`

### `research_outcome_labels`

This is the outcome table. It records results that become knowable only after
the observation time. Supported horizons are `5`, `10`, `20`, and `50` bars.
It may contain `fwd_ret`, `mfe`, `mae`, `hit_tp`, `hit_sl`, and `r_multiple`.

When there are not enough future bars, the row is preserved with
`insufficient_future_bars=1` and empty result values.

### Evaluation pricing basis

The default basis for new strategy evaluation is `next_open`:

- Signal or observation is formed at bar `t`.
- Evaluation entry price is bar `t+1` open.
- The outcome path starts after `t`.

Other permitted research bases are:

- `event_close`: comparison basis only.
- `legacy_mid`: legacy replay compatibility only; it does not represent an
  executable fill.
- `worst_case_same_bar`: conservative same-bar comparison basis only.

This decision does not change existing replay fill behavior. It defines the
new research-outcome Interface.

## Compatibility

Existing tables, exports, and research outputs remain available. The exporter
adds `event_context_features.csv` and `research_outcome_labels.csv`; it does
not replace legacy files.

The legacy `event_features` table remains for historical review and
compatibility. It is not recommended as the core input for new research.

## Deferred Work

This change does not implement:

- matched baseline
- behavior model
- rule validation, multiple-testing adjustment, or FDR
- GUI workflow changes
- automatic execution or live trading

Those depend on stable sample collection and separated feature/outcome data.
