from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


TRANSLATION_DIR = Path(__file__).resolve().parent / "translations"
SUPPORTED_LANGUAGES = {"zh_CN", "en_US"}
DISPLAY_NAME_KEYS = {
    "Setup": "display_name.setup",
    "Setup version": "display_name.setup_version",
    "episode": "display_name.episode",
    "ENTRY": "display_name.entry",
    "REJECT": "display_name.reject",
    "EXIT_NOW": "display_name.exit_now",
    "HOLD": "display_name.hold",
    "entry ATR20": "display_name.entry_atr20",
}


@lru_cache(maxsize=2)
def load_translations(language: str) -> dict[str, str]:
    language = language if language in SUPPORTED_LANGUAGES else "zh_CN"
    path = TRANSLATION_DIR / f"{language}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def tr(key: str, language: str = "zh_CN", default: str | None = None) -> str:
    language = language if language in SUPPORTED_LANGUAGES else "zh_CN"
    table = load_translations(language)
    if key in table:
        return table[key]
    return default if default is not None else key


def has_translation(key: str, language: str = "zh_CN") -> bool:
    return key in load_translations(language)


def display_name(identifier: str, language: str = "zh_CN") -> str:
    """Translate a stable internal identifier only at the presentation edge."""

    key = DISPLAY_NAME_KEYS.get(str(identifier))
    if key is None:
        return str(identifier)
    return tr(key, language, str(identifier))
