from __future__ import annotations

from collections.abc import Callable


class ResearchCancelled(RuntimeError):
    """A randomized research task stopped cooperatively at a safe boundary."""


def raise_if_research_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ResearchCancelled("research calculation cancelled at a safe batch boundary")


__all__ = ["ResearchCancelled", "raise_if_research_cancelled"]
