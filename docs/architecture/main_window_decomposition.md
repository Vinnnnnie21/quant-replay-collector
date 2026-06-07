# MainWindow decomposition baseline

## Current state

`quant_collector_app/main_app.py` is still the application shell. In the current
worktree it is below 1,200 lines and `MainWindow` retains initialization,
public slot wrappers, dialogs, table refresh triggers, result application and
session/export feedback. Static layout, market loading, replay orchestration,
chart rendering and manual trade actions now live in focused modules.

This is not an unrecoverable codebase. The first seams already exist:

- `presenters/formatters.py` and `presenters/table_presenter.py` own the shared
  table and text presentation work.
- `presenters/status_presenter.py` owns lightweight button, header, premium-plot
  and current-price-line presentation while MainWindow keeps public wrappers.
- `views/main_window_layout.py` owns static widget, plot, table and shortcut
  construction while `MainWindow._build_ui()` remains a compatibility wrapper.
- `views/main_window_presentation.py` owns translation and theme application
  while MainWindow preserves the existing public methods as thin wrappers.
- `views/main_window_connections.py` owns Qt table setup, shortcut guards and
  signal wiring while MainWindow preserves the existing wrapper methods.
- `services/trade_use_cases.py` holds Qt-free open/close trade transaction
  orchestration.
- `render_state.py`, `render/chart_render_plan.py`, `render/visible_window.py`
  and `render/marker_renderer.py` hold chart dirty flags, viewport policy,
  visible-window slicing and marker payload calculation.
- `render/chart_render_adapter.py` owns Qt-main-thread chart application while
  MainWindow preserves render method wrappers used by existing callers.
- `services/analysis_refresh.py` and `workers/analysis_refresh_worker.py` run
  heavy analysis calculations outside the Qt main thread and return results
  through explicit queued slots.
- `controllers/analysis_controller.py` owns analysis debounce, playback
  deferral, worker lifecycle and coalescing of refresh requests.
- `services/session_service.py`, `services/export_service.py` and
  `storage_core/` hold focused state, request and SQL responsibilities behind
  compatible public entry points.
- `controllers/export_task_controller.py` owns asynchronous export-worker
  lifecycle without owning export widgets or output-format logic.
- `controllers/market_data_controller.py` owns market parameter keys, dynamic
  timeframe switching and load-result application behind MainWindow slots.
- `controllers/replay_ui_controller.py` owns replay timer and control
  orchestration over the existing `ReplayController`.
- `controllers/trade_action_controller.py` owns manual open/close, sample
  interval guards and undo/redo orchestration over `TradeUseCase`.
- `controllers/trade_record_controller.py` owns the destructive clear-records
  confirmation flow.
- `multi_timeframe_panel.py` caches higher-timeframe summaries inside the same
  HTF bar.
- `ui_watchdog.py` records UI heartbeat delays and writes freeze stack dumps.

The remaining risk is that these seams are still shallow in places. MainWindow
continues to know too many implementation details behind them.

Stages 0 through 8 of this decomposition plan have been implemented as small
tested slices. The stage target of fewer than 1,200 lines has been reached.
Further work toward the optional roughly 800-line ideal should happen only
after profiling identifies a concrete stability or maintenance problem.

## Responsibility map

### UI assembly and interaction

Static widget construction has moved to `views.main_window_layout`.
Translation and theme application have moved to
`views.main_window_presentation`, and signal wiring lives in
`views.main_window_connections`. `MainWindow` keeps public wrapper methods
because those methods are part of the existing window contract.

- `_build_ui` (thin compatibility wrapper)
- `_setup_table`
- `_connect`
- `_add_shortcut`
- `_focus_is_text_entry`
- `eventFilter`
- `apply_language`
- `retranslate_ui`
- `_install_theme`
- `apply_theme`
- `open_theme_dialog`
- `open_settings_dialog`
- `toggle_detail_panel`
- `toggle_log_drawer`
- `toggle_symbol_panel`
- `filter_symbol_list`
- `on_symbol_item_selected`
- `_set_symbol_value`
- `_set_widget_role`

### Session and market state

This is a good later seam for a session service, because it mixes UI values,
runtime state and storage calls.

- `_restore_latest_session_if_any`
- `persist_session_state`
- `_on_autosave_timer`
- `_operation_context`
- `_current_market_key`
- `_is_market_params_dirty`
- `_accept_loaded_market_key`
- `_show_market_dirty_feedback`
- `_display_interval`
- `_sample_interval`
- `_is_display_interval_same_as_sample_interval`
- `start_new_session_for_current_display_interval`

