"""Account statistics and risk control service."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AccountActionType,
    AccountActivity,
    AccountDailyStats,
    AccountStatus,
    TwitterAccount,
)
from xspider.core import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# Risk thresholds
RISK_THRESHOLDS = {
    "requests_per_hour_warning": 50,  # Warning threshold
    "requests_per_hour_critical": 100,  # Critical threshold
    "rate_limit_count_warning": 2,  # Warning if rate limited 2+ times
    "rate_limit_count_critical": 5,  # Critical if rate limited 5+ times
    "error_rate_warning": 0.1,  # 10% error rate warning
    "error_rate_critical": 0.25,  # 25% error rate critical
    "response_time_warning_ms": 3000,  # 3s response time warning
    "response_time_critical_ms": 10000,  # 10s response time critical
}


class AccountStatsService:
    """Service for tracking and analyzing account statistics."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service."""
        self._session = session

    async def record_activity(
        self,
        account_id: int,
        action_type: AccountActionType,
        success: bool = True,
        response_time_ms: int | None = None,
        result_count: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        is_rate_limited: bool = False,
        endpoint: str | None = None,
        keyword: str | None = None,
        target_user_id: str | None = None,
    ) -> AccountActivity:
        """Record an account activity.

        Args:
            account_id: Twitter account ID.
            action_type: Type of action performed.
            success: Whether the action succeeded.
            response_time_ms: Response time in milliseconds.
            result_count: Number of results returned.
            error_code: Error code if failed.
            error_message: Error message if failed.
            is_rate_limited: Whether rate limited.
            endpoint: API endpoint called.
            keyword: Search keyword if applicable.
            target_user_id: Target user ID if applicable.

        Returns:
            Created AccountActivity record.
        """
        activity = AccountActivity(
            account_id=account_id,
            action_type=action_type,
            success=success,
            response_time_ms=response_time_ms,
            result_count=result_count,
            error_code=error_code,
            error_message=error_message,
            is_rate_limited=is_rate_limited,
            endpoint=endpoint,
            keyword=keyword,
            target_user_id=target_user_id,
        )
        self._session.add(activity)

        # Update account request/error count
        result = await self._session.execute(
            select(TwitterAccount).where(TwitterAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        if account:
            account.request_count += 1
            if not success:
                account.error_count += 1
            account.last_used_at = datetime.now(timezone.utc)
            if is_rate_limited:
                account.status = AccountStatus.RATE_LIMITED
                account.rate_limit_reset = datetime.now(timezone.utc) + timedelta(minutes=15)

        await self._session.commit()

        logger.debug(
            "account_stats.activity_recorded",
            account_id=account_id,
            action_type=action_type.value,
            success=success,
        )

        return activity

    async def update_daily_stats(self, account_id: int, date: datetime | None = None) -> AccountDailyStats:
        """Update or create daily statistics for an account.

        Args:
            account_id: Twitter account ID.
            date: Date to update stats for (defaults to today).

        Returns:
            Updated AccountDailyStats record.
        """
        if date is None:
            date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            date = date.replace(hour=0, minute=0, second=0, microsecond=0)

        # Get or create daily stats
        result = await self._session.execute(
            select(AccountDailyStats).where(
                AccountDailyStats.account_id == account_id,
                func.date(AccountDailyStats.stat_date) == func.date(date),
            )
        )
        stats = result.scalar_one_or_none()

        if not stats:
            stats = AccountDailyStats(
                account_id=account_id,
                stat_date=date,
            )
            self._session.add(stats)

        # Calculate stats from activities
        start_of_day = date
        end_of_day = date + timedelta(days=1)

        # Get activities for the day
        activities_result = await self._session.execute(
            select(AccountActivity).where(
                AccountActivity.account_id == account_id,
                AccountActivity.created_at >= start_of_day,
                AccountActivity.created_at < end_of_day,
            )
        )
        activities = list(activities_result.scalars().all())

        # Calculate totals
        stats.total_requests = len(activities)
        stats.successful_requests = sum(1 for a in activities if a.success)
        stats.failed_requests = sum(1 for a in activities if not a.success)
        stats.rate_limit_hits = sum(1 for a in activities if a.is_rate_limited)

        # Action breakdown
        stats.search_count = sum(1 for a in activities if a.action_type == AccountActionType.SEARCH_USER)
        stats.user_fetch_count = sum(1 for a in activities if a.action_type == AccountActionType.GET_USER_INFO)
        stats.tweet_fetch_count = sum(1 for a in activities if a.action_type == AccountActionType.GET_TWEETS)
        stats.dm_count = sum(1 for a in activities if a.action_type == AccountActionType.SEND_DM)
        stats.post_count = sum(1 for a in activities if a.action_type == AccountActionType.POST_TWEET)
        stats.reply_count = sum(1 for a in activities if a.action_type == AccountActionType.POST_REPLY)
        stats.like_count = sum(1 for a in activities if a.action_type == AccountActionType.LIKE_TWEET)

        # Response time metrics
        response_times = [a.response_time_ms for a in activities if a.response_time_ms is not None]
        if response_times:
            stats.avg_response_time_ms = sum(response_times) / len(response_times)
            stats.max_response_time_ms = max(response_times)
            stats.min_response_time_ms = min(response_times)

        # Rate limit tracking
        rate_limited_activities = [a for a in activities if a.is_rate_limited]
        if rate_limited_activities:
            stats.first_rate_limit_at = min(a.created_at for a in rate_limited_activities)
            stats.last_rate_limit_at = max(a.created_at for a in rate_limited_activities)
            # Estimate rate limit duration (15 min per rate limit)
            stats.rate_limit_duration_minutes = len(rate_limited_activities) * 15

        # Hourly distribution
        hourly_dist = {}
        for a in activities:
            hour = a.created_at.hour
            hourly_dist[str(hour)] = hourly_dist.get(str(hour), 0) + 1
        stats.hourly_distribution = json.dumps(hourly_dist)

        # Calculate risk score
        stats.risk_score = self._calculate_risk_score(stats, activities)
        stats.anomaly_detected = stats.risk_score >= 70
        if stats.anomaly_detected:
            stats.anomaly_reason = self._get_anomaly_reason(stats)

        await self._session.commit()

        return stats

    def _calculate_risk_score(
        self, stats: AccountDailyStats, activities: list[AccountActivity]
    ) -> float:
        """Calculate risk score for the day (0-100).

        Higher score = higher risk of being flagged/banned.
        """
        score = 0.0

        # Factor 1: Request volume (max 25 points)
        if stats.total_requests > 0:
            requests_per_hour = stats.total_requests / 24
            if requests_per_hour > RISK_THRESHOLDS["requests_per_hour_critical"]:
                score += 25
            elif requests_per_hour > RISK_THRESHOLDS["requests_per_hour_warning"]:
                score += 15
            elif requests_per_hour > 20:
                score += 5

        # Factor 2: Rate limit hits (max 30 points)
        if stats.rate_limit_hits >= RISK_THRESHOLDS["rate_limit_count_critical"]:
            score += 30
        elif stats.rate_limit_hits >= RISK_THRESHOLDS["rate_limit_count_warning"]:
            score += 15
        elif stats.rate_limit_hits > 0:
            score += 5

        # Factor 3: Error rate (max 20 points)
        if stats.total_requests > 0:
            error_rate = stats.failed_requests / stats.total_requests
            if error_rate >= RISK_THRESHOLDS["error_rate_critical"]:
                score += 20
            elif error_rate >= RISK_THRESHOLDS["error_rate_warning"]:
                score += 10
            elif error_rate > 0.05:
                score += 3

        # Factor 4: Response time (max 10 points)
        if stats.avg_response_time_ms:
            if stats.avg_response_time_ms >= RISK_THRESHOLDS["response_time_critical_ms"]:
                score += 10
            elif stats.avg_response_time_ms >= RISK_THRESHOLDS["response_time_warning_ms"]:
                score += 5

        # Factor 5: Burst activity (max 15 points)
        if stats.hourly_distribution:
            hourly = json.loads(stats.hourly_distribution)
            max_hourly = max(hourly.values()) if hourly else 0
            if max_hourly > RISK_THRESHOLDS["requests_per_hour_critical"]:
                score += 15
            elif max_hourly > RISK_THRESHOLDS["requests_per_hour_warning"]:
                score += 8

        return min(score, 100.0)

    def _get_anomaly_reason(self, stats: AccountDailyStats) -> str:
        """Get human-readable anomaly reason."""
        reasons = []

        if stats.rate_limit_hits >= RISK_THRESHOLDS["rate_limit_count_critical"]:
            reasons.append(f"High rate limit count ({stats.rate_limit_hits})")

        if stats.total_requests > 0:
            error_rate = stats.failed_requests / stats.total_requests
            if error_rate >= RISK_THRESHOLDS["error_rate_critical"]:
                reasons.append(f"High error rate ({error_rate:.1%})")

        requests_per_hour = stats.total_requests / 24
        if requests_per_hour > RISK_THRESHOLDS["requests_per_hour_critical"]:
            reasons.append(f"High request volume ({requests_per_hour:.1f}/hr)")

        if stats.hourly_distribution:
            hourly = json.loads(stats.hourly_distribution)
            max_hourly = max(hourly.values()) if hourly else 0
            if max_hourly > RISK_THRESHOLDS["requests_per_hour_critical"]:
                reasons.append(f"Burst activity detected ({max_hourly} requests in 1 hour)")

        return "; ".join(reasons) if reasons else "Multiple risk factors"

    async def get_account_stats(
        self, account_id: int, days: int = 7
    ) -> dict:
        """Get comprehensive statistics for an account.

        Args:
            account_id: Twitter account ID.
            days: Number of days to include.

        Returns:
            Dictionary with account statistics.
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        # Get daily stats
        result = await self._session.execute(
            select(AccountDailyStats).where(
                AccountDailyStats.account_id == account_id,
                AccountDailyStats.stat_date >= start_date,
            ).order_by(AccountDailyStats.stat_date.desc())
        )
        daily_stats = list(result.scalars().all())

        # Get account info
        account_result = await self._session.execute(
            select(TwitterAccount).where(TwitterAccount.id == account_id)
        )
        account = account_result.scalar_one_or_none()

        # Get recent activities (last 100)
        activities_result = await self._session.execute(
            select(AccountActivity).where(
                AccountActivity.account_id == account_id,
            ).order_by(AccountActivity.created_at.desc()).limit(100)
        )
        recent_activities = list(activities_result.scalars().all())

        # Calculate totals
        total_requests = sum(s.total_requests for s in daily_stats)
        total_successful = sum(s.successful_requests for s in daily_stats)
        total_failed = sum(s.failed_requests for s in daily_stats)
        total_rate_limits = sum(s.rate_limit_hits for s in daily_stats)
        avg_risk_score = sum(s.risk_score for s in daily_stats) / len(daily_stats) if daily_stats else 0

        # Calculate average response time from recent activities
        response_times = [a.response_time_ms for a in recent_activities if a.response_time_ms]
        avg_response_time_ms = sum(response_times) / len(response_times) if response_times else 0

        # Action breakdown
        action_breakdown = {
            "search": sum(s.search_count for s in daily_stats),
            "user_fetch": sum(s.user_fetch_count for s in daily_stats),
            "tweet_fetch": sum(s.tweet_fetch_count for s in daily_stats),
            "dm": sum(s.dm_count for s in daily_stats),
            "post": sum(s.post_count for s in daily_stats),
            "reply": sum(s.reply_count for s in daily_stats),
            "like": sum(s.like_count for s in daily_stats),
        }

        # Daily breakdown
        daily_breakdown = [
            {
                "date": s.stat_date.isoformat(),
                "total_requests": s.total_requests,
                "successful": s.successful_requests,
                "failed": s.failed_requests,
                "rate_limits": s.rate_limit_hits,
                "risk_score": s.risk_score,
                "anomaly": s.anomaly_detected,
            }
            for s in daily_stats
        ]

        # Risk assessment
        current_risk = daily_stats[0].risk_score if daily_stats else 0
        if current_risk >= 70:
            risk_level = "critical"
        elif current_risk >= 50:
            risk_level = "high"
        elif current_risk >= 30:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "account_id": account_id,
            "account_name": account.name if account else None,
            "account_status": account.status.value if account else None,
            "period_days": days,
            "summary": {
                "total_requests": total_requests,
                "successful_requests": total_successful,
                "failed_requests": total_failed,
                "success_rate": total_successful / total_requests if total_requests > 0 else 1.0,
                "rate_limit_hits": total_rate_limits,
                "avg_requests_per_day": total_requests / days if days > 0 else 0,
                "avg_risk_score": avg_risk_score,
                "avg_response_time_ms": avg_response_time_ms,
                "current_risk_level": risk_level,
            },
            "action_breakdown": action_breakdown,
            "daily_breakdown": daily_breakdown,
            "recent_activities": [
                {
                    "id": a.id,
                    "action_type": a.action_type.value,
                    "success": a.success,
                    "response_time_ms": a.response_time_ms,
                    "error_code": a.error_code,
                    "is_rate_limited": a.is_rate_limited,
                    "created_at": a.created_at.isoformat(),
                }
                for a in recent_activities[:20]
            ],
        }

    async def get_all_accounts_risk_summary(self) -> list[dict]:
        """Get risk summary for all accounts.

        Returns:
            List of account risk summaries.
        """
        # Get all active accounts
        accounts_result = await self._session.execute(
            select(TwitterAccount).where(TwitterAccount.status != AccountStatus.BANNED)
        )
        accounts = list(accounts_result.scalars().all())

        # Get latest daily stats for each account
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)

        summaries = []
        for account in accounts:
            # Get today's and yesterday's stats
            stats_result = await self._session.execute(
                select(AccountDailyStats).where(
                    AccountDailyStats.account_id == account.id,
                    AccountDailyStats.stat_date >= yesterday,
                ).order_by(AccountDailyStats.stat_date.desc())
            )
            stats = list(stats_result.scalars().all())

            today_stats = next((s for s in stats if s.stat_date.date() == today.date()), None)
            yesterday_stats = next((s for s in stats if s.stat_date.date() == yesterday.date()), None)

            # Determine risk level
            risk_score = today_stats.risk_score if today_stats else 0
            if risk_score >= 70:
                risk_level = "critical"
            elif risk_score >= 50:
                risk_level = "high"
            elif risk_score >= 30:
                risk_level = "medium"
            else:
                risk_level = "low"

            summaries.append({
                "account_id": account.id,
                "account_name": account.name,
                "status": account.status.value,
                "total_requests": account.request_count,
                "total_errors": account.error_count,
                "last_used": account.last_used_at.isoformat() if account.last_used_at else None,
                "today": {
                    "requests": today_stats.total_requests if today_stats else 0,
                    "rate_limits": today_stats.rate_limit_hits if today_stats else 0,
                    "risk_score": today_stats.risk_score if today_stats else 0,
                    "anomaly": today_stats.anomaly_detected if today_stats else False,
                } if today_stats else None,
                "yesterday": {
                    "requests": yesterday_stats.total_requests if yesterday_stats else 0,
                    "rate_limits": yesterday_stats.rate_limit_hits if yesterday_stats else 0,
                    "risk_score": yesterday_stats.risk_score if yesterday_stats else 0,
                } if yesterday_stats else None,
                "risk_level": risk_level,
            })

        # Sort by risk score (highest first)
        summaries.sort(key=lambda x: x["today"]["risk_score"] if x.get("today") else 0, reverse=True)

        return summaries


async def record_search_activity(
    session: AsyncSession,
    account_id: int,
    keyword: str,
    success: bool,
    result_count: int = 0,
    response_time_ms: int | None = None,
    is_rate_limited: bool = False,
    error_message: str | None = None,
) -> None:
    """Convenience function to record a search activity.

    Args:
        session: Database session.
        account_id: Twitter account ID.
        keyword: Search keyword.
        success: Whether the search succeeded.
        result_count: Number of results.
        response_time_ms: Response time in ms.
        is_rate_limited: Whether rate limited.
        error_message: Error message if failed.
    """
    service = AccountStatsService(session)
    await service.record_activity(
        account_id=account_id,
        action_type=AccountActionType.SEARCH_USER,
        success=success,
        result_count=result_count,
        response_time_ms=response_time_ms,
        is_rate_limited=is_rate_limited,
        error_message=error_message,
        keyword=keyword,
    )
