---
status: accepted
---

# Protect local research data with daily retention and atomic writes

Quant Replay Collector will retain 14 daily local database backups, create an additional backup before a database upgrade, and write settings atomically. We choose bounded local recovery over cloud synchronization because this is a personal desktop research tool and its data should remain local while still being recoverable after an interrupted write, upgrade failure or accidental change.

## Consequences

The application must report backup failures without hiding them, retain the newest 14 daily backups, and explain local disk use in user-facing settings or diagnostics. SQLite remains the authoritative research store; settings files must retain either their previous complete content or their complete new content.
