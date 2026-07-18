# Changelog

## v1.5.2 - 2026-07-17

### Fixed

- Replaced raw translation keys and hard-coded interface text with the shared Chinese and English resources across replay, analysis, settings, backtest, status, logs and background-task progress.
- Prevented English mode from falling back to Chinese when a translation is unavailable.
- Localized dynamic research-table columns, backtest validation errors, walk-forward warnings, trade state and performance output.
- Bundled both translation JSON files into the Windows executable so packaged builds match source-mode language behavior.
- Made a workspace-installed Windows executable reuse `quant_collector_app/data` instead of creating a disconnected database beside the EXE; standalone portable builds keep their executable-local data directory.
- Added transaction-safe deletion of an entire performance session, including its owned trades, events, equity and research records, while retaining K-lines and data-quality reports.
- Refreshed replay, analysis and trade-management session catalogs after deletion and regenerated continuous display numbering for remaining sessions in the same market range.
- Reordered the trade-management table around symbol, side, return and PnL, with signed return and PnL values using the existing gain/loss colours.

### Compatibility and boundaries

- Technical identifiers such as symbols, intervals, API names and research field identifiers retain their canonical values.
- Trading, replay, accounting, SQLite schema and research algorithms are unchanged. Existing saved sessions are only removed through the explicit two-step performance-session deletion action.

## v1.5.1 - 2026-07-17

### Added

- Added one background-task lifecycle for market loading, multi-timeframe loading, analysis refresh, export and premium sampling, with cooperative safe shutdown and a visible saving state.
- Added atomic settings writes, 14-day daily database backups and verified pre-migration backups.
- Added strict K-line and event-window research quality gates. Collection-time sorting, deduplication and invalid-row removal remain allowed only with an auditable quality report.
- Added deterministic, resource-bounded bootstrap and permutation statistics with seed, simulation, confidence, batching and budget metadata in manifests and reports.
- Added a reproducible 270,000-bar performance benchmark and a Windows desktop smoke checklist.
- Added transaction-safe trade-data management by performance session, individual trade or replay-time range, with deletion previews, typed second confirmation and account-equity rebuilding.
- Added replay-page continuation of an existing performance session without cloning its `session_id`.
- Added nullable TP/SL inputs that preserve `None` through trade creation and session save/restore.
- Added the `QRC` Windows desktop entry, multi-size application icon and current-user shortcut script.

### Changed

- Multi-timeframe loading now uses single-flight scheduling: active work is retained, intermediate requests are merged, stale pending work is discarded and shutdown cancels cooperatively.
- CSV export is chunked and cancellable. Complete exports are built in a staging directory, published with recoverable directory replacement and protected against transient Windows ACL or file-handle cleanup failures.
- Daily backups, large market-data preparation, analysis refresh and export remain outside the Qt UI thread; SQLite market writes use bounded batches.
- Analysis refresh returns a bounded worker-built performance payload, rejects stale revisions and reuses cached results for trade filters. The UI receives at most 2,000 equity display points.
- Historical performance reads now run in a revisioned worker, and the trade table renders bounded 200-row pages instead of creating Qt items for every trade.
- Analysis, export and daily-backup controllers finalize task lifecycles only after `QThread.finished`; shutdown requests cancellation and returns to Qt instead of waiting without a bound.
- Script-mode and package-mode self-checks now use the formal entry-logic report writer. Internal report calculation failures stop the export instead of producing a fallback success report.
- Session UI mapping and other MainWindow coordination were moved behind focused adapters without changing replay or storage contracts.
- The supported release environment is now enforced in CI as Windows/Python 3.13 with an exact dependency lock.
- Value/date inputs ignore mouse-wheel changes while their parent scroll areas continue scrolling; light-theme scrollbars use a more visible global palette.
- The header uses the QRC logo beside the application name and version. Window, header and native Windows title-bar colors follow the active light or dark theme.

### Fixed

- Research entry points now reject out-of-order, duplicate, invalid-timestamp and non-finite K-line or event-window input instead of silently sorting or deduplicating it.
- Event-window export reads now have deterministic repository ordering while the research quality gate still rejects real duplicates and reversals.
- Export cancellation can no longer publish half-written CSV files or mix new files into a previous successful export.
- Qt/pyqtgraph object ownership and cleanup were tightened to prevent intermittent native access violations during repeated layout, theme and close cycles.
- A one-point equity or PnL curve is now visibly rendered, and the chart explains empty or replay-deferred states instead of showing an unexplained blank area.
- Historical performance now reads its session K-lines in a cancellable background worker, builds a continuous replay-market-time equity curve and never falls back to or mutates the current player state.
- Historical-session revisions reject late worker results, and missing session K-lines produce an explicit recover-session message instead of a blank chart.
- Deleting current-session trades synchronizes in-memory trades, events, indexes, markers, tables and analysis; deleting historical-session trades leaves the current player unchanged.

