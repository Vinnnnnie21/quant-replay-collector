from __future__ import annotations

import json
import shutil
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from app_config import DATA_DIR
except ImportError:  # pragma: no cover - package import path
    from .app_config import DATA_DIR


APP_SETTINGS_PATH = DATA_DIR / "app_settings.json"

DEFAULT_APP_SETTINGS: dict[str, Any] = {
    "language": "zh_CN",
    "llm_provider": "mock",
    "local_api_url": "http://127.0.0.1:8765",
    "fill_mode": None,
    "fee_bps": None,
    "slippage_bps": None,
    "trade_notional": None,
    "initial_equity": None,
}

SENSITIVE_KEYS = {
    "api_key",
    "openai_api_key",
    "custom_llm_api_key",
    "llm_api_key",
    "secret",
    "token",
    "password",
}


def sanitize_app_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_APP_SETTINGS)
    if settings:
        for key, value in settings.items():
            if str(key).strip().lower() in SENSITIVE_KEYS:
                continue
            merged[key] = value
    return merged


def build_app_settings_update(
    current: dict[str, Any] | None,
    *,
    language: str,
    llm_provider: str,
    local_api_url: str,
    fill_mode: str,
    fee_bps: float,
    slippage_bps: float,
    trade_notional: float,
    initial_equity: float,
) -> dict[str, Any]:
    settings = sanitize_app_settings(current)
    settings.update(
        {
            "language": language,
            "llm_provider": llm_provider,
            "local_api_url": local_api_url,
            "fill_mode": fill_mode,
            "fee_bps": fee_bps,
            "slippage_bps": slippage_bps,
            "trade_notional": trade_notional,
            "initial_equity": initial_equity,
        }
    )
    return sanitize_app_settings(settings)


def load_app_settings(path: Path | None = None) -> dict[str, Any]:
    target = path or APP_SETTINGS_PATH
    if not target.exists():
        return dict(DEFAULT_APP_SETTINGS)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        broken = target.with_name(f"{target.stem}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.broken.json")
        try:
            shutil.copy2(target, broken)
        except OSError:
            broken = None
        suffix = f" Backup: {broken}" if broken is not None else ""
        warnings.warn(f"App settings are invalid; defaults loaded.{suffix} Reason: {exc}")
        return dict(DEFAULT_APP_SETTINGS)
    if not isinstance(data, dict):
        return dict(DEFAULT_APP_SETTINGS)
    return sanitize_app_settings(data)


def save_app_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    target = path or APP_SETTINGS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = sanitize_app_settings(settings)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
