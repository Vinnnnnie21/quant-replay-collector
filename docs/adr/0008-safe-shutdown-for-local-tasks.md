---
status: accepted
---

# Prefer safe shutdown over immediate process exit

When a user closes Quant Replay Collector while it is loading market data, exporting, or running local analysis, the application will show that it is safely saving or stopping the task and will exit only after that work reaches a safe stopping point. We reject default force termination because it can leave a Qt worker running or leave local research data incomplete; a short delay during shutdown is preferable to a crash or lost data.

## Consequences

Background tasks need a cooperative cancellation path, bounded waits, and a completion signal. Persistent writes must leave either the previous complete file or a complete new file. The close flow must remain responsive while waiting and must report unusually slow shutdown rather than silently destroying an active worker. Market-data loading, export, analysis refresh, premium sampling and multi-timeframe loading will share a small lifecycle of running, stop requested, completed and failed; this is intentionally not a general-purpose task scheduler.
