"""Influencer monitoring service for tracking tweets and commenters."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    MonitoredInfluencer,
    MonitoredTweet,
    MonitorStatus,
    TweetCommenter,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class InfluencerMonitorService:
    """Service for monitoring influencer tweets."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_influencer(
        self,
        user_id: int,
        twitter_user_id: str,
        screen_name: str,
        display_name: str | None = None,
        bio: str | None = None,
        followers_count: int = 0,
        following_count: int = 0,
        tweet_count: int = 0,
        verified: bool = False,
        profile_image_url: str | None = None,
        monitor_since: datetime | None = None,
        monitor_until: datetime | None = None,
        check_interval_minutes: int = 60,
        notes: str | None = None,
    ) -> MonitoredInfluencer:
        """Add a new influencer to monitor."""
        now = datetime.now(timezone.utc)

        influencer = MonitoredInfluencer(
            user_id=user_id,
            twitter_user_id=twitter_user_id,
            screen_name=screen_name,
            display_name=display_name,
            bio=bio,
            followers_count=followers_count,
            following_count=following_count,
            tweet_count=tweet_count,
            verified=verified,
            profile_image_url=profile_image_url,
            status=MonitorStatus.ACTIVE,
            monitor_since=monitor_since or now,
            monitor_until=monitor_until,
            check_interval_minutes=check_interval_minutes,
            next_check_at=now,  # Check immediately
            notes=notes,
        )

        self.db.add(influencer)
        await self.db.commit()
        await self.db.refresh(influencer)

        logger.info(
            "Added influencer to monitor",
            influencer_id=influencer.id,
            screen_name=screen_name,
        )

        return influencer

    async def get_influencer(self, influencer_id: int) -> MonitoredInfluencer | None:
        """Get a monitored influencer by ID."""
        result = await self.db.execute(
            select(MonitoredInfluencer).where(MonitoredInfluencer.id == influencer_id)
        )
        return result.scalar_one_or_none()

    async def get_influencer_by_screen_name(
        self, screen_name: str, user_id: int
    ) -> MonitoredInfluencer | None:
        """Get a monitored influencer by screen name for a user."""
        result = await self.db.execute(
            select(MonitoredInfluencer).where(
                MonitoredInfluencer.screen_name == screen_name,
                MonitoredInfluencer.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_influencers(
        self,
        user_id: int,
        status: MonitorStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MonitoredInfluencer], int]:
        """List monitored influencers for a user."""
        query = select(MonitoredInfluencer).where(
            MonitoredInfluencer.user_id == user_id
        )

        if status:
            query = query.where(MonitoredInfluencer.status == status)

        # Count total
        count_query = select(func.count(MonitoredInfluencer.id)).where(
            MonitoredInfluencer.user_id == user_id
        )
        if status:
            count_query = count_query.where(MonitoredInfluencer.status == status)
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(MonitoredInfluencer.created_at.desc())
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        influencers = list(result.scalars().all())

        return influencers, total

    async def update_influencer_status(
        self,
        influencer_id: int,
        status: MonitorStatus,
    ) -> MonitoredInfluencer | None:
        """Update influencer monitoring status."""
        influencer = await self.get_influencer(influencer_id)
        if not influencer:
            return None

        influencer.status = status

        if status == MonitorStatus.ACTIVE:
            # Reset next check time when reactivating
            influencer.next_check_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(influencer)

        return influencer

    async def get_influencers_due_for_check(
        self, limit: int = 10
    ) -> list[MonitoredInfluencer]:
        """Get influencers that are due for a tweet check."""
        now = datetime.now(timezone.utc)

        result = await self.db.execute(
            select(MonitoredInfluencer)
            .where(
                MonitoredInfluencer.status == MonitorStatus.ACTIVE,
                MonitoredInfluencer.next_check_at <= now,
            )
            .order_by(MonitoredInfluencer.next_check_at)
            .limit(limit)
        )

        return list(result.scalars().all())

    async def add_tweet(
        self,
        influencer_id: int,
        tweet_id: str,
        content: str,
        tweet_type: str = "tweet",
        like_count: int = 0,
        retweet_count: int = 0,
        reply_count: int = 0,
        quote_count: int = 0,
        view_count: int | None = None,
        bookmark_count: int = 0,
        has_media: bool = False,
        media_urls: list[str] | None = None,
        has_links: bool = False,
        links: list[str] | None = None,
        tweeted_at: datetime | None = None,
    ) -> MonitoredTweet | None:
        """Add a tweet from a monitored influencer."""
        # Check if tweet already exists
        existing = await self.db.execute(
            select(MonitoredTweet).where(MonitoredTweet.tweet_id == tweet_id)
        )
        if existing.scalar_one_or_none():
            logger.debug("Tweet already exists", tweet_id=tweet_id)
            return None

        tweet = MonitoredTweet(
            influencer_id=influencer_id,
            tweet_id=tweet_id,
            content=content,
            tweet_type=tweet_type,
            like_count=like_count,
            retweet_count=retweet_count,
            reply_count=reply_count,
            quote_count=quote_count,
            view_count=view_count,
            bookmark_count=bookmark_count,
            has_media=has_media,
            media_urls=json.dumps(media_urls) if media_urls else None,
            has_links=has_links,
            links=json.dumps(links) if links else None,
            tweeted_at=tweeted_at or datetime.now(timezone.utc),
        )

        self.db.add(tweet)

        # Update influencer stats
        influencer = await self.get_influencer(influencer_id)
        if influencer:
            influencer.tweets_collected += 1

        await self.db.commit()
        await self.db.refresh(tweet)

        logger.info(
            "Added monitored tweet",
            tweet_id=tweet_id,
            influencer_id=influencer_id,
        )

        return tweet

    async def get_tweets(
        self,
        influencer_id: int,
        since: datetime | None = None,
        until: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[MonitoredTweet], int]:
        """Get tweets for a monitored influencer."""
        query = select(MonitoredTweet).where(
            MonitoredTweet.influencer_id == influencer_id
        )

        if since:
            query = query.where(MonitoredTweet.tweeted_at >= since)
        if until:
            query = query.where(MonitoredTweet.tweeted_at <= until)

        # Count
        count_query = select(func.count(MonitoredTweet.id)).where(
            MonitoredTweet.influencer_id == influencer_id
        )
        if since:
            count_query = count_query.where(MonitoredTweet.tweeted_at >= since)
        if until:
            count_query = count_query.where(MonitoredTweet.tweeted_at <= until)
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(MonitoredTweet.tweeted_at.desc())
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        tweets = list(result.scalars().all())

        return tweets, total

    async def update_influencer_check_time(
        self,
        influencer_id: int,
    ) -> None:
        """Update the last and next check times for an influencer."""
        influencer = await self.get_influencer(influencer_id)
        if not influencer:
            return

        now = datetime.now(timezone.utc)
        influencer.last_checked_at = now
        influencer.next_check_at = now + timedelta(
            minutes=influencer.check_interval_minutes
        )

        await self.db.commit()

    async def get_monitoring_stats(self, user_id: int | None = None) -> dict[str, Any]:
        """Get monitoring statistics."""
        base_query = select(MonitoredInfluencer)
        if user_id:
            base_query = base_query.where(MonitoredInfluencer.user_id == user_id)

        # Total monitors
        total_result = await self.db.execute(
            select(func.count(MonitoredInfluencer.id)).select_from(
                base_query.subquery()
            )
        )
        total_monitors = total_result.scalar() or 0

        # Active monitors
        active_result = await self.db.execute(
            select(func.count(MonitoredInfluencer.id)).where(
                MonitoredInfluencer.status == MonitorStatus.ACTIVE,
                *([MonitoredInfluencer.user_id == user_id] if user_id else []),
            )
        )
        active_monitors = active_result.scalar() or 0

        # Paused monitors
        paused_result = await self.db.execute(
            select(func.count(MonitoredInfluencer.id)).where(
                MonitoredInfluencer.status == MonitorStatus.PAUSED,
                *([MonitoredInfluencer.user_id == user_id] if user_id else []),
            )
        )
        paused_monitors = paused_result.scalar() or 0

        # Total tweets collected
        tweets_result = await self.db.execute(
            select(func.coalesce(func.sum(MonitoredInfluencer.tweets_collected), 0)).where(
                *([MonitoredInfluencer.user_id == user_id] if user_id else []),
            )
        )
        total_tweets = tweets_result.scalar() or 0

        # Total commenters analyzed
        commenters_result = await self.db.execute(
            select(func.coalesce(func.sum(MonitoredInfluencer.commenters_analyzed), 0)).where(
                *([MonitoredInfluencer.user_id == user_id] if user_id else []),
            )
        )
        total_commenters = commenters_result.scalar() or 0

        # Real users, bots, DM available
        real_users_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(TweetCommenter.is_real_user == True)  # noqa: E712
        )
        real_users = real_users_result.scalar() or 0

        bots_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(TweetCommenter.is_bot == True)  # noqa: E712
        )
        bots = bots_result.scalar() or 0

        dm_available_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(TweetCommenter.can_dm == True)  # noqa: E712
        )
        dm_available = dm_available_result.scalar() or 0

        return {
            "total_monitors": total_monitors,
            "active_monitors": active_monitors,
            "paused_monitors": paused_monitors,
            "total_tweets_collected": total_tweets,
            "total_commenters_analyzed": total_commenters,
            "real_users_found": real_users,
            "bots_detected": bots,
            "dm_available_count": dm_available,
        }
