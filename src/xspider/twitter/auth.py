"""Token Pool management with rotation and rate limit awareness."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from xspider.core import AuthenticationError, RateLimitError, get_logger

if TYPE_CHECKING:
    from xspider.core.config import TwitterToken


logger = get_logger(__name__)


@dataclass
class TokenState:
    """State tracking for a single token."""

    token: "TwitterToken"
    is_valid: bool = True
    is_rate_limited: bool = False
    rate_limit_reset_at: float = 0.0
    request_count: int = 0
    error_count: int = 0
    last_used_at: float = 0.0
    consecutive_errors: int = 0

    def mark_rate_limited(self, reset_after_seconds: float = 900.0) -> None:
        """Mark token as rate limited."""
        self.is_rate_limited = True
        self.rate_limit_reset_at = time.time() + reset_after_seconds
        logger.warning(
            "Token rate limited",
            extra={
                "bearer_token_prefix": self.token.bearer_token[:20],
                "reset_after_seconds": reset_after_seconds,
            },
        )

    def mark_invalid(self) -> None:
        """Mark token as invalid (authentication failed)."""
        self.is_valid = False
        logger.error(
            "Token marked invalid",
            extra={"bearer_token_prefix": self.token.bearer_token[:20]},
        )

    def mark_success(self) -> None:
        """Mark successful request."""
        self.request_count += 1
        self.last_used_at = time.time()
        self.consecutive_errors = 0

    def mark_error(self) -> None:
        """Mark request error."""
        self.error_count += 1
        self.consecutive_errors += 1
        self.last_used_at = time.time()

    def is_available(self) -> bool:
        """Check if token is available for use."""
        if not self.is_valid:
            return False
        if self.is_rate_limited:
            if time.time() >= self.rate_limit_reset_at:
                self.is_rate_limited = False
                self.rate_limit_reset_at = 0.0
                logger.info(
                    "Token rate limit reset",
                    extra={"bearer_token_prefix": self.token.bearer_token[:20]},
                )
                return True
            return False
        return True

    def time_until_available(self) -> float:
        """Get seconds until token becomes available."""
        if not self.is_valid:
            return float("inf")
        if self.is_rate_limited:
            remaining = self.rate_limit_reset_at - time.time()
            return max(0.0, remaining)
        return 0.0


@dataclass
class TokenPool:
    """Manages a pool of Twitter tokens with rotation and rate limit awareness."""

    tokens: list[TokenState] = field(default_factory=list)
    current_index: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    max_consecutive_errors: int = 5

    @classmethod
    def from_tokens(cls, tokens: list["TwitterToken"]) -> "TokenPool":
        """Create a TokenPool from a list of TwitterToken objects."""
        pool = cls()
        for token in tokens:
            pool.tokens.append(TokenState(token=token))
        logger.info("Token pool initialized", extra={"token_count": len(tokens)})
        return pool

    def __len__(self) -> int:
        """Return number of tokens in pool."""
        return len(self.tokens)

    @property
    def available_count(self) -> int:
        """Count of available tokens."""
        return sum(1 for t in self.tokens if t.is_available())

    @property
    def valid_count(self) -> int:
        """Count of valid tokens."""
        return sum(1 for t in self.tokens if t.is_valid)

    async def get_token(self) -> "TwitterToken":
        """Get the next available token using round-robin rotation.

        Raises:
            AuthenticationError: If no valid tokens are available.
            RateLimitError: If all tokens are rate limited.
        """
        async with self._lock:
            if not self.tokens:
                raise AuthenticationError("No tokens configured in pool")

            available_tokens = [t for t in self.tokens if t.is_available()]

            if available_tokens:
                self.current_index = (self.current_index + 1) % len(self.tokens)
                while not self.tokens[self.current_index].is_available():
                    self.current_index = (self.current_index + 1) % len(self.tokens)
                return self.tokens[self.current_index].token

            valid_tokens = [t for t in self.tokens if t.is_valid]
            if not valid_tokens:
                raise AuthenticationError("All tokens are invalid")

            rate_limited = [t for t in valid_tokens if t.is_rate_limited]
            if rate_limited:
                min_wait = min(t.time_until_available() for t in rate_limited)
                raise RateLimitError(
                    f"All tokens rate limited. Retry after {min_wait:.0f}s",
                    retry_after=int(min_wait),
                )

            raise AuthenticationError("No available tokens")

    async def get_token_with_wait(
        self, max_wait_seconds: float = 900.0
    ) -> "TwitterToken":
        """Get a token, waiting if necessary for rate limits to reset.

        Args:
            max_wait_seconds: Maximum time to wait for a token.

        Returns:
            An available TwitterToken.

        Raises:
            AuthenticationError: If no valid tokens exist.
            RateLimitError: If wait time exceeds max_wait_seconds.
        """
        try:
            return await self.get_token()
        except RateLimitError as e:
            if e.retry_after and e.retry_after <= max_wait_seconds:
                logger.info(
                    "Waiting for token rate limit reset",
                    extra={"wait_seconds": e.retry_after},
                )
                await asyncio.sleep(e.retry_after)
                return await self.get_token()
            raise

    def mark_token_rate_limited(
        self, token: "TwitterToken", reset_after_seconds: float = 900.0
    ) -> None:
        """Mark a token as rate limited."""
        for state in self.tokens:
            if state.token == token:
                state.mark_rate_limited(reset_after_seconds)
                break

    def mark_token_invalid(self, token: "TwitterToken") -> None:
        """Mark a token as invalid."""
        for state in self.tokens:
            if state.token == token:
                state.mark_invalid()
                break

    def mark_token_success(self, token: "TwitterToken") -> None:
        """Mark a successful request for a token."""
        for state in self.tokens:
            if state.token == token:
                state.mark_success()
                break

    def mark_token_error(self, token: "TwitterToken") -> None:
        """Mark a request error for a token."""
        for state in self.tokens:
            if state.token == token:
                state.mark_error()
                if state.consecutive_errors >= self.max_consecutive_errors:
                    logger.warning(
                        "Token exceeded max consecutive errors",
                        extra={
                            "bearer_token_prefix": token.bearer_token[:20],
                            "consecutive_errors": state.consecutive_errors,
                        },
                    )
                break

    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "total_tokens": len(self.tokens),
            "valid_tokens": self.valid_count,
            "available_tokens": self.available_count,
            "rate_limited_tokens": sum(1 for t in self.tokens if t.is_rate_limited),
            "invalid_tokens": sum(1 for t in self.tokens if not t.is_valid),
            "total_requests": sum(t.request_count for t in self.tokens),
            "total_errors": sum(t.error_count for t in self.tokens),
        }

    def reset_rate_limits(self) -> None:
        """Reset rate limit status for all tokens."""
        for state in self.tokens:
            state.is_rate_limited = False
            state.rate_limit_reset_at = 0.0
        logger.info("All token rate limits reset")

    def reset_all(self) -> None:
        """Reset all token states."""
        for state in self.tokens:
            state.is_valid = True
            state.is_rate_limited = False
            state.rate_limit_reset_at = 0.0
            state.request_count = 0
            state.error_count = 0
            state.consecutive_errors = 0
        logger.info("All token states reset")
