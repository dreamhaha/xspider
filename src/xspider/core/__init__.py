"""Core module - configuration, logging, exceptions."""

from xspider.core.config import Settings, get_settings
from xspider.core.exceptions import (
    XSpiderError,
    RateLimitError,
    AuthenticationError,
    ScrapingError,
    GraphError,
    AuditError,
)
from xspider.core.logging import setup_logging, get_logger

__all__ = [
    "Settings",
    "get_settings",
    "XSpiderError",
    "RateLimitError",
    "AuthenticationError",
    "ScrapingError",
    "GraphError",
    "AuditError",
    "setup_logging",
    "get_logger",
]
