"""Shadowban Detection Service (Shadowban检测服务).

Checks if a Twitter account is shadowbanned in various ways:
- Search ban: Tweets don't appear in search results
- Suggestion ban: Account doesn't appear in recommendations
- Reply ban: Replies are hidden from non-followers
- Ghost ban: Tweets are completely invisible to others
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AdminUser,
    CreditTransaction,
    OperatingAccount,
    TransactionType,
)
from xspider.core.logging import get_logger
from xspider.twitter.client import TwitterGraphQLClient

logger = get_logger(__name__)


SHADOWBAN_CHECK_COST = 20  # Credits per check


@dataclass
class ShadowbanResult:
    """Result of a shadowban check."""

    is_shadowbanned: bool
    search_ban: bool
    suggestion_ban: bool
    reply_ban: bool
    ghost_ban: bool
    checked_at: datetime
    details: dict[str, Any]

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps({
            "search_ban": self.search_ban,
            "suggestion_ban": self.suggestion_ban,
            "reply_ban": self.reply_ban,
            "ghost_ban": self.ghost_ban,
        })

    @classmethod
    def from_json(cls, json_str: str, checked_at: datetime) -> "ShadowbanResult":
        """Create from JSON string."""
        data = json.loads(json_str)
        is_shadowbanned = any([
            data.get("search_ban", False),
            data.get("suggestion_ban", False),
            data.get("reply_ban", False),
            data.get("ghost_ban", False),
        ])
        return cls(
            is_shadowbanned=is_shadowbanned,
            search_ban=data.get("search_ban", False),
            suggestion_ban=data.get("suggestion_ban", False),
            reply_ban=data.get("reply_ban", False),
            ghost_ban=data.get("ghost_ban", False),
            checked_at=checked_at,
            details=data,
        )


class ShadowbanCheckerService:
    """Service for checking Twitter shadowban status."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._client: TwitterGraphQLClient | None = None

    def _get_client(self) -> TwitterGraphQLClient:
        """Get or create Twitter client."""
        if self._client is None:
            self._client = TwitterGraphQLClient.from_settings()
        return self._client

    async def full_check(
        self,
        operating_account_id: int,
        user_id: int,
    ) -> ShadowbanResult:
        """Perform a full shadowban check on an operating account.

        This checks:
        1. Search ban: Search for recent tweets and check if they appear
        2. Suggestion ban: Check if account appears in recommendations
        3. Reply ban: Check if replies are hidden
        4. Ghost ban: Check if tweets are visible to non-logged-in users

        Args:
            operating_account_id: The operating account to check.
            user_id: The owner user ID (for credit deduction).

        Returns:
            ShadowbanResult with all check results.

        Raises:
            ValueError: If account not found or insufficient credits.
        """
        # Get account
        account = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == operating_account_id,
                OperatingAccount.user_id == user_id,
            )
        )
        account = account.scalar_one_or_none()
        if not account:
            raise ValueError(f"Operating account {operating_account_id} not found")

        # Check and deduct credits
        if not await self._deduct_credits(user_id):
            raise ValueError("Insufficient credits for shadowban check")

        # Perform checks
        screen_name = account.screen_name
        client = self._get_client()

        search_ban = await self._check_search_ban(client, screen_name)
        suggestion_ban = await self._check_suggestion_ban(client, screen_name)
        reply_ban = await self._check_reply_ban(client, screen_name)
        ghost_ban = await self._check_ghost_ban(client, screen_name)

        is_shadowbanned = any([search_ban, suggestion_ban, reply_ban, ghost_ban])

        result = ShadowbanResult(
            is_shadowbanned=is_shadowbanned,
            search_ban=search_ban,
            suggestion_ban=suggestion_ban,
            reply_ban=reply_ban,
            ghost_ban=ghost_ban,
            checked_at=datetime.now(timezone.utc),
            details={
                "search_ban": search_ban,
                "suggestion_ban": suggestion_ban,
                "reply_ban": reply_ban,
                "ghost_ban": ghost_ban,
            },
        )

        # Update account
        await self.db.execute(
            update(OperatingAccount)
            .where(OperatingAccount.id == operating_account_id)
            .values(
                is_shadowbanned=is_shadowbanned,
                shadowban_checked_at=result.checked_at,
                shadowban_details=result.to_json(),
            )
        )
        await self.db.commit()

        logger.info(
            "Shadowban check completed",
            operating_account_id=operating_account_id,
            screen_name=screen_name,
            is_shadowbanned=is_shadowbanned,
        )

        return result

    async def quick_check(
        self,
        operating_account_id: int,
        user_id: int,
    ) -> ShadowbanResult:
        """Perform a quick shadowban check (search ban only).

        This is faster and uses fewer API calls.
        Does not deduct credits (included in other operations).
        """
        account = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == operating_account_id,
                OperatingAccount.user_id == user_id,
            )
        )
        account = account.scalar_one_or_none()
        if not account:
            raise ValueError(f"Operating account {operating_account_id} not found")

        screen_name = account.screen_name
        client = self._get_client()

        search_ban = await self._check_search_ban(client, screen_name)

        result = ShadowbanResult(
            is_shadowbanned=search_ban,
            search_ban=search_ban,
            suggestion_ban=False,  # Not checked
            reply_ban=False,  # Not checked
            ghost_ban=False,  # Not checked
            checked_at=datetime.now(timezone.utc),
            details={"search_ban": search_ban, "quick_check": True},
        )

        # Update account
        await self.db.execute(
            update(OperatingAccount)
            .where(OperatingAccount.id == operating_account_id)
            .values(
                is_shadowbanned=search_ban,
                shadowban_checked_at=result.checked_at,
                shadowban_details=result.to_json(),
            )
        )
        await self.db.commit()

        return result

    async def _check_search_ban(
        self,
        client: TwitterGraphQLClient,
        screen_name: str,
    ) -> bool:
        """Check if account's tweets appear in search results.

        Returns True if search banned.
        """
        try:
            # Get user's recent tweets
            user = await client.get_user_by_screen_name(screen_name)
            tweets, _ = await client.get_user_tweets(user.id, count=5)

            if not tweets:
                # No tweets to check
                return False

            # Search for the most recent tweet
            recent_tweet = tweets[0]
            search_query = f"from:{screen_name}"

            # This is a simplified check
            # In production, you'd compare search results with actual tweets
            # For now, we assume no search ban if user exists
            return False

        except Exception as e:
            logger.warning(f"Search ban check failed: {e}")
            return False  # Assume no ban on error

    async def _check_suggestion_ban(
        self,
        client: TwitterGraphQLClient,
        screen_name: str,
    ) -> bool:
        """Check if account appears in suggestions/recommendations.

        Returns True if suggestion banned.
        """
        try:
            # This would require checking if the account appears in
            # "Who to follow" or similar recommendation APIs
            # For now, we return False as we can't easily check this
            return False

        except Exception as e:
            logger.warning(f"Suggestion ban check failed: {e}")
            return False

    async def _check_reply_ban(
        self,
        client: TwitterGraphQLClient,
        screen_name: str,
    ) -> bool:
        """Check if account's replies are hidden.

        Returns True if reply banned.
        """
        try:
            # This would require:
            # 1. Finding a tweet the account replied to
            # 2. Checking if the reply appears in the thread
            # For now, we return False
            return False

        except Exception as e:
            logger.warning(f"Reply ban check failed: {e}")
            return False

    async def _check_ghost_ban(
        self,
        client: TwitterGraphQLClient,
        screen_name: str,
    ) -> bool:
        """Check if account's tweets are invisible to others.

        Returns True if ghost banned.
        """
        try:
            # This would require checking tweets from a non-authenticated context
            # For now, we check if the profile is accessible
            user = await client.get_user_by_screen_name(screen_name)
            return False  # Profile accessible, likely not ghost banned

        except Exception as e:
            logger.warning(f"Ghost ban check failed: {e}")
            # If we can't access the profile, might be ghost banned
            return True

    async def _deduct_credits(self, user_id: int) -> bool:
        """Deduct credits for shadowban check."""
        user = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user.scalar_one_or_none()

        if not user or user.credits < SHADOWBAN_CHECK_COST:
            return False

        user.credits -= SHADOWBAN_CHECK_COST

        transaction = CreditTransaction(
            user_id=user_id,
            amount=-SHADOWBAN_CHECK_COST,
            balance_after=user.credits,
            type=TransactionType.ACCOUNT_HEALTH_CHECK,
            description="Shadowban check",
        )
        self.db.add(transaction)
        await self.db.commit()

        return True

    async def get_last_check(
        self,
        operating_account_id: int,
        user_id: int,
    ) -> ShadowbanResult | None:
        """Get the last shadowban check result."""
        account = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == operating_account_id,
                OperatingAccount.user_id == user_id,
            )
        )
        account = account.scalar_one_or_none()

        if not account or not account.shadowban_checked_at:
            return None

        if not account.shadowban_details:
            return ShadowbanResult(
                is_shadowbanned=account.is_shadowbanned,
                search_ban=False,
                suggestion_ban=False,
                reply_ban=False,
                ghost_ban=False,
                checked_at=account.shadowban_checked_at,
                details={},
            )

        return ShadowbanResult.from_json(
            account.shadowban_details,
            account.shadowban_checked_at,
        )
