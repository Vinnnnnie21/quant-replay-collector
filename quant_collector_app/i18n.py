from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


TRANSLATION_DIR = Path(__file__).resolve().parent / "translations"
SUPPORTED_LANGUAGES = {"zh_CN", "en_US"}


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
    fallback = load_translations("zh_CN")
    if key in fallback:
        return fallback[key]
    return default if default is not None else key


def has_translation(key: str, language: str = "zh_CN") -> bool:
    return key in load_translations(language)
