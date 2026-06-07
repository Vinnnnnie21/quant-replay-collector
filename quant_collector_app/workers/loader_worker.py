from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6 import QtCore

try:
    from app_config import CACHE_DIR
    from app_logger import get_logger
    from market_data.client import format_request_error
    from market_data.loader import KlineLoader
    from market_data.types import LoadRequest
except ImportError:  # pragma: no cover - package import path
    from ..app_config import CACHE_DIR
    from ..app_logger import get_logger
    from ..market_data.client import format_request_error
    from ..market_data.loader import KlineLoader
    from ..market_data.types import LoadRequest


logger = get_logger(__name__)


class LoaderWorker(QtCore.QObject):
    started = QtCore.Signal()
    finished = QtCore.Signal(object, str)
    progress = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(self, cache_dir: Path | str = CACHE_DIR):
        super().__init__()
        self.kline_loader = KlineLoader(cache_dir)
        self._abort = False

    @QtCore.Slot()
    def abort(self):
        self._abort = True

    @QtCore.Slot(object)
    def load(self, request: LoadRequest):
        self._abort = False
        self.started.emit()
        try:
            frame, message = self.kline_loader.load(
                request,
                progress=self.progress.emit,
                cancelled=lambda: self._abort,
            )
            if self._abort or message == "Loading cancelled.":
                self.cancelled.emit()
            self.finished.emit(frame, message)
        except Exception as exc:
            logger.exception("Kline loading failed.")
            message = f"加载失败：{format_request_error(exc)}"
            self.failed.emit(message)
            self.finished.emit(pd.DataFrame(), message)


__all__ = ["LoaderWorker"]
