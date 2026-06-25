# Release Hygiene

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
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-v1.4.1-Clean
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-v1.4.1-Clean
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
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-v1.4.1-Clean
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-v1.4.1-Clean
```

Inspect local-only files before staging:

```powershell
git status --ignored --short
git ls-files -- ".venv/**" "**/__pycache__/**" ".pytest_cache/**" "dist/**" "performance_reports/**" "quant_collector_app/data/**" "quant_collector_app/logs/**" "Backup/**" ".codex-backups/**" "backup_old/**" "*.zip"
```

The second command must produce no tracked runtime data, archives, caches, logs, backups or database files.

Publish through a branch:

```powershell
git switch -c release/v1.4.1
git add .gitignore .github README.md docs quant_collector_app requirements.txt run_app.py scripts start.bat tests
git status --short
git commit -m "Prepare v1.4.1 hotfix release"
git push -u origin release/v1.4.1
```

Open a pull request to `main`. GitHub Actions will run compilation, tests, the core health check, build a downloadable clean artifact and reject contaminated output. Create a GitHub Release from the reviewed merge commit or a release tag, and upload the checked clean artifact rather than the development directory.

For a manually uploaded archive, package only the checked output:

```powershell
Compress-Archive -Path dist/QuantReplayCollector-v1.4.1-Clean/* -DestinationPath QuantReplayCollector-v1.4.1-Clean.zip -Force
```
