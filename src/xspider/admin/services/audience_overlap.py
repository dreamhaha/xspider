"""Audience Overlap Analysis Service (受众重合度分析服务)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AudienceOverlapAnalysis,
    MonitoredInfluencer,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class AudienceOverlapService:
    """
    Analyze follower overlap between influencers.

    Helps identify:
    - Competitor audience overlap
    - Potential collaboration partners
    - Audience uniqueness
    """

    CREDITS_PER_ANALYSIS = 5  # Cost per overlap analysis

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def analyze_overlap(
        self,
        user_id: int,
        influencer_a_id: int,
        influencer_b_id: int,
    ) -> AudienceOverlapAnalysis:
        """
        Analyze follower overlap between two influencers.

        Args:
            user_id: User requesting the analysis
            influencer_a_id: First influencer ID
            influencer_b_id: Second influencer ID

        Returns:
            AudienceOverlapAnalysis with results
        """
        # Get influencer info
        result_a = await self.db.execute(
            select(MonitoredInfluencer).where(
                MonitoredInfluencer.id == influencer_a_id
            )
        )
        influencer_a = result_a.scalar_one_or_none()

        result_b = await self.db.execute(
            select(MonitoredInfluencer).where(
                MonitoredInfluencer.id == influencer_b_id
            )
        )
        influencer_b = result_b.scalar_one_or_none()

        if not influencer_a or not influencer_b:
            raise ValueError("Influencer not found")

        # Fetch followers for both influencers
        followers_a = await self._fetch_followers(influencer_a.twitter_user_id)
        followers_b = await self._fetch_followers(influencer_b.twitter_user_id)

        # Calculate overlap
        set_a = set(followers_a)
        set_b = set(followers_b)

        overlap = set_a & set_b
        only_a = set_a - set_b
        only_b = set_b - set_a
        union = set_a | set_b

        overlap_count = len(overlap)
        jaccard_index = len(overlap) / len(union) if union else 0.0
        overlap_pct_a = (overlap_count / len(set_a) * 100) if set_a else 0.0
        overlap_pct_b = (overlap_count / len(set_b) * 100) if set_b else 0.0

        # Get sample overlap users (for display)
        sample_overlap_ids = list(overlap)[:20]
        sample_overlap_users = await self._get_user_profiles(sample_overlap_ids)

        # Create analysis record
        analysis = AudienceOverlapAnalysis(
            user_id=user_id,
            influencer_a_id=influencer_a_id,
            influencer_b_id=influencer_b_id,
            influencer_a_screen_name=influencer_a.screen_name,
            influencer_b_screen_name=influencer_b.screen_name,
            followers_a_count=len(set_a),
            followers_b_count=len(set_b),
            overlap_count=overlap_count,
            unique_a_count=len(only_a),
            unique_b_count=len(only_b),
            jaccard_index=jaccard_index,
            overlap_percentage_a=overlap_pct_a,
            overlap_percentage_b=overlap_pct_b,
            sample_overlap_users=json.dumps(sample_overlap_users),
            credits_used=self.CREDITS_PER_ANALYSIS,
        )

        self.db.add(analysis)
        await self.db.commit()
        await self.db.refresh(analysis)

        logger.info(
            "Audience overlap analysis completed",
            analysis_id=analysis.id,
            influencer_a=influencer_a.screen_name,
            influencer_b=influencer_b.screen_name,
            overlap_count=overlap_count,
            jaccard_index=round(jaccard_index, 4),
        )

        return analysis

    async def _fetch_followers(
        self,
        twitter_user_id: str,
        max_count: int = 5000,
    ) -> list[str]:
        """Fetch follower IDs for an account."""
        try:
            from xspider.admin.services.token_pool_integration import (
                create_managed_client,
            )

            client = await create_managed_client()
            follower_ids = []

            async for follower in client.iter_followers(
                twitter_user_id, max_count=max_count
            ):
                follower_ids.append(follower.get("rest_id", ""))

            return follower_ids

        except Exception as e:
            logger.warning(
                "Failed to fetch followers",
                twitter_user_id=twitter_user_id,
                error=str(e),
            )
            return []

    async def _get_user_profiles(
        self,
        user_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Get basic profile info for a list of user IDs."""
        if not user_ids:
            return []

        try:
            from xspider.admin.services.token_pool_integration import (
                create_managed_client,
            )

            client = await create_managed_client()
            profiles = []

            for user_id in user_ids[:20]:  # Limit to 20
                try:
                    user = await client.get_user_by_id(user_id)
                    if user:
                        legacy = user.get("legacy", {})
                        profiles.append({
                            "user_id": user_id,
                            "screen_name": legacy.get("screen_name", ""),
                            "name": legacy.get("name", ""),
                            "followers_count": legacy.get("followers_count", 0),
                            "profile_image_url": legacy.get(
                                "profile_image_url_https", ""
                            ),
                        })
                except Exception:
                    continue

            return profiles

        except Exception as e:
            logger.warning("Failed to get user profiles", error=str(e))
            return []

    async def get_analysis_history(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AudienceOverlapAnalysis], int]:
        """Get overlap analysis history for a user."""
        # Count
        count_result = await self.db.execute(
            select(func.count(AudienceOverlapAnalysis.id)).where(
                AudienceOverlapAnalysis.user_id == user_id
            )
        )
        total = count_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(AudienceOverlapAnalysis)
            .where(AudienceOverlapAnalysis.user_id == user_id)
            .order_by(AudienceOverlapAnalysis.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        analyses = list(result.scalars().all())

        return analyses, total

    async def get_analysis_by_id(
        self,
        analysis_id: int,
        user_id: int,
    ) -> AudienceOverlapAnalysis | None:
        """Get a specific analysis by ID."""
        result = await self.db.execute(
            select(AudienceOverlapAnalysis).where(
                AudienceOverlapAnalysis.id == analysis_id,
                AudienceOverlapAnalysis.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_similar_audiences(
        self,
        user_id: int,
        target_influencer_id: int,
        min_overlap_pct: float = 30.0,
    ) -> list[dict[str, Any]]:
        """
        Find influencers with similar audiences.

        Searches through existing analyses to find influencers
        with high audience overlap with the target.
        """
        result = await self.db.execute(
            select(AudienceOverlapAnalysis).where(
                AudienceOverlapAnalysis.user_id == user_id,
                (
                    (AudienceOverlapAnalysis.influencer_a_id == target_influencer_id) |
                    (AudienceOverlapAnalysis.influencer_b_id == target_influencer_id)
                ),
            )
        )
        analyses = list(result.scalars().all())

        similar = []
        for analysis in analyses:
            if analysis.influencer_a_id == target_influencer_id:
                other_id = analysis.influencer_b_id
                other_name = analysis.influencer_b_screen_name
                overlap_pct = analysis.overlap_percentage_a
            else:
                other_id = analysis.influencer_a_id
                other_name = analysis.influencer_a_screen_name
                overlap_pct = analysis.overlap_percentage_b

            if overlap_pct >= min_overlap_pct:
                similar.append({
                    "influencer_id": other_id,
                    "screen_name": other_name,
                    "overlap_percentage": overlap_pct,
                    "jaccard_index": analysis.jaccard_index,
                    "overlap_count": analysis.overlap_count,
                    "analysis_id": analysis.id,
                })

        # Sort by overlap percentage
        similar.sort(key=lambda x: x["overlap_percentage"], reverse=True)

        return similar

    async def compare_multiple(
        self,
        user_id: int,
        influencer_ids: list[int],
    ) -> dict[str, Any]:
        """
        Compare audiences across multiple influencers.

        Returns a matrix of pairwise overlaps.
        """
        if len(influencer_ids) < 2:
            raise ValueError("Need at least 2 influencers to compare")

        if len(influencer_ids) > 10:
            raise ValueError("Maximum 10 influencers allowed")

        # Get influencer info
        result = await self.db.execute(
            select(MonitoredInfluencer).where(
                MonitoredInfluencer.id.in_(influencer_ids)
            )
        )
        influencers = {i.id: i for i in result.scalars().all()}

        # Build comparison matrix
        matrix = {}
        analyses_created = []

        for i, id_a in enumerate(influencer_ids):
            for id_b in influencer_ids[i + 1:]:
                # Check if analysis already exists
                existing = await self.db.execute(
                    select(AudienceOverlapAnalysis).where(
                        AudienceOverlapAnalysis.user_id == user_id,
                        (
                            (
                                (AudienceOverlapAnalysis.influencer_a_id == id_a) &
                                (AudienceOverlapAnalysis.influencer_b_id == id_b)
                            ) |
                            (
                                (AudienceOverlapAnalysis.influencer_a_id == id_b) &
                                (AudienceOverlapAnalysis.influencer_b_id == id_a)
                            )
                        ),
                    )
                )
                analysis = existing.scalar_one_or_none()

                if not analysis:
                    # Create new analysis
                    analysis = await self.analyze_overlap(user_id, id_a, id_b)
                    analyses_created.append(analysis.id)

                key = f"{id_a}-{id_b}"
                matrix[key] = {
                    "influencer_a_id": id_a,
                    "influencer_b_id": id_b,
                    "influencer_a_name": influencers.get(id_a, {}).screen_name
                        if id_a in influencers else "",
                    "influencer_b_name": influencers.get(id_b, {}).screen_name
                        if id_b in influencers else "",
                    "overlap_count": analysis.overlap_count,
                    "jaccard_index": analysis.jaccard_index,
                    "overlap_pct_a": analysis.overlap_percentage_a,
                    "overlap_pct_b": analysis.overlap_percentage_b,
                }

        return {
            "influencer_count": len(influencer_ids),
            "comparisons": len(matrix),
            "new_analyses": len(analyses_created),
            "matrix": matrix,
        }
