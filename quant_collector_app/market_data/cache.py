from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .quality import DataQualityReport
from .transforms import normalize_kline_df
from .types import LoadRequest, make_bjt


class KlineCache:
    def __init__(self, cache_dir: Path | str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path(self, symbol: str, interval: str, request: LoadRequest) -> Path:
        return self.cache_dir / (
            f"{symbol}_{interval}_{request.start_dt_bjt.strftime('%Y%m%d')}_"
            f"{request.end_dt_bjt.strftime('%Y%m%d')}_bjt.csv"
        )

    @staticmethod
    def manifest_path(cache_path: Path) -> Path:
        return cache_path.with_suffix(".manifest.json")

    def read(self, cache_path: Path, request: LoadRequest, interval: str) -> tuple[pd.DataFrame, dict[str, int]]:
        try:
            raw_df = pd.read_csv(cache_path)
            return normalize_kline_df(
                raw_df,
                request.start_dt_bjt,
                request.end_dt_bjt,
                interval,
                f"Cache {cache_path.name}",
            )
        except Exception as exc:
            raise ValueError(f"Cache read failed for {cache_path.name}: {exc}") from exc

    def write_frame(self, cache_path: Path, frame: pd.DataFrame) -> None:
        frame.to_csv(cache_path, index=False)

    def write_manifest(
        self,
        cache_path: Path,
        request: LoadRequest,
        symbol: str,
        interval: str,
        report: DataQualityReport,
    ) -> None:
        manifest = {
            "symbol": symbol,
            "interval": interval,
            "start_time_bjt": make_bjt(request.start_dt_bjt).isoformat(timespec="seconds"),
            "end_time_bjt": make_bjt(request.end_dt_bjt).isoformat(timespec="seconds"),
            "row_count": report.actual_bars,
            "created_at": report.created_at,
            "source": report.source,
            "quality_report": report.to_dict(),
        }
        self.manifest_path(cache_path).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_manifest(self, cache_path: Path) -> dict | None:
        path = self.manifest_path(cache_path)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cache manifest read failed for {path.name}: {exc}") from exc


__all__ = ["KlineCache"]
