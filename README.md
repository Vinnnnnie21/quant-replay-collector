# Quant Replay Collector

Quant Replay Collector is a Windows desktop research app for replaying crypto K-line data and turning discretionary chart observations into structured, auditable samples.

It is built for review and research, not live execution. It does not connect to Binance order APIs, does not place trades, and does not provide investment advice.

## Screenshots

![Main replay workspace](docs/screenshots/main_ui.png)

![Research analysis workspace](docs/screenshots/analysis_workspace.png)

![Strategy consistency panel](docs/screenshots/strategy_consistency.png)

## What It Does

- Replay market data and inspect candles bar by bar.
- Record manual open/close decisions, tags and notes during replay.
- Build event windows, context features and outcome labels for later research.
- Export CSV, JSON, Markdown and Parquet research artifacts.
- Run research-only event studies, factor checks, time-series diagnostics and backtests.
- Audit whether a set of trades is internally consistent with a declared strategy profile.
- Optionally expose local read-only data through the app's API layer.

## Current Scope

- Version: `1.4.1`
- SQLite schema: `6`
- Desktop stack: PySide6, pyqtgraph, pandas, numpy
- Primary platform: Windows PowerShell
- Runtime data: local files under `quant_collector_app/data/`, `quant_collector_app/logs/` and cache/export folders

The app is intentionally local-first. Generated research output is diagnostic evidence, not a buy/sell signal.

## Install

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If the virtual environment already exists, only run the last command.

## Run

```powershell
.\.venv\Scripts\python.exe run_app.py
```

Equivalent package entry point:

```powershell
.\.venv\Scripts\python.exe -m quant_collector_app
```

## Research Workflow

```text
load/replay K-lines
  -> mark trades, events and subjective observations
  -> extract event windows and decision-time context features
  -> keep post-event outcome labels physically separate
  -> analyze, export, backtest and review consistency
```

The separation between context features and outcome labels is a core project rule. Features used for research models must only use data visible at the decision point. Forward returns, MFE, MAE, win/loss and stop/take outcomes are post-event labels for audit and reporting.

## Entry Logic Research

Entry logic research studies the user's long-entry judgment boundary. The supervised label is `human_decision`, not future return:

- `ENTRY`: the user would consider a long entry at that decision point.
- `REJECT`: the user rejects the setup.
- `UNCERTAIN`: the setup is unclear.
- `UNLABELED`: the candidate has not been reviewed and is not automatically a negative sample.

Scores such as `human_entry_similarity` and `setup_confidence` are review prioritization signals. They are not trading instructions.

## Validate

Use the project virtual environment so the checks run against the same dependencies as the desktop app:

```powershell
.\.venv\Scripts\python.exe -m compileall -q quant_collector_app tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m quant_collector_app.self_check --core
.\.venv\Scripts\python.exe scripts\clean_release.py --output dist\QuantReplayCollector-CI
.\.venv\Scripts\python.exe scripts\check_release_clean.py dist\QuantReplayCollector-CI
```

`verify_before_push.bat` runs the same release gate used before publishing.

## Clean Release Policy

`scripts/clean_release.py` builds a public source package and excludes local state:

- virtual environments
- previous `dist/` output
- local SQLite databases
- logs, caches, exports and settings
- Python cache directories
- backup folders
- local agent workflow files
- performance reports

It writes `clean_release_report.json` and `clean_release_report.md`. Run `scripts/check_release_clean.py` on the generated directory before uploading any artifact.

## Project Layout

```text
quant_collector_app/       desktop app, services, storage, research modules
quant_collector_app/views/ Qt widgets and presentation helpers
quant_collector_app/research/
                           event, entry-logic and validation research code
quant_collector_app/backtesting/
                           research-only backtest engine and strategies
quant_collector_app/storage_core/
                           SQLite migrations and repositories
scripts/                   diagnostics and clean-release tooling
tests/                     unit, integration and GUI-adjacent regression tests
docs/                      architecture, release, testing and research notes
```

## Documentation

- [Architecture](docs/architecture.md)
- [Backtesting](docs/backtesting.md)
- [Research workflow](docs/research_workflow.md)
- [Daily research workflow](docs/research_daily_workflow.md)
- [Entry logic research](docs/research_entry_logic_modeling.md)
- [Strategy consistency](docs/strategy_consistency.md)
- [Testing](docs/testing.md)
- [Release hygiene](docs/release.md)

## License

MIT. See [LICENSE](LICENSE).
