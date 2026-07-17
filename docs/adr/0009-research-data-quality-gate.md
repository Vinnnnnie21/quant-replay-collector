---
status: accepted
---

# Repair source data audibly and reject invalid research input

Quant Replay Collector may normalize raw market-data input during collection only when the repair is recorded in its data-quality report. Backtesting, statistical analysis and strategy research will reject invalid time ordering, duplicate bars, missing critical prices and non-finite numeric values because a plausible-looking result from uncertain data is worse than a clearly blocked calculation.

## Consequences

Collection remains resilient to imperfect API or cache data, while research results retain a clear trust boundary. User-facing errors must identify the offending condition and direct the user to reload or inspect the data-quality report. No research calculation may silently sort, deduplicate or fill invalid input after the quality gate.