### Compatibility and boundaries

- No live-trading or exchange-order API was added.
- Simulated trading, fees, slippage, PnL, TP/SL, backtesting rules, research features, future-data isolation, SQLite schema and export schemas retain their existing meaning.
- Current-session snapshot handoff, cancellation inside an active SQLite call and visible-desktop performance remain explicit follow-up verification risks.

## v1.5.0 - 2026-07-11

### Added

- Exchange-style free chart pan and zoom, explicit follow-latest framing, dual price axes and a right-axis current-price badge.
- Session-level initial equity, per-trade notional and optional TP/SL settings.
- Multiple independent long and short replay positions with FIFO fallback for manual close and per-position automatic TP/SL exits.
- A funds-management performance workspace with continuous equity including unrealized PnL, signed equity/PnL curves, account metrics, closed-trade details and a labeled PnL distribution.
- OpenGL acceleration for the main chart with automatic software fallback, plus 120 Hz target-machine validation.
- `0.1x` to `10x` centered playback stops and left/right arrow speed control; `Shift+Right` retains single-bar stepping.
- Switchable colour presets: `黑色配色` (OKX-style near-black), `灰色配色`, `研究配色`, `高对比配色`.
- Unified dark "pill" design language for buttons, period/timeframe chips, inputs and event-tag toggles, applied via per-control local stylesheets (reliable fills under the Fusion style) plus drop shadows.
- Free vertical (price) zoom with `Ctrl` + mouse wheel; `重置缩放 / Reset zoom` restores automatic fitting.
- `entry_logic.reject` / `entry_logic.uncertain` translation keys and `tests/test_analysis_i18n.py` (data-analysis page i18n contract).

### Changed

- Manual open/close actions no longer pause replay playback.
- Manual open/close actions preserve follow-latest state and use lightweight table refreshes during playback.
- Performance trade results and distribution use signed red/green presentation, and redundant legacy performance tabs were removed.

### Fixed

- Removed full-dataframe TP/SL scans and full-chart picture rebuilds from the replay hot path.
- Kept new K-lines visible while replay continues during chart dragging.
- Prevented session restore controls from overwriting the saved replay cursor before market data loads.
- Prevented the current-price label and long account-setting labels from covering or clipping chart and form content.
- Closing a position with `C` / `X` failed with multiple open positions: restored the truncated `selected_open_trade` and added side-aware auto-selection.
- Data-analysis page no longer mixes Chinese/English: the `REJECT` / `UNCERTAIN` buttons were hard-coded and now use `_tr`.

## v1.4.1 Hotfix

### Added

- Added a research-only `StrategyRuleParams` contract for reproducible Deep V reversal simulations.
- Added backtest date-range filtering by symbol, interval and `open_time_bjt`.
- Added the current long-only Deep V reversal historical backtest workflow.
- Added explicit analysis-to-backtest threshold mapping for user review before simulation.
- Added `BacktestService`, `BacktestController`, backtest presenter and minimal backtest panel controls.
- Added descriptive manual-vs-rule comparison after rule simulation. Manual trades are not rule inputs.
- Added entry logic research modules for `human_decision` annotations, loose observation candidates, decision-time context features, isolated post-event outcome labels, chronological and walk-forward validation, distribution diagnostics, prototype scoring, PU-style ranking, active review queues, experiment manifests and Markdown/JSON reports.
- Added optional entry logic export files: `entry_annotations.csv`, `entry_observation_universe.csv`, `entry_context_features.csv`, `entry_outcome_labels.csv`, `entry_logic_scores.csv`, `entry_review_queue.csv`, `entry_logic_report.md` and `entry_logic_report.json`.
- Added SQLite schema version `6` with an idempotent `entry_annotations` table migration. Existing sessions and legacy tables remain compatible.

### Fixed

- Reduced replay UI freeze risk during high-speed playback plus manual trade actions.
- Limited premium plot refreshes to recent premium samples instead of reading the full premium history table.
- Deferred heavier event-study, dataset-summary and performance-summary refreshes after open/close trade transactions.
- Reordered replay rendering so visible range is determined before chart item rebuilds.
- Reduced redundant chart rebuilds while browsing a fixed historical window.
- Added background UI freeze watchdog dumps under the local logs directory.
- Cached multi-timeframe context summaries within the same higher-timeframe bar.
- Returned analysis-worker results through explicit queued Qt slots before
  applying event-study, dataset-summary and performance-summary output to widgets.
- Moved analysis debounce and worker lifecycle into a focused controller, and
  coalesced requests arriving during an active refresh.
- Moved chart viewport and dirty-flag decisions into a Qt-free render plan while
  keeping all widget updates on the Qt main thread.
- Indexed event-marker payloads so cursor movement inside the same event
  boundary does not rescan every recorded event.
- Cleaned analysis and export workers when their QThread finishes, waited for
  threads to stop before deletion, and isolated queued controller-test
  callbacks so full-suite runs do not inherit stale Qt events.
