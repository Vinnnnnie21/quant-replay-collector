from __future__ import annotations

import datetime as dt
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from PySide6 import QtCore, QtGui
import pyqtgraph as pg

from app_config import BINANCE_FAPI, BJT, CACHE_DIR, EVENT_WINDOW_POST_BARS, EVENT_WINDOW_PRE_BARS, UTC
from app_logger import get_logger


logger = get_logger(__name__)

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


def clamp(a, lo, hi):
    return lo if a < lo else hi if a > hi else a


def interval_to_ms(interval: str) -> int:
    interval = normalize_interval(interval)
    unit = interval[-1]
    val = int(interval[:-1])
    mult = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}.get(unit)
    if mult is None:
        raise ValueError(f"不支持的K线周期：{interval}")
    return val * mult


def normalize_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,30}", value):
        raise ValueError("交易对格式无效，请使用类似 BTCUSDT、ETHUSDT 的大写字母/数字组合。")
    return value


def normalize_interval(interval: str) -> str:
    value = str(interval or "").strip()
    if value not in VALID_INTERVALS:
        allowed = ", ".join(sorted(VALID_INTERVALS, key=lambda x: (x[-1], int(x[:-1]))))
        raise ValueError(f"K线周期不支持：{value or '(空)'}。支持周期：{allowed}")
    return value


