"""Operating Account Management Service (运营账号管理服务)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from xspider.admin.models import (
    AdminUser,
    CreditTransaction,
    InteractionMode,
    OperatingAccount,
    OperatingFollowerSnapshot,
    RiskLevel,
    TransactionType,
    TwitterAccount,
)
from xspider.core.logging import get_logger
from xspider.twitter.client import TwitterGraphQLClient
from xspider.twitter.mutation_rate_limiter import MutationRateLimiter

logger = get_logger(__name__)


# Credit costs for operations
CREDIT_COSTS = {
    "shadowban_check": 20,
}


class OperatingAccountService:
    """Service for managing operating accounts (运营账号)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._mutation_limiters: dict[int, MutationRateLimiter] = {}

    def _get_mutation_limiter(self, account_id: int) -> MutationRateLimiter:
        """Get or create a mutation rate limiter for an account."""
        if account_id not in self._mutation_limiters:
            self._mutation_limiters[account_id] = MutationRateLimiter(
                account_id=str(account_id)
            )
        return self._mutation_limiters[account_id]

    async def register_operating_account(
        self,
        user_id: int,
        twitter_account_id: int,
        niche_tags: list[str] | None = None,
        persona: str | None = None,
        daily_tweets_limit: int = 5,
        daily_replies_limit: int = 20,
        daily_dms_limit: int = 50,
        interaction_mode: InteractionMode = InteractionMode.REVIEW,
        notes: str | None = None,
    ) -> OperatingAccount:
        """Register a Twitter account as an operating account.

        Args:
            user_id: Owner user ID.
            twitter_account_id: ID of the Twitter account to register.
            niche_tags: List of niche/industry tags.
            persona: Account persona description.
            daily_tweets_limit: Maximum tweets per day.
            daily_replies_limit: Maximum replies per day.
            daily_dms_limit: Maximum DMs per day.
            interaction_mode: AUTO or REVIEW mode.
            notes: Optional notes.

        Returns:
            The created OperatingAccount.

        Raises:
            ValueError: If Twitter account not found or already registered.
        """
        # Check if Twitter account exists
        twitter_account = await self.db.execute(
            select(TwitterAccount).where(TwitterAccount.id == twitter_account_id)
        )
        twitter_account = twitter_account.scalar_one_or_none()
        if not twitter_account:
            raise ValueError(f"Twitter account {twitter_account_id} not found")

        # Check if already registered as operating account
        existing = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.twitter_account_id == twitter_account_id
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(
                f"Twitter account {twitter_account_id} is already registered as operating account"
            )

        # Fetch Twitter profile info
        try:
            client = TwitterGraphQLClient.from_settings()
            # We need to get the user info from Twitter
            # For now, we'll use placeholder data
            twitter_user_id = "placeholder"
            screen_name = twitter_account.name or "unknown"
            display_name = twitter_account.name
            bio = None
            followers_count = 0
            following_count = 0
            tweet_count = 0
            profile_image_url = None
        except Exception as e:
            logger.warning(f"Failed to fetch Twitter profile: {e}")
            twitter_user_id = "placeholder"
            screen_name = twitter_account.name or "unknown"
            display_name = None
            bio = None
            followers_count = 0
            following_count = 0
            tweet_count = 0
            profile_image_url = None

        # Create operating account
        operating_account = OperatingAccount(
            user_id=user_id,
            twitter_account_id=twitter_account_id,
            twitter_user_id=twitter_user_id,
            screen_name=screen_name,
            display_name=display_name,
            bio=bio,
            followers_count=followers_count,
            following_count=following_count,
            tweet_count=tweet_count,
            profile_image_url=profile_image_url,
            niche_tags=json.dumps(niche_tags) if niche_tags else None,
            persona=persona,
            auto_reply_enabled=False,
            interaction_mode=interaction_mode,
            daily_tweets_limit=daily_tweets_limit,
            daily_replies_limit=daily_replies_limit,
            daily_dms_limit=daily_dms_limit,
            risk_level=RiskLevel.LOW,
            notes=notes,
        )

        self.db.add(operating_account)
        await self.db.commit()
        await self.db.refresh(operating_account)

        logger.info(
            "Registered operating account",
            operating_account_id=operating_account.id,
            twitter_account_id=twitter_account_id,
        )

        return operating_account

    async def get_operating_account(
        self,
        operating_account_id: int,
        user_id: int,
    ) -> OperatingAccount | None:
        """Get an operating account by ID."""
        result = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == operating_account_id,
                OperatingAccount.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_operating_accounts(
        self,
        user_id: int,
        include_inactive: bool = False,
    ) -> list[OperatingAccount]:
        """List all operating accounts for a user."""
        query = select(OperatingAccount).where(OperatingAccount.user_id == user_id)

        if not include_inactive:
            query = query.where(OperatingAccount.is_active == True)

        query = query.order_by(OperatingAccount.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_operating_account(
        self,
        operating_account_id: int,
        user_id: int,
        niche_tags: list[str] | None = None,
        persona: str | None = None,
        daily_tweets_limit: int | None = None,
        daily_replies_limit: int | None = None,
        daily_dms_limit: int | None = None,
        auto_reply_enabled: bool | None = None,
        interaction_mode: InteractionMode | None = None,
        is_active: bool | None = None,
        notes: str | None = None,
    ) -> OperatingAccount | None:
        """Update an operating account."""
        account = await self.get_operating_account(operating_account_id, user_id)
        if not account:
            return None

        if niche_tags is not None:
            account.niche_tags = json.dumps(niche_tags)
        if persona is not None:
            account.persona = persona
        if daily_tweets_limit is not None:
            account.daily_tweets_limit = daily_tweets_limit
        if daily_replies_limit is not None:
            account.daily_replies_limit = daily_replies_limit
        if daily_dms_limit is not None:
            account.daily_dms_limit = daily_dms_limit
        if auto_reply_enabled is not None:
            account.auto_reply_enabled = auto_reply_enabled
        if interaction_mode is not None:
            account.interaction_mode = interaction_mode
        if is_active is not None:
            account.is_active = is_active
        if notes is not None:
            account.notes = notes

        await self.db.commit()
        await self.db.refresh(account)

        return account

    async def delete_operating_account(
        self,
        operating_account_id: int,
        user_id: int,
    ) -> bool:
        """Delete an operating account."""
        account = await self.get_operating_account(operating_account_id, user_id)
        if not account:
            return False

        await self.db.delete(account)
        await self.db.commit()

        return True

    async def reset_daily_counters(
        self,
        operating_account_id: int,
    ) -> None:
        """Reset daily usage counters for an account."""
        await self.db.execute(
            update(OperatingAccount)
            .where(OperatingAccount.id == operating_account_id)
            .values(
                tweets_today=0,
                replies_today=0,
                dms_today=0,
                last_reset_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    async def increment_usage(
        self,
        operating_account_id: int,
        usage_type: str,
        count: int = 1,
    ) -> bool:
        """Increment usage counter and check against limits.

        Args:
            operating_account_id: The account ID.
            usage_type: One of "tweet", "reply", "dm".
            count: Number to increment by.

        Returns:
            True if within limits, False if limit exceeded.
        """
        account = await self.db.execute(
            select(OperatingAccount).where(OperatingAccount.id == operating_account_id)
        )
        account = account.scalar_one_or_none()
        if not account:
            return False

        # Check if we need to reset (new day)
        now = datetime.now(timezone.utc)
        if account.last_reset_at:
            if account.last_reset_at.date() < now.date():
                await self.reset_daily_counters(operating_account_id)
                account.tweets_today = 0
                account.replies_today = 0
                account.dms_today = 0

        # Check limits and increment
        if usage_type == "tweet":
            if account.tweets_today >= account.daily_tweets_limit:
                return False
            account.tweets_today += count
            account.total_tweets_posted += count
        elif usage_type == "reply":
            if account.replies_today >= account.daily_replies_limit:
                return False
            account.replies_today += count
            account.total_replies_posted += count
        elif usage_type == "dm":
            if account.dms_today >= account.daily_dms_limit:
                return False
            account.dms_today += count
            account.total_dms_sent += count
        else:
            return False

        await self.db.commit()
        return True

    async def can_post(
        self,
        operating_account_id: int,
        post_type: str,
    ) -> tuple[bool, str]:
        """Check if an account can post (not rate limited, not banned).

        Returns:
            Tuple of (can_post, reason).
        """
        account = await self.db.execute(
            select(OperatingAccount).where(OperatingAccount.id == operating_account_id)
        )
        account = account.scalar_one_or_none()

        if not account:
            return False, "Account not found"

        if not account.is_active:
            return False, "Account is inactive"

        if account.is_shadowbanned:
            return False, "Account is shadowbanned"

        if account.risk_level == RiskLevel.CRITICAL:
            return False, "Account risk level is critical"

        # Check daily limits
        now = datetime.now(timezone.utc)
        if account.last_reset_at and account.last_reset_at.date() < now.date():
            # New day, counters would be reset
            return True, "OK"

        if post_type == "tweet":
            if account.tweets_today >= account.daily_tweets_limit:
                return False, f"Daily tweet limit ({account.daily_tweets_limit}) reached"
        elif post_type == "reply":
            if account.replies_today >= account.daily_replies_limit:
                return False, f"Daily reply limit ({account.daily_replies_limit}) reached"
        elif post_type == "dm":
            if account.dms_today >= account.daily_dms_limit:
                return False, f"Daily DM limit ({account.daily_dms_limit}) reached"

        # Check mutation rate limiter
        limiter = self._get_mutation_limiter(operating_account_id)
        if post_type == "tweet" and not limiter.can_tweet():
            return False, "Rate limited (too many tweets recently)"
        elif post_type == "reply" and not limiter.can_reply():
            return False, "Rate limited (too many replies recently)"

        return True, "OK"

    async def evaluate_risk_level(
        self,
        operating_account_id: int,
    ) -> RiskLevel:
        """Evaluate and update the risk level for an account.

        Risk factors:
        - Shadowban status
        - Error rate
        - Posting frequency
        - Account age
        """
        account = await self.db.execute(
            select(OperatingAccount).where(OperatingAccount.id == operating_account_id)
        )
        account = account.scalar_one_or_none()
        if not account:
            return RiskLevel.LOW

        risk_score = 0

        # Shadowban is high risk
        if account.is_shadowbanned:
            risk_score += 50

        # High posting volume increases risk
        if account.tweets_today > 10:
            risk_score += 10
        if account.replies_today > 50:
            risk_score += 10

        # Check follower ratio (low followers + high activity = risky)
        if account.followers_count < 100 and account.total_tweets_posted > 50:
            risk_score += 20

        # Determine risk level
        if risk_score >= 60:
            new_level = RiskLevel.CRITICAL
        elif risk_score >= 40:
            new_level = RiskLevel.HIGH
        elif risk_score >= 20:
            new_level = RiskLevel.MEDIUM
        else:
            new_level = RiskLevel.LOW

        # Update if changed
        if account.risk_level != new_level:
            account.risk_level = new_level
            await self.db.commit()

        return new_level

    async def get_daily_stats(
        self,
        operating_account_id: int,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """Get daily statistics for an operating account."""
        result = await self.db.execute(
            select(OperatingFollowerSnapshot)
            .where(OperatingFollowerSnapshot.operating_account_id == operating_account_id)
            .order_by(OperatingFollowerSnapshot.snapshot_at.desc())
            .limit(days)
        )
        snapshots = list(result.scalars().all())

        return [
            {
                "date": snapshot.snapshot_at.isoformat(),
                "followers_count": snapshot.followers_count,
                "followers_change": snapshot.followers_change,
                "followers_change_pct": snapshot.followers_change_pct,
                "tweets_posted": snapshot.tweets_posted,
                "replies_posted": snapshot.replies_posted,
                "total_engagement": snapshot.total_engagement,
            }
            for snapshot in snapshots
        ]

    async def take_follower_snapshot(
        self,
        operating_account_id: int,
    ) -> OperatingFollowerSnapshot:
        """Take a follower snapshot for growth tracking."""
        account = await self.db.execute(
            select(OperatingAccount).where(OperatingAccount.id == operating_account_id)
        )
        account = account.scalar_one_or_none()
        if not account:
            raise ValueError(f"Operating account {operating_account_id} not found")

        # Get previous snapshot
        prev_result = await self.db.execute(
            select(OperatingFollowerSnapshot)
            .where(OperatingFollowerSnapshot.operating_account_id == operating_account_id)
            .order_by(OperatingFollowerSnapshot.snapshot_at.desc())
            .limit(1)
        )
        prev_snapshot = prev_result.scalar_one_or_none()

        # Calculate changes
        followers_change = 0
        followers_change_pct = 0.0
        if prev_snapshot:
            followers_change = account.followers_count - prev_snapshot.followers_count
            if prev_snapshot.followers_count > 0:
                followers_change_pct = (
                    followers_change / prev_snapshot.followers_count
                ) * 100

        snapshot = OperatingFollowerSnapshot(
            operating_account_id=operating_account_id,
            followers_count=account.followers_count,
            following_count=account.following_count,
            tweet_count=account.tweet_count,
            followers_change=followers_change,
            followers_change_pct=followers_change_pct,
            tweets_posted=account.tweets_today,
            replies_posted=account.replies_today,
            total_engagement=account.total_engagement_received,
        )

        self.db.add(snapshot)
        await self.db.commit()
        await self.db.refresh(snapshot)

        return snapshot

    async def deduct_credits(
        self,
        user_id: int,
        transaction_type: TransactionType,
        description: str,
    ) -> bool:
        """Deduct credits for an operation.

        Returns:
            True if credits were deducted, False if insufficient balance.
        """
        cost = CREDIT_COSTS.get(transaction_type.value, 0)
        if cost == 0:
            return True

        user = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user.scalar_one_or_none()
        if not user or user.credits < cost:
            return False

        user.credits -= cost

        transaction = CreditTransaction(
            user_id=user_id,
            amount=-cost,
            balance_after=user.credits,
            type=transaction_type,
            description=description,
        )
        self.db.add(transaction)
        await self.db.commit()

        return True