- Moved asynchronous export-worker lifecycle out of `MainWindow` into a
  focused controller while preserving export requests and output formats.
- Moved static MainWindow widget and plot construction into
  `views.main_window_layout` while retaining a thin compatibility wrapper and
  the existing interaction callbacks.
- Moved MainWindow translation and theme application into
  `views.main_window_presentation` without changing the public window methods.
- Moved lightweight header, button, premium-plot and current-price-line updates
  into `presenters.status_presenter` while preserving MainWindow wrappers.
- Moved Qt table setup, shortcut guards and signal wiring into
  `views.main_window_connections` without changing connected slots.
- Moved Qt-main-thread chart application into `render.chart_render_adapter`
  while preserving render plans, visible-window limits and MainWindow wrappers.
- Moved market parameter keys, dynamic timeframe switching and load-result
  application into `controllers.market_data_controller` while preserving
  MainWindow slots and sample-interval guards.
- Moved replay UI orchestration into `controllers.replay_ui_controller`, and
  manual trade/undo/redo orchestration into
  `controllers.trade_action_controller`.
- Moved the destructive clear-records confirmation flow into
  `controllers.trade_record_controller`.
- Reduced `main_app.py` below the 1,200-line stage target without changing
  trade, replay, SQLite or research schema semantics.

### Changed

- Moved table formatting, trade transaction orchestration, visible-window
  calculation, marker payload calculation, session/export request construction
  and domain SQL behind focused presenter, service, render and repository seams.
- Added package-mode import regression coverage while retaining the existing
  Windows script and PyInstaller-compatible launch paths.
- Added a minimal Analysis Workspace entry for generating entry logic reports
  and loading the top-k review queue through the existing background export
  task path.

### Release Hygiene

- Keep publishing through `scripts/clean_release.py`; do not upload development directories containing `dist`, logs, caches, databases or pytest temporary folders.
- Clean release generation and verification reject private `.env` files, local
  settings, SQLite files, logs and local archives regardless of their directory.
- Public clean-release reports omit local absolute paths and individual skipped
  file names.
- Clean releases exclude local agent workflow directories such as `.agents/`,
  `.scratch/` and `docs/agents/`.

### Research Safety

- Backtests are historical simulations for testing rule hypotheses. They are
  not trading signals, future-return predictions or investment advice.
- Entry logic research learns the user's opening-judgment boundary. Its labels
  are `human_decision`, not future returns, and its scores are
  `human_entry_similarity` / `setup_confidence`, not buy/sell signals.
- `ENTRY`, `REJECT`, `UNCERTAIN` and `UNLABELED` remain human annotation states.
  `UNLABELED` and unopened samples are not treated as negative samples by
  default.
- Entry context features and outcome labels are exported separately. Outcome
  labels are for posterior diagnostics only and must not be used as model
  inputs.
- Entry logic validation uses chronological or walk-forward splits with purge
  and embargo; random financial time-series splits are not used.
- Quant Replay Collector does not connect to Binance live-order APIs or place
  automatic orders.
- Manual trading semantics and existing research/export semantics remain
  unchanged. SQLite migrations are append-only and keep old sessions readable.

### Known Limitations

- The current Deep V workflow supports `long_only`, `tp_sl_timeout` exits and a
  single open position.
- The selected backtest symbol and interval must match the currently loaded
  K-line data; the backtest panel does not automatically reload another market.
- Equity-curve presentation remains minimal.
- Full Qt GUI tests require PySide6 and a stable GUI-capable test environment.

## v1.4.0

### Added

- Dynamic timeframe switching with timestamp anchoring on the main replay chart.
- Multi-timeframe read-only context for higher-timeframe market state.
- Research dataset scaffolding for observation universe and strategy samples.
- Separate context-feature and outcome-label research paths.
- Matched baseline, behavior statistics and candidate-rule validation controls.

### Changed

- Display interval and trade-sample interval are treated separately during replay.
- Rule validation exposes FDR adjustment, purged chronological split, embargo handling and out-of-sample degradation gates.
- Version metadata and release documentation now identify the `v1.4.0` release.

### Fixed

- Changing the displayed timeframe can retain the current market-time position instead of restarting from the beginning.
- Existing trade samples are protected from silent cross-interval `bar_index` reuse.

### Research Safety

- Higher-timeframe context is read-only and is not a trading signal.
- Context features and future outcome labels remain separated to reduce leakage risk.
- Matched baseline and validation statistics are research evidence only; they do not imply future profitability.
- Quant Replay Collector does not connect to Binance order APIs, place live trades or provide investment advice.

### Release Hygiene

- Publish only output produced by `scripts/clean_release.py`.
- Run `scripts/check_release_clean.py` on that output before creating an archive or uploading a release asset.
- Do not publish a development directory containing caches, databases, logs, exports or local settings.
