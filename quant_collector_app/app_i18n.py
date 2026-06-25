from __future__ import annotations

try:
    from i18n import SUPPORTED_LANGUAGES, has_translation, load_translations, tr
except ImportError:  # pragma: no cover - package import path
    from .i18n import SUPPORTED_LANGUAGES, has_translation, load_translations, tr


__all__ = ["SUPPORTED_LANGUAGES", "has_translation", "load_translations", "tr"]
