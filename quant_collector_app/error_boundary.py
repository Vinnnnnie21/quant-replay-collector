from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from errors import UserFacingError


T = TypeVar("T")


def run_user_action(
    action: Callable[[], T],
    *,
    logger: logging.Logger,
    fallback_message: str,
) -> tuple[T | None, str | None]:
    """Run a UI-triggered operation and return a short user-facing error."""
    try:
        return action(), None
    except UserFacingError as exc:
        logger.warning("%s: %s", fallback_message, exc, exc_info=True)
        return None, str(exc)
    except Exception:
        logger.exception(fallback_message)
        return None, fallback_message


__all__ = ["run_user_action"]
