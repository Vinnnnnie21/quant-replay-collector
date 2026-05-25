from __future__ import annotations

from typing import Any


class PremiumController:
    def __init__(self) -> None:
        self.inflight = False
        self.last_status: str | None = None
        self.last_error: str | None = None

    def begin_sample(self) -> bool:
        if self.inflight:
            return False
        self.inflight = True
        return True

    def complete_sample(self, row: dict[str, Any], storage) -> None:
        self.inflight = False
        self.last_status = str(row.get("sample_status") or "ERROR")
        self.last_error = row.get("error_message")
        storage.insert_premium_sample(row)
