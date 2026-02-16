"""Internationalization (i18n) module for xspider admin."""

from xspider.admin.i18n.middleware import I18nMiddleware, get_lang
from xspider.admin.i18n.translator import Translator, get_all_translations, get_text, t

__all__ = [
    "I18nMiddleware",
    "Translator",
    "get_all_translations",
    "get_lang",
    "get_text",
    "t",
]
