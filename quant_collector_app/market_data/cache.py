from __future__ import annotations

import datetime as dt
import json
import math
import os
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from .quality import DataQualityReport
from .transforms import normalize_kline_df
from .types import LoadRequest, interval_to_ms, make_bjt


DEFAULT_CACHE_LIMIT_BYTES = 5 * 1024**3
HISTORICAL_CACHE_READ_CHUNK_ROWS = 10_000


def _cache_file_date_range(
    path: Path,
    *,
    symbol: str,
    interval: str,
) -> tuple[dt.date, dt.date] | None:
    prefix = f"{symbol}_{interval}_"
    suffix = "_bjt.csv"
    if not path.name.startswith(prefix) or not path.name.endswith(suffix):
        return None
    range_text = path.name[len(prefix) : -len(suffix)]
    try:
        start_text, end_text = range_text.split("_", maxsplit=1)
        return (
            dt.datetime.strptime(start_text, "%Y%m%d").date(),
            dt.datetime.strptime(end_text, "%Y%m%d").date(),
        )
    except ValueError:
        return None


def _cached_curve_rows_from_path(
    path: Path,
    *,
    start_time_utc_ms: int,
    end_time_utc_ms: int,
    cancelled: Callable[[], bool],
    chunk_rows: int,
) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    wanted_columns = {
        "open_time_ms",
        "open_time_utc_ms",
        "open_time_bjt",
        "close",
    }
    try:
        chunks = pd.read_csv(
            path,
            usecols=lambda column: column in wanted_columns,
            chunksize=chunk_rows,
            float_precision="round_trip",
        )
        for chunk in chunks:
            if cancelled():
                return rows
            time_column = (
                "open_time_utc_ms"
                if "open_time_utc_ms" in chunk.columns
                else "open_time_ms"
                if "open_time_ms" in chunk.columns
                else None
            )
            if time_column is None or "close" not in chunk.columns:
                return {}
            utc_values = pd.to_numeric(chunk[time_column], errors="coerce")
            close_values = pd.to_numeric(chunk["close"], errors="coerce")
            in_range = utc_values.between(
                int(start_time_utc_ms),
                int(end_time_utc_ms),
                inclusive="both",
            )
            if not bool(in_range.any()):
                continue
            selected = pd.DataFrame(
                {
                    "open_time_utc_ms": utc_values[in_range],
                    "close": close_values[in_range],
                    "open_time_bjt": (
                        chunk.loc[in_range, "open_time_bjt"]
                        if "open_time_bjt" in chunk.columns
                        else None
                    ),
                }
            )
            if selected["open_time_utc_ms"].isna().any() or any(
                not math.isfinite(float(value)) for value in selected["close"]
            ):
                return {}
            for row in selected.itertuples(index=False):
                utc_ms = int(row.open_time_utc_ms)
                market_time = row.open_time_bjt
                if pd.isna(market_time) or not str(market_time).strip():
                    market_time = None
                rows.setdefault(
                    utc_ms,
                    {
                        "open_time_utc_ms": utc_ms,
                        "open_time_bjt": market_time,
                        "close": float(row.close),
                    },
                )
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError):
        return {}
    return rows


def read_cached_kline_range(
    cache_dir: Path | str,
    *,
    symbol: str,
    interval: str,
    start_time_utc_ms: int,
    end_time_utc_ms: int,
    minimum_rows: int = 1,
    cancelled: Callable[[], bool] | None = None,
    chunk_rows: int = HISTORICAL_CACHE_READ_CHUNK_ROWS,
) -> list[dict]:
    """Read curve columns from existing cache files without mutating the cache."""

    cancelled = cancelled or (lambda: False)
    directory = Path(cache_dir)
    if not directory.is_dir() or cancelled():
        return []
    start_date = make_bjt(
        dt.datetime.fromtimestamp(int(start_time_utc_ms) / 1_000, dt.UTC)
    ).date()
    end_date = make_bjt(
        dt.datetime.fromtimestamp(int(end_time_utc_ms) / 1_000, dt.UTC)
    ).date()
    exact = directory / (
        f"{symbol}_{interval}_{start_date:%Y%m%d}_{end_date:%Y%m%d}_bjt.csv"
    )
    candidates = []
    if exact.is_file():
        candidates.append(exact)
    for path in sorted(directory.glob(f"{symbol}_{interval}_*_bjt.csv")):
        if path == exact or not path.is_file():
            continue
        cached_range = _cache_file_date_range(
            path,
            symbol=symbol,
            interval=interval,
        )
        if cached_range is None:
            continue
        cached_start, cached_end = cached_range
        if cached_start <= end_date and cached_end >= start_date:
            candidates.append(path)

    rows_by_time: dict[int, dict] = {}
    for index, path in enumerate(candidates):
        if cancelled():
            return []
        path_rows = _cached_curve_rows_from_path(
            path,
            start_time_utc_ms=start_time_utc_ms,
            end_time_utc_ms=end_time_utc_ms,
            cancelled=cancelled,
            chunk_rows=max(1, int(chunk_rows)),
        )
        if cancelled():
            return []
        for utc_ms, row in path_rows.items():
            rows_by_time.setdefault(utc_ms, row)
        if index == 0 and path == exact and len(rows_by_time) >= max(1, minimum_rows):
            break

    return [
        {"bar_index": index, **rows_by_time[utc_ms]}
        for index, utc_ms in enumerate(sorted(rows_by_time))
    ]


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
            raw_df = pd.read_csv(cache_path, float_precision="round_trip")
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
                raw = pd.read_csv(path, float_precision="round_trip")
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


__all__ = [
    "DEFAULT_CACHE_LIMIT_BYTES",
    "HISTORICAL_CACHE_READ_CHUNK_ROWS",
    "KlineCache",
    "read_cached_kline_range",
]
