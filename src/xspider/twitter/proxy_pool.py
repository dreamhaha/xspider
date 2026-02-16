"""Proxy pool management with rotation and health tracking."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum

from xspider.core import ScrapingError, get_logger


logger = get_logger(__name__)


class ProxyProtocol(str, Enum):
    """Supported proxy protocols."""

    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


@dataclass
class ProxyState:
    """State tracking for a single proxy."""

    url: str
    is_healthy: bool = True
    is_blocked: bool = False
    blocked_until: float = 0.0
    request_count: int = 0
    error_count: int = 0
    consecutive_errors: int = 0
    last_used_at: float = 0.0
    last_error_at: float = 0.0
    avg_response_time_ms: float = 0.0
    _response_times: list[float] = field(default_factory=list)

    def mark_success(self, response_time_ms: float = 0.0) -> None:
        """Mark a successful request."""
        self.request_count += 1
        self.last_used_at = time.time()
        self.consecutive_errors = 0
        self.is_healthy = True
        if response_time_ms > 0:
            self._response_times.append(response_time_ms)
            if len(self._response_times) > 100:
                self._response_times = self._response_times[-100:]
            self.avg_response_time_ms = sum(self._response_times) / len(
                self._response_times
            )

    def mark_error(self, block_seconds: float = 0.0) -> None:
        """Mark a request error."""
        self.error_count += 1
        self.consecutive_errors += 1
        self.last_error_at = time.time()
        self.last_used_at = time.time()

        if self.consecutive_errors >= 3:
            self.is_healthy = False

        if block_seconds > 0:
            self.is_blocked = True
            self.blocked_until = time.time() + block_seconds

    def mark_blocked(self, block_seconds: float = 300.0) -> None:
        """Mark proxy as blocked."""
        self.is_blocked = True
        self.blocked_until = time.time() + block_seconds
        logger.warning(
            "Proxy blocked",
            extra={
                "proxy_url": self._masked_url(),
                "block_seconds": block_seconds,
            },
        )

    def is_available(self) -> bool:
        """Check if proxy is available for use."""
        if not self.is_healthy:
            return False
        if self.is_blocked:
            if time.time() >= self.blocked_until:
                self.is_blocked = False
                self.blocked_until = 0.0
                return True
            return False
        return True

    def time_until_available(self) -> float:
        """Get seconds until proxy becomes available."""
        if not self.is_healthy:
            return float("inf")
        if self.is_blocked:
            remaining = self.blocked_until - time.time()
            return max(0.0, remaining)
        return 0.0

    def _masked_url(self) -> str:
        """Return masked URL for logging."""
        if "@" in self.url:
            protocol, rest = self.url.split("://", 1)
            creds, host = rest.rsplit("@", 1)
            return f"{protocol}://****:****@{host}"
        return self.url


@dataclass
class ProxyPool:
    """Manages a pool of proxies with rotation and health tracking."""

    proxies: list[ProxyState] = field(default_factory=list)
    current_index: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    max_consecutive_errors: int = 5
    allow_no_proxy: bool = True

    @classmethod
    def from_urls(cls, urls: list[str], allow_no_proxy: bool = True) -> "ProxyPool":
        """Create a ProxyPool from a list of proxy URLs."""
        pool = cls(allow_no_proxy=allow_no_proxy)
        for url in urls:
            if url.strip():
                pool.proxies.append(ProxyState(url=url.strip()))
        logger.info("Proxy pool initialized", extra={"proxy_count": len(pool.proxies)})
        return pool

    def __len__(self) -> int:
        """Return number of proxies in pool."""
        return len(self.proxies)

    @property
    def available_count(self) -> int:
        """Count of available proxies."""
        return sum(1 for p in self.proxies if p.is_available())

    @property
    def healthy_count(self) -> int:
        """Count of healthy proxies."""
        return sum(1 for p in self.proxies if p.is_healthy)

    async def get_proxy(self) -> str | None:
        """Get the next available proxy using round-robin rotation.

        Returns:
            Proxy URL or None if no proxy should be used.

        Raises:
            ScrapingError: If no proxies are available and allow_no_proxy is False.
        """
        async with self._lock:
            if not self.proxies:
                if self.allow_no_proxy:
                    return None
                raise ScrapingError("No proxies configured in pool")

            available_proxies = [p for p in self.proxies if p.is_available()]

            if available_proxies:
                self.current_index = (self.current_index + 1) % len(self.proxies)
                attempts = 0
                while (
                    not self.proxies[self.current_index].is_available()
                    and attempts < len(self.proxies)
                ):
                    self.current_index = (self.current_index + 1) % len(self.proxies)
                    attempts += 1
                if self.proxies[self.current_index].is_available():
                    return self.proxies[self.current_index].url

            if self.allow_no_proxy:
                logger.warning("No available proxies, proceeding without proxy")
                return None

            healthy = [p for p in self.proxies if p.is_healthy]
            if not healthy:
                raise ScrapingError("All proxies are unhealthy")

            blocked = [p for p in healthy if p.is_blocked]
            if blocked:
                min_wait = min(p.time_until_available() for p in blocked)
                raise ScrapingError(
                    f"All proxies blocked. Retry after {min_wait:.0f}s"
                )

            raise ScrapingError("No available proxies")

    async def get_proxy_with_wait(
        self, max_wait_seconds: float = 300.0
    ) -> str | None:
        """Get a proxy, waiting if necessary for blocks to clear.

        Args:
            max_wait_seconds: Maximum time to wait for a proxy.

        Returns:
            Proxy URL or None if no proxy should be used.
        """
        try:
            return await self.get_proxy()
        except ScrapingError:
            if self.allow_no_proxy:
                return None

            blocked = [p for p in self.proxies if p.is_blocked and p.is_healthy]
            if blocked:
                min_wait = min(p.time_until_available() for p in blocked)
                if min_wait <= max_wait_seconds:
                    logger.info(
                        "Waiting for proxy block to clear",
                        extra={"wait_seconds": min_wait},
                    )
                    await asyncio.sleep(min_wait)
                    return await self.get_proxy()
            raise

    def mark_proxy_success(
        self, proxy_url: str | None, response_time_ms: float = 0.0
    ) -> None:
        """Mark a successful request for a proxy."""
        if proxy_url is None:
            return
        for state in self.proxies:
            if state.url == proxy_url:
                state.mark_success(response_time_ms)
                break

    def mark_proxy_error(
        self, proxy_url: str | None, block_seconds: float = 0.0
    ) -> None:
        """Mark a request error for a proxy."""
        if proxy_url is None:
            return
        for state in self.proxies:
            if state.url == proxy_url:
                state.mark_error(block_seconds)
                if state.consecutive_errors >= self.max_consecutive_errors:
                    logger.warning(
                        "Proxy exceeded max consecutive errors",
                        extra={
                            "proxy_url": state._masked_url(),
                            "consecutive_errors": state.consecutive_errors,
                        },
                    )
                break

    def mark_proxy_blocked(
        self, proxy_url: str | None, block_seconds: float = 300.0
    ) -> None:
        """Mark a proxy as blocked."""
        if proxy_url is None:
            return
        for state in self.proxies:
            if state.url == proxy_url:
                state.mark_blocked(block_seconds)
                break

    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "total_proxies": len(self.proxies),
            "healthy_proxies": self.healthy_count,
            "available_proxies": self.available_count,
            "blocked_proxies": sum(1 for p in self.proxies if p.is_blocked),
            "unhealthy_proxies": sum(1 for p in self.proxies if not p.is_healthy),
            "total_requests": sum(p.request_count for p in self.proxies),
            "total_errors": sum(p.error_count for p in self.proxies),
            "avg_response_time_ms": (
                sum(p.avg_response_time_ms for p in self.proxies) / len(self.proxies)
                if self.proxies
                else 0.0
            ),
        }

    def reset_blocks(self) -> None:
        """Reset block status for all proxies."""
        for state in self.proxies:
            state.is_blocked = False
            state.blocked_until = 0.0
        logger.info("All proxy blocks reset")

    def reset_health(self) -> None:
        """Reset health status for all proxies."""
        for state in self.proxies:
            state.is_healthy = True
            state.consecutive_errors = 0
        logger.info("All proxy health reset")

    def reset_all(self) -> None:
        """Reset all proxy states."""
        for state in self.proxies:
            state.is_healthy = True
            state.is_blocked = False
            state.blocked_until = 0.0
            state.request_count = 0
            state.error_count = 0
            state.consecutive_errors = 0
            state._response_times = []
            state.avg_response_time_ms = 0.0
        logger.info("All proxy states reset")

    def remove_unhealthy(self) -> int:
        """Remove unhealthy proxies from the pool.

        Returns:
            Number of proxies removed.
        """
        initial_count = len(self.proxies)
        self.proxies = [p for p in self.proxies if p.is_healthy]
        removed = initial_count - len(self.proxies)
        if removed > 0:
            logger.info("Removed unhealthy proxies", extra={"removed_count": removed})
        return removed

    def add_proxy(self, url: str) -> None:
        """Add a new proxy to the pool."""
        if url.strip():
            self.proxies.append(ProxyState(url=url.strip()))
            logger.info("Proxy added to pool", extra={"proxy_count": len(self.proxies)})
