---
status: accepted
---

# Preserve missing ancillary K-line data and backfill it on demand

The market-data schema stores the exchange's raw quote volume, trade count, taker-buy base volume, and taker-buy quote volume alongside OHLCV. Existing rows keep these new fields null until their original ranges are fetched again; missing values are never converted to zero. The application checks completeness for a requested research range and runs a cancellable, retryable range backfill, while data maintenance offers an explicit full-history backfill. It does not redownload all history during application startup. Replay may continue with legacy OHLCV, but any structural-similarity formula that requires the ancillary fields refuses to run until its range is complete. This adds a temporary mixed-completeness state, but preserves data truth and avoids blocking startup with an unbounded network task.
