"""Service for scraping tweet commenters (replies)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    DMStatus,
    MonitoredTweet,
    TweetCommenter,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class CommenterScraperService:
    """Service for scraping and managing tweet commenters."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_commenter(
        self,
        tweet_id: int,
        twitter_user_id: str,
        screen_name: str,
        comment_text: str,
        comment_tweet_id: str,
        commented_at: datetime,
        display_name: str | None = None,
        bio: str | None = None,
        profile_image_url: str | None = None,
        followers_count: int = 0,
        following_count: int = 0,
        tweet_count: int = 0,
        verified: bool = False,
        account_created_at: datetime | None = None,
        comment_like_count: int = 0,
        comment_reply_count: int = 0,
    ) -> TweetCommenter | None:
        """Add a commenter to a tweet."""
        # Check if already exists
        existing = await self.db.execute(
            select(TweetCommenter).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.comment_tweet_id == comment_tweet_id,
            )
        )
        if existing.scalar_one_or_none():
            logger.debug(
                "Commenter already exists",
                tweet_id=tweet_id,
                comment_tweet_id=comment_tweet_id,
            )
            return None

        commenter = TweetCommenter(
            tweet_id=tweet_id,
            twitter_user_id=twitter_user_id,
            screen_name=screen_name,
            display_name=display_name,
            bio=bio,
            profile_image_url=profile_image_url,
            followers_count=followers_count,
            following_count=following_count,
            tweet_count=tweet_count,
            verified=verified,
            account_created_at=account_created_at,
            comment_text=comment_text,
            comment_tweet_id=comment_tweet_id,
            commented_at=commented_at,
            comment_like_count=comment_like_count,
            comment_reply_count=comment_reply_count,
            dm_status=DMStatus.UNKNOWN,
        )

        self.db.add(commenter)

        # Update tweet stats
        tweet_result = await self.db.execute(
            select(MonitoredTweet).where(MonitoredTweet.id == tweet_id)
        )
        tweet = tweet_result.scalar_one_or_none()
        if tweet:
            tweet.total_commenters += 1

        await self.db.commit()
        await self.db.refresh(commenter)

        return commenter

    async def get_commenters(
        self,
        tweet_id: int,
        is_analyzed: bool | None = None,
        is_real_user: bool | None = None,
        is_bot: bool | None = None,
        can_dm: bool | None = None,
        min_authenticity_score: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[TweetCommenter], int]:
        """Get commenters for a tweet with filters."""
        query = select(TweetCommenter).where(TweetCommenter.tweet_id == tweet_id)

        # Apply filters
        if is_analyzed is not None:
            query = query.where(TweetCommenter.is_analyzed == is_analyzed)
        if is_real_user is not None:
            query = query.where(TweetCommenter.is_real_user == is_real_user)
        if is_bot is not None:
            query = query.where(TweetCommenter.is_bot == is_bot)
        if can_dm is not None:
            query = query.where(TweetCommenter.can_dm == can_dm)
        if min_authenticity_score is not None:
            query = query.where(
                TweetCommenter.authenticity_score >= min_authenticity_score
            )

        # Count
        count_query = select(func.count(TweetCommenter.id)).where(
            TweetCommenter.tweet_id == tweet_id
        )
        # Apply same filters to count
        if is_analyzed is not None:
            count_query = count_query.where(TweetCommenter.is_analyzed == is_analyzed)
        if is_real_user is not None:
            count_query = count_query.where(TweetCommenter.is_real_user == is_real_user)
        if is_bot is not None:
            count_query = count_query.where(TweetCommenter.is_bot == is_bot)
        if can_dm is not None:
            count_query = count_query.where(TweetCommenter.can_dm == can_dm)
        if min_authenticity_score is not None:
            count_query = count_query.where(
                TweetCommenter.authenticity_score >= min_authenticity_score
            )

        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(TweetCommenter.authenticity_score.desc())
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        commenters = list(result.scalars().all())

        return commenters, total

    async def get_commenters_for_influencer(
        self,
        influencer_id: int,
        is_real_user: bool | None = None,
        can_dm: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[TweetCommenter], int]:
        """Get all commenters across all tweets of an influencer."""
        # Get tweet IDs for this influencer
        tweet_ids_query = select(MonitoredTweet.id).where(
            MonitoredTweet.influencer_id == influencer_id
        )
        tweet_ids_result = await self.db.execute(tweet_ids_query)
        tweet_ids = [row[0] for row in tweet_ids_result.fetchall()]

        if not tweet_ids:
            return [], 0

        query = select(TweetCommenter).where(TweetCommenter.tweet_id.in_(tweet_ids))

        if is_real_user is not None:
            query = query.where(TweetCommenter.is_real_user == is_real_user)
        if can_dm is not None:
            query = query.where(TweetCommenter.can_dm == can_dm)

        # Count
        count_query = select(func.count(TweetCommenter.id)).where(
            TweetCommenter.tweet_id.in_(tweet_ids)
        )
        if is_real_user is not None:
            count_query = count_query.where(TweetCommenter.is_real_user == is_real_user)
        if can_dm is not None:
            count_query = count_query.where(TweetCommenter.can_dm == can_dm)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(TweetCommenter.authenticity_score.desc())
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        commenters = list(result.scalars().all())

        return commenters, total

    async def mark_tweet_commenters_scraped(self, tweet_id: int) -> None:
        """Mark a tweet as having its commenters scraped."""
        result = await self.db.execute(
            select(MonitoredTweet).where(MonitoredTweet.id == tweet_id)
        )
        tweet = result.scalar_one_or_none()
        if tweet:
            tweet.commenters_scraped = True
            await self.db.commit()

    async def get_analysis_summary(self, tweet_id: int) -> dict[str, Any]:
        """Get analysis summary for a tweet's commenters."""
        # Total and analyzed count
        total_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id
            )
        )
        total = total_result.scalar() or 0

        analyzed_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.is_analyzed == True,  # noqa: E712
            )
        )
        analyzed = analyzed_result.scalar() or 0

        # Real users
        real_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.is_real_user == True,  # noqa: E712
            )
        )
        real_users = real_result.scalar() or 0

        # Suspicious
        suspicious_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.is_suspicious == True,  # noqa: E712
            )
        )
        suspicious = suspicious_result.scalar() or 0

        # Bots
        bots_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.is_bot == True,  # noqa: E712
            )
        )
        bots = bots_result.scalar() or 0

        # Can DM
        can_dm_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.can_dm == True,  # noqa: E712
            )
        )
        can_dm_count = can_dm_result.scalar() or 0

        # Average authenticity score
        avg_result = await self.db.execute(
            select(func.avg(TweetCommenter.authenticity_score)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.is_analyzed == True,  # noqa: E712
            )
        )
        avg_score = avg_result.scalar() or 0.0

        # Label distribution
        from xspider.admin.models import AuthenticityLabel

        label_distribution = {}
        for label in AuthenticityLabel:
            label_result = await self.db.execute(
                select(func.count(TweetCommenter.id)).where(
                    TweetCommenter.tweet_id == tweet_id,
                    TweetCommenter.primary_label == label,
                )
            )
            count = label_result.scalar() or 0
            if count > 0:
                label_distribution[label.value] = count

        return {
            "tweet_id": tweet_id,
            "total_commenters": total,
            "analyzed_count": analyzed,
            "real_users": real_users,
            "suspicious": suspicious,
            "bots": bots,
            "can_dm_count": can_dm_count,
            "average_authenticity_score": round(avg_score, 2),
            "label_distribution": label_distribution,
        }

    async def scrape_tweet_replies(
        self,
        tweet: MonitoredTweet,
        max_replies: int = 100,
    ) -> int:
        """
        Scrape replies for a tweet using Twitter API.

        Returns the number of new commenters added.
        """
        from xspider.admin.services.token_pool_integration import create_managed_client

        try:
            client = await create_managed_client()
        except RuntimeError as e:
            logger.error("Failed to create Twitter client", error=str(e))
            return 0

        added_count = 0

        try:
            # Use the search endpoint to find replies
            # Twitter API: GET /2/tweets/search/recent with query "conversation_id:{tweet_id}"
            # For GraphQL, we use TweetDetail endpoint

            async for reply in client.iter_tweet_replies(tweet.tweet_id, max_count=max_replies):
                # Extract user info from reply
                user = reply.get("core", {}).get("user_results", {}).get("result", {})
                legacy_user = user.get("legacy", {})
                legacy_tweet = reply.get("legacy", {})

                if not legacy_user or not legacy_tweet:
                    continue

                twitter_user_id = user.get("rest_id", "")
                screen_name = legacy_user.get("screen_name", "")

                if not twitter_user_id or not screen_name:
                    continue

                # Parse created_at
                created_at_str = legacy_tweet.get("created_at", "")
                try:
                    commented_at = datetime.strptime(
                        created_at_str, "%a %b %d %H:%M:%S %z %Y"
                    )
                except (ValueError, TypeError):
                    commented_at = datetime.now(timezone.utc)

                # Parse account created_at
                account_created_str = legacy_user.get("created_at", "")
                try:
                    account_created_at = datetime.strptime(
                        account_created_str, "%a %b %d %H:%M:%S %z %Y"
                    )
                except (ValueError, TypeError):
                    account_created_at = None

                commenter = await self.add_commenter(
                    tweet_id=tweet.id,
                    twitter_user_id=twitter_user_id,
                    screen_name=screen_name,
                    display_name=legacy_user.get("name"),
                    bio=legacy_user.get("description"),
                    profile_image_url=legacy_user.get("profile_image_url_https"),
                    followers_count=legacy_user.get("followers_count", 0),
                    following_count=legacy_user.get("friends_count", 0),
                    tweet_count=legacy_user.get("statuses_count", 0),
                    verified=legacy_user.get("verified", False),
                    account_created_at=account_created_at,
                    comment_text=legacy_tweet.get("full_text", ""),
                    comment_tweet_id=reply.get("rest_id", ""),
                    commented_at=commented_at,
                    comment_like_count=legacy_tweet.get("favorite_count", 0),
                    comment_reply_count=legacy_tweet.get("reply_count", 0),
                )

                if commenter:
                    added_count += 1

        except Exception as e:
            logger.exception("Error scraping tweet replies", tweet_id=tweet.tweet_id)

        # Mark tweet as scraped
        await self.mark_tweet_commenters_scraped(tweet.id)

        logger.info(
            "Scraped tweet replies",
            tweet_id=tweet.tweet_id,
            added_count=added_count,
        )

        return added_count
