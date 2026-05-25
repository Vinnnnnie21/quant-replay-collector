from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from app_config import BJT, UTC


VALID_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w",
}

BINANCE_RAW_COLUMNS = [
    "open_time_ms", "open", "high", "low", "close", "volume",
    "close_time_ms", "qav", "num_trades", "tbbav", "tbqav", "ignore",
]

PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]


def clamp(value, low, high):
    return low if value < low else high if value > high else value


def normalize_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,30}", value):
        raise ValueError("交易对格式无效，请使用类似 BTCUSDT、ETHUSDT 的大写字母/数字组合。")
    return value


def normalize_interval(interval: str) -> str:
    value = str(interval or "").strip()
    if value not in VALID_INTERVALS:
        allowed = ", ".join(sorted(VALID_INTERVALS, key=lambda item: (item[-1], int(item[:-1]))))
        raise ValueError(f"K线周期不支持：{value or '(空)'}。支持周期：{allowed}")
    return value


def interval_to_ms(interval: str) -> int:
    interval = normalize_interval(interval)
    unit = interval[-1]
    value = int(interval[:-1])
    multiplier = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}.get(unit)
    if multiplier is None:
        raise ValueError(f"不支持的K线周期：{interval}")
    return value * multiplier


def make_bjt(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        result = value
    elif hasattr(value, "to_pydatetime"):
        result = value.to_pydatetime()
    else:
        from pandas import to_datetime

        result = to_datetime(value).to_pydatetime()
    if result.tzinfo is None:
        result = result.replace(tzinfo=BJT)
    return result.astimezone(BJT)


def validate_date_range(start_dt_bjt: dt.datetime, end_dt_bjt: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    start = make_bjt(start_dt_bjt)
    end = make_bjt(end_dt_bjt)
    if end < start:
        raise ValueError("日期范围无效：结束时间早于开始时间。")
    return start, end


def bjt_now_iso() -> str:
    return dt.datetime.now(BJT).isoformat(timespec="seconds")


def to_api_utc_ms_from_bjt(value: dt.datetime) -> int:
    return int(make_bjt(value).astimezone(UTC).timestamp() * 1000)


def utc_ms_to_bjt(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000.0, UTC).astimezone(BJT)


@dataclass
class LoadRequest:
    symbol: str
    interval: str
    start_dt_bjt: dt.datetime
    end_dt_bjt: dt.datetime
    use_cache: bool = True


class DataLoadCancelled(RuntimeError):
    pass
