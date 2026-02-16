"""Token bucket rate limiter for API request throttling."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from xspider.core import RateLimitError, get_logger


logger = get_logger(__name__)


@dataclass
class TokenBucket:
    """Token bucket rate limiter implementation.

    Uses the token bucket algorithm to control request rates.
    Tokens are added at a fixed rate, and each request consumes one token.
    """

    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill_at: float = field(default_factory=time.time)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        """Initialize tokens to capacity."""
        self.tokens = self.capacity

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill_at
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill_at = now

    async def acquire(self, tokens: float = 1.0, wait: bool = True) -> bool:
        """Acquire tokens from the bucket.

        Args:
            tokens: Number of tokens to acquire.
            wait: If True, wait until tokens are available. If False, return False immediately.

        Returns:
            True if tokens were acquired, False if not (only when wait=False).

        Raises:
            RateLimitError: If tokens > capacity.
        """
        if tokens > self.capacity:
            raise RateLimitError(
                f"Requested tokens ({tokens}) exceeds bucket capacity ({self.capacity})"
            )

        async with self._lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            if not wait:
                return False

            wait_time = (tokens - self.tokens) / self.refill_rate
            logger.debug(
                "Rate limiter waiting",
                extra={"wait_seconds": wait_time, "tokens_needed": tokens},
            )
            await asyncio.sleep(wait_time)

            self._refill()
            self.tokens -= tokens
            return True

    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens without waiting.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens were acquired, False otherwise.
        """
        return await self.acquire(tokens, wait=False)

    def time_until_available(self, tokens: float = 1.0) -> float:
        """Get time until specified tokens will be available.

        Args:
            tokens: Number of tokens needed.

        Returns:
            Seconds until tokens will be available.
        """
        self._refill()
        if self.tokens >= tokens:
            return 0.0
        return (tokens - self.tokens) / self.refill_rate

    def available_tokens(self) -> float:
        """Get current available tokens."""
        self._refill()
        return self.tokens

    def reset(self) -> None:
        """Reset bucket to full capacity."""
        self.tokens = self.capacity
        self.last_refill_at = time.time()


