# Release Hygiene

## v1.4.0 Release Notes

`v1.4.0` adds timestamp-anchored dynamic timeframe switching, separates display interval from trade-sample interval, and keeps higher-timeframe context read-only. The research dataset now distinguishes observation samples, context features and outcome labels, and includes matched baseline, behavior statistics and rule-validation controls.

This is a replay and research application. It does not connect to Binance order APIs, does not submit live trades and does not provide investment advice.

## Clean Package

Run from PowerShell at the repository root:

```powershell
python scripts/clean_release.py --output dist/QuantReplayCollector-v1.4.0-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-v1.4.0-Clean
```

The output contains the source package, documentation, tests, requirements and launch scripts. It includes `clean_release_report.json` and `clean_release_report.md`.

The generator does not copy virtual environments, previous distribution output, performance reports, backup folders, Python caches, local SQLite files, cache data, exported studies, log files or local settings. It does not delete those files from the working copy.

Do not upload the development repository directory, a local working tree archive, or a manually selected source folder. A release artifact must be built from the directory produced by `scripts/clean_release.py`, and `scripts/check_release_clean.py` must pass on that exact directory before packaging or upload.

## Git Tracking Policy

Runtime databases, settings, exports, cache and logs remain local. Before publishing a release, check tracked paths with Git and remove any accidentally tracked local artifacts from the index without deleting the local copy.

## GitHub Publication Flow

Do not publish a development working tree directly to `main`. Prepare a release branch, let CI verify it, then merge or tag the reviewed commit.

PowerShell verification commands:

```powershell
$env:PYTHONPATH = ".;quant_collector_app"
python -m compileall quant_collector_app scripts
python -m pytest -q
python quant_collector_app/self_check.py --core
python scripts/clean_release.py --output dist/QuantReplayCollector-v1.4.0-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-v1.4.0-Clean
```

Inspect local-only files before staging:

```powershell
git status --ignored --short
git ls-files -- ".venv/**" "**/__pycache__/**" ".pytest_cache/**" "dist/**" "performance_reports/**" "quant_collector_app/data/**" "quant_collector_app/logs/**" "Backup/**" ".codex-backups/**" "backup_old/**" "*.zip"
```

The second command must produce no tracked runtime data, archives, caches, logs, backups or database files.

Publish through a branch:

```powershell
git switch -c release/v1.4.0
git add .gitignore .github README.md docs quant_collector_app requirements.txt run_app.py scripts start.bat tests
git status --short
git commit -m "Prepare v1.4.0 release metadata and documentation"
git push -u origin release/v1.4.0
```

Open a pull request to `main`. GitHub Actions will run compilation, tests, the core health check, build a downloadable clean artifact and reject contaminated output. Create a GitHub Release from the reviewed merge commit or a release tag, and upload the checked clean artifact rather than the development directory.

For a manually uploaded archive, package only the checked output:

```powershell
Compress-Archive -Path dist/QuantReplayCollector-v1.4.0-Clean/* -DestinationPath QuantReplayCollector-v1.4.0-Clean.zip -Force
```
