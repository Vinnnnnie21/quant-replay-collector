from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from atomic_write import atomic_write_text
    from ui_style import DARK_THEME, LIGHT_THEME, normalize_theme_settings
    from version import __version__
except ImportError:  # pragma: no cover - package import path
    from .atomic_write import atomic_write_text
    from .ui_style import DARK_THEME, LIGHT_THEME, normalize_theme_settings
    from .version import __version__

APP_NAME = "Quant Replay Collector"
APP_VERSION = __version__
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


@dataclass(frozen=True)
class ApplicationPaths:
    root_dir: Path
    data_dir: Path
    cache_dir: Path
    export_dir: Path
    log_dir: Path
    backup_dir: Path


def resolve_application_paths(
    *,
    module_file: str | Path,
    executable: str | Path,
    frozen: bool,
    runtime_root: str | Path | None = None,
) -> ApplicationPaths:
    module_dir = Path(module_file).resolve().parent
    if runtime_root is not None:
        root_dir = Path(runtime_root).resolve()
        uses_workspace_layout = False
    elif frozen:
        executable_dir = Path(executable).resolve().parent
        workspace_app_dir = executable_dir.parent / "quant_collector_app"
        is_workspace_build = (
            (workspace_app_dir / "__init__.py").is_file()
            and (workspace_app_dir / "app_config.py").is_file()
        )
        root_dir = workspace_app_dir if is_workspace_build else executable_dir
        uses_workspace_layout = is_workspace_build
    else:
        root_dir = module_dir
        uses_workspace_layout = True

    data_dir = root_dir / "data"
    backup_root = root_dir.parent if uses_workspace_layout else root_dir
    return ApplicationPaths(
        root_dir=root_dir,
        data_dir=data_dir,
        cache_dir=data_dir / "cache",
        export_dir=data_dir / "exports",
        log_dir=root_dir / "logs",
        backup_dir=backup_root / "backups",
    )


APPLICATION_PATHS = resolve_application_paths(
    module_file=__file__,
    executable=sys.executable,
    frozen=bool(getattr(sys, "frozen", False)),
    runtime_root=os.environ.get("QRC_RUNTIME_ROOT") or None,
)
ROOT_DIR = APPLICATION_PATHS.root_dir
DATA_DIR = APPLICATION_PATHS.data_dir
CACHE_DIR = APPLICATION_PATHS.cache_dir
EXPORT_DIR = APPLICATION_PATHS.export_dir
LOG_DIR = APPLICATION_PATHS.log_dir
BACKUP_DIR = APPLICATION_PATHS.backup_dir
DB_PATH = DATA_DIR / "quant_replay.db"
THEME_CONFIG_PATH = DATA_DIR / "theme_settings.json"

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/klines"

DEFAULT_THEME = normalize_theme_settings(LIGHT_THEME)

THEME_PRESETS = {
    LIGHT_THEME["name"]: normalize_theme_settings(LIGHT_THEME),
    DARK_THEME["name"]: normalize_theme_settings(DARK_THEME),
}

def load_theme_settings() -> dict:
    if THEME_CONFIG_PATH.exists():
        try:
            data = json.loads(THEME_CONFIG_PATH.read_text(encoding="utf-8"))
            return normalize_theme_settings(data)
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
    normalized = normalize_theme_settings(theme)
    atomic_write_text(
        THEME_CONFIG_PATH,
        json.dumps(normalized, ensure_ascii=False, indent=2),
        replace_fn=os.replace,
    )
