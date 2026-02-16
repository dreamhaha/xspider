"""Dashboard routes for admin module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import (
    AccountStatus,
    AdminUser,
    CreditTransaction,
    MonitoredInfluencer,
    MonitorStatus,
    ProxyServer,
    ProxyStatus,
    SearchStatus,
    TransactionType,
    TweetCommenter,
    TwitterAccount,
    UserSearch,
)
from xspider.admin.schemas import (
    AccountStatusDistribution,
    DailySearchStats,
    DashboardStats,
    MonitoringStats,
    ProxyStatusDistribution,
    RecentActivity,
)

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> DashboardStats:
    """Get dashboard statistics."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Account stats
    account_result = await db.execute(select(func.count(TwitterAccount.id)))
    total_accounts = account_result.scalar() or 0

    active_accounts_result = await db.execute(
        select(func.count(TwitterAccount.id)).where(
            TwitterAccount.status == AccountStatus.ACTIVE
        )
    )
    active_accounts = active_accounts_result.scalar() or 0

    rate_limited_result = await db.execute(
        select(func.count(TwitterAccount.id)).where(
            TwitterAccount.status == AccountStatus.RATE_LIMITED
        )
    )
    rate_limited_accounts = rate_limited_result.scalar() or 0

    error_accounts_result = await db.execute(
        select(func.count(TwitterAccount.id)).where(
            TwitterAccount.status.in_([AccountStatus.BANNED, AccountStatus.ERROR])
        )
    )
    error_accounts = error_accounts_result.scalar() or 0

    # Proxy stats
    proxy_total_result = await db.execute(select(func.count(ProxyServer.id)))
    total_proxies = proxy_total_result.scalar() or 0

    active_proxies_result = await db.execute(
        select(func.count(ProxyServer.id)).where(
            ProxyServer.status == ProxyStatus.ACTIVE
        )
    )
    active_proxies = active_proxies_result.scalar() or 0

    error_proxies_result = await db.execute(
        select(func.count(ProxyServer.id)).where(ProxyServer.status == ProxyStatus.ERROR)
    )
    error_proxies = error_proxies_result.scalar() or 0

    # User stats
    user_total_result = await db.execute(select(func.count(AdminUser.id)))
    total_users = user_total_result.scalar() or 0

    active_users_result = await db.execute(
        select(func.count(AdminUser.id)).where(AdminUser.last_login_at >= today_start)
    )
    active_users_today = active_users_result.scalar() or 0

    # Search stats
    searches_today_result = await db.execute(
        select(func.count(UserSearch.id)).where(UserSearch.created_at >= today_start)
    )
    searches_today = searches_today_result.scalar() or 0

    searches_running_result = await db.execute(
        select(func.count(UserSearch.id)).where(
            UserSearch.status == SearchStatus.RUNNING
        )
    )
    searches_running = searches_running_result.scalar() or 0

    # Credits used today
    credits_result = await db.execute(
        select(func.coalesce(func.sum(func.abs(CreditTransaction.amount)), 0)).where(
            CreditTransaction.created_at >= today_start,
            CreditTransaction.type != TransactionType.RECHARGE,
        )
    )
    total_credits_used_today = credits_result.scalar() or 0

    return DashboardStats(
        total_accounts=total_accounts,
        active_accounts=active_accounts,
        rate_limited_accounts=rate_limited_accounts,
        error_accounts=error_accounts,
        total_proxies=total_proxies,
        active_proxies=active_proxies,
        error_proxies=error_proxies,
        total_users=total_users,
        active_users_today=active_users_today,
        searches_today=searches_today,
        searches_running=searches_running,
        total_credits_used_today=total_credits_used_today,
    )


