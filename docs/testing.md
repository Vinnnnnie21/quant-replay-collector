# Testing

Quant Replay Collector is developed and validated as a Windows desktop application.

## PowerShell Validation

Run from the repository root:

```powershell
python -m compileall quant_collector_app scripts
python -m pytest -q
python quant_collector_app/self_check.py --core
python -m quant_collector_app.self_check --core
python scripts/profile_startup.py
python scripts/profile_imports.py
python scripts/clean_release.py --output dist/QuantReplayCollector-v1.6.0-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-v1.6.0-Clean
```

`self_check --core` and `--all` use temporary databases and do not open the
application database. To audit a database copy, pass it explicitly with
`--database <path>`; `--backup-database` also requires that explicit path.

The default suite disables pytest's reusable cache and assigns every process a
new `.test-artifacts/pytest-tmp-run-<pid>-<uuid>` base directory. This avoids
reopening or recursively deleting a previous Windows run whose inherited ACL
may no longer be usable. CI and one-off diagnostics can still pass an explicit
`--basetemp`; that choice is preserved. `.test-artifacts` is local-only and is
excluded from release packages. `python scripts/cleanup_test_artifacts.py` is
dry-run by default; pass `--apply` only after reviewing the known pytest paths
it reports. The cleanup command refuses symbolic links and Windows junctions.

`PySide6` and `pyqtgraph` are required for full desktop startup and GUI import checks. Tests that specifically need unavailable GUI dependencies should skip rather than fail in a reduced environment.

When GUI dependencies are installed, also run:

```powershell
python quant_collector_app/self_check.py --gui
python quant_collector_app/self_check.py --all
python scripts/profile_startup.py
```

## Release Data Policy

The clean release generator copies application source, documentation, tests, declared dependencies and launchers. It excludes local databases, cache, exports, logs, settings, virtual environments, backup directories, compiled Python files, performance reports and prior build output. It does not remove any local user data.
