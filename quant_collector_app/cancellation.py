from __future__ import annotations

import threading


class CancellationToken:
    """Small thread-safe flag shared without crossing QObject affinity."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    def is_requested(self) -> bool:
        return self._event.is_set()


__all__ = ["CancellationToken"]
