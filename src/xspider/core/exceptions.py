"""Custom exceptions for xspider."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class XSpiderError(Exception):
    """Base exception for all xspider errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class RateLimitError(XSpiderError):
    """Raised when Twitter rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        reset_time: datetime | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(
            message,
            details={
                "reset_time": reset_time.isoformat() if reset_time else None,
                "retry_after": retry_after,
            },
        )
        self.reset_time = reset_time
        self.retry_after = retry_after


class RateLimitExhausted(RateLimitError):
    """Raised when all tokens in the pool are rate limited."""

    def __init__(self, earliest_reset: datetime) -> None:
        super().__init__(
            message="All tokens exhausted",
            reset_time=earliest_reset,
        )


class AuthenticationError(XSpiderError):
    """Raised when Twitter authentication fails."""

    def __init__(self, message: str = "Authentication failed", token_id: str | None = None) -> None:
        super().__init__(message, details={"token_id": token_id})
        self.token_id = token_id


class ScrapingError(XSpiderError):
    """Raised when scraping operation fails."""

    def __init__(
        self,
        message: str,
        user_id: str | None = None,
        endpoint: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            details={
                "user_id": user_id,
                "endpoint": endpoint,
                "status_code": status_code,
            },
        )
        self.user_id = user_id
        self.endpoint = endpoint
        self.status_code = status_code


class GraphError(XSpiderError):
    """Raised when graph operations fail."""

    def __init__(
        self,
        message: str,
        node_count: int | None = None,
        edge_count: int | None = None,
    ) -> None:
        super().__init__(
            message,
            details={"node_count": node_count, "edge_count": edge_count},
        )


class AuditError(XSpiderError):
    """Raised when AI audit operation fails."""

    def __init__(
        self,
        message: str,
        user_id: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            message,
            details={"user_id": user_id, "model": model},
        )


class DatabaseError(XSpiderError):
    """Raised when database operations fail."""

    def __init__(self, message: str, operation: str | None = None) -> None:
        super().__init__(message, details={"operation": operation})


class ProxyError(XSpiderError):
    """Raised when proxy operations fail."""

    def __init__(self, message: str, proxy_url: str | None = None) -> None:
        super().__init__(message, details={"proxy_url": proxy_url})


class NoHealthyProxyError(ProxyError):
    """Raised when no healthy proxies are available."""

    def __init__(self) -> None:
        super().__init__("No healthy proxies available")
