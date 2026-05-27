from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import warnings
from datetime import datetime
from pathlib import Path

from ui_style import EXCHANGE_DARK_THEME, RESEARCH_SLATE_THEME, CONTRAST_DARK_THEME

APP_NAME = "Quant Replay Collector"
APP_VERSION = "1.4.0"
DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_INTERVAL = "1m"
DEFAULT_INITIAL_EQUITY = 10_000.0
DEFAULT_TRADE_NOTIONAL = 1_000.0
DEFAULT_FEE_BPS = 4.0
DEFAULT_SLIPPAGE_BPS = 1.0
DEFAULT_FILL_MODE = "MID"
EVENT_WINDOW_PRE_BARS = 20
EVENT_WINDOW_POST_BARS = 20
EVENT_TAGS = [
    "深V反转",
    "长下影",
    "放量",
    "恐慌针",
    "跌破前低后收回",
    "二次探底",
    "假突破",
    "加速衰竭",
    "主观高确定性",
    "其他",
]

BINANCE_TOP_MARKET_CAP_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT",
    "SUIUSDT", "HBARUSDT", "BCHUSDT", "TONUSDT", "DOTUSDT",
    "LTCUSDT", "XLMUSDT", "NEARUSDT", "UNIUSDT", "APTUSDT",
    "ICPUSDT", "ETCUSDT", "POLUSDT", "ATOMUSDT", "ARBUSDT",
    "FILUSDT", "FETUSDT", "OPUSDT", "INJUSDT", "STXUSDT",
    "IMXUSDT", "SEIUSDT", "AAVEUSDT", "GRTUSDT", "RUNEUSDT",
    "LDOUSDT", "ALGOUSDT", "QNTUSDT", "FLOWUSDT", "SANDUSDT",
    "MANAUSDT", "AXSUSDT", "EGLDUSDT", "THETAUSDT", "APEUSDT",
    "KAVAUSDT", "SNXUSDT", "CHZUSDT", "CRVUSDT", "COMPUSDT",
    "ZECUSDT", "DASHUSDT", "IOTAUSDT", "MINAUSDT", "DYDXUSDT",
    "GMXUSDT", "BLURUSDT", "WLDUSDT", "TIAUSDT", "JUPUSDT",
    "PYTHUSDT", "JTOUSDT", "WIFUSDT", "1000SHIBUSDT", "1000PEPEUSDT",
    "1000BONKUSDT", "1000FLOKIUSDT", "RENDERUSDT", "TAOUSDT", "ENAUSDT",
    "PENDLEUSDT", "STRKUSDT", "ZKUSDT", "ZROUSDT", "AEVOUSDT",
    "ALTUSDT", "MANTAUSDT", "DYMUSDT", "NOTUSDT", "ORDIUSDT",
    "1000SATSUSDT", "BOMEUSDT", "WUSDT", "ARUSDT", "ETHFIUSDT",
    "OMNIUSDT", "PORTALUSDT", "PIXELUSDT", "ACEUSDT", "NFPUSDT",
    "AIUSDT", "XAIUSDT", "MEMEUSDT", "MAVUSDT", "IDUSDT",
    "ROSEUSDT", "KASUSDT", "VETUSDT", "FTMUSDT", "ONDOUSDT",
]

UTC = dt.timezone.utc
BJT = dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")

def _resolve_root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT_DIR = _resolve_root_dir()
DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
EXPORT_DIR = DATA_DIR / "exports"
LOG_DIR = ROOT_DIR / "logs"
DB_PATH = DATA_DIR / "quant_replay.db"
THEME_CONFIG_PATH = DATA_DIR / "theme_settings.json"

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/klines"

DEFAULT_THEME = dict(EXCHANGE_DARK_THEME, name="交易暗色")

THEME_PRESETS = {
    "交易暗色": dict(EXCHANGE_DARK_THEME, name="交易暗色"),
    "研究灰蓝": dict(RESEARCH_SLATE_THEME, name="研究灰蓝"),
    "高对比暗色": dict(CONTRAST_DARK_THEME, name="高对比暗色"),
}

def load_theme_settings() -> dict:
    if THEME_CONFIG_PATH.exists():
        try:
            data = json.loads(THEME_CONFIG_PATH.read_text(encoding="utf-8"))
            if data.get("name") not in THEME_PRESETS:
                return dict(DEFAULT_THEME)
            merged = dict(DEFAULT_THEME)
            merged.update(data)
            return merged
        except Exception as exc:
            broken = THEME_CONFIG_PATH.with_name(
                f"{THEME_CONFIG_PATH.stem}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.broken.json"
            )
            try:
                shutil.copy2(THEME_CONFIG_PATH, broken)
            except OSError:
                broken = None
            suffix = f" Backup: {broken}" if broken is not None else ""
            warnings.warn(f"Theme settings are invalid; defaults loaded.{suffix} Reason: {exc}")
    return dict(DEFAULT_THEME)


def save_theme_settings(theme: dict) -> None:
    THEME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    THEME_CONFIG_PATH.write_text(json.dumps(theme, ensure_ascii=False, indent=2), encoding="utf-8")
