"""Rate limiter specifically for Twitter mutation operations (POST).

Mutation operations (posting, replying, liking, etc.) have much stricter limits
than read operations to avoid account bans and shadowbans.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from xspider.core import RateLimitError, get_logger


logger = get_logger(__name__)


@dataclass
class MutationLimits:
    """Rate limits for different mutation types per time period."""

    # Per hour limits (conservative to avoid bans)
    tweets_per_hour: int = 5
    replies_per_hour: int = 20
    likes_per_hour: int = 50
    retweets_per_hour: int = 20
    dms_per_hour: int = 20

    # Per day limits
    tweets_per_day: int = 50
    replies_per_day: int = 200
    likes_per_day: int = 500
    retweets_per_day: int = 200
    dms_per_day: int = 50

    # Minimum delay between same-type operations (seconds)
    min_tweet_delay: float = 30.0
    min_reply_delay: float = 10.0
    min_like_delay: float = 2.0
    min_retweet_delay: float = 5.0
    min_dm_delay: float = 30.0


@dataclass
class MutationCounter:
    """Tracks mutation counts for rate limiting."""

    hourly_count: int = 0
    daily_count: int = 0
    hour_start: float = field(default_factory=time.time)
    day_start: float = field(default_factory=time.time)
    last_operation: float = 0.0

    def reset_if_needed(self) -> None:
        """Reset counters if time periods have elapsed."""
        now = time.time()

        # Reset hourly counter
        if now - self.hour_start >= 3600:
            self.hourly_count = 0
            self.hour_start = now

        # Reset daily counter
        if now - self.day_start >= 86400:
            self.daily_count = 0
            self.day_start = now

    def can_proceed(
        self,
        hourly_limit: int,
        daily_limit: int,
        min_delay: float,
    ) -> tuple[bool, float]:
        """Check if operation can proceed.

        Returns:
            Tuple of (can_proceed, wait_time_seconds).
        """
        self.reset_if_needed()
        now = time.time()

        # Check hourly limit
        if self.hourly_count >= hourly_limit:
            wait_until = self.hour_start + 3600
            return False, max(0, wait_until - now)

        # Check daily limit
        if self.daily_count >= daily_limit:
            wait_until = self.day_start + 86400
            return False, max(0, wait_until - now)

        # Check minimum delay
        if self.last_operation > 0:
            time_since_last = now - self.last_operation
            if time_since_last < min_delay:
                return False, min_delay - time_since_last

        return True, 0.0

    def record_operation(self) -> None:
        """Record that an operation was performed."""
        self.reset_if_needed()
        self.hourly_count += 1
        self.daily_count += 1
        self.last_operation = time.time()


@dataclass
class MutationRateLimiter:
    """Rate limiter for Twitter mutation operations.

    Enforces conservative limits to prevent account bans and shadowbans.
    Each account should have its own instance of this limiter.
    """

    account_id: str
    limits: MutationLimits = field(default_factory=MutationLimits)
    _counters: dict[str, MutationCounter] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _get_counter(self, operation_type: str) -> MutationCounter:
        """Get or create counter for operation type."""
        if operation_type not in self._counters:
            self._counters[operation_type] = MutationCounter()
        return self._counters[operation_type]

    def _get_limits_for_operation(
        self, operation_type: str
    ) -> tuple[int, int, float]:
        """Get hourly limit, daily limit, and min delay for operation type."""
        limits_map = {
            "tweet": (
                self.limits.tweets_per_hour,
                self.limits.tweets_per_day,
                self.limits.min_tweet_delay,
            ),
            "reply": (
                self.limits.replies_per_hour,
                self.limits.replies_per_day,
                self.limits.min_reply_delay,
            ),
            "like": (
                self.limits.likes_per_hour,
                self.limits.likes_per_day,
                self.limits.min_like_delay,
            ),
            "retweet": (
                self.limits.retweets_per_hour,
                self.limits.retweets_per_day,
                self.limits.min_retweet_delay,
            ),
            "dm": (
                self.limits.dms_per_hour,
                self.limits.dms_per_day,
                self.limits.min_dm_delay,
            ),
        }
        return limits_map.get(
            operation_type,
            (10, 100, 5.0),  # Default conservative limits
        )

    async def acquire(
        self,
        operation_type: str,
        wait: bool = True,
    ) -> bool:
        """Acquire permission to perform a mutation operation.

        Args:
            operation_type: Type of operation (tweet, reply, like, retweet, dm).
            wait: If True, wait until operation can proceed. If False, return immediately.

        Returns:
            True if operation can proceed, False if rate limited and wait=False.

        Raises:
            RateLimitError: If rate limited and wait=False.
        """
        async with self._lock:
            counter = self._get_counter(operation_type)
            hourly_limit, daily_limit, min_delay = self._get_limits_for_operation(
                operation_type
            )

            while True:
                can_proceed, wait_time = counter.can_proceed(
                    hourly_limit, daily_limit, min_delay
                )

                if can_proceed:
                    counter.record_operation()
                    logger.debug(
                        f"Mutation {operation_type} allowed for account {self.account_id}",
                        extra={
                            "operation_type": operation_type,
                            "hourly_count": counter.hourly_count,
                            "daily_count": counter.daily_count,
                        },
                    )
                    return True

                if not wait:
                    raise RateLimitError(
                        f"Rate limit exceeded for {operation_type}",
                        retry_after=int(wait_time),
                    )

                logger.info(
                    f"Mutation rate limit: waiting {wait_time:.1f}s for {operation_type}",
                    extra={
                        "account_id": self.account_id,
                        "operation_type": operation_type,
                        "wait_time": wait_time,
                    },
                )

                # Release lock while waiting
                await asyncio.sleep(min(wait_time, 60.0))

    def get_remaining(self, operation_type: str) -> dict[str, int]:
        """Get remaining capacity for an operation type.

        Returns:
            Dictionary with remaining hourly and daily counts.
        """
        counter = self._get_counter(operation_type)
        counter.reset_if_needed()

        hourly_limit, daily_limit, _ = self._get_limits_for_operation(operation_type)

        return {
            "hourly_remaining": max(0, hourly_limit - counter.hourly_count),
            "daily_remaining": max(0, daily_limit - counter.daily_count),
            "hourly_limit": hourly_limit,
            "daily_limit": daily_limit,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get statistics for all operation types."""
        stats = {
            "account_id": self.account_id,
            "operations": {},
        }

        for op_type in ["tweet", "reply", "like", "retweet", "dm"]:
            counter = self._get_counter(op_type)
            counter.reset_if_needed()

            hourly_limit, daily_limit, _ = self._get_limits_for_operation(op_type)

            stats["operations"][op_type] = {
                "hourly_count": counter.hourly_count,
                "hourly_limit": hourly_limit,
                "daily_count": counter.daily_count,
                "daily_limit": daily_limit,
                "last_operation": datetime.fromtimestamp(counter.last_operation).isoformat()
                if counter.last_operation > 0
                else None,
            }

        return stats

    def reset(self) -> None:
        """Reset all counters (use with caution)."""
        self._counters.clear()

    def can_tweet(self) -> bool:
        """Check if a tweet can be posted right now."""
        counter = self._get_counter("tweet")
        hourly_limit, daily_limit, min_delay = self._get_limits_for_operation("tweet")
        can_proceed, _ = counter.can_proceed(hourly_limit, daily_limit, min_delay)
        return can_proceed

    def can_reply(self) -> bool:
        """Check if a reply can be posted right now."""
        counter = self._get_counter("reply")
        hourly_limit, daily_limit, min_delay = self._get_limits_for_operation("reply")
        can_proceed, _ = counter.can_proceed(hourly_limit, daily_limit, min_delay)
        return can_proceed


class AccountMutationLimiterPool:
    """Pool of mutation rate limiters for multiple accounts."""

    def __init__(self, limits: MutationLimits | None = None) -> None:
        self._limiters: dict[str, MutationRateLimiter] = {}
        self._limits = limits or MutationLimits()
        self._lock = asyncio.Lock()

    async def get_limiter(self, account_id: str) -> MutationRateLimiter:
        """Get or create a rate limiter for an account."""
        async with self._lock:
            if account_id not in self._limiters:
                self._limiters[account_id] = MutationRateLimiter(
                    account_id=account_id,
                    limits=self._limits,
                )
            return self._limiters[account_id]

    async def acquire(
        self,
        account_id: str,
        operation_type: str,
        wait: bool = True,
    ) -> bool:
        """Acquire permission for an operation on a specific account."""
        limiter = await self.get_limiter(account_id)
        return await limiter.acquire(operation_type, wait)

    def get_all_stats(self) -> dict[str, Any]:
        """Get statistics for all accounts."""
        return {
            account_id: limiter.get_stats()
            for account_id, limiter in self._limiters.items()
        }
