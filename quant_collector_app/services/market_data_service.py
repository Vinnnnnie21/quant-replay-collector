from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

try:
    from app_config import CACHE_DIR
    from market_data.client import MarketDataClient
    from market_data.loader import KlineLoader
    from market_data.types import LoadRequest
except ImportError:  # pragma: no cover - package import path
    from ..app_config import CACHE_DIR
    from ..market_data.client import MarketDataClient
    from ..market_data.loader import KlineLoader
    from ..market_data.types import LoadRequest


class MarketDataService:
    """Application-facing orchestration for kline loading without Qt dependencies."""

    def __init__(self, cache_dir: Path | str = CACHE_DIR, client: MarketDataClient | None = None):
        self.loader = KlineLoader(cache_dir, client)

    def load_klines(
        self,
        request: LoadRequest,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[pd.DataFrame, str]:
        return self.loader.load(request, progress=progress, cancelled=cancelled)


__all__ = ["MarketDataClient", "MarketDataService", "KlineLoader", "LoadRequest"]
