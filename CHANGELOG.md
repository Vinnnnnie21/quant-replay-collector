# Changelog

## v1.4.0

### Added

- Dynamic timeframe switching with timestamp anchoring on the main replay chart.
- Multi-timeframe read-only context for higher-timeframe market state.
- Research dataset scaffolding for observation universe and strategy samples.
- Separate context-feature and outcome-label research paths.
- Matched baseline, behavior statistics and candidate-rule validation controls.

### Changed

- Display interval and trade-sample interval are treated separately during replay.
- Rule validation exposes FDR adjustment, purged chronological split, embargo handling and out-of-sample degradation gates.
- Version metadata and release documentation now identify the `v1.4.0` release.

### Fixed

- Changing the displayed timeframe can retain the current market-time position instead of restarting from the beginning.
- Existing trade samples are protected from silent cross-interval `bar_index` reuse.

### Research Safety

- Higher-timeframe context is read-only and is not a trading signal.
- Context features and future outcome labels remain separated to reduce leakage risk.
- Matched baseline and validation statistics are research evidence only; they do not imply future profitability.
- Quant Replay Collector does not connect to Binance order APIs, place live trades or provide investment advice.

### Release Hygiene

- Publish only output produced by `scripts/clean_release.py`.
- Run `scripts/check_release_clean.py` on that output before creating an archive or uploading a release asset.
- Do not publish a development directory containing caches, databases, logs, exports or local settings.
