"""CRM and Sales Funnel Service (销售漏斗管理服务)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AdminUser,
    AIOpener,
    DMStatus,
    IntentLabel,
    LeadActivity,
    LeadStage,
    SalesLead,
    TweetCommenter,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class CRMService:
    """Service for managing sales leads and CRM kanban board."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_lead_from_commenter(
        self,
        user_id: int,
        commenter: TweetCommenter,
        source_influencer: str | None = None,
    ) -> SalesLead:
        """Create a sales lead from a tweet commenter."""
        # Check if lead already exists
        existing = await self.db.execute(
            select(SalesLead).where(
                SalesLead.user_id == user_id,
                SalesLead.twitter_user_id == commenter.twitter_user_id,
            )
        )
        if existing.scalar_one_or_none():
            logger.debug(
                "Lead already exists",
                twitter_user_id=commenter.twitter_user_id,
            )
            return existing.scalar_one()

        # Calculate intent score
        intent_score = self._calculate_intent_score(commenter)

        lead = SalesLead(
            user_id=user_id,
            commenter_id=commenter.id,
            twitter_user_id=commenter.twitter_user_id,
            screen_name=commenter.screen_name,
            display_name=commenter.display_name,
            bio=commenter.bio,
            profile_image_url=commenter.profile_image_url,
            followers_count=commenter.followers_count,
            authenticity_score=commenter.authenticity_score,
            intent_score=intent_score,
            stage=LeadStage.DISCOVERED,
            dm_status=commenter.dm_status,
            intent_label=commenter.intent_label,
            last_active_at=commenter.commented_at,
            source_tweet_id=commenter.comment_tweet_id,
            source_influencer=source_influencer,
        )

        self.db.add(lead)
        await self.db.commit()
        await self.db.refresh(lead)

        # Log activity
        await self._log_activity(
            lead_id=lead.id,
            user_id=user_id,
            activity_type="created",
            description=f"Lead created from commenter @{commenter.screen_name}",
        )

        logger.info(
            "Created lead from commenter",
            lead_id=lead.id,
            screen_name=commenter.screen_name,
        )

        return lead

    def _calculate_intent_score(self, commenter: TweetCommenter) -> float:
        """Calculate intent score based on multiple factors."""
        score = 0.0

        # Base score from authenticity
        score += commenter.authenticity_score * 0.3  # Max 30

        # Intent label bonus
        intent_weights = {
            IntentLabel.LOOKING_FOR_SOLUTION: 25,
            IntentLabel.ASKING_PRICE: 30,
            IntentLabel.COMPLAINING: 20,  # Complaining about competitors
            IntentLabel.INTERESTED: 15,
            IntentLabel.RECOMMENDING: 5,
            IntentLabel.NEUTRAL: 0,
            IntentLabel.SPAM: -20,
        }
        if commenter.intent_label:
            score += intent_weights.get(commenter.intent_label, 0)

        # DM availability bonus
        if commenter.dm_status == DMStatus.OPEN:
            score += 15
        elif commenter.dm_status == DMStatus.FOLLOWERS_ONLY:
            score += 5

        # Engagement level
        if commenter.followers_count > 1000:
            score += 10
        if commenter.comment_like_count > 5:
            score += 5

        return max(0, min(100, score))

    async def update_lead_stage(
        self,
        lead_id: int,
        user_id: int,
        new_stage: LeadStage,
        notes: str | None = None,
    ) -> SalesLead:
        """Update the stage of a sales lead."""
        result = await self.db.execute(
            select(SalesLead).where(
                SalesLead.id == lead_id,
                SalesLead.user_id == user_id,
            )
        )
        lead = result.scalar_one_or_none()

        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        old_stage = lead.stage
        lead.stage = new_stage
        lead.stage_updated_at = datetime.now(timezone.utc)

        if notes:
            lead.notes = notes

        await self.db.commit()
        await self.db.refresh(lead)

        # Log activity
        await self._log_activity(
            lead_id=lead.id,
            user_id=user_id,
            activity_type="stage_change",
            old_value=old_stage.value,
            new_value=new_stage.value,
            description=f"Stage changed from {old_stage.value} to {new_stage.value}",
        )

        return lead

    async def get_leads_by_stage(
        self,
        user_id: int,
        stage: LeadStage | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[SalesLead], int]:
        """Get leads filtered by stage."""
        query = select(SalesLead).where(SalesLead.user_id == user_id)

        if stage:
            query = query.where(SalesLead.stage == stage)

        # Count
        count_query = select(func.count(SalesLead.id)).where(
            SalesLead.user_id == user_id
        )
        if stage:
            count_query = count_query.where(SalesLead.stage == stage)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate and order by intent score
        offset = (page - 1) * page_size
        query = query.order_by(SalesLead.intent_score.desc())
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        leads = list(result.scalars().all())

        return leads, total

    async def get_kanban_board(self, user_id: int) -> dict[str, list[SalesLead]]:
        """Get all leads organized by stage for kanban board."""
        result = await self.db.execute(
            select(SalesLead)
            .where(SalesLead.user_id == user_id)
            .order_by(SalesLead.intent_score.desc())
        )
        leads = list(result.scalars().all())

        board = {stage.value: [] for stage in LeadStage}
        for lead in leads:
            board[lead.stage.value].append(lead)

        return board

    async def get_kanban_stats(self, user_id: int) -> dict[str, Any]:
        """Get statistics for the kanban board."""
        stats = {}

        for stage in LeadStage:
            result = await self.db.execute(
                select(func.count(SalesLead.id)).where(
                    SalesLead.user_id == user_id,
                    SalesLead.stage == stage,
                )
            )
            stats[stage.value] = result.scalar() or 0

        # Additional stats
        # High intent leads
        high_intent_result = await self.db.execute(
            select(func.count(SalesLead.id)).where(
                SalesLead.user_id == user_id,
                SalesLead.intent_score >= 70,
            )
        )
        stats["high_intent"] = high_intent_result.scalar() or 0

        # DM available
        dm_result = await self.db.execute(
            select(func.count(SalesLead.id)).where(
                SalesLead.user_id == user_id,
                SalesLead.dm_status == DMStatus.OPEN,
            )
        )
        stats["dm_available"] = dm_result.scalar() or 0

        # Conversion rate
        total = sum(stats.get(s.value, 0) for s in LeadStage)
        converted = stats.get(LeadStage.CONVERTED.value, 0)
        stats["conversion_rate"] = (converted / total * 100) if total > 0 else 0

        return stats

    async def bulk_convert_to_leads(
        self,
        user_id: int,
        tweet_id: int,
        min_authenticity_score: float = 50.0,
        only_real_users: bool = True,
        only_dm_available: bool = False,
    ) -> int:
        """Convert all qualifying commenters from a tweet to leads."""
        from xspider.admin.models import MonitoredInfluencer, MonitoredTweet

        # Get tweet info
        tweet_result = await self.db.execute(
            select(MonitoredTweet)
            .join(MonitoredInfluencer)
            .where(MonitoredTweet.id == tweet_id)
        )
        tweet = tweet_result.scalar_one_or_none()

        if not tweet:
            return 0

        source_influencer = tweet.influencer.screen_name

        # Query commenters
        query = select(TweetCommenter).where(
            TweetCommenter.tweet_id == tweet_id,
            TweetCommenter.authenticity_score >= min_authenticity_score,
        )

        if only_real_users:
            query = query.where(TweetCommenter.is_real_user == True)  # noqa: E712

        if only_dm_available:
            query = query.where(TweetCommenter.dm_status == DMStatus.OPEN)

        result = await self.db.execute(query)
        commenters = list(result.scalars().all())

        created_count = 0
        for commenter in commenters:
            try:
                await self.create_lead_from_commenter(
                    user_id=user_id,
                    commenter=commenter,
                    source_influencer=source_influencer,
                )
                created_count += 1
            except Exception as e:
                logger.warning(
                    "Failed to create lead",
                    commenter_id=commenter.id,
                    error=str(e),
                )

        logger.info(
            "Bulk converted commenters to leads",
            tweet_id=tweet_id,
            created_count=created_count,
        )

        return created_count

    async def add_lead_note(
        self,
        lead_id: int,
        user_id: int,
        note: str,
    ) -> SalesLead:
        """Add a note to a lead."""
        result = await self.db.execute(
            select(SalesLead).where(
                SalesLead.id == lead_id,
                SalesLead.user_id == user_id,
            )
        )
        lead = result.scalar_one_or_none()

        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        lead.notes = note
        await self.db.commit()
        await self.db.refresh(lead)

        await self._log_activity(
            lead_id=lead.id,
            user_id=user_id,
            activity_type="note_added",
            description=note[:100] + "..." if len(note) > 100 else note,
        )

        return lead

    async def update_lead_tags(
        self,
        lead_id: int,
        user_id: int,
        tags: list[str],
    ) -> SalesLead:
        """Update tags for a lead."""
        result = await self.db.execute(
            select(SalesLead).where(
                SalesLead.id == lead_id,
                SalesLead.user_id == user_id,
            )
        )
        lead = result.scalar_one_or_none()

        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        lead.tags = json.dumps(tags)
        await self.db.commit()
        await self.db.refresh(lead)

        return lead

    async def get_lead_activities(
        self,
        lead_id: int,
        limit: int = 20,
    ) -> list[LeadActivity]:
        """Get activity history for a lead."""
        result = await self.db.execute(
            select(LeadActivity)
            .where(LeadActivity.lead_id == lead_id)
            .order_by(LeadActivity.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _log_activity(
        self,
        lead_id: int,
        user_id: int,
        activity_type: str,
        old_value: str | None = None,
        new_value: str | None = None,
        description: str | None = None,
    ) -> LeadActivity:
        """Log an activity for a lead."""
        activity = LeadActivity(
            lead_id=lead_id,
            user_id=user_id,
            activity_type=activity_type,
            old_value=old_value,
            new_value=new_value,
            description=description,
        )
        self.db.add(activity)
        await self.db.commit()
        return activity

    async def search_leads(
        self,
        user_id: int,
        query: str | None = None,
        stages: list[LeadStage] | None = None,
        intent_labels: list[IntentLabel] | None = None,
        min_intent_score: float | None = None,
        dm_available_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[SalesLead], int]:
        """Search leads with various filters."""
        base_query = select(SalesLead).where(SalesLead.user_id == user_id)

        if query:
            search_pattern = f"%{query}%"
            base_query = base_query.where(
                (SalesLead.screen_name.ilike(search_pattern)) |
                (SalesLead.display_name.ilike(search_pattern)) |
                (SalesLead.bio.ilike(search_pattern))
            )

        if stages:
            base_query = base_query.where(SalesLead.stage.in_(stages))

        if intent_labels:
            base_query = base_query.where(SalesLead.intent_label.in_(intent_labels))

        if min_intent_score:
            base_query = base_query.where(SalesLead.intent_score >= min_intent_score)

        if dm_available_only:
            base_query = base_query.where(SalesLead.dm_status == DMStatus.OPEN)

        # Count
        count_query = select(func.count()).select_from(base_query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        base_query = base_query.order_by(SalesLead.intent_score.desc())
        base_query = base_query.offset(offset).limit(page_size)

        result = await self.db.execute(base_query)
        leads = list(result.scalars().all())

        return leads, total

    async def create_lead(
        self,
        user_id: int,
        twitter_handle: str,
        source: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
    ) -> SalesLead:
        """Create a lead manually from Twitter handle."""
        # Clean handle
        twitter_handle = twitter_handle.lstrip("@").strip()

        # Check if lead already exists
        existing = await self.db.execute(
            select(SalesLead).where(
                SalesLead.user_id == user_id,
                SalesLead.screen_name == twitter_handle,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Lead @{twitter_handle} already exists")

        lead = SalesLead(
            user_id=user_id,
            screen_name=twitter_handle,
            stage=LeadStage.NEW_LEAD,
            tags=json.dumps(tags) if tags else None,
            notes=notes,
            source_influencer=source,
            stage_updated_at=datetime.now(timezone.utc),
        )

        self.db.add(lead)
        await self.db.commit()
        await self.db.refresh(lead)

        # Log activity
        await self._log_activity(
            lead_id=lead.id,
            user_id=user_id,
            activity_type="created",
            description=f"Lead @{twitter_handle} created manually",
        )

        return lead

    async def get_lead_by_id(
        self,
        lead_id: int,
        user_id: int,
    ) -> SalesLead | None:
        """Get a lead by ID."""
        result = await self.db.execute(
            select(SalesLead).where(
                SalesLead.id == lead_id,
                SalesLead.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
