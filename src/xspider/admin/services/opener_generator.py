"""AI Opener Generator Service (AI破冰文案生成服务)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AIOpener,
    SalesLead,
    TweetCommenter,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class OpenerGenerator:
    """
    AI-powered conversation opener generator.

    Generates personalized icebreaker messages based on:
    - Target user's recent tweets
    - Their bio and interests
    - Comment context
    """

    CREDITS_PER_GENERATION = 3  # Cost per opener generation

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def generate_openers(
        self,
        user_id: int,
        target_screen_name: str,
        target_twitter_id: str,
        lead_id: int | None = None,
        commenter_id: int | None = None,
        num_openers: int = 3,
    ) -> AIOpener:
        """
        Generate personalized opener messages for a target user.

        Args:
            user_id: The user requesting the generation
            target_screen_name: Target's Twitter username
            target_twitter_id: Target's Twitter ID
            lead_id: Optional associated lead ID
            commenter_id: Optional associated commenter ID
            num_openers: Number of openers to generate (default 3)

        Returns:
            AIOpener with generated messages
        """
        # Fetch target's recent tweets and bio
        context = await self._gather_context(
            target_screen_name=target_screen_name,
            target_twitter_id=target_twitter_id,
            commenter_id=commenter_id,
        )

        # Generate openers using LLM
        openers = await self._generate_with_llm(
            context=context,
            num_openers=num_openers,
        )

        # Calculate tokens used (approximate)
        tokens_used = len(json.dumps(context)) // 4 + len(json.dumps(openers)) // 4

        # Save to database
        ai_opener = AIOpener(
            user_id=user_id,
            lead_id=lead_id,
            commenter_id=commenter_id,
            target_screen_name=target_screen_name,
            target_twitter_id=target_twitter_id,
            recent_tweets=json.dumps(context.get("recent_tweets", [])),
            user_bio=context.get("bio"),
            user_interests=json.dumps(context.get("interests", [])),
            openers=json.dumps(openers),
            model_used=context.get("model", "gpt-4"),
            tokens_used=tokens_used,
            credits_used=self.CREDITS_PER_GENERATION,
        )

        self.db.add(ai_opener)

        # Update lead if provided
        if lead_id:
            lead_result = await self.db.execute(
                select(SalesLead).where(SalesLead.id == lead_id)
            )
            lead = lead_result.scalar_one_or_none()
            if lead:
                lead.opener_generated = True
                lead.opener_text = openers[0] if openers else None

        await self.db.commit()
        await self.db.refresh(ai_opener)

        logger.info(
            "Generated openers",
            target=target_screen_name,
            num_openers=len(openers),
            tokens_used=tokens_used,
        )

        return ai_opener

    async def _gather_context(
        self,
        target_screen_name: str,
        target_twitter_id: str,
        commenter_id: int | None = None,
    ) -> dict[str, Any]:
        """Gather context about the target user."""
        context: dict[str, Any] = {
            "screen_name": target_screen_name,
            "recent_tweets": [],
            "bio": None,
            "interests": [],
        }

        # Get commenter info if available
        if commenter_id:
            result = await self.db.execute(
                select(TweetCommenter).where(TweetCommenter.id == commenter_id)
            )
            commenter = result.scalar_one_or_none()
            if commenter:
                context["bio"] = commenter.bio
                context["comment"] = commenter.comment_text
                context["followers"] = commenter.followers_count

        # Try to fetch recent tweets via API
        try:
            from xspider.admin.services.token_pool_integration import create_managed_client

            client = await create_managed_client()
            tweets = []

            async for tweet in client.iter_user_tweets(target_twitter_id, max_count=5):
                legacy = tweet.get("legacy", {})
                tweets.append({
                    "text": legacy.get("full_text", ""),
                    "likes": legacy.get("favorite_count", 0),
                    "created_at": legacy.get("created_at", ""),
                })

            context["recent_tweets"] = tweets

            # Extract interests from tweets
            interests = self._extract_interests(tweets)
            context["interests"] = interests

        except Exception as e:
            logger.warning("Failed to fetch user tweets", error=str(e))

        return context

    def _extract_interests(self, tweets: list[dict]) -> list[str]:
        """Extract interests from tweet content."""
        import re

        interests = set()

        # Common interest patterns
        interest_patterns = [
            (r"#(\w+)", "hashtag"),
            (r"\b(AI|ML|crypto|web3|NFT|DeFi|startup|tech)\b", "topic"),
            (r"\b(building|launching|working on)\b", "activity"),
        ]

        for tweet in tweets:
            text = tweet.get("text", "")

            for pattern, _ in interest_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                interests.update(m.lower() for m in matches if len(m) > 2)

        return list(interests)[:10]

    async def _generate_with_llm(
        self,
        context: dict[str, Any],
        num_openers: int = 3,
    ) -> list[str]:
        """Generate openers using LLM."""
        from xspider.ai.client import get_llm_client
        from xspider.core.config import get_settings

        settings = get_settings()
        if not settings.openai_api_key and not settings.anthropic_api_key:
            # Fallback to template-based openers
            return self._generate_template_openers(context, num_openers)

        try:
            client = get_llm_client()
            context["model"] = "gpt-4"

            # Build prompt
            tweets_text = ""
            if context.get("recent_tweets"):
                tweets_text = "\n".join(
                    f"- {t['text'][:200]}" for t in context["recent_tweets"][:5]
                )

            prompt = f"""Generate {num_openers} personalized conversation openers (DM icebreakers) for reaching out to this Twitter user.

