"""Twitter account pool with rate limit tracking and rotation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from twikit import Client
from twikit.errors import TooManyRequests

from xspider.core import get_logger

if TYPE_CHECKING:
    from xspider.admin.models import TwitterAccount

logger = get_logger(__name__)

# Activity callback type for recording stats
ActivityCallback = Callable[[int, str, bool, int, int | None, bool, str | None], None]

# Rate limit reset time in seconds (Twitter usually resets after 15 minutes)
RATE_LIMIT_RESET_SECONDS = 900


@dataclass
class AccountState:
    """State tracking for a Twitter account."""

    account_id: int
    ct0: str
    auth_token: str
    client: Client | None = None
    is_rate_limited: bool = False
    rate_limit_reset_at: datetime | None = None
    last_used_at: datetime | None = None
    request_count: int = 0
    error_count: int = 0

    def is_available(self) -> bool:
        """Check if account is available for use."""
        if not self.is_rate_limited:
            return True

        # Check if rate limit has expired
        if self.rate_limit_reset_at:
            now = datetime.now(timezone.utc)
            if now >= self.rate_limit_reset_at:
                self.is_rate_limited = False
                self.rate_limit_reset_at = None
                return True

        return False

    def mark_rate_limited(self, reset_seconds: int = RATE_LIMIT_RESET_SECONDS) -> None:
        """Mark account as rate limited."""
        self.is_rate_limited = True
        self.rate_limit_reset_at = datetime.now(timezone.utc) + \
            __import__('datetime').timedelta(seconds=reset_seconds)
        logger.warning(
            "account_pool.rate_limited",
            account_id=self.account_id,
            reset_at=self.rate_limit_reset_at.isoformat(),
        )

    def mark_used(self) -> None:
        """Mark account as just used."""
        self.last_used_at = datetime.now(timezone.utc)
        self.request_count += 1

    def mark_error(self) -> None:
        """Mark an error on this account."""
        self.error_count += 1

    def get_client(self) -> Client:
        """Get or create twikit client for this account."""
        if self.client is None:
            self.client = Client(language="en-US")
            self.client.set_cookies({
                "ct0": self.ct0,
                "auth_token": self.auth_token,
            })
        return self.client


@dataclass
class AccountPool:
    """Pool of Twitter accounts with rotation and rate limit handling."""

    accounts: list[AccountState] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _round_robin_index: int = 0

    @classmethod
    def from_db_accounts(cls, db_accounts: list["TwitterAccount"]) -> "AccountPool":
        """Create pool from database account records."""
        states = [
            AccountState(
                account_id=acc.id,
                ct0=acc.ct0,
                auth_token=acc.auth_token,
            )
            for acc in db_accounts
        ]
        return cls(accounts=states)

    def __len__(self) -> int:
        return len(self.accounts)

    def get_available_count(self) -> int:
        """Get number of available accounts."""
        return sum(1 for acc in self.accounts if acc.is_available())

    async def get_account(self) -> AccountState | None:
        """Get next available account using round-robin with rate limit awareness.

        Returns None if no accounts are available.
        """
        async with self._lock:
            if not self.accounts:
                return None

            # Try to find an available account starting from round-robin index
            n = len(self.accounts)
            for i in range(n):
                idx = (self._round_robin_index + i) % n
                account = self.accounts[idx]

                if account.is_available():
                    self._round_robin_index = (idx + 1) % n
                    account.mark_used()
                    return account

            # No available accounts
            return None

    async def get_multiple_accounts(self, count: int) -> list[AccountState]:
        """Get multiple available accounts for concurrent operations.

        Args:
            count: Maximum number of accounts to return.

        Returns:
            List of available accounts (may be fewer than requested).
        """
        async with self._lock:
            available = [acc for acc in self.accounts if acc.is_available()]

            # Sort by least recently used
            available.sort(key=lambda x: x.last_used_at or datetime.min.replace(tzinfo=timezone.utc))

            # Take up to 'count' accounts
            selected = available[:count]

            # Mark them as used
            for acc in selected:
                acc.mark_used()

            return selected

    def mark_rate_limited(self, account_id: int) -> None:
        """Mark an account as rate limited."""
        for acc in self.accounts:
            if acc.account_id == account_id:
                acc.mark_rate_limited()
                break

    def get_stats(self) -> dict:
        """Get pool statistics."""
        available = sum(1 for acc in self.accounts if acc.is_available())
        rate_limited = sum(1 for acc in self.accounts if acc.is_rate_limited)

        return {
            "total_accounts": len(self.accounts),
            "available_accounts": available,
            "rate_limited_accounts": rate_limited,
            "accounts": [
                {
                    "id": acc.account_id,
                    "is_available": acc.is_available(),
                    "is_rate_limited": acc.is_rate_limited,
                    "request_count": acc.request_count,
                    "error_count": acc.error_count,
                    "rate_limit_reset_at": acc.rate_limit_reset_at.isoformat() if acc.rate_limit_reset_at else None,
                }
                for acc in self.accounts
            ],
        }


@dataclass
class SearchResult:
    """Result of a search operation with timing info."""

    users: list
    was_rate_limited: bool
    response_time_ms: int
    error_message: str | None = None


async def search_with_account(
    account: AccountState,
    keyword: str,
    max_results: int = 50,
) -> tuple[list, bool, int, str | None]:
    """Search for users with a specific account.

    Args:
        account: Account state to use.
        keyword: Search keyword.
        max_results: Maximum results to return.

    Returns:
        Tuple of (users list, was_rate_limited, response_time_ms, error_message).
    """
    client = account.get_client()
    users = []
    was_rate_limited = False
    error_message = None

    start_time = time.time()

    try:
        results = await client.search_user(keyword, count=max_results)
        users = list(results)
        logger.info(
            "account_pool.search_success",
            account_id=account.account_id,
            keyword=keyword,
            results=len(users),
        )
    except TooManyRequests:
        account.mark_rate_limited()
        was_rate_limited = True
        error_message = "Rate limited (429)"
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "rate limit" in error_str.lower():
            account.mark_rate_limited()
            was_rate_limited = True
            error_message = f"Rate limited: {error_str}"
        else:
            account.mark_error()
            error_message = error_str
            logger.warning(
                "account_pool.search_error",
                account_id=account.account_id,
                keyword=keyword,
                error=error_str,
            )

    response_time_ms = int((time.time() - start_time) * 1000)

    return users, was_rate_limited, response_time_ms, error_message


@dataclass
class SearchStats:
    """Statistics from concurrent search."""

    total_searches: int = 0
    successful_searches: int = 0
    failed_searches: int = 0
    rate_limited_searches: int = 0
    total_results: int = 0
    avg_response_time_ms: float = 0.0
    account_activities: list = field(default_factory=list)


async def concurrent_search(
    pool: AccountPool,
    keywords: list[str],
    max_results_per_keyword: int = 50,
) -> tuple[list, SearchStats]:
    """Search multiple keywords concurrently using multiple accounts.

    Args:
        pool: Account pool to use.
        keywords: List of keywords to search.
        max_results_per_keyword: Max results per keyword.

    Returns:
        Tuple of (all discovered users, search statistics).
    """
    all_users = []
    remaining_keywords = list(keywords)
    retry_keywords = []
    stats = SearchStats()
    response_times = []

    while remaining_keywords:
        # Get available accounts
        available_count = pool.get_available_count()

        if available_count == 0:
            # No accounts available, add remaining keywords to retry
            retry_keywords.extend(remaining_keywords)
            logger.warning(
                "account_pool.no_available_accounts",
                remaining_keywords=len(remaining_keywords),
            )
            break

        # Get accounts for concurrent search
        batch_size = min(available_count, len(remaining_keywords))
        accounts = await pool.get_multiple_accounts(batch_size)

        if not accounts:
            break

        # Create concurrent search tasks
        batch_keywords = remaining_keywords[:len(accounts)]
        remaining_keywords = remaining_keywords[len(accounts):]

        tasks = [
            search_with_account(account, keyword, max_results_per_keyword)
            for account, keyword in zip(accounts, batch_keywords)
        ]

        # Execute concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            stats.total_searches += 1

            if isinstance(result, Exception):
                stats.failed_searches += 1
                logger.error(
                    "account_pool.concurrent_search_error",
                    keyword=batch_keywords[i],
                    error=str(result),
                )
                # Record failed activity
                stats.account_activities.append({
                    "account_id": accounts[i].account_id,
                    "keyword": batch_keywords[i],
                    "success": False,
                    "result_count": 0,
                    "response_time_ms": 0,
                    "is_rate_limited": False,
                    "error_message": str(result),
                })
                continue

            users, was_rate_limited, response_time_ms, error_message = result
            response_times.append(response_time_ms)

            if was_rate_limited:
                stats.rate_limited_searches += 1
                retry_keywords.append(batch_keywords[i])
            elif error_message:
                stats.failed_searches += 1
            else:
                stats.successful_searches += 1
                stats.total_results += len(users)

            all_users.extend(users)

            # Record activity for stats
            stats.account_activities.append({
                "account_id": accounts[i].account_id,
                "keyword": batch_keywords[i],
                "success": not error_message and not was_rate_limited,
                "result_count": len(users),
                "response_time_ms": response_time_ms,
                "is_rate_limited": was_rate_limited,
                "error_message": error_message,
            })

        # Small delay between batches to be respectful
        if remaining_keywords:
            await asyncio.sleep(1)

    # Handle retry keywords with remaining available accounts
    if retry_keywords:
        logger.info(
            "account_pool.retrying_keywords",
            count=len(retry_keywords),
        )
        for keyword in retry_keywords:
            account = await pool.get_account()
            if not account:
                break

            stats.total_searches += 1
            users, was_rate_limited, response_time_ms, error_message = await search_with_account(
                account, keyword, max_results_per_keyword
            )
            response_times.append(response_time_ms)

            if was_rate_limited:
                stats.rate_limited_searches += 1
            elif error_message:
                stats.failed_searches += 1
            else:
                stats.successful_searches += 1
                stats.total_results += len(users)

            all_users.extend(users)

            # Record activity
            stats.account_activities.append({
                "account_id": account.account_id,
                "keyword": keyword,
                "success": not error_message and not was_rate_limited,
                "result_count": len(users),
                "response_time_ms": response_time_ms,
                "is_rate_limited": was_rate_limited,
                "error_message": error_message,
            })

            await asyncio.sleep(2)  # Longer delay for retries

    # Calculate average response time
    if response_times:
        stats.avg_response_time_ms = sum(response_times) / len(response_times)

    return all_users, stats


async def get_followers_with_account(
    account: AccountState,
    user_id: str,
    max_results: int = 100,
) -> tuple[list, bool, int, str | None]:
    """Get followers of a user with a specific account.

    Args:
        account: Account state to use.
        user_id: Twitter user ID to get followers for.
        max_results: Maximum followers to return.

    Returns:
        Tuple of (followers list, was_rate_limited, response_time_ms, error_message).
    """
    client = account.get_client()
    followers = []
    was_rate_limited = False
    error_message = None

    start_time = time.time()

    try:
        # Get followers with pagination
        result = await client.get_user_followers(user_id, count=min(max_results, 200))
        followers = list(result)

        # If we need more, paginate
        while len(followers) < max_results and result.next_cursor:
            try:
                result = await result.next()
                followers.extend(list(result))
            except TooManyRequests:
                account.mark_rate_limited()
                was_rate_limited = True
                break
            except Exception:
                break

        logger.info(
            "account_pool.get_followers_success",
            account_id=account.account_id,
            user_id=user_id,
            results=len(followers),
        )
    except TooManyRequests:
        account.mark_rate_limited()
        was_rate_limited = True
        error_message = "Rate limited (429)"
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "rate limit" in error_str.lower():
            account.mark_rate_limited()
            was_rate_limited = True
            error_message = f"Rate limited: {error_str}"
        else:
            account.mark_error()
            error_message = error_str
            logger.warning(
                "account_pool.get_followers_error",
                account_id=account.account_id,
                user_id=user_id,
                error=error_str,
            )

    response_time_ms = int((time.time() - start_time) * 1000)

    return followers[:max_results], was_rate_limited, response_time_ms, error_message


@dataclass
class CrawlStats:
    """Statistics from concurrent follower crawling."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limited_requests: int = 0
    total_followers: int = 0
    avg_response_time_ms: float = 0.0
    account_activities: list = field(default_factory=list)


