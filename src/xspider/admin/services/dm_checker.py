"""Service for checking if users can receive direct messages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    DMStatus,
    MonitoredTweet,
    TweetCommenter,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class DMCheckerService:
    """
    Service for checking if Twitter users can receive DMs.

    DM availability depends on user settings:
    - Open: Anyone can DM
    - Followers only: Only people they follow can DM
    - Closed: DMs are disabled

    We determine this by:
    1. Checking user profile settings (if available via API)
    2. Attempting to check DM conversation eligibility
    3. Inferring from user behavior patterns
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def check_dm_status(
        self,
        commenter: TweetCommenter,
    ) -> DMStatus:
        """
        Check if a user can receive DMs.

        Returns the DM status (open, followers_only, closed, unknown).
        """
        from xspider.admin.services.token_pool_integration import create_managed_client

        try:
            client = await create_managed_client()
        except RuntimeError as e:
            logger.error("Failed to create Twitter client", error=str(e))
            return DMStatus.UNKNOWN

        try:
            # Use Twitter's DM eligibility check endpoint
            # This checks if we can send a DM to this user
            user_id = commenter.twitter_user_id

            # Try to get user settings via GraphQL
            dm_status = await self._check_user_dm_settings(client, user_id)

            if dm_status != DMStatus.UNKNOWN:
                return dm_status

            # Fallback: Infer from user profile
            return await self._infer_dm_status(commenter)

        except Exception as e:
            logger.warning(
                "Failed to check DM status",
                user_id=commenter.twitter_user_id,
                error=str(e),
            )
            return DMStatus.UNKNOWN

    async def _check_user_dm_settings(
        self,
        client: Any,
        user_id: str,
    ) -> DMStatus:
        """Check DM settings via Twitter API."""
        try:
            # Try UserByRestId endpoint to get detailed user info
            user_data = await client.get_user_by_id(user_id)

            if not user_data:
                return DMStatus.UNKNOWN

            # Check legacy.can_dm field if available
            legacy = user_data.get("legacy", {})

            # Check can_dm field (direct indicator)
            if "can_dm" in legacy:
                return DMStatus.OPEN if legacy["can_dm"] else DMStatus.CLOSED

            # Check can_media_tag as proxy (usually correlates with DM settings)
            if legacy.get("can_media_tag", False):
                return DMStatus.OPEN

            # Check protected account (usually closed DMs)
            if legacy.get("protected", False):
                return DMStatus.FOLLOWERS_ONLY

            return DMStatus.UNKNOWN

        except Exception as e:
            logger.debug("Could not check user DM settings", error=str(e))
            return DMStatus.UNKNOWN

    async def _infer_dm_status(self, commenter: TweetCommenter) -> DMStatus:
        """Infer DM status from user profile characteristics."""
        # Verified users often have open DMs for business
        if commenter.verified:
            return DMStatus.OPEN

        # High follower accounts often restrict DMs
        if commenter.followers_count > 100000:
            return DMStatus.FOLLOWERS_ONLY

        # Users with business-like bios often have open DMs
        if commenter.bio:
            bio_lower = commenter.bio.lower()
            dm_indicators = [
                "dm for",
                "dm me",
                "dms open",
                "open for dm",
                "business inquiries",
                "contact:",
                "email:",
                "booking",
                "collab",
            ]
            if any(indicator in bio_lower for indicator in dm_indicators):
                return DMStatus.OPEN

            # Indicators of restricted DMs
            closed_indicators = [
                "no dms",
                "dms closed",
                "don't dm",
                "do not dm",
            ]
            if any(indicator in bio_lower for indicator in closed_indicators):
                return DMStatus.CLOSED

        # Default to unknown if we can't determine
        return DMStatus.UNKNOWN

    async def check_and_save(
        self,
        commenter: TweetCommenter,
    ) -> TweetCommenter:
        """Check DM status and save to database."""
        dm_status = await self.check_dm_status(commenter)

        commenter.dm_status = dm_status
        commenter.can_dm = dm_status == DMStatus.OPEN
        commenter.dm_checked_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(commenter)

        return commenter

    async def check_tweet_commenters(
        self,
        tweet_id: int,
        only_real_users: bool = True,
        force_recheck: bool = False,
    ) -> int:
        """
        Check DM status for all commenters of a tweet.

        Args:
            tweet_id: The tweet ID
            only_real_users: Only check users marked as real (not bots)
            force_recheck: Re-check already checked users

        Returns:
            Number of users checked
        """
        query = select(TweetCommenter).where(TweetCommenter.tweet_id == tweet_id)

        if only_real_users:
            query = query.where(TweetCommenter.is_real_user == True)  # noqa: E712

        if not force_recheck:
            query = query.where(TweetCommenter.dm_status == DMStatus.UNKNOWN)

        result = await self.db.execute(query)
        commenters = list(result.scalars().all())

        checked_count = 0
        for commenter in commenters:
            try:
                await self.check_and_save(commenter)
                checked_count += 1
            except Exception as e:
                logger.error(
                    "Failed to check DM status",
                    commenter_id=commenter.id,
                    error=str(e),
                )

        logger.info(
            "Checked DM status for commenters",
            tweet_id=tweet_id,
            checked_count=checked_count,
        )

        return checked_count

    async def get_dm_summary(self, tweet_id: int) -> dict[str, Any]:
        """Get DM availability summary for a tweet's commenters."""
        from sqlalchemy import func

        # Total real users
        total_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.is_real_user == True,  # noqa: E712
            )
        )
        total_real = total_result.scalar() or 0

        # Open DMs
        open_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.dm_status == DMStatus.OPEN,
            )
        )
        dm_open = open_result.scalar() or 0

        # Followers only
        followers_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.dm_status == DMStatus.FOLLOWERS_ONLY,
            )
        )
        dm_followers = followers_result.scalar() or 0

        # Closed
        closed_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.dm_status == DMStatus.CLOSED,
            )
        )
        dm_closed = closed_result.scalar() or 0

        # Unknown
        unknown_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.dm_status == DMStatus.UNKNOWN,
            )
        )
        dm_unknown = unknown_result.scalar() or 0

        return {
            "tweet_id": tweet_id,
            "total_real_users": total_real,
            "dm_open": dm_open,
            "dm_followers_only": dm_followers,
            "dm_closed": dm_closed,
            "dm_unknown": dm_unknown,
            "dm_available_rate": (dm_open / total_real * 100) if total_real > 0 else 0,
        }

    async def batch_check_influencer_commenters(
        self,
        influencer_id: int,
        only_real_users: bool = True,
    ) -> int:
        """Check DM status for all commenters across an influencer's tweets."""
        # Get all tweets for this influencer
        tweet_result = await self.db.execute(
            select(MonitoredTweet.id).where(
                MonitoredTweet.influencer_id == influencer_id
            )
        )
        tweet_ids = [row[0] for row in tweet_result.fetchall()]

        total_checked = 0
        for tweet_id in tweet_ids:
            checked = await self.check_tweet_commenters(
                tweet_id=tweet_id,
                only_real_users=only_real_users,
            )
            total_checked += checked

        logger.info(
            "Batch checked DM status for influencer",
            influencer_id=influencer_id,
            total_checked=total_checked,
        )

        return total_checked