### Market loading and dynamic timeframe switching

The implementation now lives in `controllers.market_data_controller`.
`MainWindow` keeps compatible slots for the display interval versus sample
interval distinction, which protects trade samples from cross-interval
bar-index pollution.

- `load_data`
- `on_load_progress`
- `on_loaded`
- `_persist_loaded_market_data`
- `load_or_toggle_play`
- `_update_load_play_button`
- `on_market_params_changed`
- `on_interval_changed_for_dynamic_switch`
- `_clear_timeframe_switch_pending`

### Replay controls

Replay semantics remain central product behavior. Their orchestration now lives
in `controllers.replay_ui_controller`, while these methods remain compatible
window slots.

- `on_timer`
- `toggle_play`
- `step_once`
- `jump_to_end`
- `toggle_follow`
- `on_user_interaction`
- `reset_view`
- `on_speed_changed`
- `current_speed`

### Chart rendering

Render policy, visible-window calculation, item rebuild keys and marker diffing
now live in the focused render modules. MainWindow keeps compatible wrappers
and applies the resulting UI changes on the Qt main thread.

- `_chart_render_state`
- `_should_render_now`
- `_mark_rendered`
- `_rebuild_items`
- `_current_xrange`
- `_set_xrange`
- `_clamp_xrange`
- `_soft_follow_should_apply`
- `_autoscale_y`
- `_sync_markers`
- `_update_current_price_line`
- `_update_header`
- `_render`

Current good behavior to preserve:

- `_rebuild_items()` slices by visible range instead of rebuilding the full
  history.
- The rebuild key ignores cursor growth when the visible window is an old free
  view.
- `_render()` consults `RenderState` before refreshing series, markers, price
  line, header and multi-timeframe context.
- `MarkerPayloadCache` indexes events only when the event set, market frame or
  display interval changes, and reuses payloads while cursor movement remains
  inside the same event boundary.

Remaining risk:

- `_render()` now applies a Qt-free `ChartRenderPlan`, so follow/free viewport
  decisions and dirty-flag interpretation no longer live in the window class.
  It still owns status-text construction and the ordering of Qt widget updates.

### Manual trade workflow

`TradeUseCase` owns SQLite transaction orchestration and
`controllers.trade_action_controller` owns manual trade UI orchestration.
MainWindow keeps compatible wrappers and user-facing dialogs.

- `_pause_replay_for_manual_trade`
- `_trade_use_case`
- `_raise_trade_action_error`
- `request_open_trade`
- `request_close_trade`
- `selected_open_trade`
- `execute_command`
- `undo`
- `redo`

Current good behavior to preserve:

- Playback is paused before manual trade actions.
- `_trade_transaction_active` protects against repeated clicks.
- Heavy analysis refresh is deferred after trade actions.
- Display interval and sample interval mismatch blocks recording.

Remaining risk:

- `trade_action_controller.py` is a focused but sizeable controller. It should
  not absorb unrelated session, analysis or rendering responsibilities.

### Table and presenter work

The table seam exists, but it needs cleanup before it becomes a reliable
interface.

- `_refresh_tables`
- `_populate_tables`
- `_current_equity_rows`
- `_populate_event_study_table`

Current state:

- Shared Chinese labels and table output are covered by UTF-8 presenter tests.
- MainWindow still decides when tables refresh and still owns selection
  restoration and signal blocking.

### Analysis refresh

Heavy analysis calculation is no longer executed directly in the trade path.

- `_schedule_deferred_analysis_refresh`
- `_run_deferred_analysis_refresh`
- `_feature_rows_for_session`
- `_event_rows_for_study`
- `_refresh_dataset_summary`
- `_refresh_performance_summary`

Current good behavior to preserve:

- Trade actions call `_refresh_tables(include_heavy=False)` and schedule a
  deferred refresh instead of immediately running all analysis.
- Deferred analysis waits while replay is active.
- Event-study, dataset-summary and performance-summary calculations run in
  `AnalysisRefreshWorker`.
- Results return through explicit queued Qt slots before MainWindow updates
  widgets.
- Refresh requests arriving while a worker is active are coalesced into one
  follow-up refresh.
- Worker deletion follows QThread completion, and controller tests drain queued
  callbacks between cases so the full suite does not inherit stale Qt events.

Remaining risk:

- Snapshot construction and final Qt table/text application still run on the
  main thread. Very large sessions can still cause a short pause at those
  boundaries and should be profiled before further extraction.

