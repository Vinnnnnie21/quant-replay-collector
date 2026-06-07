# ADR-0005: MainWindow Decomposition

## Status

Accepted for v1.4.1 stabilization work.

## Context

Quant Replay Collector is a desktop research tool for crypto market replay,
manual trade-event labeling, execution-cost simulation, event-study analysis,
research dataset export, strategy consistency audit, local SQLite persistence
and readonly local API context.

It is not a live trading system and must not become one during refactoring.

The current `MainWindow` still owns too much implementation detail:

- Qt layout and widget wiring.
- Market loading and dynamic timeframe switching.
- Replay controls.
- Chart rendering and marker synchronization.
- Manual open/close trade workflow.
- Undo/redo local state mutation.
- Table population.
- Event study, dataset summary and performance summary refresh.
- Session persistence.
- Export task coordination.
- Premium sampling and plotting.
- Multi-timeframe context refresh.

Several seams already exist, but they are not deep enough yet:

- presenters for table and text display;
- `TradeUseCase` for Qt-free trade transaction orchestration;
- `RenderState` for chart dirty flags;
- `UiFreezeWatchdog` for freeze diagnostics;
- multi-timeframe panel summary caching.

The real risk is not one isolated bug. The risk is that new behavior keeps
being added to `MainWindow`, making UI freezes, import regressions and test
gaps harder to isolate.

## Decision

We will decompose `MainWindow` in small, independently testable stages. Each
stage must keep public behavior compatible and must not change trading
semantics, SQLite schema, research schema or release boundaries.

The migration order is:

1. Establish the responsibility map and safety net.
2. Move display formatting and table population behind presenter seams.
3. Move non-UI manual trade transaction orchestration behind trade use cases.
4. Move chart render policy, visible-window math and marker diffing behind
   render seams.
5. Move heavy analysis refresh scheduling behind an analysis refresh service.
6. Move session, settings and export coordination behind focused services.
7. Reduce import-path compatibility shims gradually, without breaking Windows
   launch or packaging.
8. Re-run full stability and clean-release verification.

`MainWindow` remains the Qt shell. It may still:

- construct and own widgets;
- connect Qt signals;
- read current UI state;
- call services and presenters;
- show user-facing errors;
- apply returned results to Qt widgets on the main thread.

The extracted modules must not become new giant controllers. The interface of
each module must be smaller than the implementation it hides.

## Compatibility Rules

- No Binance live trading API integration.
- No automated order placement.
- No change to open/close fill-price semantics.
- No change to fee, slippage or PnL semantics.
- No SQLite schema change.
- No research schema change.
- No future-leakage boundary changes.
- No candidate rule may be described as a trading signal.
- No sample-internal result may be described as future profitability.
- No Qt widget update may run from `threading.Timer` or a worker thread.
- No release artifact may include runtime data, logs, databases, caches or
  private configuration.

## Testing Strategy

Every stage must run its narrow tests plus entrypoint checks. Stages that touch
rendering or trade actions must also run the replay and trade regression tests.

Baseline checks:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q tests/test_entrypoints.py tests/test_trade_use_cases.py tests/test_presenters.py
```

Full stabilization checks:

```powershell
python -m pytest -q
python quant_collector_app/self_check.py --core
python -m quant_collector_app.self_check --core
python scripts/clean_release.py --output dist/QuantReplayCollector-v1.4.1-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-v1.4.1-Clean
```

If full pytest is slow, run:

```powershell
python -m pytest --durations=20
```

Slow tests must be explained, not skipped by default.

## Consequences

This ADR deliberately favors small reversible changes over a clean rewrite.
That means `MainWindow` will remain large for several commits. This is
acceptable as long as each stage removes a real responsibility and strengthens
test seams.

The presenter, trade-use-case, render, session/export and analysis-refresh
seams have now been introduced under regression tests. Heavy analysis
calculation runs in a worker and returns through explicit queued Qt slots before
widgets are updated.

`MainWindow` remains large and still owns substantial coordination. Snapshot
construction, UI result application, marker payload generation and session
persistence remain areas to profile and migrate in later small changes.

## Deferred Work

This ADR does not implement a new GUI layout, schema migration, strategy
feature, live trading capability or import-system rewrite. Those changes need
separate scopes and tests.
