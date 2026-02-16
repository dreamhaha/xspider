"""Data Privacy and Retention Service (数据隐私与保留服务)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AIOpener,
    AudienceOverlapAnalysis,
    CreditTransaction,
    DataRetentionPolicy,
    DiscoveredInfluencer,
    FollowerSnapshot,
    LeadActivity,
    MonitoredTweet,
    SalesLead,
    TweetCommenter,
    UserSearch,
    WebhookLog,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class PrivacyService:
    """
    Service for managing data privacy and retention.

    Implements:
    - GDPR compliance features
    - Data retention policies
    - Data export for users
    - Data deletion requests
    """

    # Default retention periods (days)
    DEFAULT_RETENTION = {
        "search_results": 90,
        "commenter_data": 60,
        "lead_data": 180,
        "analytics": 365,
        "webhooks": 30,
        "transactions": 730,  # 2 years for financial records
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ==================== Retention Policies ====================

    async def get_retention_policy(
        self,
        user_id: int,
    ) -> DataRetentionPolicy | None:
        """Get retention policy for a user."""
        result = await self.db.execute(
            select(DataRetentionPolicy).where(
                DataRetentionPolicy.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def set_retention_policy(
        self,
        user_id: int,
        search_results_days: int | None = None,
        commenter_data_days: int | None = None,
        lead_data_days: int | None = None,
        analytics_days: int | None = None,
        webhook_logs_days: int | None = None,
        auto_delete_enabled: bool = True,
    ) -> DataRetentionPolicy:
        """Set or update retention policy for a user."""
        existing = await self.get_retention_policy(user_id)

        if existing:
            if search_results_days is not None:
                existing.search_results_days = search_results_days
            if commenter_data_days is not None:
                existing.commenter_data_days = commenter_data_days
            if lead_data_days is not None:
                existing.lead_data_days = lead_data_days
            if analytics_days is not None:
                existing.analytics_days = analytics_days
            if webhook_logs_days is not None:
                existing.webhook_logs_days = webhook_logs_days
            existing.auto_delete_enabled = auto_delete_enabled

            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        policy = DataRetentionPolicy(
            user_id=user_id,
            search_results_days=search_results_days or self.DEFAULT_RETENTION["search_results"],
            commenter_data_days=commenter_data_days or self.DEFAULT_RETENTION["commenter_data"],
            lead_data_days=lead_data_days or self.DEFAULT_RETENTION["lead_data"],
            analytics_days=analytics_days or self.DEFAULT_RETENTION["analytics"],
            webhook_logs_days=webhook_logs_days or self.DEFAULT_RETENTION["webhooks"],
            auto_delete_enabled=auto_delete_enabled,
        )

        self.db.add(policy)
        await self.db.commit()
        await self.db.refresh(policy)

        return policy

    # ==================== Data Cleanup ====================

    async def cleanup_expired_data(
        self,
        user_id: int | None = None,
    ) -> dict[str, int]:
        """
        Clean up expired data based on retention policies.

        Args:
            user_id: Optional user ID to clean up data for.
                    If None, cleans up for all users.

        Returns:
            Dict with counts of deleted records per table
        """
        stats = {
            "search_results": 0,
            "commenters": 0,
            "leads": 0,
            "snapshots": 0,
            "webhook_logs": 0,
        }

        if user_id:
            users = [user_id]
        else:
            # Get all users with policies
            result = await self.db.execute(
                select(DataRetentionPolicy.user_id).where(
                    DataRetentionPolicy.auto_delete_enabled == True  # noqa: E712
                )
            )
            users = [row[0] for row in result.all()]

        for uid in users:
            policy = await self.get_retention_policy(uid)
            if not policy or not policy.auto_delete_enabled:
                continue

            user_stats = await self._cleanup_user_data(uid, policy)
            for key, count in user_stats.items():
                stats[key] += count

        logger.info("Data cleanup completed", stats=stats)
        return stats

    async def _cleanup_user_data(
        self,
        user_id: int,
        policy: DataRetentionPolicy,
    ) -> dict[str, int]:
        """Clean up data for a specific user."""
        stats = {}
        now = datetime.now(timezone.utc)

        # Clean up search results and influencers
        if policy.search_results_days:
            cutoff = now - timedelta(days=policy.search_results_days)

            # Get search IDs to delete
            search_result = await self.db.execute(
                select(UserSearch.id).where(
                    UserSearch.user_id == user_id,
                    UserSearch.created_at < cutoff,
                )
            )
            search_ids = [row[0] for row in search_result.all()]

            if search_ids:
                # Delete discovered influencers
                await self.db.execute(
                    delete(DiscoveredInfluencer).where(
                        DiscoveredInfluencer.search_id.in_(search_ids)
                    )
                )
                # Delete searches
                del_result = await self.db.execute(
                    delete(UserSearch).where(UserSearch.id.in_(search_ids))
                )
                stats["search_results"] = del_result.rowcount

        # Clean up commenter data
        if policy.commenter_data_days:
            cutoff = now - timedelta(days=policy.commenter_data_days)

            # Get old tweets
            tweet_result = await self.db.execute(
                select(MonitoredTweet.id)
                .join(MonitoredTweet.influencer)
                .where(
                    MonitoredTweet.influencer.has(user_id=user_id),
                    MonitoredTweet.scraped_at < cutoff,
                )
            )
            tweet_ids = [row[0] for row in tweet_result.all()]

            if tweet_ids:
                del_result = await self.db.execute(
                    delete(TweetCommenter).where(
                        TweetCommenter.tweet_id.in_(tweet_ids)
                    )
                )
                stats["commenters"] = del_result.rowcount

        # Clean up lead activity (but keep leads)
        if policy.lead_data_days:
            cutoff = now - timedelta(days=policy.lead_data_days)

            # Get leads to find activities
            lead_result = await self.db.execute(
                select(SalesLead.id).where(SalesLead.user_id == user_id)
            )
            lead_ids = [row[0] for row in lead_result.all()]

            if lead_ids:
                del_result = await self.db.execute(
                    delete(LeadActivity).where(
                        LeadActivity.lead_id.in_(lead_ids),
                        LeadActivity.created_at < cutoff,
                    )
                )
                stats["lead_activities"] = del_result.rowcount

        # Clean up analytics/snapshots
        if policy.analytics_days:
            cutoff = now - timedelta(days=policy.analytics_days)

            del_result = await self.db.execute(
                delete(FollowerSnapshot)
                .where(FollowerSnapshot.snapshot_at < cutoff)
                .where(
                    FollowerSnapshot.influencer.has(user_id=user_id)
                )
            )
            stats["snapshots"] = del_result.rowcount

        # Clean up webhook logs
        if policy.webhook_logs_days:
            cutoff = now - timedelta(days=policy.webhook_logs_days)

            del_result = await self.db.execute(
                delete(WebhookLog)
                .where(WebhookLog.created_at < cutoff)
                .where(
                    WebhookLog.webhook.has(user_id=user_id)
                )
            )
            stats["webhook_logs"] = del_result.rowcount

        await self.db.commit()
        return stats

    # ==================== Data Export ====================

    async def export_user_data(
        self,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Export all user data for GDPR compliance.

        Returns a dict containing all data associated with the user.
        """
        from xspider.admin.models import AdminUser, MonitoredInfluencer

        export = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
        }

        # User info
        user_result = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            export["user_info"] = {
                "username": user.username,
                "email": user.email,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            }

        # Searches
        search_result = await self.db.execute(
            select(UserSearch).where(UserSearch.user_id == user_id)
        )
        searches = list(search_result.scalars().all())
        export["searches"] = [
            {
                "id": s.id,
                "keywords": s.keywords,
                "industry": s.industry,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "status": s.status,
            }
            for s in searches
        ]

        # Leads
        lead_result = await self.db.execute(
            select(SalesLead).where(SalesLead.user_id == user_id)
        )
        leads = list(lead_result.scalars().all())
        export["leads"] = [
            {
                "id": l.id,
                "screen_name": l.screen_name,
                "stage": l.stage.value if l.stage else None,
                "intent_score": l.intent_score,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ]

        # Monitored influencers
        influencer_result = await self.db.execute(
            select(MonitoredInfluencer).where(MonitoredInfluencer.user_id == user_id)
        )
        influencers = list(influencer_result.scalars().all())
        export["monitored_influencers"] = [
            {
                "id": i.id,
                "screen_name": i.screen_name,
                "followers_count": i.followers_count,
                "status": i.status.value if i.status else None,
            }
            for i in influencers
        ]

        # AI Openers
        opener_result = await self.db.execute(
            select(AIOpener).where(AIOpener.user_id == user_id)
        )
        openers = list(opener_result.scalars().all())
        export["ai_openers"] = [
            {
                "id": o.id,
                "target_screen_name": o.target_screen_name,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "is_used": o.is_used,
            }
            for o in openers
        ]

        # Transactions (summary only)
        tx_result = await self.db.execute(
            select(CreditTransaction).where(CreditTransaction.user_id == user_id)
        )
        transactions = list(tx_result.scalars().all())
        export["credit_transactions"] = [
            {
                "id": t.id,
                "amount": t.amount,
                "type": t.type.value if t.type else None,
                "description": t.description,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transactions
        ]

        logger.info("User data exported", user_id=user_id)
        return export

    # ==================== Data Deletion ====================

    async def delete_user_data(
        self,
        user_id: int,
        keep_transactions: bool = True,
    ) -> dict[str, int]:
        """
        Delete all user data (GDPR right to be forgotten).

        Args:
            user_id: User ID to delete data for
            keep_transactions: Whether to keep financial transactions

        Returns:
            Dict with counts of deleted records
        """
        stats = {}

        # Delete AI openers
        del_result = await self.db.execute(
            delete(AIOpener).where(AIOpener.user_id == user_id)
        )
        stats["ai_openers"] = del_result.rowcount

        # Delete audience analyses
        del_result = await self.db.execute(
            delete(AudienceOverlapAnalysis).where(
                AudienceOverlapAnalysis.user_id == user_id
            )
        )
        stats["audience_analyses"] = del_result.rowcount

        # Delete lead activities
        lead_result = await self.db.execute(
            select(SalesLead.id).where(SalesLead.user_id == user_id)
        )
        lead_ids = [row[0] for row in lead_result.all()]
        if lead_ids:
            del_result = await self.db.execute(
                delete(LeadActivity).where(LeadActivity.lead_id.in_(lead_ids))
            )
            stats["lead_activities"] = del_result.rowcount

        # Delete leads
        del_result = await self.db.execute(
            delete(SalesLead).where(SalesLead.user_id == user_id)
        )
        stats["leads"] = del_result.rowcount

        # Delete searches and discovered influencers
        search_result = await self.db.execute(
            select(UserSearch.id).where(UserSearch.user_id == user_id)
        )
        search_ids = [row[0] for row in search_result.all()]
        if search_ids:
            await self.db.execute(
                delete(DiscoveredInfluencer).where(
                    DiscoveredInfluencer.search_id.in_(search_ids)
                )
            )
            del_result = await self.db.execute(
                delete(UserSearch).where(UserSearch.id.in_(search_ids))
            )
            stats["searches"] = del_result.rowcount

        # Delete retention policy
        await self.db.execute(
            delete(DataRetentionPolicy).where(DataRetentionPolicy.user_id == user_id)
        )

        # Optionally delete transactions
        if not keep_transactions:
            del_result = await self.db.execute(
                delete(CreditTransaction).where(CreditTransaction.user_id == user_id)
            )
            stats["transactions"] = del_result.rowcount

        await self.db.commit()

        logger.info("User data deleted", user_id=user_id, stats=stats)
        return stats

    # ==================== Statistics ====================

    async def get_data_stats(self, user_id: int) -> dict[str, Any]:
        """Get data storage statistics for a user."""
        stats = {}

        # Searches count
        search_count = await self.db.execute(
            select(func.count(UserSearch.id)).where(UserSearch.user_id == user_id)
        )
        stats["searches"] = search_count.scalar() or 0

        # Leads count
        lead_count = await self.db.execute(
            select(func.count(SalesLead.id)).where(SalesLead.user_id == user_id)
        )
        stats["leads"] = lead_count.scalar() or 0

        # AI openers count
        opener_count = await self.db.execute(
            select(func.count(AIOpener.id)).where(AIOpener.user_id == user_id)
        )
        stats["ai_openers"] = opener_count.scalar() or 0

        # Get oldest data dates
        oldest_search = await self.db.execute(
            select(func.min(UserSearch.created_at)).where(
                UserSearch.user_id == user_id
            )
        )
        stats["oldest_search"] = oldest_search.scalar()

        # Retention policy
        policy = await self.get_retention_policy(user_id)
        if policy:
            stats["retention_policy"] = {
                "search_results_days": policy.search_results_days,
                "commenter_data_days": policy.commenter_data_days,
                "lead_data_days": policy.lead_data_days,
                "auto_delete_enabled": policy.auto_delete_enabled,
            }
        else:
            stats["retention_policy"] = None

        return stats
