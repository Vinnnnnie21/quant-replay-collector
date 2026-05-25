from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass

import pandas as pd

from app_config import UTC
from .types import interval_to_ms, make_bjt, to_api_utc_ms_from_bjt


@dataclass(frozen=True)
class DataQualityReport:
    report_id: str
    symbol: str
    interval: str
    start_time_bjt: str
    end_time_bjt: str
    expected_bars: int
    actual_bars: int
    missing_bars: int
    duplicated_bars: int
    invalid_rows: int
    first_open_time_bjt: str | None
    last_open_time_bjt: str | None
    created_at: str
    source: str
    strictly_increasing: bool
    data_quality_status: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    def to_storage_row(self) -> dict:
        row = self.to_dict()
        row["report_json"] = json.dumps(row, ensure_ascii=False, sort_keys=True)
        return row


def assess_data_quality(
    df: pd.DataFrame,
    symbol: str,
    interval: str,
    start_dt_bjt: dt.datetime,
    end_dt_bjt: dt.datetime,
    source: str,
    clean_stats: dict[str, int] | None = None,
) -> DataQualityReport:
    clean_stats = clean_stats or {}
    step_ms = interval_to_ms(interval)
    start_ms = to_api_utc_ms_from_bjt(start_dt_bjt)
    end_ms = to_api_utc_ms_from_bjt(end_dt_bjt)
    expected = max(0, int((end_ms - start_ms) // step_ms) + 1)
    opens = pd.to_numeric(df.get("open_time_ms"), errors="coerce").dropna().astype("int64")
    strictly_increasing = bool(
        int(clean_stats.get("out_of_order", 0)) == 0
        and (len(opens) < 2 or (opens.diff().dropna() > 0).all())
    )
    duplicated = int(clean_stats.get("dropped_duplicates", 0)) + int(opens.duplicated().sum())
    invalid = int(clean_stats.get("dropped_invalid", 0))
    actual = int(len(df))
    missing = max(0, expected - int(opens.nunique()))
    status = "PASS"
    if invalid or not strictly_increasing:
        status = "FAIL"
    elif duplicated or missing:
        status = "WARNING"
    first = make_bjt(df["open_time_bjt"].iloc[0]).isoformat(timespec="seconds") if actual else None
    last = make_bjt(df["open_time_bjt"].iloc[-1]).isoformat(timespec="seconds") if actual else None
    return DataQualityReport(
        report_id=f"dqr_{uuid.uuid4().hex}",
        symbol=symbol,
        interval=interval,
        start_time_bjt=make_bjt(start_dt_bjt).isoformat(timespec="seconds"),
        end_time_bjt=make_bjt(end_dt_bjt).isoformat(timespec="seconds"),
        expected_bars=expected,
        actual_bars=actual,
        missing_bars=missing,
        duplicated_bars=duplicated,
        invalid_rows=invalid,
        first_open_time_bjt=first,
        last_open_time_bjt=last,
        created_at=dt.datetime.now(UTC).isoformat(timespec="seconds"),
        source=source,
        strictly_increasing=strictly_increasing,
        data_quality_status=status,
    )


__all__ = ["DataQualityReport", "assess_data_quality"]
