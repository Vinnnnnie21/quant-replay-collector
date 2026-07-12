---
status: accepted
---

# Use a range-aware disk cache for market data

Market data will be cached by symbol and candle interval as time coverage rather than only by an exact requested start/end pair. A request fully covered by local data reads and slices that data without network access. A partially covered request downloads only missing intervals, then normalizes, merges, deduplicates, sorts, and validates continuity before making the result available.

## Consequences

Disk is the durable cache; memory holds only the active working window and bounded temporary merge data. Cache metadata must record covered intervals and support atomic updates so an interrupted download cannot mark a gap as complete. Overlapping candles are resolved deterministically, using the newly downloaded validated row when timestamps match. Cache files use a configurable size limit that defaults to 5 GB and least-recently-used cleanup, but data required by the current session cannot be evicted while in use.

The loader must distinguish complete cache hits, partial hits, and misses in its result metadata and data-quality reporting. Existing exact-range cache files remain readable and may be incorporated into the coverage index rather than being discarded.