### Export and premium

These are lower priority for the MainWindow split, but still add coordination
weight.

- `_ensure_export_controller`
- `export_session`
- `start_export_task`
- `_on_export_finished`
- `_on_export_failed`
- `_on_export_cancelled`
- `_finish_export_task`
- `request_premium_sample`
- `on_premium_sample`
- `_refresh_premium_plot`

Current state:

- `ExportTaskController` owns worker/QThread creation, completion, failure,
  cancellation and cleanup, and does not delete a thread before it has stopped.
- MainWindow retains directory selection, button state, status text, callbacks
  and result dialogs.

## Migration order

### Stage 0: architecture baseline and safety net

Scope: documentation and existing test verification only.

Files:

- `docs/architecture/main_window_decomposition.md`
- `docs/adr/ADR-0005-main-window-decomposition.md`

Acceptance:

- MainWindow responsibilities are mapped.
- High-risk UI freeze paths are named.
- Next stages have file-level scope and test commands.
- No trade semantics, SQLite schema or research schema changes.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q tests/test_entrypoints.py tests/test_trade_use_cases.py tests/test_presenters.py
```

### Stage 1: presenter cleanup

Scope: presentation only.

Files:

- `quant_collector_app/presenters/formatters.py`
- `quant_collector_app/presenters/table_presenter.py`
- `quant_collector_app/main_app.py`
- `tests/test_presenters.py`

Tasks:

- Fix mojibake Chinese labels in presenter output.
- Remove or wrap any remaining duplicate formatter logic in MainWindow.
- Keep table columns, order, IDs and numeric formatting unchanged.
- Keep presenters free of storage, replay and trade state mutation.

Acceptance:

- Presenter tests assert correct UTF-8 Chinese text, not mojibake.
- MainWindow decides when to refresh; presenters decide how rows look.
- No transaction, replay or storage behavior changes.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q tests/test_presenters.py tests/test_entrypoints.py
python -m pytest -q tests/test_trade_use_cases.py tests/test_trade_action_pauses_replay.py
```

### Stage 2: trade use-case layer

Scope: move remaining non-UI transaction orchestration behind
`TradeUseCase`.

Files:

- `quant_collector_app/services/trade_use_cases.py`
- `quant_collector_app/main_app.py`
- `tests/test_trade_use_cases.py`
- `tests/test_trade_action_pauses_replay.py`

Tasks:

- Keep MainWindow responsible for button events, pause, button enablement,
  dialogs and UI refresh scheduling.
- Move validation and transaction result assembly behind the use-case interface.
- Keep undo/redo payloads stable.
- Do not change fill price, fee, slippage or PnL semantics.

Acceptance:

- `request_open_trade()` and `request_close_trade()` are thinner.
- Trade actions still pause replay and block duplicate clicks.
- Error paths restore trade buttons.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q tests/test_trade_use_cases.py tests/test_trade_action_pauses_replay.py
python -m pytest -q tests/test_storage_trade_flow.py tests/test_controllers.py
```

### Stage 3: chart render controller

Scope: render policy and visible-window math.

Files:

- `quant_collector_app/render_state.py` or `quant_collector_app/render/render_state.py`
- `quant_collector_app/render/chart_render_plan.py`
- `quant_collector_app/render/visible_window.py`
- `quant_collector_app/render/marker_renderer.py`
- `quant_collector_app/main_app.py`
- `tests/test_replay_render_budget.py`
- `tests/test_multi_timeframe_refresh_throttle.py`

Tasks:

- Move visible-window rebuild decisions out of MainWindow.
- Move marker diff key construction out of MainWindow.
- Keep all Qt item updates on the main thread.
- Do not use `threading.Timer` for Qt widget updates.

Acceptance:

- Free-view cursor movement with unchanged visible range does not call
  `set_data()`.
- Follow-latest rebuilds the target window before moving xRange.
- Marker payloads do not refresh when events are unchanged.
- Multi-timeframe context refreshes only when the containing HTF bar changes.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q tests/test_replay_render_budget.py tests/test_multi_timeframe_refresh_throttle.py
python -m pytest -q tests/test_dynamic_timeframe_switch.py tests/test_reset_view_semantics.py
```

### Stage 4: analysis refresh service

Scope: scheduling of heavy analysis refresh.

Files:

- `quant_collector_app/services/analysis_refresh_service.py`
- optional `quant_collector_app/workers/analysis_worker.py`
- `quant_collector_app/main_app.py`
- new analysis refresh tests

