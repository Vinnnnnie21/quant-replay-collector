# Release Hygiene

## v1.5.2 Release Notes

`v1.5.2` is a language-consistency hotfix. Chinese mode now uses Chinese interface text and English mode uses English interface text throughout replay, analysis, settings and backtest views. Dynamic status, progress, validation, warning and table text is translated through the same resources, and English no longer falls back to Chinese for a missing key.

The Windows executable now bundles `translations/zh_CN.json` and `translations/en_US.json`, preventing packaged builds from displaying raw keys such as `trading_replay` or `trade_actions`. Canonical technical identifiers such as symbols, intervals, API names and stored enum values remain unchanged. This release does not change trading, replay, accounting, SQLite data, saved sessions or research algorithms.

Clean release commands:

```powershell
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-v1.5.2-Clean
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-v1.5.2-Clean
```

## v1.5.1 Release Notes

`v1.5.1` hardens the existing local research workflow. It adds cooperative safe shutdown, atomic settings, bounded daily and pre-migration backups, strict research data-quality gates, reproducible randomized statistics, resource budgets and measured 270,000-bar performance coverage. It does not add live trading or change simulated execution, fees, slippage, PnL, backtesting, research features or future-data isolation.

Large exports are now chunked, cancellable and published as a recoverable directory transaction so a cancelled re-export cannot contaminate an earlier successful export. Multi-timeframe and analysis work use single-flight or revision-based stale-result protection. Analysis rendering consumes a bounded worker payload, and one-point equity/PnL curves plus empty or replay-deferred states are visible in the chart.

Analysis, export and daily-backup shutdown is non-blocking on the Qt thread: task state is finalized only after the underlying `QThread.finished` signal. Historical performance reads are revisioned background work, and the performance trade table uses bounded 200-row pages. Both self-check entry modes use the formal entry-logic report writer; a calculation failure is reported as a failed export rather than replaced with a fallback success report.

The supported release target is Windows x64 with Python 3.13. CI now validates that runtime and installs the exact versions in `requirements-lock.txt`.

Clean release commands:

```powershell
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-v1.5.1-Clean
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-v1.5.1-Clean
```

### Windows desktop entry

`quant_collector_app\build_windows.bat` produces `quant_collector_app\dist\QRC.exe`. From the release root, create the current user's `QRC.lnk` desktop shortcut with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\create_desktop_shortcut.ps1 -TargetPath .\quant_collector_app\dist\QRC.exe
```

The explicit `ExecutionPolicy Bypass` applies only to this script process and does not change the user's PowerShell policy. Add `-DryRun` to print the resolved shortcut, target, working directory and icon without creating a `.lnk` file. The script needs no administrator rights, does not write the registry and accepts explicit `-TargetPath`, `-DesktopPath`, `-IconPath` and `-ShortcutName` parameters. The application window selects `quant_collector_app/assets/app_logo.png` for dark themes and `quant_collector_app/assets/app_logo_light.png` for light themes. `quant_collector_app/assets/app_icon.ico` is the fixed Windows executable and shortcut icon generated from the dark-theme logo. If the icon is removed, shortcut creation still falls back to the executable's default icon.

Regenerate the multi-size icon after replacing the PNG source:

```powershell
.\.venv\Scripts\python.exe scripts\generate_app_icon.py --source quant_collector_app\assets\app_logo.png --output quant_collector_app\assets\app_icon.ico
```

## v1.5.0 Release Notes

`v1.5.0` expands the local replay workspace into a usable simulated trading and funds-management workflow while preserving the project's research boundary. It adds exchange-style free chart navigation, explicit follow-latest framing, `0.1x` to `10x` playback stops, keyboard speed control, an axis-based current-price badge and OpenGL acceleration with software fallback. The target Windows system passed the 120 Hz frame-time budget during physical display validation.

Replay trading now supports session-level initial equity, per-trade notional, fees, slippage and optional TP/SL settings. Every open action creates an independent position. Manual close uses the selected position or FIFO fallback, automatic TP/SL scans bars only when replay moves forward, and manual trade actions preserve playback and follow-latest state.

The performance workspace adds continuous account equity including unrealized PnL, signed equity and cumulative-PnL curves, account metrics, closed-trade details, red/green PnL presentation and a labeled realized-PnL distribution. Chart rendering now uses chunked candle and volume pictures, active dragging avoids full application rebuilds, and TP/SL no longer converts the complete market dataframe on every timer tick.

SQLite schema version `6` remains current and existing sessions remain readable. This release does not connect to exchange order APIs, place live trades or provide investment advice.

Clean release commands:

```powershell
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-v1.5.0-Clean --release-version 1.5.0
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-v1.5.0-Clean
```

## v1.4.1 Hotfix Notes

`v1.4.1` is a focused stability, engineering-hygiene, backtesting and entry-logic research hotfix for the v1.4 line. It reduces main-thread work during high-speed playback plus manual trade actions, limits premium chart reads to recent samples, adds a background UI freeze watchdog, and avoids redundant chart and multi-timeframe context refreshes.

It also adds a research-only Deep V backtesting workflow with `StrategyRuleParams`, selected historical date ranges, analysis-to-backtest parameter mapping, `BacktestService`, `BacktestController`, result presentation and descriptive manual-vs-rule comparison. The backtest panel therefore has new parameter, date-range and result controls; this is a functional addition, not a cosmetic redesign.

Entry logic research adds a separate study layer for learning the user's long-entry judgment boundary. It uses `human_decision` labels (`ENTRY`, `REJECT`, `UNCERTAIN`, `UNLABELED`), decision-time context features, isolated post-event outcome labels, chronological/walk-forward validation with purge and embargo, pandas/numpy prototype and PU-style scoring, active review queues, optional exports and Markdown/JSON reports. Scores such as `human_entry_similarity` and `setup_confidence` are similarity diagnostics, not buy/sell signals.

This release does not change manual trading semantics or live-trading behavior. SQLite migrations are append-only: schema version `6` adds `entry_annotations` while preserving existing sessions and old tables. Existing CSV, JSON, Markdown and Parquet exports remain available; entry logic files are optional additions. Quant Replay Collector remains a local replay and research tool; it does not connect to Binance order APIs, submit live trades or provide investment advice. Historical simulations and entry logic outputs are research diagnostics and do not predict future returns.

Internal stabilization work moved table presentation, trade transaction
orchestration, visible-window and marker calculations, session/export request
construction, and storage SQL behind focused modules. Heavy analysis
calculations run in a worker and return through queued Qt slots before widgets
are updated. `main_app.py` remains a large Qt coordination shell; v1.4.1 does
not claim that its final decomposition is complete.

Clean release commands:

```powershell
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-v1.4.1-Clean
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-v1.4.1-Clean
```

## v1.4.0 Release Notes

`v1.4.0` adds timestamp-anchored dynamic timeframe switching, separates display interval from trade-sample interval, and keeps higher-timeframe context read-only. The research dataset now distinguishes observation samples, context features and outcome labels, and includes matched baseline, behavior statistics and rule-validation controls.

This is a replay and research application. It does not connect to Binance order APIs, does not submit live trades and does not provide investment advice.

## Clean Package

Run from PowerShell at the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-v1.5.2-Clean
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-v1.5.2-Clean
```