def validate_date_range(start_dt_bjt: dt.datetime, end_dt_bjt: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    start = make_bjt(start_dt_bjt)
    end = make_bjt(end_dt_bjt)
    if end < start:
        raise ValueError("日期范围无效：结束时间早于开始时间。")
    return start, end


def _series_to_bjt(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    if getattr(parsed.dt, "tz", None) is None:
        return parsed.dt.tz_localize(BJT)
    return parsed.dt.tz_convert(BJT)


def _normalize_kline_df(
    df: pd.DataFrame,
    start_dt_bjt: dt.datetime,
    end_dt_bjt: dt.datetime,
    interval: str,
    source_name: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    if df is None or df.empty:
        raise ValueError(f"{source_name} 没有K线数据。")

    missing_prices = [c for c in PRICE_COLUMNS if c not in df.columns]
    if missing_prices:
        raise ValueError(f"{source_name} 缺少必要价格字段：{', '.join(missing_prices)}")

    out = df.copy()
    for col in PRICE_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    if "open_time_ms" in out.columns:
        out["open_time_ms"] = pd.to_numeric(out["open_time_ms"], errors="coerce")
        out["open_time_bjt"] = pd.to_datetime(out["open_time_ms"], unit="ms", utc=True, errors="coerce").dt.tz_convert(BJT)
    elif "open_time_bjt" in out.columns:
        out["open_time_bjt"] = _series_to_bjt(out["open_time_bjt"])
        out["open_time_ms"] = (out["open_time_bjt"].dt.tz_convert(UTC).astype("int64") // 1_000_000).astype("Int64")
    else:
        raise ValueError(f"{source_name} 缺少 open_time_ms 或 open_time_bjt 字段。")

    if "close_time_ms" in out.columns:
        out["close_time_ms"] = pd.to_numeric(out["close_time_ms"], errors="coerce")
        out["close_time_bjt"] = pd.to_datetime(out["close_time_ms"], unit="ms", utc=True, errors="coerce").dt.tz_convert(BJT)
    elif "close_time_bjt" in out.columns:
        out["close_time_bjt"] = _series_to_bjt(out["close_time_bjt"])
        out["close_time_ms"] = (out["close_time_bjt"].dt.tz_convert(UTC).astype("int64") // 1_000_000).astype("Int64")
    else:
        step_ms = interval_to_ms(interval)
        out["close_time_ms"] = out["open_time_ms"] + step_ms - 1
        out["close_time_bjt"] = pd.to_datetime(out["close_time_ms"], unit="ms", utc=True, errors="coerce").dt.tz_convert(BJT)

    before = len(out)
    out = out.dropna(subset=["open_time_bjt", "close_time_bjt", *PRICE_COLUMNS]).copy()
    dropped_invalid = before - len(out)
    before_time_order = len(out)
    out = out[out["close_time_bjt"] >= out["open_time_bjt"]].copy()
    dropped_invalid += before_time_order - len(out)
    for col in ("open_time_ms", "close_time_ms"):
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("int64")

    out = out.sort_values("open_time_bjt")
    before_dedup = len(out)
    out = out.drop_duplicates(subset=["open_time_bjt"], keep="last")
    dropped_duplicates = before_dedup - len(out)

    start, end = validate_date_range(start_dt_bjt, end_dt_bjt)
    out = out[(out["open_time_bjt"] >= start) & (out["open_time_bjt"] <= end)].copy()
    out = out.reset_index(drop=True)
    out["bar_index"] = np.arange(len(out), dtype=int)

    if out.empty:
        raise ValueError(f"{source_name} 清洗后没有落在所选日期范围内的K线。")

    return out, {"dropped_invalid": dropped_invalid, "dropped_duplicates": dropped_duplicates}


def _format_request_error(e: Exception) -> str:
    if isinstance(e, requests.exceptions.Timeout):
        return "网络请求超时，请检查网络或稍后重试。"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "无法连接 Binance Futures API，请检查网络、代理或地区访问限制。"
    if isinstance(e, requests.exceptions.HTTPError):
        resp = e.response
        if resp is not None:
            body = (resp.text or "").strip().replace("\n", " ")[:200]
            return f"Binance API 返回 HTTP {resp.status_code}：{body or resp.reason}"
        return f"Binance API HTTP 错误：{e}"
    if isinstance(e, requests.exceptions.RequestException):
        return f"网络请求失败：{type(e).__name__}: {e}"
    if isinstance(e, (ValueError, RuntimeError)):
        return str(e)
    return f"{type(e).__name__}: {e}"


def bjt_now_iso() -> str:
    return dt.datetime.now(BJT).isoformat(timespec="seconds")


def make_bjt(dt_like) -> dt.datetime:
    if isinstance(dt_like, pd.Timestamp):
        value = dt_like.to_pydatetime()
    elif isinstance(dt_like, dt.datetime):
        value = dt_like
    else:
        value = pd.to_datetime(dt_like).to_pydatetime()
    if value.tzinfo is None:
        value = value.replace(tzinfo=BJT)
    return value.astimezone(BJT)


def to_api_utc_ms_from_bjt(d: dt.datetime) -> int:
    if isinstance(d, pd.Timestamp):
        d = d.to_pydatetime()
    if d.tzinfo is None:
        d = d.replace(tzinfo=BJT)
    return int(d.astimezone(UTC).timestamp() * 1000)


def utc_ms_to_bjt(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000.0, UTC).astimezone(BJT)


@dataclass
class LoadRequest:
    symbol: str
    interval: str
    start_dt_bjt: dt.datetime
    end_dt_bjt: dt.datetime
    use_cache: bool = True


class LoaderWorker(QtCore.QObject):
    finished = QtCore.Signal(object, str)
    progress = QtCore.Signal(str)

    def __init__(self, cache_dir: Path | str = CACHE_DIR):
        super().__init__()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._abort = False

    @QtCore.Slot()
    def abort(self):
        self._abort = True

    def _cache_path(self, symbol: str, interval: str, start_dt_bjt: dt.datetime, end_dt_bjt: dt.datetime):
        return self.cache_dir / f"{symbol}_{interval}_{start_dt_bjt.strftime('%Y%m%d')}_{end_dt_bjt.strftime('%Y%m%d')}_bjt.csv"

    def _read_cache(self, cache_path: Path, req: LoadRequest, symbol: str, interval: str):
        if not cache_path.exists():
            return None
        df = pd.read_csv(cache_path)
        df, stats = _normalize_kline_df(df, req.start_dt_bjt, req.end_dt_bjt, interval, f"缓存 {cache_path.name}")
        if stats["dropped_invalid"] or stats["dropped_duplicates"]:
            self.progress.emit(
                f"缓存已自动清洗：无效行 {stats['dropped_invalid']}，重复K线 {stats['dropped_duplicates']}"
            )
        return df

    @QtCore.Slot(object)
    def load(self, req: LoadRequest):
        self._abort = False
        symbol = ""
        interval = ""
        cache_path: Path | None = None
        try:
            symbol = normalize_symbol(req.symbol)
            interval = normalize_interval(req.interval)
            start_dt_bjt, end_dt_bjt = validate_date_range(req.start_dt_bjt, req.end_dt_bjt)
            req = LoadRequest(symbol=symbol, interval=interval, start_dt_bjt=start_dt_bjt, end_dt_bjt=end_dt_bjt, use_cache=req.use_cache)
            cache_path = self._cache_path(symbol, interval, start_dt_bjt, end_dt_bjt)
            # TODO: Persist full session K lines for session-level time series analysis without changing old databases.

            if req.use_cache and cache_path.exists():
                try:
                    df = self._read_cache(cache_path, req, symbol, interval)
                    if df is not None:
                        self.finished.emit(df, f"已从缓存加载 {cache_path.name}，K线={len(df)}")
                        return
                except Exception as e:
                    logger.warning("缓存读取失败，将尝试重新下载：%s", cache_path, exc_info=True)
                    self.progress.emit(f"缓存不可用，将尝试重新下载：{_format_request_error(e)}")

            start_ms = to_api_utc_ms_from_bjt(start_dt_bjt)
            end_ms = to_api_utc_ms_from_bjt(end_dt_bjt)
            step_ms = interval_to_ms(interval)
            limit = 1000
            cur = start_ms
            raw: list[list] = []
            safety = 0
            self.progress.emit(f"开始从 Binance 下载K线：{symbol} {interval} {start_dt_bjt.date()} ~ {end_dt_bjt.date()}")
            while cur <= end_ms and not self._abort:
                safety += 1
                if safety > 10000:
                    raise RuntimeError("下载循环超过安全上限，请缩小日期范围后重试。")
                resp = requests.get(
                    BINANCE_FAPI,
                    params={
                        "symbol": symbol,
                        "interval": interval,
                        "startTime": cur,
                        "endTime": end_ms,
                        "limit": limit,
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                batch = resp.json()
                if not isinstance(batch, list):
                    raise RuntimeError(f"Binance API 返回格式异常：{str(batch)[:200]}")
                if not batch:
                    break
                bad_rows = [row for row in batch if not isinstance(row, list) or len(row) < len(BINANCE_RAW_COLUMNS)]
                if bad_rows:
                    raise RuntimeError(f"Binance API 返回K线字段不完整，异常行数={len(bad_rows)}")
                raw.extend([row[:len(BINANCE_RAW_COLUMNS)] for row in batch])
                last_open = int(batch[-1][0])
                cur = last_open + step_ms
                self.progress.emit(f"下载中... 已获取 {len(raw)} 根")
                if len(batch) < limit:
                    break

            if self._abort:
                self.finished.emit(pd.DataFrame(), "已取消加载。")
                return

            if not raw:
                self.finished.emit(pd.DataFrame(), f"未获取到任何K线：{symbol} {interval}，请检查交易对、周期或日期范围。")
                return

            df = pd.DataFrame(raw, columns=BINANCE_RAW_COLUMNS)
            df, stats = _normalize_kline_df(df, start_dt_bjt, end_dt_bjt, interval, "Binance 下载结果")
            try:
                df.to_csv(cache_path, index=False)
            except Exception:
                logger.warning("K线缓存写入失败：%s", cache_path, exc_info=True)
                pass
            clean_note = ""
            if stats["dropped_invalid"] or stats["dropped_duplicates"]:
                clean_note = f"，已清洗无效行 {stats['dropped_invalid']}、重复K线 {stats['dropped_duplicates']}"
            self.finished.emit(df, f"下载完成，K线={len(df)}{clean_note}，缓存={cache_path.name}")
        except Exception as e:
            logger.exception("K线加载失败：symbol=%s interval=%s cache=%s", symbol, interval, cache_path)
            if cache_path is not None and not req.use_cache:
                try:
                    df = self._read_cache(cache_path, req, symbol, interval)
                    if df is not None:
                        self.finished.emit(
                            df,
                            f"在线刷新失败，已回退到缓存 {cache_path.name}，K线={len(df)}；原因：{_format_request_error(e)}",
                        )
                        return
                except Exception:
                    logger.warning("在线刷新失败后回退缓存也失败：%s", cache_path, exc_info=True)
                    pass
            self.finished.emit(pd.DataFrame(), f"加载失败：{_format_request_error(e)}")


class IndexTimeAxis(pg.AxisItem):
    def __init__(self, orientation='bottom'):
        super().__init__(orientation=orientation)
        self._times = None
        self._cache: dict[int, str] = {}
        try:
            self.enableAutoSIPrefix(False)
        except Exception:
            pass

    def set_times(self, times: np.ndarray | list):
        self._times = np.asarray(times, dtype=object)
        self._cache.clear()
        self.update()

    def tickStrings(self, values, scale, spacing):
        if self._times is None or len(self._times) == 0:
            return ["" for _ in values]
        out = []
        show_time = spacing <= 120
        n = len(self._times)
        for v in values:
            try:
                idx = int(round(float(v) * float(scale)))
                if idx < 0 or idx >= n:
                    out.append("")
                    continue
                if idx not in self._cache:
                    t = make_bjt(self._times[idx])
                    self._cache[idx] = t.strftime("%m-%d %H:%M") if show_time else t.strftime("%Y-%m-%d")
                out.append(self._cache[idx])
            except Exception:
                out.append("")
        return out


class KViewBox(pg.ViewBox):
    userInteracted = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setMouseEnabled(x=True, y=False)
        self.setMenuEnabled(False)

    def wheelEvent(self, ev, axis=None):
        try:
            delta = ev.delta() if hasattr(ev, 'delta') else ev.angleDelta().y()
            if delta == 0:
                ev.ignore()
                return
            self.userInteracted.emit()
            (x0, x1), _ = self.viewRange()
            span = max(1.0, x1 - x0)
            center = self.mapSceneToView(ev.scenePos()).x()
            factor = 0.9 if delta > 0 else 1.1
            new_span = span * factor
            new_x0 = center - (center - x0) * factor
            new_x1 = new_x0 + new_span
            self.setXRange(new_x0, new_x1, padding=0.0)
            ev.accept()
        except Exception:
            ev.ignore()

    def mouseDragEvent(self, ev, axis=None):
        if ev.button() == QtCore.Qt.LeftButton:
            self.userInteracted.emit()
        super().mouseDragEvent(ev, axis=axis)


class CandlestickItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self._picture = None
        self._bounds = QtCore.QRectF(0, 0, 1, 1)
        self._data = None
        self._w = 0.7
        self._pen_up = pg.mkPen("#00C853")
        self._pen_dn = pg.mkPen("#FF5252")
        self._brush_up = pg.mkBrush("#00C853")
        self._brush_dn = pg.mkBrush("#FF5252")
        self._wick_pen = pg.mkPen("#B0BEC5")

    def set_data(self, x, o, h, l, c, candle_width=0.7):
        self._data = (np.asarray(x, dtype=float), np.asarray(o, dtype=float), np.asarray(h, dtype=float),
                      np.asarray(l, dtype=float), np.asarray(c, dtype=float))
        self._w = float(candle_width)
        self._rebuild()

    def set_style(self, up_color: str, down_color: str, wick_color: str):
        self._pen_up = pg.mkPen(up_color)
        self._pen_dn = pg.mkPen(down_color)
        self._brush_up = pg.mkBrush(up_color)
        self._brush_dn = pg.mkBrush(down_color)
        self._wick_pen = pg.mkPen(wick_color)
        if self._data is not None:
            self._rebuild()

    def _rebuild(self):
        if self._data is None or len(self._data[0]) == 0:
            self._picture = QtGui.QPicture()
            self._bounds = QtCore.QRectF(0, 0, 1, 1)
            self.prepareGeometryChange()
            self.update()
            return
        x, o, h, l, c = self._data
        pic = QtGui.QPicture()
        p = QtGui.QPainter(pic)
        p.setPen(self._wick_pen)
        for xi, hi, li in zip(x, h, l):
            p.drawLine(QtCore.QPointF(xi, li), QtCore.QPointF(xi, hi))
        for xi, oi, ci in zip(x, o, c):
            up = ci >= oi
            p.setPen(self._pen_up if up else self._pen_dn)
            p.setBrush(self._brush_up if up else self._brush_dn)
            top = max(oi, ci)
            bot = min(oi, ci)
            if abs(top - bot) < 1e-8:
                bot = top - 1e-8
            p.drawRect(QtCore.QRectF(xi - self._w / 2.0, bot, self._w, top - bot))
        p.end()
        self._picture = pic
        xmin, xmax = float(x.min()), float(x.max())
        ymin, ymax = float(l.min()), float(h.max())
        self.prepareGeometryChange()
        self._bounds = QtCore.QRectF(xmin - 1.0, ymin, (xmax - xmin) + 2.0, max(1e-6, ymax - ymin))
        self.update()

    def paint(self, painter, opt, widget):
        if self._picture is not None:
            painter.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        return self._bounds


class VolumeItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self._picture = None
        self._bounds = QtCore.QRectF(0, 0, 1, 1)
        self._data = None
        self._w = 0.7
        self._brush_up = pg.mkBrush("#00C853")
        self._brush_dn = pg.mkBrush("#FF5252")
        self._pen_none = pg.mkPen(None)

    def set_data(self, x, vol, upmask, bar_width=0.7):
        self._data = (np.asarray(x, dtype=float), np.asarray(vol, dtype=float), np.asarray(upmask, dtype=bool))
        self._w = float(bar_width)
        self._rebuild()

    def set_style(self, up_color: str, down_color: str):
        self._brush_up = pg.mkBrush(up_color)
        self._brush_dn = pg.mkBrush(down_color)
        if self._data is not None:
            self._rebuild()

    def _rebuild(self):
        if self._data is None or len(self._data[0]) == 0:
            self._picture = QtGui.QPicture()
            self._bounds = QtCore.QRectF(0, 0, 1, 1)
            self.prepareGeometryChange()
            self.update()
            return
        x, v, up = self._data
        pic = QtGui.QPicture()
        p = QtGui.QPainter(pic)
        p.setPen(self._pen_none)
        for xi, vi, is_up in zip(x, v, up):
            p.setBrush(self._brush_up if is_up else self._brush_dn)
            p.drawRect(QtCore.QRectF(xi - self._w / 2.0, 0.0, self._w, max(0.0, float(vi))))
        p.end()
        self._picture = pic
        xmin, xmax = float(x.min()), float(x.max())
        ymax = float(v.max()) if len(v) else 1.0
        self.prepareGeometryChange()
        self._bounds = QtCore.QRectF(xmin - 1.0, 0.0, (xmax - xmin) + 2.0, max(1e-6, ymax))
        self.update()

    def paint(self, painter, opt, widget):
        if self._picture is not None:
            painter.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        return self._bounds


def compute_price_proxy(row: pd.Series) -> float:
    return float(row["high"] + row["low"]) / 2.0


def build_window_rows(df: pd.DataFrame, event_idx: int, pre_bars: int | None = None, post_bars: int | None = None):
    pre = EVENT_WINDOW_PRE_BARS if pre_bars is None else int(pre_bars)
    post = EVENT_WINDOW_POST_BARS if post_bars is None else int(post_bars)
    pre = max(0, pre)
    post = max(0, post)
    rows = []
    for offset in range(-pre, post + 1):
        idx = event_idx + offset
        if 0 <= idx < len(df):
            row = df.iloc[idx]
            rows.append(
                {
                    "offset": offset,
                    "is_event_bar": 1 if offset == 0 else 0,
                    "bar_index": int(row["bar_index"]),
                    "bar_open_time_bjt": make_bjt(row["open_time_bjt"]).isoformat(timespec="seconds"),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "is_missing_padding": 0,
                }
            )
        else:
            rows.append(
                {
                    "offset": offset,
                    "is_event_bar": 1 if offset == 0 else 0,
                    "bar_index": None,
                    "bar_open_time_bjt": None,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "volume": None,
                    "is_missing_padding": 1,
                }
            )
    return rows


def _safe_return(a: float | None, b: float | None):
    if a is None or b is None or a == 0:
        return math.nan
    return (b / a) - 1.0


def _slice_closes(df: pd.DataFrame, start: int, end: int):
    if start < 0 or end >= len(df) or start > end:
        return None
    return df.iloc[start:end + 1]["close"].astype(float).to_numpy()


def _trailing_run(df: pd.DataFrame, event_idx: int, bullish: bool):
    count = 0
    for i in range(event_idx, -1, -1):
        row = df.iloc[i]
        cond = float(row["close"]) >= float(row["open"]) if bullish else float(row["close"]) < float(row["open"])
        if cond:
            count += 1
        else:
            break
    return count


def build_feature_row(df: pd.DataFrame, event_idx: int, side: str):
    row = df.iloc[event_idx]
    o, h, l, c, v = [float(row[k]) for k in ["open", "high", "low", "close", "volume"]]
    price_proxy = compute_price_proxy(row)
    event_range = h - l
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    prev_5_vol = df.iloc[max(0, event_idx - 5):event_idx]["volume"].astype(float)
    prev_5_vol_mean = float(prev_5_vol.mean()) if len(prev_5_vol) else math.nan
    vol_ratio_5 = v / prev_5_vol_mean if prev_5_vol_mean and not math.isnan(prev_5_vol_mean) else math.nan

    def pre_ret(n: int):
        if event_idx - n < 0 or event_idx - 1 < 0:
            return math.nan
        start = float(df.iloc[event_idx - n]["close"])
        end = float(df.iloc[event_idx - 1]["close"])
        return _safe_return(start, end)

    def pre_vol(n: int):
        closes = _slice_closes(df, event_idx - n, event_idx - 1)
        if closes is None or len(closes) < 2:
            return math.nan
        pct = pd.Series(closes).pct_change().dropna()
        return float(pct.std(ddof=0)) if len(pct) else math.nan

    prev10 = df.iloc[max(0, event_idx - 10):event_idx]
    prev_high10 = float(prev10["high"].max()) if len(prev10) else math.nan
    prev_low10 = float(prev10["low"].min()) if len(prev10) else math.nan

    def fwd_ret(n: int):
        if event_idx + n >= len(df):
            return math.nan
        end = float(df.iloc[event_idx + n]["close"])
        raw = _safe_return(price_proxy, end)
        return raw

    raw_fwd = {n: fwd_ret(n) for n in (1, 3, 5, 10)}
    side_mult = 1.0 if side == "LONG" else -1.0
    side_fwd = {n: (raw_fwd[n] * side_mult if not math.isnan(raw_fwd[n]) else math.nan) for n in raw_fwd}

    future_slice = df.iloc[event_idx + 1:min(len(df), event_idx + 11)]
    if len(future_slice):
        future_high = float(future_slice["high"].max())
        future_low = float(future_slice["low"].min())
        if side == "LONG":
            mfe_10 = _safe_return(price_proxy, future_high)
            mae_10 = _safe_return(price_proxy, future_low)
        else:
            mfe_10 = (price_proxy - future_low) / price_proxy if price_proxy else math.nan
            mae_10 = (price_proxy - future_high) / price_proxy if price_proxy else math.nan
    else:
        mfe_10 = math.nan
        mae_10 = math.nan

    return {
        "price_proxy": price_proxy,
        "event_body": body,
        "event_upper_wick": upper,
        "event_lower_wick": lower,
        "event_range": event_range,
        "event_volume": v,
        "event_vol_ratio_5": vol_ratio_5,
        "pre_ret_3": pre_ret(3),
        "pre_ret_5": pre_ret(5),
        "pre_ret_10": pre_ret(10),
        "pre_vol_3": pre_vol(3),
        "pre_vol_5": pre_vol(5),
        "pre_vol_10": pre_vol(10),
        "prev_high10_dist_pct": _safe_return(price_proxy, prev_high10),
        "prev_low10_dist_pct": _safe_return(price_proxy, prev_low10),
        "bull_run_count": _trailing_run(df, event_idx, bullish=True),
        "bear_run_count": _trailing_run(df, event_idx, bullish=False),
        "event_upper_ratio": upper / event_range if event_range else math.nan,
        "event_lower_ratio": lower / event_range if event_range else math.nan,
        "event_body_ratio": body / event_range if event_range else math.nan,
        "fwd_ret_1": raw_fwd[1],
        "fwd_ret_3": raw_fwd[3],
        "fwd_ret_5": raw_fwd[5],
        "fwd_ret_10": raw_fwd[10],
        "fwd_ret_1_side_adj": side_fwd[1],
        "fwd_ret_3_side_adj": side_fwd[3],
        "fwd_ret_5_side_adj": side_fwd[5],
        "fwd_ret_10_side_adj": side_fwd[10],
        "mfe_10": mfe_10,
        "mae_10": mae_10,
    }
