# ADR: Entry Logic Modeling Research Boundary

- Status: Accepted
- Date: 2026-06-18
- Scope: implemented research boundary, persistence and optional export

## Context

Quant Replay Collector is a discretionary trading research and replay sample collector. It is not a live trading robot and not a generic candlestick player.

The entry logic research question is narrow: can the system structure the user's deep V long-entry judgment so it becomes explainable and reproducible?

The target behavior is long-side entry judgment after a prior decline inside a broader rising market, where the user pays attention to volume expansion, lower wick rejection, or a following bullish confirmation candle.

Existing ADRs already set important constraints:

- Research inputs and future outcomes are separated.
- Matched baseline selects controls from context features only.
- Candidate rules are hypotheses, not trading signals.
- Time-series validation must avoid random splits.
- `MainWindow` must not absorb new research implementation.

## Decision

We will introduce entry logic modeling as a research layer, not a trading layer.

The model label is `human_decision`, not `future_return`.

Allowed `human_decision` values are:

- `ENTRY`
- `REJECT`
- `UNCERTAIN`
- `UNLABELED`

Allowed public report/export score names are:

- `entry_logic_score`
- `human_entry_similarity`
- `setup_confidence`

The PU prototype may expose `pu_entry_score` as an internal ranking/evaluation field. It must be documented as similarity research output, not an executable recommendation.

`buy_signal` is forbidden. So are equivalent names that imply an executable order recommendation.

Context features may only use data visible at decision time. Outcome labels remain separate and are used only for post-hoc analysis.

Unopened samples are not negative samples by default. `NO_ACTION`, `AUTO_CANDIDATE`, and `SCHEDULED_BAR` observations remain unlabeled until a human marks them `REJECT`, `UNCERTAIN`, or `ENTRY`.

Temporal validation must support chronological split, walk-forward split, purge, and embargo. Random financial time-series splits are not allowed.

The first modeling prototype uses pandas / numpy only. Heavy dependencies such as sklearn, torch, tensorflow, and xgboost are out of scope.

## Module Map

`research.observation_universe` remains the legacy sample-universe interface.

`research.entry_observation_universe` generates loose review candidates for entry logic research.

`research.entry_annotations` owns `human_decision` and `decision_timing` validation.

`research.entry_context_features` owns decision-time entry context features.

`research.entry_outcome_labels` owns post-event outcome labels for posterior diagnostics.

`research.temporal_validation` owns chronological, walk-forward, purge and embargo utilities for entry logic research.

`research.entry_logic_scoring` and `research.pu_entry_learning` own lightweight similarity scoring.

`research.active_label_selection` owns manual review queue selection.

`research.entry_logic_report` owns Markdown/JSON research reporting.

`time_series_analysis` remains the market-sequence diagnostics package. New market-phase or reversal-neighborhood analysis should live there.

`strategy_consistency.profile` remains the strategy declaration interface.

`backtesting` remains a historical replay and comparison package. It must not become a source of model labels.

`main_app.py` remains the Qt shell. Any UI integration should call a small research interface or exported artifacts.

## Data Rules

`context features` may include:

- prior returns
- realized volatility
- drawdown and range measures
- volume spike measures
- lower-wick and reclaim measures
- time/session and regime labels visible at decision time

`context features` may not include:

- `fwd_ret`
- MFE
- MAE
- `hit_tp`
- `hit_sl`
- realized PnL
- manual final return
- future bars beyond the decision point

`outcome labels` may include future returns and path outcomes, but only after model scoring and only in diagnostic reports.

## Statistical Diagnostics

The research report must include distribution diagnostics for candidate inputs and model scores:

- skewness
- excess kurtosis
- quantiles
- distribution drift
- ACF
- Ljung-Box

If the sample is too small, diagnostics must say so directly. Missing p-values or unstable estimates cannot be treated as evidence.

## Consequences

The new layer can explain when a market setup resembles the user's historical ENTRY decisions.

It cannot place orders, trigger alerts as buy signals, or claim future profitability.

The research system gains a cleaner seam between:

- human behavior labels
- decision-time context
- model similarity scores
- post-event outcome analysis

This improves locality: leakage checks, label rules, and temporal validation live in research modules instead of spreading through UI or export code.

## Compatibility

This ADR keeps these compatibility rules:

- `quant_collector_app/main_app.py`
- `quant_collector_app/backtesting/`
- trading logic
- backtesting logic

SQLite changes are append-only. Schema version `6` adds `entry_annotations` through an idempotent migration and keeps old sessions readable.

Export changes are optional additions. Existing CSV, JSON, Markdown and Parquet exports remain intact, while entry logic files may be appended when data is available.

## Deferred Work

The following remain separate future work:

- richer annotation UI
- episode-aware grouping beyond bar-level purge/embargo
- calibration beyond prototype / PU ranking
- richer report charts
- broader UI exploration for reviewing and editing labels
