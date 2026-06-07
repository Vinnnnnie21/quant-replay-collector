# Desktop Architecture

## Startup Path

`run_app.py` and `python -m quant_collector_app` dispatch to `main_app.main()`. Startup explicitly creates runtime directories and configures rotating logging. Importing configuration, logging or the readonly API module does not initialize storage as a side effect.

Heavy user tools are lazy:

- `AnalysisWorkspace`, `BacktestPanel` and `StrategyConsistencyPanel` are loaded when the analysis window is opened.
- `Exporter` and its analysis/report dependencies are loaded when an export task is started.
- The readonly API creates its `StorageManager` on the first data request.
- `scripts/profile_startup.py` verifies the deferred optional-module list instead of assuming that imports stayed lazy.

## Boundaries

- `market_data.client`, `market_data.cache`, `market_data.loader`, `market_data.quality`, `market_data.transforms` and `market_data.features` are non-GUI market-data modules.
- `views.main_window_layout` owns the static MainWindow widget tree and shortcut
  construction; `views.main_window_presentation` applies translations and
  themes; `views.main_window_connections` owns Qt table setup, shortcut guards
  and signal wiring. `views.candlestick_item`, `views.volume_item`,
  `views.chart_axis` and `views.k_view_box` own pyqtgraph display objects.
  `workers.loader_worker` owns the Qt loading bridge.
- The `market_data` package exports the previous public names for compatibility and imports GUI classes only when those names are requested.
- `ReplayController`, `TradeController`, `PremiumController` and `ExportController` contain already separated business boundaries retained during incremental migration.
- `presenters.formatters`, `presenters.table_presenter` and
  `presenters.status_presenter` own display formatting, Qt table population and
  lightweight status/chart presentation without reading SQLite or changing
  trade state.
- `services.trade_use_cases.TradeUseCase` owns Qt-free open/close transaction orchestration while `MainWindow` retains button handling, pause behavior and UI result application.
- `services.session_service` and `services.export_service` construct session and export requests without owning Qt widgets.
- `StorageManager` remains the compatible public storage API while `storage_core` repositories own migrations and domain SQL.
- `AppState` defines task and session state shapes while existing UI fields remain in place during incremental migration.
- `render_state.RenderState`, `render.chart_render_plan`,
  `render.chart_render_adapter`, `render.visible_window` and
  `render.marker_renderer` isolate dirty flags, viewport decisions, Qt chart
  application, large-history plot slicing and cached marker payload
  calculation from MainWindow.
- `workers.export_worker.ExportWorker` runs export/report generation off the UI thread.
- `workers.analysis_refresh_worker.AnalysisRefreshWorker` runs event-study, dataset-summary and performance-summary calculations off the UI thread. Results are delivered to explicit queued `MainWindow` slots before widgets are updated.
- `controllers.analysis_controller.AnalysisRefreshController` owns analysis
  debounce, playback deferral, worker lifecycle and coalescing of requests that
  arrive during a running refresh.
- `controllers.export_task_controller.ExportTaskController` owns asynchronous
  export-worker and QThread lifecycle; `MainWindow` keeps export UI feedback.
- `controllers.market_data_controller` owns market parameter keys, dynamic
  timeframe-switch orchestration and load-result application while MainWindow
  keeps the existing signal-slot surface.
- `controllers.replay_ui_controller` owns replay timer and control
  orchestration over `ReplayController`; `controllers.trade_action_controller`
  owns manual open/close and undo/redo UI orchestration over `TradeUseCase`.
- `controllers.trade_record_controller` owns the destructive clear-records
  confirmation flow.
- `services.market_data_service.MarketDataService` coordinates kline loading without Qt dependencies.
- `services.export_service.ExportService` and `services.analysis_service.AnalysisService` delay exporter and research imports until work is requested.
- `research` answers questions about annotated event samples; `time_series_analysis` answers questions about market-series distribution, dependence, volatility and tail risk. Their reports and UI tabs are separate.
- `i18n.py` loads research and time-series display strings from JSON resources while CSV/JSON export keys remain language-independent.

## Background Tasks

Kline loading continues through `LoaderWorker` on a `QThread`, with progress and lifecycle signals. Export and deferred heavy analysis use separate workers. Network, parsing, validation and report generation do not need to execute inside paint or button event handlers. Qt widgets are updated only on the main thread.

## Scope Limit

`main_app.py` is now below 1,200 lines. It remains the Qt shell and keeps public
slot wrappers, initialization, dialogs and result application, while static
layout, presentation, market loading, replay control, manual trade actions,
rendering and heavy analysis scheduling live behind focused modules. It has
reached the stage target, but not the optional long-term ideal of roughly 800
lines.