The output contains the source package, public documentation, tests, requirements and launch scripts. It includes `clean_release_report.json` and `clean_release_report.md`. The default public reports omit local absolute paths and individual skipped file names.

The generator does not copy virtual environments, previous distribution output, performance reports, backup folders, Python caches, local SQLite files, cache data, exported studies, log files, local settings or local agent workflow directories such as `.agents/`, `.scratch/` and `docs/agents/`. It does not delete those files from the working copy.

Do not upload the development repository directory, a local working tree archive, or a manually selected source folder. A release artifact must be built from the directory produced by `scripts/clean_release.py`, and `scripts/check_release_clean.py` must pass on that exact directory before packaging or upload.

## Git Tracking Policy

Runtime databases, settings, exports, cache and logs remain local. Before publishing a release, check tracked paths with Git and remove any accidentally tracked local artifacts from the index without deleting the local copy.

## GitHub Publication Flow

Do not publish a development working tree directly to `main`. Prepare a release branch, let CI verify it, then merge or tag the reviewed commit.

PowerShell verification commands. Use the project virtual environment so release validation does not accidentally run against an incomplete system Python:

```powershell
.\.venv\Scripts\python.exe -m compileall -q quant_collector_app tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m quant_collector_app.self_check --core
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-v1.5.2-Clean
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-v1.5.2-Clean
```

Inspect local-only files before staging:

```powershell
git status --ignored --short
git ls-files -- ".venv/**" "**/__pycache__/**" ".pytest_cache/**" "dist/**" "performance_reports/**" "quant_collector_app/data/**" "quant_collector_app/logs/**" "Backup/**" ".codex-backups/**" "backup_old/**" "*.zip"
```

The second command must produce no tracked runtime data, archives, caches, logs, backups or database files.

Publish through a branch:

```powershell
git switch -c release/v1.5.2
git add .gitignore .github README.md CHANGELOG.md docs quant_collector_app requirements.txt requirements-lock.txt run_app.py run_app.pyw scripts start.bat tests
git status --short
git commit -m "Prepare v1.5.2 release"
git push -u origin release/v1.5.2
```

Open a pull request to `main`. GitHub Actions will run compilation, tests, the core health check, build a downloadable clean artifact and reject contaminated output. Create a GitHub Release from the reviewed merge commit or a release tag, and upload the checked clean artifact rather than the development directory.

For a manually uploaded archive, package only the checked output:

```powershell
Compress-Archive -Path dist/QuantReplayCollector-v1.5.2-Clean/* -DestinationPath QuantReplayCollector-v1.5.2-Clean.zip -Force
```
