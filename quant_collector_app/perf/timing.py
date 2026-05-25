from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class PerfTimer:
    name: str
    sink: Callable[[str, float], None] | None = None
    elapsed_seconds: float = 0.0

    def __enter__(self):
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.elapsed_seconds = time.perf_counter() - self._started
        if self.sink is not None:
            self.sink(self.name, self.elapsed_seconds)
        return False
