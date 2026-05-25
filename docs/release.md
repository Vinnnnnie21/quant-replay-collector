# Release Hygiene

## Clean Package

Run from PowerShell at the repository root:

```powershell
python scripts/clean_release.py --output dist/QuantReplayCollector-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-Clean
```

The output contains the source package, documentation, tests, requirements and launch scripts. It includes `clean_release_report.json` and `clean_release_report.md`.

The generator does not copy virtual environments, previous distribution output, performance reports, backup folders, Python caches, local SQLite files, cache data, exported studies, log files or local settings. It does not delete those files from the working copy.

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
python scripts/clean_release.py --output dist/QuantReplayCollector-Clean
python scripts/check_release_clean.py dist/QuantReplayCollector-Clean
```

Inspect local-only files before staging:

```powershell
git status --ignored --short
git ls-files -- ".venv/**" "**/__pycache__/**" ".pytest_cache/**" "dist/**" "performance_reports/**" "quant_collector_app/data/**" "quant_collector_app/logs/**" "Backup/**" ".codex-backups/**" "backup_old/**" "*.zip"
```

The second command must produce no tracked runtime data, archives, caches, logs, backups or database files.

Publish through a branch:

```powershell
git switch -c codex/research-localization-time-series-release
git add .gitignore .github README.md docs quant_collector_app requirements.txt run_app.py scripts start.bat tests
git status --short
git commit -m "Prepare research localization and time-series release"
git push -u origin codex/research-localization-time-series-release
```

Open a pull request to `main`. GitHub Actions will run compilation, tests, the core health check, build a downloadable `QuantReplayCollector-Clean` artifact and reject contaminated output. Create a GitHub Release from the reviewed merge commit or a release tag, and upload the CI clean artifact rather than the development directory.

For a manually uploaded archive, package only the checked output:

```powershell
Compress-Archive -Path dist/QuantReplayCollector-Clean/* -DestinationPath QuantReplayCollector-Clean.zip -Force
```
