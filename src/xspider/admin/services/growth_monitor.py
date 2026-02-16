"""Growth Anomaly Detection Service (增长异常检测服务)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    FollowerSnapshot,
    MonitoredInfluencer,
    MonitoredTweet,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class GrowthMonitor:
    """
    Monitor for detecting suspicious follower growth patterns.

    Detects:
    - Sudden follower spikes without viral content
    - Unusual follower/engagement ratios
    - Bot-like follower acquisition patterns
    """

    # Anomaly thresholds
    SPIKE_THRESHOLD_PCT = 10.0  # 10% growth in 24h is suspicious
    MIN_FOLLOWERS_FOR_ANALYSIS = 1000  # Only analyze accounts with 1k+ followers
    ENGAGEMENT_RATE_THRESHOLD = 0.5  # Min expected engagement rate %

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def take_snapshot(
        self,
        influencer: MonitoredInfluencer,
    ) -> FollowerSnapshot:
        """Take a snapshot of current follower metrics."""
        # Get previous snapshot for comparison
        prev_result = await self.db.execute(
            select(FollowerSnapshot)
            .where(FollowerSnapshot.influencer_id == influencer.id)
            .order_by(FollowerSnapshot.snapshot_at.desc())
            .limit(1)
        )
        prev_snapshot = prev_result.scalar_one_or_none()

        # Calculate engagement metrics from recent tweets
        avg_likes, avg_retweets, avg_replies = await self._calculate_engagement(
            influencer.id
        )

        # Calculate growth
        followers_change = 0
        followers_change_pct = 0.0

        if prev_snapshot:
            followers_change = influencer.followers_count - prev_snapshot.followers_count
            if prev_snapshot.followers_count > 0:
                followers_change_pct = (
                    followers_change / prev_snapshot.followers_count * 100
                )

        # Detect anomaly
        is_anomaly = False
        anomaly_type = None
        anomaly_score = 0.0

        if influencer.followers_count >= self.MIN_FOLLOWERS_FOR_ANALYSIS:
            anomaly_result = await self._detect_anomaly(
                influencer=influencer,
                followers_change=followers_change,
                followers_change_pct=followers_change_pct,
                avg_likes=avg_likes,
                avg_retweets=avg_retweets,
                prev_snapshot=prev_snapshot,
            )
            is_anomaly = anomaly_result["is_anomaly"]
            anomaly_type = anomaly_result.get("type")
            anomaly_score = anomaly_result.get("score", 0.0)

        snapshot = FollowerSnapshot(
            influencer_id=influencer.id,
            followers_count=influencer.followers_count,
            following_count=influencer.following_count,
            tweet_count=influencer.tweet_count,
            avg_likes=avg_likes,
            avg_retweets=avg_retweets,
            avg_replies=avg_replies,
            followers_change=followers_change,
            followers_change_pct=followers_change_pct,
            is_anomaly=is_anomaly,
            anomaly_type=anomaly_type,
            anomaly_score=anomaly_score,
        )

        self.db.add(snapshot)
        await self.db.commit()
        await self.db.refresh(snapshot)

        if is_anomaly:
            logger.warning(
                "Growth anomaly detected",
                influencer_id=influencer.id,
                screen_name=influencer.screen_name,
                anomaly_type=anomaly_type,
                anomaly_score=anomaly_score,
                followers_change=followers_change,
                followers_change_pct=followers_change_pct,
            )

        return snapshot

    async def _calculate_engagement(
        self,
        influencer_id: int,
    ) -> tuple[float, float, float]:
        """Calculate average engagement metrics from recent tweets."""
        # Get tweets from last 7 days
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        result = await self.db.execute(
            select(
                func.avg(MonitoredTweet.like_count),
                func.avg(MonitoredTweet.retweet_count),
                func.avg(MonitoredTweet.reply_count),
            ).where(
                MonitoredTweet.influencer_id == influencer_id,
                MonitoredTweet.tweeted_at >= week_ago,
            )
        )
        row = result.one_or_none()

        if row and row[0] is not None:
            return float(row[0] or 0), float(row[1] or 0), float(row[2] or 0)

        return 0.0, 0.0, 0.0

    async def _detect_anomaly(
        self,
        influencer: MonitoredInfluencer,
        followers_change: int,
        followers_change_pct: float,
        avg_likes: float,
        avg_retweets: float,
        prev_snapshot: FollowerSnapshot | None,
    ) -> dict[str, Any]:
        """Detect growth anomalies."""
        anomaly_score = 0.0
        anomaly_type = None

        # 1. Sudden spike detection
        if followers_change_pct > self.SPIKE_THRESHOLD_PCT:
            # Check if there was viral content
            viral_content = await self._has_viral_content(
                influencer.id,
                days=1,
                min_engagement_ratio=10.0,  # 10x normal engagement
            )

            if not viral_content:
                anomaly_score = min(100, followers_change_pct * 5)
                anomaly_type = "suspicious_growth"

        # 2. Sudden drop detection
        elif followers_change_pct < -5.0:  # Lost more than 5% followers
            anomaly_score = min(100, abs(followers_change_pct) * 5)
            anomaly_type = "sudden_drop"

        # 3. Low engagement ratio
        if influencer.followers_count > 10000 and avg_likes > 0:
            engagement_rate = (avg_likes / influencer.followers_count) * 100
            if engagement_rate < self.ENGAGEMENT_RATE_THRESHOLD:
                # Existing followers might be bots
                if anomaly_type is None:
                    anomaly_type = "low_engagement"
                    anomaly_score = max(anomaly_score, 50)

        # 4. Following/Follower ratio anomaly
        if influencer.followers_count > 0:
            ratio = influencer.following_count / influencer.followers_count
            if ratio > 2.0:  # Following 2x more than followers
                if anomaly_type is None:
                    anomaly_type = "suspicious_ratio"
                    anomaly_score = max(anomaly_score, 30)

        return {
            "is_anomaly": anomaly_score > 30,
            "type": anomaly_type,
            "score": anomaly_score,
        }

    async def _has_viral_content(
        self,
        influencer_id: int,
        days: int = 1,
        min_engagement_ratio: float = 10.0,
    ) -> bool:
        """Check if there was viral content that could explain growth."""
        # Get average engagement
        avg_likes, avg_retweets, _ = await self._calculate_engagement(influencer_id)
        avg_engagement = avg_likes + avg_retweets

        if avg_engagement == 0:
            return False

        # Check recent tweets for viral content
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(MonitoredTweet).where(
                MonitoredTweet.influencer_id == influencer_id,
                MonitoredTweet.tweeted_at >= since,
            )
        )
        tweets = list(result.scalars().all())

        for tweet in tweets:
            engagement = tweet.like_count + tweet.retweet_count
            if engagement > avg_engagement * min_engagement_ratio:
                return True

        return False

    async def get_growth_history(
        self,
        influencer_id: int,
        days: int = 30,
    ) -> list[FollowerSnapshot]:
        """Get growth history for an influencer."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(FollowerSnapshot)
            .where(
                FollowerSnapshot.influencer_id == influencer_id,
                FollowerSnapshot.snapshot_at >= since,
            )
            .order_by(FollowerSnapshot.snapshot_at)
        )

        return list(result.scalars().all())

    async def get_anomalies(
        self,
        user_id: int | None = None,
        days: int = 7,
        min_score: float = 30.0,
    ) -> list[dict[str, Any]]:
        """Get recent anomalies across all monitored influencers."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        query = (
            select(FollowerSnapshot, MonitoredInfluencer)
            .join(MonitoredInfluencer)
            .where(
                FollowerSnapshot.is_anomaly == True,  # noqa: E712
                FollowerSnapshot.anomaly_score >= min_score,
                FollowerSnapshot.snapshot_at >= since,
            )
        )

        if user_id:
            query = query.where(MonitoredInfluencer.user_id == user_id)

        query = query.order_by(FollowerSnapshot.anomaly_score.desc())

        result = await self.db.execute(query)
        rows = result.all()

        anomalies = []
        for snapshot, influencer in rows:
            anomalies.append({
                "influencer_id": influencer.id,
                "screen_name": influencer.screen_name,
                "display_name": influencer.display_name,
                "followers_count": snapshot.followers_count,
                "followers_change": snapshot.followers_change,
                "followers_change_pct": snapshot.followers_change_pct,
                "anomaly_type": snapshot.anomaly_type,
                "anomaly_score": snapshot.anomaly_score,
                "snapshot_at": snapshot.snapshot_at,
            })

        return anomalies

    async def get_growth_summary(self, influencer_id: int) -> dict[str, Any]:
        """Get growth summary for an influencer."""
        # Get latest snapshot
        latest_result = await self.db.execute(
            select(FollowerSnapshot)
            .where(FollowerSnapshot.influencer_id == influencer_id)
            .order_by(FollowerSnapshot.snapshot_at.desc())
            .limit(1)
        )
        latest = latest_result.scalar_one_or_none()

        # Get snapshot from 7 days ago
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        week_result = await self.db.execute(
            select(FollowerSnapshot)
            .where(
                FollowerSnapshot.influencer_id == influencer_id,
                FollowerSnapshot.snapshot_at <= week_ago,
            )
            .order_by(FollowerSnapshot.snapshot_at.desc())
            .limit(1)
        )
        week_snapshot = week_result.scalar_one_or_none()

        # Get snapshot from 30 days ago
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        month_result = await self.db.execute(
            select(FollowerSnapshot)
            .where(
                FollowerSnapshot.influencer_id == influencer_id,
                FollowerSnapshot.snapshot_at <= month_ago,
            )
            .order_by(FollowerSnapshot.snapshot_at.desc())
            .limit(1)
        )
        month_snapshot = month_result.scalar_one_or_none()

        # Calculate growth
        growth_7d = 0
        growth_7d_pct = 0.0
        growth_30d = 0
        growth_30d_pct = 0.0

        if latest and week_snapshot:
            growth_7d = latest.followers_count - week_snapshot.followers_count
            if week_snapshot.followers_count > 0:
                growth_7d_pct = growth_7d / week_snapshot.followers_count * 100

        if latest and month_snapshot:
            growth_30d = latest.followers_count - month_snapshot.followers_count
            if month_snapshot.followers_count > 0:
                growth_30d_pct = growth_30d / month_snapshot.followers_count * 100

        # Count anomalies
        anomaly_result = await self.db.execute(
            select(func.count(FollowerSnapshot.id)).where(
                FollowerSnapshot.influencer_id == influencer_id,
                FollowerSnapshot.is_anomaly == True,  # noqa: E712
            )
        )
        anomaly_count = anomaly_result.scalar() or 0

        return {
            "influencer_id": influencer_id,
            "current_followers": latest.followers_count if latest else 0,
            "growth_7d": growth_7d,
            "growth_7d_pct": round(growth_7d_pct, 2),
            "growth_30d": growth_30d,
            "growth_30d_pct": round(growth_30d_pct, 2),
            "avg_likes": latest.avg_likes if latest else 0,
            "avg_retweets": latest.avg_retweets if latest else 0,
            "anomaly_count": anomaly_count,
            "latest_snapshot_at": latest.snapshot_at if latest else None,
        }

    async def batch_take_snapshots(
        self,
        user_id: int | None = None,
    ) -> int:
        """Take snapshots for all active monitored influencers."""
        from xspider.admin.models import MonitorStatus

        query = select(MonitoredInfluencer).where(
            MonitoredInfluencer.status == MonitorStatus.ACTIVE
        )

        if user_id:
            query = query.where(MonitoredInfluencer.user_id == user_id)

        result = await self.db.execute(query)
        influencers = list(result.scalars().all())

        count = 0
        for influencer in influencers:
            try:
                await self.take_snapshot(influencer)
                count += 1
            except Exception as e:
                logger.error(
                    "Failed to take snapshot",
                    influencer_id=influencer.id,
                    error=str(e),
                )

        logger.info("Batch snapshots completed", count=count)
        return count