@dataclass
class EndpointRateLimiter:
    """Rate limiter for specific API endpoints.

    Different endpoints may have different rate limits.
    """

    buckets: dict[str, TokenBucket] = field(default_factory=dict)
    default_capacity: float = 50.0
    default_refill_rate: float = 1.0  # tokens per second
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def configure_endpoint(
        self,
        endpoint: str,
        capacity: float,
        refill_rate: float,
    ) -> None:
        """Configure rate limit for a specific endpoint.

        Args:
            endpoint: Endpoint identifier.
            capacity: Maximum tokens (requests) in bucket.
            refill_rate: Token refill rate per second.
        """
        self.buckets[endpoint] = TokenBucket(
            capacity=capacity,
            refill_rate=refill_rate,
        )
        logger.debug(
            "Endpoint rate limit configured",
            extra={
                "endpoint": endpoint,
                "capacity": capacity,
                "refill_rate": refill_rate,
            },
        )

    def _get_bucket(self, endpoint: str) -> TokenBucket:
        """Get or create bucket for endpoint."""
        if endpoint not in self.buckets:
            self.buckets[endpoint] = TokenBucket(
                capacity=self.default_capacity,
                refill_rate=self.default_refill_rate,
            )
        return self.buckets[endpoint]

    async def acquire(
        self, endpoint: str, tokens: float = 1.0, wait: bool = True
    ) -> bool:
        """Acquire tokens for an endpoint.

        Args:
            endpoint: Endpoint identifier.
            tokens: Number of tokens to acquire.
            wait: If True, wait until tokens are available.

        Returns:
            True if tokens were acquired.
        """
        bucket = self._get_bucket(endpoint)
        return await bucket.acquire(tokens, wait)

    async def try_acquire(self, endpoint: str, tokens: float = 1.0) -> bool:
        """Try to acquire tokens without waiting."""
        bucket = self._get_bucket(endpoint)
        return await bucket.try_acquire(tokens)

    def time_until_available(self, endpoint: str, tokens: float = 1.0) -> float:
        """Get time until tokens available for endpoint."""
        bucket = self._get_bucket(endpoint)
        return bucket.time_until_available(tokens)

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics."""
        return {
            endpoint: {
                "available_tokens": bucket.available_tokens(),
                "capacity": bucket.capacity,
                "refill_rate": bucket.refill_rate,
            }
            for endpoint, bucket in self.buckets.items()
        }

    def reset_endpoint(self, endpoint: str) -> None:
        """Reset rate limit for a specific endpoint."""
        if endpoint in self.buckets:
            self.buckets[endpoint].reset()

    def reset_all(self) -> None:
        """Reset all endpoint rate limits."""
        for bucket in self.buckets.values():
            bucket.reset()


@dataclass
class AdaptiveRateLimiter:
    """Rate limiter that adapts based on server responses.

    Automatically adjusts rate limits based on rate limit headers
    and error responses from the server.
    """

    base_limiter: EndpointRateLimiter = field(default_factory=EndpointRateLimiter)
    min_capacity: float = 5.0
    max_capacity: float = 100.0
    backoff_factor: float = 0.5
    recovery_factor: float = 1.1
    _consecutive_successes: dict[str, int] = field(default_factory=dict)
    _consecutive_rate_limits: dict[str, int] = field(default_factory=dict)

    async def acquire(
        self, endpoint: str, tokens: float = 1.0, wait: bool = True
    ) -> bool:
        """Acquire tokens with adaptive behavior."""
        return await self.base_limiter.acquire(endpoint, tokens, wait)

    def on_success(self, endpoint: str) -> None:
        """Record successful request, potentially increasing rate."""
        self._consecutive_successes[endpoint] = (
            self._consecutive_successes.get(endpoint, 0) + 1
        )
        self._consecutive_rate_limits[endpoint] = 0

        if self._consecutive_successes[endpoint] >= 10:
            bucket = self.base_limiter._get_bucket(endpoint)
            new_capacity = min(
                self.max_capacity, bucket.capacity * self.recovery_factor
            )
            if new_capacity != bucket.capacity:
                bucket.capacity = new_capacity
                logger.debug(
                    "Rate limit capacity increased",
                    extra={"endpoint": endpoint, "new_capacity": new_capacity},
                )
            self._consecutive_successes[endpoint] = 0

    def on_rate_limit(
        self,
        endpoint: str,
        retry_after: float | None = None,
    ) -> None:
        """Record rate limit response, reducing rate."""
        self._consecutive_rate_limits[endpoint] = (
            self._consecutive_rate_limits.get(endpoint, 0) + 1
        )
        self._consecutive_successes[endpoint] = 0

        bucket = self.base_limiter._get_bucket(endpoint)

        new_capacity = max(self.min_capacity, bucket.capacity * self.backoff_factor)
        bucket.capacity = new_capacity
        bucket.tokens = min(bucket.tokens, new_capacity)

        logger.warning(
            "Rate limit hit, reducing capacity",
            extra={
                "endpoint": endpoint,
                "new_capacity": new_capacity,
                "retry_after": retry_after,
                "consecutive_rate_limits": self._consecutive_rate_limits[endpoint],
            },
        )

    def on_rate_limit_headers(
        self,
        endpoint: str,
        limit: int | None = None,
        remaining: int | None = None,
        reset: float | None = None,
    ) -> None:
        """Update rate limiter based on response headers.

        Args:
            endpoint: Endpoint identifier.
            limit: X-Rate-Limit-Limit header value.
            remaining: X-Rate-Limit-Remaining header value.
            reset: X-Rate-Limit-Reset header value (Unix timestamp).
        """
        bucket = self.base_limiter._get_bucket(endpoint)

        if limit is not None:
            bucket.capacity = min(self.max_capacity, float(limit))

        if remaining is not None:
            bucket.tokens = min(bucket.capacity, float(remaining))

        if reset is not None:
            time_until_reset = max(0.0, reset - time.time())
            if time_until_reset > 0 and limit:
                bucket.refill_rate = limit / time_until_reset

    def get_stats(self) -> dict[str, Any]:
        """Get adaptive rate limiter statistics."""
        return {
            "base_stats": self.base_limiter.get_stats(),
            "consecutive_successes": dict(self._consecutive_successes),
            "consecutive_rate_limits": dict(self._consecutive_rate_limits),
        }

    def reset_all(self) -> None:
        """Reset all rate limiters and counters."""
        self.base_limiter.reset_all()
        self._consecutive_successes.clear()
        self._consecutive_rate_limits.clear()
