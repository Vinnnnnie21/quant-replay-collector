from __future__ import annotations

try:
    from i18n import SUPPORTED_LANGUAGES, has_translation, load_translations, tr
except ImportError:  # pragma: no cover - package import path
    from .i18n import SUPPORTED_LANGUAGES, has_translation, load_translations, tr


def translate_for(target, key: str, default: str | None = None) -> str:
    """Translate for a window-like object without requiring a concrete Qt class."""
    translator = getattr(target, "tr", None)
    if callable(translator):
        try:
            value = str(translator(key, default))
        except TypeError:
            value = str(translator(key))
        if value != key:
            return value
    language = str(getattr(target, "current_language", "zh_CN") or "zh_CN")
    return tr(key, language, default)


__all__ = [
    "SUPPORTED_LANGUAGES",
    "has_translation",
    "load_translations",
    "tr",
    "translate_for",
]