async def concurrent_get_followers(
    pool: AccountPool,
    user_ids: list[str],
    max_followers_per_user: int = 100,
    delay_between_batches: float = 1.0,
) -> tuple[list, CrawlStats]:
    """Get followers for multiple users concurrently using multiple accounts.

    Args:
        pool: Account pool to use.
        user_ids: List of user IDs to get followers for.
        max_followers_per_user: Max followers per user.
        delay_between_batches: Delay between request batches.

    Returns:
        Tuple of (all followers, crawl statistics).
    """
    all_followers = []
    remaining_user_ids = list(user_ids)
    retry_user_ids = []
    stats = CrawlStats()
    response_times = []

    while remaining_user_ids:
        # Get available accounts
        available_count = pool.get_available_count()

        if available_count == 0:
            # No accounts available, add remaining to retry
            retry_user_ids.extend(remaining_user_ids)
            logger.warning(
                "account_pool.no_available_accounts_for_followers",
                remaining_users=len(remaining_user_ids),
            )
            break

        # Get accounts for concurrent requests
        batch_size = min(available_count, len(remaining_user_ids))
        accounts = await pool.get_multiple_accounts(batch_size)

        if not accounts:
            break

        # Create concurrent tasks
        batch_user_ids = remaining_user_ids[:len(accounts)]
        remaining_user_ids = remaining_user_ids[len(accounts):]

        tasks = [
            get_followers_with_account(account, user_id, max_followers_per_user)
            for account, user_id in zip(accounts, batch_user_ids)
        ]

        # Execute concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            stats.total_requests += 1

            if isinstance(result, Exception):
                stats.failed_requests += 1
                logger.error(
                    "account_pool.concurrent_followers_error",
                    user_id=batch_user_ids[i],
                    error=str(result),
                )
                stats.account_activities.append({
                    "account_id": accounts[i].account_id,
                    "user_id": batch_user_ids[i],
                    "success": False,
                    "result_count": 0,
                    "response_time_ms": 0,
                    "is_rate_limited": False,
                    "error_message": str(result),
                })
                continue

            followers, was_rate_limited, response_time_ms, error_message = result
            response_times.append(response_time_ms)

            if was_rate_limited:
                stats.rate_limited_requests += 1
                retry_user_ids.append(batch_user_ids[i])
            elif error_message:
                stats.failed_requests += 1
            else:
                stats.successful_requests += 1
                stats.total_followers += len(followers)

            all_followers.extend(followers)

            stats.account_activities.append({
                "account_id": accounts[i].account_id,
                "user_id": batch_user_ids[i],
                "success": not error_message and not was_rate_limited,
                "result_count": len(followers),
                "response_time_ms": response_time_ms,
                "is_rate_limited": was_rate_limited,
                "error_message": error_message,
            })

        # Delay between batches
        if remaining_user_ids:
            await asyncio.sleep(delay_between_batches)

    # Handle retry user IDs with remaining available accounts
    if retry_user_ids:
        logger.info(
            "account_pool.retrying_followers",
            count=len(retry_user_ids),
        )
        for user_id in retry_user_ids:
            account = await pool.get_account()
            if not account:
                break

            stats.total_requests += 1
            followers, was_rate_limited, response_time_ms, error_message = await get_followers_with_account(
                account, user_id, max_followers_per_user
            )
            response_times.append(response_time_ms)

            if was_rate_limited:
                stats.rate_limited_requests += 1
            elif error_message:
                stats.failed_requests += 1
            else:
                stats.successful_requests += 1
                stats.total_followers += len(followers)

            all_followers.extend(followers)

            stats.account_activities.append({
                "account_id": account.account_id,
                "user_id": user_id,
                "success": not error_message and not was_rate_limited,
                "result_count": len(followers),
                "response_time_ms": response_time_ms,
                "is_rate_limited": was_rate_limited,
                "error_message": error_message,
            })

            await asyncio.sleep(2)  # Longer delay for retries

    # Calculate average response time
    if response_times:
        stats.avg_response_time_ms = sum(response_times) / len(response_times)

    return all_followers, stats
