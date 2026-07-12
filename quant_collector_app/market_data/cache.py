from __future__ import annotations

import json
import os
import datetime as dt
from pathlib import Path

import pandas as pd

from .quality import DataQualityReport
from .transforms import normalize_kline_df
from .types import LoadRequest, interval_to_ms, make_bjt


DEFAULT_CACHE_LIMIT_BYTES = 5 * 1024**3


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
        temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
        frame.to_csv(temporary, index=False)
        os.replace(temporary, cache_path)

    def candidate_paths(self, symbol: str, interval: str) -> list[Path]:
        return sorted(self.cache_dir.glob(f"{symbol}_{interval}_*_bjt.csv"))

    def read_available(
        self, symbol: str, interval: str, request: LoadRequest
    ) -> tuple[pd.DataFrame, dict[str, int], list[Path]]:
        frames: list[pd.DataFrame] = []
        used: list[Path] = []
        for path in self.candidate_paths(symbol, interval):
            try:
                raw = pd.read_csv(path)
                frame, _stats = normalize_kline_df(
                    raw, request.start_dt_bjt, request.end_dt_bjt, interval, f"Cache {path.name}"
                )
            except Exception:
                continue
            frames.append(frame)
            used.append(path)
            try:
                os.utime(path, None)
            except OSError:
                pass
        if not frames:
            raise ValueError("No overlapping cached market data.")
        combined = pd.concat(frames, ignore_index=True)
        frame, stats = normalize_kline_df(
            combined, request.start_dt_bjt, request.end_dt_bjt, interval, "Combined cache"
        )
        return frame, stats, used

    @staticmethod
    def missing_ranges(frame: pd.DataFrame, request: LoadRequest, interval: str) -> list[tuple[dt.datetime, dt.datetime]]:
        step = interval_to_ms(interval)
        start = int(make_bjt(request.start_dt_bjt).timestamp() * 1000)
        end = int(make_bjt(request.end_dt_bjt).timestamp() * 1000)
        first_expected = ((start + step - 1) // step) * step
        last_expected = (end // step) * step
        if last_expected < first_expected:
            return []
        present = sorted({int(value) for value in frame.get("open_time_ms", []) if first_expected <= int(value) <= last_expected})
        gaps: list[tuple[int, int]] = []
        cursor = first_expected
        for value in present:
            if value > cursor:
                gaps.append((cursor, value - step))
            cursor = max(cursor, value + step)
        if cursor <= last_expected:
            gaps.append((cursor, last_expected))
        zone = make_bjt(request.start_dt_bjt).tzinfo
        return [
            (dt.datetime.fromtimestamp(left / 1000, zone), dt.datetime.fromtimestamp(right / 1000, zone))
            for left, right in gaps
        ]

    def enforce_limit(self, limit_bytes: int = DEFAULT_CACHE_LIMIT_BYTES, protected: set[Path] | None = None) -> None:
        protected = {path.resolve() for path in (protected or set())}
        files = [path for path in self.cache_dir.glob("*_bjt.csv") if path.is_file()]
        total = sum(path.stat().st_size for path in files)
        if total <= limit_bytes:
            return
        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            if path.resolve() in protected:
                continue
            size = path.stat().st_size
            try:
                path.unlink()
                manifest = self.manifest_path(path)
                if manifest.exists():
                    manifest.unlink()
            except OSError:
                continue
            total -= size
            if total <= limit_bytes:
                break

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


__all__ = ["DEFAULT_CACHE_LIMIT_BYTES", "KlineCache"]
