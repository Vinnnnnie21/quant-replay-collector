from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd


# 10,000 rows keeps each pandas call bounded without excessive open/append churn.
DEFAULT_CSV_CHUNK_ROWS = 10_000


def write_dataframe_csv_atomic(
    frame: pd.DataFrame,
    path: Path,
    *,
    checkpoint: Callable[[], None] | None = None,
    on_chunk_written: Callable[[int, int], None] | None = None,
    chunk_rows: int = DEFAULT_CSV_CHUNK_ROWS,
) -> None:
    """Write ordered CSV chunks and publish only after every chunk succeeds."""
    rows_per_chunk = int(chunk_rows)
    if rows_per_chunk <= 0:
        raise ValueError("chunk_rows must be a positive integer")
    partial_path = path.with_name(f"{path.name}.partial")
    partial_path.unlink(missing_ok=True)
    chunk_count = max(1, (len(frame) + rows_per_chunk - 1) // rows_per_chunk)
    try:
        for chunk_index in range(chunk_count):
            if checkpoint is not None:
                checkpoint()
            start = chunk_index * rows_per_chunk
            stop = min(len(frame), start + rows_per_chunk)
            frame.iloc[start:stop].to_csv(
                partial_path,
                index=False,
                mode="w" if chunk_index == 0 else "a",
                header=chunk_index == 0,
            )
            if on_chunk_written is not None:
                on_chunk_written(chunk_index + 1, chunk_count)
            if checkpoint is not None:
                checkpoint()
        partial_path.replace(path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise


__all__ = ["DEFAULT_CSV_CHUNK_ROWS", "write_dataframe_csv_atomic"]
