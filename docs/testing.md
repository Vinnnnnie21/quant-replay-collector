# Testing

Quant Replay Collector is developed and validated as a Windows desktop application.

## PowerShell Validation

Run from the repository root:

```powershell
$env:PYTHONPATH = ".;quant_collector_app"
python -m compileall quant_collector_app scripts
python -m pytest -q
python quant_collector_app/self_check.py --core
python scripts/profile_startup.py
python scripts/profile_imports.py
python scripts/clean_release.py --output dist/QuantReplayCollector-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-Clean
```

`PySide6` and `pyqtgraph` are required for full desktop startup and GUI import checks. Tests that specifically need unavailable GUI dependencies should skip rather than fail in a reduced environment.

When GUI dependencies are installed, also run:

```powershell
python quant_collector_app/self_check.py --gui
python quant_collector_app/self_check.py --all
python scripts/profile_startup.py
```

## Release Data Policy

The clean release generator copies application source, documentation, tests, declared dependencies and launchers. It excludes local databases, cache, exports, logs, settings, virtual environments, backup directories, compiled Python files, performance reports and prior build output. It does not remove any local user data.
