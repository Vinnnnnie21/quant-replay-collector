from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_config import DATA_DIR


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


def load_app_settings(path: Path | None = None) -> dict[str, Any]:
    target = path or APP_SETTINGS_PATH
    if not target.exists():
        return dict(DEFAULT_APP_SETTINGS)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_APP_SETTINGS)
    if not isinstance(data, dict):
        return dict(DEFAULT_APP_SETTINGS)
    return sanitize_app_settings(data)


def save_app_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    target = path or APP_SETTINGS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = sanitize_app_settings(settings)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
