# Changelog

## v1.4.1 Hotfix

### Added

- Added a research-only `StrategyRuleParams` contract for reproducible Deep V reversal simulations.
- Added backtest date-range filtering by symbol, interval and `open_time_bjt`.
- Added the current long-only Deep V reversal historical backtest workflow.
- Added explicit analysis-to-backtest threshold mapping for user review before simulation.
- Added `BacktestService`, `BacktestController`, backtest presenter and minimal backtest panel controls.
- Added descriptive manual-vs-rule comparison after rule simulation. Manual trades are not rule inputs.

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
- Quant Replay Collector does not connect to Binance live-order APIs or place
  automatic orders.
- Manual trading semantics, SQLite schema and research schema remain unchanged.

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
