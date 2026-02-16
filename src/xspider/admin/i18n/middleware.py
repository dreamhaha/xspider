"""i18n middleware for language detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from xspider.admin.i18n.translator import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.types import ASGIApp


class I18nMiddleware(BaseHTTPMiddleware):
    """Middleware to detect language from Accept-Language header."""

    def __init__(self, app: ASGIApp) -> None:
        """Initialize middleware."""
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        """
        Extract language from Accept-Language header and store in request.state.

        The Accept-Language header format:
            Accept-Language: zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7

        This middleware:
        1. Parses the header
        2. Extracts the primary language (highest priority)
        3. Normalizes to supported language (zh, en, ja)
        4. Stores in request.state.lang
        """
        accept_language = request.headers.get("Accept-Language", "")
        lang = self._parse_accept_language(accept_language)
        request.state.lang = lang

        return await call_next(request)

    def _parse_accept_language(self, header: str) -> str:
        """
        Parse Accept-Language header and return best matching language.

        Args:
            header: Accept-Language header value

        Returns:
            Language code (en, zh, or ja)
        """
        if not header:
            return DEFAULT_LANGUAGE

        # Parse language preferences
        languages: list[tuple[str, float]] = []

        for part in header.split(","):
            part = part.strip()
            if not part:
                continue

            # Handle quality factor (q=0.8)
            if ";q=" in part:
                lang_part, q_part = part.split(";q=", 1)
                try:
                    quality = float(q_part)
                except ValueError:
                    quality = 1.0
            else:
                lang_part = part
                quality = 1.0

            # Normalize language code (zh-CN -> zh)
            lang_code = lang_part.strip().lower().split("-")[0]
            languages.append((lang_code, quality))

        # Sort by quality (highest first)
        languages.sort(key=lambda x: x[1], reverse=True)

        # Return first supported language
        for lang_code, _ in languages:
            if lang_code in SUPPORTED_LANGUAGES:
                return lang_code

        return DEFAULT_LANGUAGE


def get_lang(request: Request) -> str:
    """
    Get language from request state.

    Usage as FastAPI dependency:
        @router.post("/login")
        async def login(lang: str = Depends(get_lang)):
            raise HTTPException(detail=t("auth.invalid_credentials", lang))
    """
    return getattr(request.state, "lang", DEFAULT_LANGUAGE)
