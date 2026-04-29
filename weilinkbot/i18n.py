"""Internationalization — loads JSON translation files, exposes t() function."""

from __future__ import annotations

import json
import locale
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

LOCALES_DIR = Path(__file__).parent / "locales"

_translations: dict[str, dict[str, str]] = {}  # lang_code -> {key: text}
_current_lang: str = "en"
_fallback_lang: str = "en"


def init(lang: str | None = None) -> None:
    """Load all translation files and set current language.

    Priority: lang argument > WEILINKBOT_LANGUAGE env > system locale > "en"
    """
    global _current_lang
    _current_lang = lang or _detect_language()

    _translations.clear()
    for f in LOCALES_DIR.glob("*.json"):
        code = f.stem  # "en", "zh-CN"
        _translations[code] = json.loads(f.read_text("utf-8"))
        logger.info("Loaded locale: %s (%d keys)", code, len(_translations[code]))

    if _current_lang not in _translations:
        logger.warning("Locale '%s' not found, falling back to '%s'", _current_lang, _fallback_lang)
        _current_lang = _fallback_lang


def t(key: str, **kwargs) -> str:
    """Translate a key to the current language.

    Falls back to English, then returns the key itself.
    Supports {name} placeholders via kwargs.
    """
    text = _translations.get(_current_lang, {}).get(key)
    if text is None:
        text = _translations.get(_fallback_lang, {}).get(key)
    if text is None:
        return key
    return text.format(**kwargs) if kwargs else text


def get_lang() -> str:
    """Return the current language code."""
    return _current_lang


def set_lang(lang: str) -> bool:
    """Set the current language at runtime. Returns True if successful."""
    global _current_lang
    if lang in _translations:
        _current_lang = lang
        logger.info("Language switched to '%s'", lang)
        return True
    logger.warning("Locale '%s' not found, keeping '%s'", lang, _current_lang)
    return False


def get_available_langs() -> list[str]:
    """Return list of available language codes."""
    return list(_translations.keys())


def _detect_language() -> str:
    """Detect language from env var or system locale."""
    # 1. Explicit env var
    env_lang = os.environ.get("WEILINKBOT_LANGUAGE")
    if env_lang:
        return env_lang

    # 2. System locale
    try:
        sys_locale = locale.getlocale()[0] or ""
    except Exception:
        sys_locale = ""

    if sys_locale.startswith("zh"):
        return "zh-CN"

    return "en"
