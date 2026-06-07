from __future__ import annotations

import threading
import time
from functools import wraps
from typing import Callable


def throttle(func: Callable, interval_ms: int) -> Callable:
    interval = max(0.0, float(interval_ms) / 1000.0)
    last_call = -float("inf")
    lock = threading.Lock()

    @wraps(func)
    def wrapped(*args, **kwargs):
        nonlocal last_call
        now = time.monotonic()
        with lock:
            if now - last_call < interval:
                return None
            last_call = now
        return func(*args, **kwargs)

    return wrapped


def debounce(func: Callable, wait_ms: int) -> Callable:
    """Debounce plain Python callbacks.

    This uses ``threading.Timer``. Do not use it to update Qt widgets; Qt UI
    refreshes must stay on the main thread via ``QTimer`` or queued signals.
    """

    wait = max(0.0, float(wait_ms) / 1000.0)
    timer: threading.Timer | None = None
    lock = threading.Lock()

    @wraps(func)
    def wrapped(*args, **kwargs):
        nonlocal timer
        with lock:
            if timer is not None:
                timer.cancel()
            timer = threading.Timer(wait, func, args=args, kwargs=kwargs)
            timer.daemon = True
            timer.start()
        return timer

    return wrapped
