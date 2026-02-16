"""Translation lookup module for i18n support."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

# Supported languages
SUPPORTED_LANGUAGES = ("en", "zh", "ja")
DEFAULT_LANGUAGE = "en"

# Module directory for locales
LOCALES_DIR = Path(__file__).parent / "locales"

logger = logging.getLogger(__name__)


class Translator:
    """Handles translation lookups with nested key support."""

    _instance: Translator | None = None
    _lock = threading.Lock()
    _translations: dict[str, dict[str, Any]]

    def __new__(cls) -> Translator:
        """Thread-safe singleton pattern to avoid reloading translations."""
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._translations = {}
                    cls._instance._load_translations()
        return cls._instance

    def _load_translations(self) -> None:
        """Load all translation files at startup with error handling."""
        for lang in SUPPORTED_LANGUAGES:
            locale_file = LOCALES_DIR / f"{lang}.json"
            if locale_file.exists():
                try:
                    with open(locale_file, encoding="utf-8") as f:
                        self._translations[lang] = json.load(f)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in {locale_file}: {e}")
                    self._translations[lang] = {}
                except OSError as e:
                    logger.error(f"Failed to read {locale_file}: {e}")
                    self._translations[lang] = {}
            else:
                logger.warning(f"Translation file not found: {locale_file}")
                self._translations[lang] = {}

    def get_text(
        self,
        key: str,
        lang: str = DEFAULT_LANGUAGE,
        **kwargs: Any,
    ) -> str:
        """
        Get translated text for a nested key.

        Args:
            key: Dot-separated key path (e.g., "auth.invalid_credentials")
            lang: Language code (en, zh, ja)
            **kwargs: Placeholder substitutions (e.g., name="John")

        Returns:
            Translated string with placeholders replaced
        """
        # Normalize language code
        lang = self._normalize_lang(lang)

        # Get translation from specified language
        text = self._lookup_key(key, lang)

        # Fallback to English if not found
        if text is None and lang != DEFAULT_LANGUAGE:
            text = self._lookup_key(key, DEFAULT_LANGUAGE)

        # Return key if still not found
        if text is None:
            return key

        # Replace placeholders with sanitized values
        if kwargs:
            for placeholder, value in kwargs.items():
                # Sanitize value to prevent nested placeholder injection
                safe_value = str(value).replace("{", "{{").replace("}", "}}")
                text = text.replace(f"{{{placeholder}}}", safe_value)

        return text

    def _normalize_lang(self, lang: str) -> str:
        """Normalize language code to supported format."""
        if not lang:
            return DEFAULT_LANGUAGE

        # Handle language codes like "zh-CN", "ja-JP", etc.
        lang = lang.lower().split("-")[0].split("_")[0]

        return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    def _lookup_key(self, key: str, lang: str) -> str | None:
        """Look up a nested key in translations."""
        translations = self._translations.get(lang, {})
        parts = key.split(".")

        current = translations
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current if isinstance(current, str) else None

    def get_all_translations(self, lang: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        """Get all translations for a language (for frontend use)."""
        lang = self._normalize_lang(lang)
        return self._translations.get(lang, self._translations.get(DEFAULT_LANGUAGE, {}))


# Global translator instance
_translator = Translator()


def get_text(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    """
    Get translated text for a key.

    Convenience function that uses the global translator instance.

    Args:
        key: Dot-separated key path (e.g., "auth.invalid_credentials")
        lang: Language code (en, zh, ja)
        **kwargs: Placeholder substitutions

    Returns:
        Translated string
    """
    return _translator.get_text(key, lang, **kwargs)


def t(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    """
    Shorthand alias for get_text.

    Usage:
        t("auth.invalid_credentials", "zh")
        t("users.password_reset", "en", username="admin")
    """
    return get_text(key, lang, **kwargs)


def get_all_translations(lang: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    """Get all translations for a language."""
    return _translator.get_all_translations(lang)
