"""Content Rewrite Service (AI内容改写服务)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AdminUser,
    ContentRewrite,
    ContentStatus,
    CreditTransaction,
    OperatingAccount,
    RewriteTone,
    TransactionType,
)
from xspider.ai.client import LLMClient, create_llm_client
from xspider.ai.engagement_prompts import (
    HASHTAG_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    get_rewrite_prompt,
)
from xspider.core.logging import get_logger
from xspider.twitter.client import TwitterGraphQLClient

logger = get_logger(__name__)


REWRITE_CREDIT_COST = 5  # Credits per rewrite


class ContentRewriteService:
    """Service for AI-powered content rewriting."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._llm: LLMClient | None = None
        self._twitter_client: TwitterGraphQLClient | None = None

    def _get_llm(self) -> LLMClient:
        """Get or create LLM client."""
        if self._llm is None:
            self._llm = create_llm_client()
        return self._llm

    def _get_twitter_client(self) -> TwitterGraphQLClient:
        """Get or create Twitter client."""
        if self._twitter_client is None:
            self._twitter_client = TwitterGraphQLClient.from_settings()
        return self._twitter_client

    async def rewrite_content(
        self,
        user_id: int,
        operating_account_id: int,
        source_content: str,
        tone: RewriteTone = RewriteTone.PROFESSIONAL,
        source_tweet_id: str | None = None,
        source_tweet_url: str | None = None,
        source_author: str | None = None,
        custom_instructions: str | None = None,
    ) -> ContentRewrite:
        """Rewrite content using AI.

        Args:
            user_id: The owner user ID.
            operating_account_id: The operating account to use.
            source_content: The content to rewrite.
            tone: The tone to use for rewriting.
            source_tweet_id: Original tweet ID (optional).
            source_tweet_url: Original tweet URL (optional).
            source_author: Original author (optional).
            custom_instructions: Custom rewrite instructions.

        Returns:
            The created ContentRewrite record.

        Raises:
            ValueError: If insufficient credits or invalid account.
        """
        # Verify account ownership
        account = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == operating_account_id,
                OperatingAccount.user_id == user_id,
            )
        )
        account = account.scalar_one_or_none()
        if not account:
            raise ValueError(f"Operating account {operating_account_id} not found")

        # Check and deduct credits
        if not await self._deduct_credits(user_id):
            raise ValueError("Insufficient credits for content rewrite")

        # Generate rewrite prompt
        prompt = get_rewrite_prompt(tone, source_content, custom_instructions)

        # Call LLM for rewriting
        llm = self._get_llm()

        try:
            rewritten_content, tokens_used = await self._call_llm(
                system_prompt=REWRITE_SYSTEM_PROMPT,
                user_prompt=prompt,
            )

            # For thread style, parse into parts
            thread_parts = None
            if tone == RewriteTone.THREAD_STYLE:
                thread_parts = self._parse_thread(rewritten_content)
                if thread_parts:
                    thread_parts = json.dumps(thread_parts)
                    # Use first tweet as main content
                    rewritten_content = thread_parts[0] if isinstance(thread_parts, list) else rewritten_content

            # Generate hashtags
            hashtags = await self._generate_hashtags(rewritten_content)

            # Create record
            rewrite = ContentRewrite(
                user_id=user_id,
                operating_account_id=operating_account_id,
                source_content=source_content,
                source_tweet_id=source_tweet_id,
                source_tweet_url=source_tweet_url,
                source_author=source_author,
                tone=tone,
                custom_instructions=custom_instructions,
                rewritten_content=rewritten_content,
                generated_hashtags=json.dumps(hashtags) if hashtags else None,
                thread_parts=thread_parts,
                status=ContentStatus.DRAFT,
                model_used=llm.model,
                tokens_used=tokens_used,
                credits_used=REWRITE_CREDIT_COST,
            )

            self.db.add(rewrite)
            await self.db.commit()
            await self.db.refresh(rewrite)

            logger.info(
                "Content rewritten",
                rewrite_id=rewrite.id,
                tone=tone.value,
                tokens_used=tokens_used,
            )

            return rewrite

        except Exception as e:
            logger.error(f"Content rewrite failed: {e}")
            raise ValueError(f"Content rewrite failed: {e}")

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, int]:
        """Call LLM and return content and token count."""
        llm = self._get_llm()

        try:
            content = await llm.complete(
                prompt=user_prompt,
                system_prompt=system_prompt or "You are a helpful assistant.",
                max_tokens=1024,
            )
            # Token count is not directly available, estimate
            tokens = len(content.split()) * 2 + len(user_prompt.split()) * 2
            return content.strip(), tokens
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            # Return placeholder on error
            return f"[Rewrite of: {user_prompt[:100]}...]", 0

    def _parse_thread(self, content: str) -> list[str] | None:
        """Parse thread content into individual tweets."""
        # Split by --- or numbered markers
        parts = re.split(r'\n---\n|\n-{3,}\n', content)

        if len(parts) > 1:
            return [p.strip() for p in parts if p.strip()]

        # Try numbered format (1/, 2/, etc.)
        numbered_parts = re.split(r'\n\d+[/\.]\s*', content)
        if len(numbered_parts) > 1:
            return [p.strip() for p in numbered_parts if p.strip()]

        return None

    async def _generate_hashtags(self, content: str) -> list[str]:
        """Generate relevant hashtags for content."""
        try:
            prompt = HASHTAG_PROMPT.format(content=content)
            response, _ = await self._call_llm("", prompt)

            # Parse hashtags from response
            hashtags = re.findall(r'#\w+', response)
            return hashtags[:5]  # Max 5 hashtags

        except Exception as e:
            logger.warning(f"Hashtag generation failed: {e}")
            return []

    async def get_rewrite(
        self,
        rewrite_id: int,
        user_id: int,
    ) -> ContentRewrite | None:
        """Get a content rewrite by ID."""
        result = await self.db.execute(
            select(ContentRewrite).where(
                ContentRewrite.id == rewrite_id,
                ContentRewrite.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_rewrites(
        self,
        user_id: int,
        operating_account_id: int | None = None,
        status: ContentStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ContentRewrite]:
        """List content rewrites for a user."""
        query = select(ContentRewrite).where(ContentRewrite.user_id == user_id)

        if operating_account_id:
            query = query.where(ContentRewrite.operating_account_id == operating_account_id)
        if status:
            query = query.where(ContentRewrite.status == status)

        query = query.order_by(ContentRewrite.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def schedule_publish(
        self,
        rewrite_id: int,
        user_id: int,
        scheduled_at: datetime,
    ) -> ContentRewrite | None:
        """Schedule content for publishing."""
        rewrite = await self.get_rewrite(rewrite_id, user_id)
        if not rewrite:
            return None

        if rewrite.status != ContentStatus.DRAFT:
            raise ValueError(f"Cannot schedule content with status {rewrite.status.value}")

        if scheduled_at <= datetime.now(timezone.utc):
            raise ValueError("Scheduled time must be in the future")

        rewrite.status = ContentStatus.SCHEDULED
        rewrite.scheduled_at = scheduled_at

        await self.db.commit()
        await self.db.refresh(rewrite)

        return rewrite

    async def publish_now(
        self,
        rewrite_id: int,
        user_id: int,
    ) -> dict[str, Any]:
        """Publish content immediately."""
        rewrite = await self.get_rewrite(rewrite_id, user_id)
        if not rewrite:
            raise ValueError(f"Content rewrite {rewrite_id} not found")

        if rewrite.status == ContentStatus.PUBLISHED:
            raise ValueError("Content already published")

        if not rewrite.rewritten_content:
            raise ValueError("No rewritten content to publish")

        # Get operating account
        account = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == rewrite.operating_account_id
            )
        )
        account = account.scalar_one_or_none()
        if not account:
            raise ValueError("Operating account not found")

        # Publish via Twitter API
        try:
            client = self._get_twitter_client()

            # Handle thread publishing
            if rewrite.tone == RewriteTone.THREAD_STYLE and rewrite.thread_parts:
                thread_parts = json.loads(rewrite.thread_parts)
                tweet_ids = []

                # Post first tweet
                result = await client.post_tweet(thread_parts[0])
                tweet_ids.append(result["tweet_id"])
                prev_tweet_id = result["tweet_id"]

                # Post subsequent tweets as replies
                for part in thread_parts[1:]:
                    result = await client.reply_to_tweet(prev_tweet_id, part)
                    tweet_ids.append(result["tweet_id"])
                    prev_tweet_id = result["tweet_id"]

                published_tweet_id = tweet_ids[0]

            else:
                # Single tweet
                content = rewrite.rewritten_content

                # Add hashtags if available
                if rewrite.generated_hashtags:
                    hashtags = json.loads(rewrite.generated_hashtags)
                    hashtag_str = " ".join(hashtags[:3])  # Max 3 hashtags
                    if len(content) + len(hashtag_str) + 1 <= 280:
                        content = f"{content} {hashtag_str}"

                result = await client.post_tweet(content)
                published_tweet_id = result["tweet_id"]

            # Update record
            rewrite.status = ContentStatus.PUBLISHED
            rewrite.published_at = datetime.now(timezone.utc)
            rewrite.published_tweet_id = published_tweet_id

            # Update account stats
            account.tweets_today += 1
            account.total_tweets_posted += 1

            await self.db.commit()

            return {
                "success": True,
                "rewrite_id": rewrite_id,
                "published_tweet_id": published_tweet_id,
                "published_at": rewrite.published_at.isoformat(),
            }

        except Exception as e:
            logger.error(f"Publish failed: {e}")
            rewrite.status = ContentStatus.FAILED
            rewrite.error_message = str(e)
            await self.db.commit()

            return {
                "success": False,
                "rewrite_id": rewrite_id,
                "error": str(e),
            }

    async def delete_rewrite(
        self,
        rewrite_id: int,
        user_id: int,
    ) -> bool:
        """Delete a content rewrite (drafts only)."""
        rewrite = await self.get_rewrite(rewrite_id, user_id)
        if not rewrite:
            return False

        if rewrite.status == ContentStatus.PUBLISHED:
            raise ValueError("Cannot delete published content")

        await self.db.delete(rewrite)
        await self.db.commit()

        return True

    async def generate_quick_rewrite(
        self,
        user_id: int,
        content: str,
    ) -> str:
        """Generate a quick rewrite without saving (for preview)."""
        prompt = f"""Rewrite the following content to be more engaging and shareable on Twitter.
Keep the core message but make it more compelling.

Original content:
{content}

Rewritten version:"""

        system_prompt = "You are a social media expert who creates engaging Twitter content."

        try:
            rewritten, _ = await self._call_llm(system_prompt, prompt)
            return rewritten.strip()
        except Exception as e:
            logger.error(f"Quick rewrite failed: {e}")
            return f"[Error generating rewrite: {e}]"

    async def create_rewrite(
        self,
        user_id: int,
        original_content: str,
        rewritten_content: str | None = None,
        scheduled_at: datetime | None = None,
        operating_account_id: int | None = None,
    ) -> ContentRewrite:
        """Create a content rewrite entry (manual)."""
        status = ContentStatus.DRAFT
        if scheduled_at:
            status = ContentStatus.SCHEDULED

        rewrite = ContentRewrite(
            user_id=user_id,
            operating_account_id=operating_account_id,
            source_content=original_content,
            rewritten_content=rewritten_content,
            status=status,
            scheduled_at=scheduled_at,
        )

        self.db.add(rewrite)
        await self.db.commit()
        await self.db.refresh(rewrite)

        return rewrite

    async def update_engagement_stats(
        self,
        rewrite_id: int,
        user_id: int,
    ) -> dict[str, int] | None:
        """Update engagement stats for published content."""
        rewrite = await self.get_rewrite(rewrite_id, user_id)
        if not rewrite or not rewrite.published_tweet_id:
            return None

        try:
            client = self._get_twitter_client()
            tweet = await client.get_tweet(rewrite.published_tweet_id)

            rewrite.likes_count = tweet.metrics.like_count
            rewrite.retweets_count = tweet.metrics.retweet_count
            rewrite.replies_count = tweet.metrics.reply_count
            rewrite.last_engagement_check = datetime.now(timezone.utc)

            await self.db.commit()

            return {
                "likes": rewrite.likes_count,
                "retweets": rewrite.retweets_count,
                "replies": rewrite.replies_count,
            }

        except Exception as e:
            logger.warning(f"Failed to update engagement stats: {e}")
            return None

    async def _deduct_credits(self, user_id: int) -> bool:
        """Deduct credits for content rewrite."""
        user = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user.scalar_one_or_none()

        if not user or user.credits < REWRITE_CREDIT_COST:
            return False

        user.credits -= REWRITE_CREDIT_COST

        transaction = CreditTransaction(
            user_id=user_id,
            amount=-REWRITE_CREDIT_COST,
            balance_after=user.credits,
            type=TransactionType.AI_TWEET_REWRITE,
            description="AI content rewrite",
        )
        self.db.add(transaction)
        await self.db.commit()

        return True
