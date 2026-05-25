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
- `views.candlestick_item`, `views.volume_item`, `views.chart_axis` and `views.k_view_box` own pyqtgraph display objects. `workers.loader_worker` owns the Qt loading bridge.
- The `market_data` package exports the previous public names for compatibility and imports GUI classes only when those names are requested.
- `ReplayController`, `TradeController`, `PremiumController` and `ExportController` contain already separated business boundaries retained during incremental migration.
- `AppState` defines task and session state shapes while existing UI fields remain in place during incremental migration.
- `views.chart_view.visible_bar_bounds()` isolates large-history plot slicing from Qt widgets.
- `workers.export_worker.ExportWorker` runs export/report generation off the UI thread.
- `services.market_data_service.MarketDataService` coordinates kline loading without Qt dependencies.
- `services.export_service.ExportService` and `services.analysis_service.AnalysisService` delay exporter and research imports until work is requested.
- `research` answers questions about annotated event samples; `time_series_analysis` answers questions about market-series distribution, dependence, volatility and tail risk. Their reports and UI tabs are separate.
- `i18n.py` loads research and time-series display strings from JSON resources while CSV/JSON export keys remain language-independent.

## Background Tasks

Kline loading continues through `LoaderWorker` on a `QThread`, with progress and lifecycle signals. Export uses a separate worker. Network, parsing, validation and report generation do not need to execute inside paint or button event handlers.

## Scope Limit

`main_app.py` remains large because UI layout, trade commands and table refresh wiring have not been rewritten. This release separates market data and research presentation boundaries but does not claim that the window class has reached its target size. Further extraction needs GUI workflow coverage first.