Target User: @{context['screen_name']}
Bio: {context.get('bio', 'Not available')}
Interests: {', '.join(context.get('interests', ['Not available']))}

Recent Tweets:
{tweets_text if tweets_text else 'Not available'}

{f"Their recent comment: {context.get('comment', '')}" if context.get('comment') else ""}

Requirements:
1. Each opener should be casual, friendly, and NOT salesy
2. Reference something specific from their tweets or bio
3. Ask an engaging question or share a genuine observation
4. Keep each under 280 characters (Twitter DM friendly)
5. Make them feel personalized, not templated

Return as a JSON array of {num_openers} strings:
["opener1", "opener2", "opener3"]
"""

            response = await client.complete_json(prompt)

            if isinstance(response, list):
                return response[:num_openers]
            elif isinstance(response, dict) and "openers" in response:
                return response["openers"][:num_openers]

        except Exception as e:
            logger.error("LLM generation failed", error=str(e))

        # Fallback
        return self._generate_template_openers(context, num_openers)

    def _generate_template_openers(
        self,
        context: dict[str, Any],
        num_openers: int = 3,
    ) -> list[str]:
        """Generate template-based openers as fallback."""
        screen_name = context.get("screen_name", "there")
        interests = context.get("interests", [])
        bio = context.get("bio", "")

        templates = [
            f"Hey @{screen_name}! Came across your profile and found your content really interesting. Would love to connect!",
            f"Hi @{screen_name}! I noticed we're both interested in {interests[0] if interests else 'similar topics'}. Always great to connect with like-minded people!",
            f"Hey! Saw your recent tweet and it resonated with me. Mind if I ask you a quick question about {interests[0] if interests else 'your work'}?",
            f"Hi @{screen_name}! Your perspective on {interests[0] if interests else 'things'} is refreshing. Would love to hear more about your journey.",
            f"Hey! I've been following your content and really appreciate your insights. Quick question - what got you started in this space?",
        ]

        return templates[:num_openers]

    async def get_user_openers(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AIOpener], int]:
        """Get all openers generated by a user."""
        from sqlalchemy import func

        # Count
        count_result = await self.db.execute(
            select(func.count(AIOpener.id)).where(AIOpener.user_id == user_id)
        )
        total = count_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(AIOpener)
            .where(AIOpener.user_id == user_id)
            .order_by(AIOpener.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        openers = list(result.scalars().all())

        return openers, total

    async def mark_opener_used(
        self,
        opener_id: int,
        user_id: int,
        selected_index: int = 0,
    ) -> AIOpener:
        """Mark an opener as used."""
        result = await self.db.execute(
            select(AIOpener).where(
                AIOpener.id == opener_id,
                AIOpener.user_id == user_id,
            )
        )
        opener = result.scalar_one_or_none()

        if not opener:
            raise ValueError(f"Opener {opener_id} not found")

        opener.is_used = True
        opener.used_at = datetime.now(timezone.utc)
        opener.selected_opener = selected_index

        await self.db.commit()
        await self.db.refresh(opener)

        return opener

    async def mark_response_received(
        self,
        opener_id: int,
        user_id: int,
    ) -> AIOpener:
        """Mark that a response was received for an opener."""
        result = await self.db.execute(
            select(AIOpener).where(
                AIOpener.id == opener_id,
                AIOpener.user_id == user_id,
            )
        )
        opener = result.scalar_one_or_none()

        if not opener:
            raise ValueError(f"Opener {opener_id} not found")

        opener.response_received = True
        await self.db.commit()
        await self.db.refresh(opener)

        return opener

    async def get_opener_stats(self, user_id: int) -> dict[str, Any]:
        """Get opener generation statistics for a user."""
        from sqlalchemy import func

        # Total generated
        total_result = await self.db.execute(
            select(func.count(AIOpener.id)).where(AIOpener.user_id == user_id)
        )
        total = total_result.scalar() or 0

        # Used
        used_result = await self.db.execute(
            select(func.count(AIOpener.id)).where(
                AIOpener.user_id == user_id,
                AIOpener.is_used == True,  # noqa: E712
            )
        )
        used = used_result.scalar() or 0

        # Responses received
        response_result = await self.db.execute(
            select(func.count(AIOpener.id)).where(
                AIOpener.user_id == user_id,
                AIOpener.response_received == True,  # noqa: E712
            )
        )
        responses = response_result.scalar() or 0

        # Credits used
        credits_result = await self.db.execute(
            select(func.sum(AIOpener.credits_used)).where(AIOpener.user_id == user_id)
        )
        credits_used = credits_result.scalar() or 0

        return {
            "total_generated": total,
            "total_used": used,
            "total_responses": responses,
            "response_rate": (responses / used * 100) if used > 0 else 0,
            "credits_used": credits_used,
        }
