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
