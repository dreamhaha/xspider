"""Integration service to connect admin-managed accounts with TwitterGraphQLClient."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import AccountStatus, ProxyServer, ProxyStatus, TwitterAccount
from xspider.core.config import TwitterToken
from xspider.core.logging import get_logger
from xspider.storage.database import get_database
from xspider.twitter.auth import TokenPool, TokenState

logger = get_logger(__name__)


class ManagedTokenPool(TokenPool):
    """
    Token pool that uses accounts managed in the admin database.

    Extends the base TokenPool to load tokens from the database
    and persist status changes back to the database.
    """

    def __init__(self) -> None:
        # Initialize without tokens - they'll be loaded from DB
        super().__init__([])
        self._db_account_ids: dict[int, int] = {}  # token_index -> account_id

    @classmethod
    async def from_database(cls) -> "ManagedTokenPool":
        """Create a token pool from database accounts."""
        pool = cls()
        await pool.reload_from_database()
        return pool

    async def reload_from_database(self) -> None:
        """Load or reload tokens from the database."""
        db = get_database()

        async with db.session() as session:
            # Get all active or rate-limited accounts
            result = await session.execute(
                select(TwitterAccount).where(
                    TwitterAccount.status.in_([
                        AccountStatus.ACTIVE,
                        AccountStatus.RATE_LIMITED,
                    ])
                )
            )
            accounts = list(result.scalars().all())

        # Clear existing tokens
        self._tokens = []
        self._states = []
        self._db_account_ids = {}

        # Add tokens from database
        for idx, account in enumerate(accounts):
            token = TwitterToken(
                bearer_token=account.bearer_token,
                ct0=account.ct0,
                auth_token=account.auth_token,
            )
            self._tokens.append(token)

            # Set initial state based on database status
            is_rate_limited = account.status == AccountStatus.RATE_LIMITED
            state = TokenState(
                is_valid=True,
                is_rate_limited=is_rate_limited,
                request_count=account.request_count,
                rate_limit_reset=account.rate_limit_reset,
            )
            self._states.append(state)

            # Track account ID for persistence
            self._db_account_ids[idx] = account.id

        logger.info(
            "Loaded tokens from database",
            total=len(self._tokens),
            active=sum(1 for s in self._states if s.is_available),
        )

    async def persist_state(self, token_index: int) -> None:
        """Persist token state changes back to the database."""
        if token_index not in self._db_account_ids:
            return

        account_id = self._db_account_ids[token_index]
        state = self._states[token_index]

        db = get_database()
        async with db.session() as session:
            result = await session.execute(
                select(TwitterAccount).where(TwitterAccount.id == account_id)
            )
            account = result.scalar_one_or_none()

            if not account:
                return

            # Update account status based on token state
            if not state.is_valid:
                account.status = AccountStatus.ERROR
                account.error_count += 1
            elif state.is_rate_limited:
                account.status = AccountStatus.RATE_LIMITED
                account.rate_limit_reset = state.rate_limit_reset
            else:
                account.status = AccountStatus.ACTIVE
                account.rate_limit_reset = None

            account.request_count = state.request_count
            account.last_used_at = datetime.now(timezone.utc)

            await session.commit()

    def mark_rate_limited(
        self,
        token_index: int,
        reset_time: datetime | None = None,
    ) -> None:
        """Mark a token as rate limited and persist to database."""
        super().mark_rate_limited(token_index, reset_time)

        # Persist to database (fire and forget)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.persist_state(token_index))
            else:
                asyncio.run(self.persist_state(token_index))
        except Exception as e:
            logger.warning("Failed to persist rate limit state", error=str(e))

    def mark_invalid(self, token_index: int) -> None:
        """Mark a token as invalid and persist to database."""
        super().mark_invalid(token_index)

        # Persist to database
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.persist_state(token_index))
            else:
                asyncio.run(self.persist_state(token_index))
        except Exception as e:
            logger.warning("Failed to persist invalid state", error=str(e))

    def increment_request_count(self, token_index: int) -> None:
        """Increment request count and periodically persist."""
        super().increment_request_count(token_index)

        # Persist every 10 requests
        if self._states[token_index].request_count % 10 == 0:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.persist_state(token_index))
            except Exception:
                pass


async def get_managed_proxy_urls() -> list[str]:
    """Get active proxy URLs from the database."""
    db = get_database()

    async with db.session() as session:
        result = await session.execute(
            select(ProxyServer).where(ProxyServer.status == ProxyStatus.ACTIVE)
        )
        proxies = list(result.scalars().all())

    return [proxy.url for proxy in proxies]


async def create_managed_client():
    """
    Create a TwitterGraphQLClient using admin-managed accounts and proxies.

    Returns a client configured with tokens and proxies from the database.
    """
    from xspider.twitter.client import TwitterGraphQLClient
    from xspider.twitter.proxy_pool import ProxyPool

    # Load tokens from database
    token_pool = await ManagedTokenPool.from_database()

    if not token_pool.has_available():
        raise RuntimeError(
            "No active Twitter accounts available. "
            "Please add accounts in the admin panel."
        )

    # Load proxies from database
    proxy_urls = await get_managed_proxy_urls()
    proxy_pool = ProxyPool(proxy_urls) if proxy_urls else None

    # Create client
    client = TwitterGraphQLClient(
        token_pool=token_pool,
        proxy_pool=proxy_pool,
    )

    logger.info(
        "Created managed Twitter client",
        tokens=len(token_pool._tokens),
        proxies=len(proxy_urls),
    )

    return client