@router.get("/account-distribution", response_model=AccountStatusDistribution)
async def get_account_status_distribution(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountStatusDistribution:
    """Get account status distribution for charts."""
    status_counts = {
        "active": 0,
        "rate_limited": 0,
        "banned": 0,
        "needs_verify": 0,
        "error": 0,
    }

    for status in AccountStatus:
        result = await db.execute(
            select(func.count(TwitterAccount.id)).where(
                TwitterAccount.status == status
            )
        )
        count = result.scalar() or 0
        status_counts[status.value] = count

    return AccountStatusDistribution(**status_counts)


@router.get("/proxy-distribution", response_model=ProxyStatusDistribution)
async def get_proxy_status_distribution(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> ProxyStatusDistribution:
    """Get proxy status distribution for charts."""
    status_counts = {"active": 0, "inactive": 0, "error": 0}

    for status in ProxyStatus:
        result = await db.execute(
            select(func.count(ProxyServer.id)).where(ProxyServer.status == status)
        )
        count = result.scalar() or 0
        status_counts[status.value] = count

    return ProxyStatusDistribution(**status_counts)


@router.get("/daily-searches", response_model=list[DailySearchStats])
async def get_daily_search_stats(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    days: int = 7,
    db: AsyncSession = Depends(get_db_session),
) -> list[DailySearchStats]:
    """Get daily search statistics for the last N days."""
    now = datetime.now(timezone.utc)
    stats = []

    for i in range(days - 1, -1, -1):
        day_start = (now - timedelta(days=i)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = day_start + timedelta(days=1)

        # Count searches
        search_result = await db.execute(
            select(func.count(UserSearch.id)).where(
                UserSearch.created_at >= day_start,
                UserSearch.created_at < day_end,
            )
        )
        searches = search_result.scalar() or 0

        # Sum credits used
        credits_result = await db.execute(
            select(func.coalesce(func.sum(func.abs(CreditTransaction.amount)), 0)).where(
                CreditTransaction.created_at >= day_start,
                CreditTransaction.created_at < day_end,
                CreditTransaction.type != TransactionType.RECHARGE,
            )
        )
        credits_used = credits_result.scalar() or 0

        stats.append(
            DailySearchStats(
                date=day_start.strftime("%Y-%m-%d"),
                searches=searches,
                credits_used=credits_used,
            )
        )

    return stats


@router.get("/recent-activity", response_model=list[RecentActivity])
async def get_recent_activity(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    limit: int = 10,
    db: AsyncSession = Depends(get_db_session),
) -> list[RecentActivity]:
    """Get recent activity feed."""
    activities = []

    # Recent searches
    search_result = await db.execute(
        select(UserSearch)
        .join(AdminUser)
        .order_by(UserSearch.created_at.desc())
        .limit(limit)
    )
    for search in search_result.scalars():
        activities.append(
            RecentActivity(
                type="search",
                description=f"Started search for '{search.keywords[:50]}...'",
                user=search.user.username,
                timestamp=search.created_at,
            )
        )

    # Recent logins
    login_result = await db.execute(
        select(AdminUser)
        .where(AdminUser.last_login_at.isnot(None))
        .order_by(AdminUser.last_login_at.desc())
        .limit(limit)
    )
    for user in login_result.scalars():
        if user.last_login_at:
            activities.append(
                RecentActivity(
                    type="login",
                    description="User logged in",
                    user=user.username,
                    timestamp=user.last_login_at,
                )
            )

    # Recent recharges
    recharge_result = await db.execute(
        select(CreditTransaction)
        .join(AdminUser, CreditTransaction.user_id == AdminUser.id)
        .where(CreditTransaction.type == TransactionType.RECHARGE)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    for tx in recharge_result.scalars():
        activities.append(
            RecentActivity(
                type="recharge",
                description=f"Recharged {tx.amount} credits",
                user=tx.user.username,
                timestamp=tx.created_at,
            )
        )

    # Sort by timestamp and return top N
    activities.sort(key=lambda x: x.timestamp, reverse=True)
    return activities[:limit]


@router.get("/monitoring-stats", response_model=MonitoringStats)
async def get_monitoring_stats(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> MonitoringStats:
    """Get monitoring statistics for dashboard."""
    # Total monitors
    total_result = await db.execute(select(func.count(MonitoredInfluencer.id)))
    total_monitors = total_result.scalar() or 0

    # Active monitors
    active_result = await db.execute(
        select(func.count(MonitoredInfluencer.id)).where(
            MonitoredInfluencer.status == MonitorStatus.ACTIVE
        )
    )
    active_monitors = active_result.scalar() or 0

    # Paused monitors
    paused_result = await db.execute(
        select(func.count(MonitoredInfluencer.id)).where(
            MonitoredInfluencer.status == MonitorStatus.PAUSED
        )
    )
    paused_monitors = paused_result.scalar() or 0

    # Total tweets collected
    tweets_result = await db.execute(
        select(func.coalesce(func.sum(MonitoredInfluencer.tweets_collected), 0))
    )
    total_tweets_collected = tweets_result.scalar() or 0

    # Total commenters analyzed
    commenters_result = await db.execute(
        select(func.coalesce(func.sum(MonitoredInfluencer.commenters_analyzed), 0))
    )
    total_commenters_analyzed = commenters_result.scalar() or 0

    # Real users found
    real_result = await db.execute(
        select(func.count(TweetCommenter.id)).where(
            TweetCommenter.is_real_user == True  # noqa: E712
        )
    )
    real_users_found = real_result.scalar() or 0

    # Bots detected
    bots_result = await db.execute(
        select(func.count(TweetCommenter.id)).where(
            TweetCommenter.is_bot == True  # noqa: E712
        )
    )
    bots_detected = bots_result.scalar() or 0

    # DM available
    dm_result = await db.execute(
        select(func.count(TweetCommenter.id)).where(
            TweetCommenter.can_dm == True  # noqa: E712
        )
    )
    dm_available_count = dm_result.scalar() or 0

    return MonitoringStats(
        total_monitors=total_monitors,
        active_monitors=active_monitors,
        paused_monitors=paused_monitors,
        total_tweets_collected=total_tweets_collected,
        total_commenters_analyzed=total_commenters_analyzed,
        real_users_found=real_users_found,
        bots_detected=bots_detected,
        dm_available_count=dm_available_count,
    )
