# Performance Diagnostics

Quant Replay Collector is a desktop research tool. Performance work targets replay responsiveness and research task isolation, not live execution.

## Profile Commands

Run from the repository root in PowerShell:

```powershell
python scripts/profile_startup.py
python scripts/profile_imports.py
python scripts/profile_runtime.py
```

Reports are written under `performance_reports/`.

- `startup_profile.json` and `startup_profile.md` measure Qt application creation, configuration/theme load, temporary SQLite initialization, main-window construction and first render.
- The startup profile also records runtime-directory initialization, logging initialization and whether optional analysis/API/export modules remained deferred.
- `import_profile.json` and `import_profile.md` execute key module imports in separate Python processes.
- `runtime_profile.json` and `runtime_profile.md` measure chart item preparation for 1,000, 10,000 and 50,000 synthetic bars.

The startup probe uses a temporary database and disables premium sampling during window construction. It does not modify the user's research database.

## Runtime Controls

- The replay timer uses an 8 ms interval; chart work remains dirty-flagged and
  is separately throttled to 8 ms during direct interaction or 50 ms during
  playback.
- GPU chart rendering is the default. The Storage settings tab exposes a
  software-rendering compatibility mode for driver diagnosis; OpenGL startup
  failures fall back automatically.
- Chart refresh uses a dirty flag.
- Histories over 2,000 bars prepare only the visible range plus a margin.
- Export and research-pack generation initiated from the UI run in `ExportWorker`.
- Kline HTTP, cache parsing and data-quality work run through `LoaderWorker`; pure loader code does not import Qt.

The profile scripts deliberately report unavailable dependencies and headless Qt failures as report data. That distinction matters in CI and on fresh Windows installations.

## v1.6 decision-research reference budgets

The release gate uses a six-month one-minute reference size of 270,000 market
positions. `tests/test_v16_decision_research_benchmark.py` freezes these Windows
Python 3.13 wall-time ceilings: structural candidate scan 5 seconds, behavior
training 30 seconds, full 15-cell matched inference 15 seconds, immutable
snapshot report publication 5 seconds, and cooperative cancellation 1 second.
The benchmark uses 100 balanced behavior samples, 30 matched pairs across 10
episodes, the specified 5,000 bootstrap and 10,000 sign-flip draws, and the
complete Markdown/JSON/CSV/PNG snapshot package.

## v1.6.0-rc.2 startup and package measurements

Measured on Windows 11, Python 3.13.3, PySide6/Qt 6.11.1. Runtime data was redirected with `QRC_RUNTIME_ROOT` to an isolated empty directory; premium sampling was disabled for source profiling. Times are wall-clock seconds unless noted.

| Measurement | rc.1 baseline | rc.2 result |
| --- | ---: | ---: |
| `main_app` cold import | 2.289 | 2.229 |
| Source startup probe, full process | 3.745 | 3.441 |
| Data-analysis import chain | 5.345 | 0.209 |
| Data-analysis shell construction | 0.078 | 0.386 |
| Data-analysis open, including first import | 5.443 | 0.675 |
| Decision-research tab activation after shell | — | 0.011 |

The analysis shell is much faster and no longer loads `scipy` or `sklearn`, but the combined first import and construction is still about 175 ms above the aspirational 500 ms target on this machine. The raw measurement is retained rather than weakening the target.

PyInstaller comparison used identical source and dependency inputs:

| Format | Size | Cold complete-process time | Warm complete-process time | Warm interactive milestone |
| --- | ---: | ---: | ---: | ---: |
| onedir | 369,422,500 bytes | 6.483 | 5.694 / 5.482 | 2.816 / 2.682 |
| onefile | 147,854,660 bytes | 15.391 | 15.209 | 3.140 after extraction |

The complete-process measurement includes the fixed 1.2-second smoke window and cooperative shutdown, so the format comparison is more useful than its absolute value. onefile pays roughly eight seconds of extraction/process overhead on every run. rc.2 therefore ships as onedir. The two warm onedir interactive measurements have a median of 2.749 seconds, within the 3-second warm-interactive budget.

A separate 50 ms process-family sample recorded a 371.9 MiB peak working set
for the final onedir package and 385.4 MiB for the onefile reference. The
process-family total is used because the onefile bootloader starts a second
same-name process after extraction.

Reproduce source measurements with `scripts/profile_startup.py` and `scripts/profile_imports.py`. Enable application milestones with `QRC_STARTUP_TIMING=1` and set `QRC_STARTUP_TIMING_FILE` to a writable diagnostic path. Packaged smoke tests additionally set `QRC_NATIVE_SMOKE_EXIT_MS` and an isolated `QRC_RUNTIME_ROOT`.

## v1.6.0 formal release measurements

Measured on 2026-07-21 with the locked Windows 11 / CPython 3.13 environment.
The complete performance-marked suite passed in 328.41 seconds (330.419 seconds
outer wall time). The decision-research reference case produced:

| Task | Result | Frozen ceiling |
| --- | ---: | ---: |
| Structural candidate scan, 270,000 positions | 0.9105 s | 5 s |
| Elastic-net behavior training | 0.0402 s | 30 s |
| Complete 15-cell matched inference | 0.0654 s | 15 s |
| Immutable snapshot publication | 0.0794 s | 5 s |
| Cooperative cancellation | 0.1250 s | 1 s |

The Qt native lifecycle subprocess passed separately in 71.39 seconds. A fresh
source startup profile completed in 2.713 seconds wall time; the cold probe was
2.340 seconds and main-window construction was 0.568 seconds. All 19 profiled
module imports succeeded.