Tasks:

- Debounce repeated refresh requests.
- Delay heavy refresh while playback is active.
- Prevent overlapping heavy refresh runs.
- Keep pure calculation separate from Qt widget updates.

Acceptance:

- Trade commit path does not synchronously run event study, dataset summary or
  performance summary.
- Refresh errors are logged and displayed without affecting trade state.
- Existing statistical outputs are unchanged.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q tests/test_trade_action_pauses_replay.py tests/test_replay_render_budget.py
python -m pytest -q tests/test_entrypoints.py
```

### Stage 5: session, settings and export control

Scope: reduce MainWindow coordination weight outside the replay path.

Files:

- `quant_collector_app/services/session_service.py`
- `quant_collector_app/controllers/settings_controller.py`
- `quant_collector_app/services/export_service.py`
- `quant_collector_app/main_app.py`

Tasks:

- Move session state construction, restore and autosave policy out of
  MainWindow.
- Keep settings application explicit and testable.
- Keep export execution Qt-free except for worker signal delivery.

Acceptance:

- Session roundtrip still works.
- Export still produces CSV/JSON/Markdown outputs.
- Missing Parquet engines do not break CSV export.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python quant_collector_app/self_check.py --core
python -m quant_collector_app.self_check --core
python -m pytest -q tests/test_entrypoints.py
```

### Stage 6: import-system convergence

Scope: package imports and launch compatibility.

Files:

- `tests/conftest.py`
- `quant_collector_app/__main__.py`
- `quant_collector_app/self_check.py`
- selected modules with top-level imports

Tasks:

- Keep `python run_app.py` working.
- Keep `python -m quant_collector_app` working.
- Keep script-mode and package-mode self-check working.
- Reduce reliance on test-only `sys.path` injection gradually.

Acceptance:

- No manual `PYTHONPATH=.` requirement.
- No broad import migration in a single commit.
- PyInstaller entry assumptions are not broken.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q tests/test_entrypoints.py
python quant_collector_app/self_check.py --core
python -m quant_collector_app.self_check --core
```

### Stage 7: full stability verification

Scope: prove the refactor did not weaken the product path.

Tasks:

- Run full pytest.
- If slow, run duration profiling instead of skipping tests.
- Recheck the high-risk scenario: BTCUSDT, 5m, 2024-04-01 to 2024-05-01,
  roughly 8,928 bars, high-speed playback, manual open/close/open.
- Confirm watchdog dump path still works.

Acceptance:

- Full tests pass, except environment-dependent GUI skips.
- No collection errors.
- Slow tests are named with cause and next action.
- High-risk playback path has render and trade-action evidence.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q
python -m pytest --durations=20
python quant_collector_app/self_check.py --core
python -m quant_collector_app.self_check --core
```

### Stage 8: clean release and documentation consistency

Scope: release hygiene and public claims.

Files:

- `README.md`
- `CHANGELOG.md`
- `docs/release.md`
- `docs/architecture.md`
- `scripts/clean_release.py`
- `scripts/check_release_clean.py`

Tasks:

- Keep v1.4.1 framed as a hotfix, not a new major feature release.
- Confirm no live trading, automated trading or investment-advice claims.
- Confirm candidate rules are described as hypotheses, not signals.
- Confirm clean release excludes runtime data and local artifacts.

Acceptance:

- `check_release_clean.py` rejects db, sqlite, logs, data, zip, pycache,
  pytest cache and performance reports.
- README and release docs match actual code.
- No runtime artifacts are staged.

Tests:

```powershell
python -m compileall -q quant_collector_app tests
python -m pytest -q
python quant_collector_app/self_check.py --core
python -m quant_collector_app.self_check --core
python scripts/clean_release.py --output dist/QuantReplayCollector-v1.4.1-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-v1.4.1-Clean
```

## Stop conditions

Stop the current stage and report before continuing if any of these happen:

- A change touches SQLite schema, research schema or trade calculation
  semantics.
- A stage requires a large MainWindow rewrite instead of a small seam change.
- A new controller starts becoming another giant object.
- GUI tests fail by collection error rather than dependency skip.
- Full pytest shows a new failure unrelated to the intended seam.
- A release check finds runtime data in the clean output.

## Next action

Stop structural extraction for this hotfix. Profile real large-session replay
and analysis snapshot construction before choosing another slice. Do not
combine later decomposition with trading semantics, storage schema or research
schema changes.
