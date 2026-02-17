"""Smart Interaction Service (智能互动服务).

Handles automated engagement with KOL tweets:
- KOL watchlist management
- Relevance evaluation
- Comment generation (3 strategies)
- Approval workflow
- Execution
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AdminUser,
    CommentStrategy,
    CreditTransaction,
    InteractionMode,
    KOLWatchlist,
    OperatingAccount,
    SmartInteraction,
    TransactionType,
)
from xspider.ai.client import LLMClient, create_llm_client
from xspider.ai.engagement_prompts import (
    COMMENT_GENERATION_SYSTEM,
    RELEVANCE_CHECK_PROMPT,
    get_comment_generation_prompt,
)
from xspider.core.logging import get_logger
from xspider.twitter.client import TwitterGraphQLClient

logger = get_logger(__name__)


# Credit costs
SMART_INTERACTION_AUTO_COST = 10
SMART_INTERACTION_REVIEW_COST = 5


class SmartInteractionService:
    """Service for smart KOL interaction management."""

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

    # ==================== KOL Watchlist Management ====================

    async def add_to_watchlist(
        self,
        user_id: int,
        operating_account_id: int,
        kol_screen_name: str,
        interaction_mode: InteractionMode = InteractionMode.REVIEW,
        relevance_threshold: float = 0.8,
        preferred_strategies: list[CommentStrategy] | None = None,
    ) -> KOLWatchlist:
        """Add a KOL to the watchlist for monitoring.

        Args:
            user_id: Owner user ID.
            operating_account_id: Operating account to use for interactions.
            kol_screen_name: KOL's Twitter handle.
            interaction_mode: AUTO or REVIEW mode.
            relevance_threshold: Minimum relevance score to interact.
            preferred_strategies: Preferred comment strategies.

        Returns:
            Created KOLWatchlist entry.
        """
        # Verify operating account ownership
        account = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == operating_account_id,
                OperatingAccount.user_id == user_id,
            )
        )
        account = account.scalar_one_or_none()
        if not account:
            raise ValueError(f"Operating account {operating_account_id} not found")

        # Check if already watching
        existing = await self.db.execute(
            select(KOLWatchlist).where(
                KOLWatchlist.operating_account_id == operating_account_id,
                KOLWatchlist.kol_screen_name == kol_screen_name,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Already watching @{kol_screen_name}")

        # Fetch KOL info from Twitter
        try:
            client = self._get_twitter_client()
            kol_user = await client.get_user_by_screen_name(kol_screen_name)

            kol_twitter_id = kol_user.id
            kol_display_name = kol_user.name
            kol_followers_count = kol_user.followers_count
            kol_bio = kol_user.bio
        except Exception as e:
            logger.warning(f"Failed to fetch KOL info: {e}")
            kol_twitter_id = "unknown"
            kol_display_name = kol_screen_name
            kol_followers_count = 0
            kol_bio = None

        # Create watchlist entry
        watchlist = KOLWatchlist(
            user_id=user_id,
            operating_account_id=operating_account_id,
            kol_twitter_id=kol_twitter_id,
            kol_screen_name=kol_screen_name,
            kol_display_name=kol_display_name,
            kol_followers_count=kol_followers_count,
            kol_bio=kol_bio,
            interaction_mode=interaction_mode,
            relevance_threshold=relevance_threshold,
            preferred_strategies=json.dumps([s.value for s in preferred_strategies])
            if preferred_strategies
            else None,
        )

        self.db.add(watchlist)
        await self.db.commit()
        await self.db.refresh(watchlist)

        logger.info(
            "Added KOL to watchlist",
            watchlist_id=watchlist.id,
            kol_screen_name=kol_screen_name,
        )

        return watchlist

    async def remove_from_watchlist(
        self,
        watchlist_id: int,
        user_id: int,
    ) -> bool:
        """Remove a KOL from the watchlist."""
        result = await self.db.execute(
            select(KOLWatchlist).where(
                KOLWatchlist.id == watchlist_id,
                KOLWatchlist.user_id == user_id,
            )
        )
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            return False

        await self.db.delete(watchlist)
        await self.db.commit()

        return True

    async def list_watchlist(
        self,
        user_id: int,
        operating_account_id: int | None = None,
        include_inactive: bool = False,
    ) -> list[KOLWatchlist]:
        """List KOLs in the watchlist."""
        query = select(KOLWatchlist).where(KOLWatchlist.user_id == user_id)

        if operating_account_id:
            query = query.where(KOLWatchlist.operating_account_id == operating_account_id)
        if not include_inactive:
            query = query.where(KOLWatchlist.is_active == True)

        query = query.order_by(KOLWatchlist.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_watchlist(
        self,
        watchlist_id: int,
        user_id: int,
        interaction_mode: InteractionMode | None = None,
        relevance_threshold: float | None = None,
        preferred_strategies: list[CommentStrategy] | None = None,
        is_active: bool | None = None,
    ) -> KOLWatchlist | None:
        """Update watchlist entry settings."""
        result = await self.db.execute(
            select(KOLWatchlist).where(
                KOLWatchlist.id == watchlist_id,
                KOLWatchlist.user_id == user_id,
            )
        )
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            return None

        if interaction_mode is not None:
            watchlist.interaction_mode = interaction_mode
        if relevance_threshold is not None:
            watchlist.relevance_threshold = relevance_threshold
        if preferred_strategies is not None:
            watchlist.preferred_strategies = json.dumps([s.value for s in preferred_strategies])
        if is_active is not None:
            watchlist.is_active = is_active

        await self.db.commit()
        await self.db.refresh(watchlist)

        return watchlist

    # ==================== Interaction Generation ====================

    async def generate_interaction(
        self,
        user_id: int,
        operating_account_id: int,
        target_tweet_url: str,
        mode: InteractionMode = InteractionMode.REVIEW,
        kol_watchlist_id: int | None = None,
    ) -> SmartInteraction:
        """Generate a smart interaction for a target tweet.

        This:
        1. Parses the tweet URL
        2. Fetches tweet content
        3. Evaluates relevance
        4. Generates 3 comment strategies
        5. Creates an interaction record

        Args:
            user_id: Owner user ID.
            operating_account_id: Operating account to use.
            target_tweet_url: URL of the tweet to interact with.
            mode: AUTO or REVIEW mode.
            kol_watchlist_id: Associated watchlist entry (optional).

        Returns:
            Created SmartInteraction.
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

        # Check credits
        cost = SMART_INTERACTION_AUTO_COST if mode == InteractionMode.AUTO else SMART_INTERACTION_REVIEW_COST
        if not await self._check_credits(user_id, cost):
            raise ValueError(f"Insufficient credits (need {cost})")

        # Parse tweet URL
        tweet_id = self._parse_tweet_url(target_tweet_url)
        if not tweet_id:
            raise ValueError(f"Invalid tweet URL: {target_tweet_url}")

        # Fetch tweet
        client = self._get_twitter_client()
        try:
            tweet = await client.get_tweet(tweet_id)
            tweet_content = tweet.text
            author_id = tweet.author.id
            author_name = tweet.author.screen_name
        except Exception as e:
            raise ValueError(f"Failed to fetch tweet: {e}")

        # Evaluate relevance
        niche_tags = json.loads(account.niche_tags) if account.niche_tags else []
        relevance_score, relevance_reasoning = await self._evaluate_relevance(
            tweet_content=tweet_content,
            niche_tags=niche_tags,
            persona=account.persona,
        )

        # Generate comments (3 strategies)
        generated_comments = await self._generate_comments(
            tweet_content=tweet_content,
            niche_tags=niche_tags,
            persona=account.persona,
        )

        # Deduct credits
        await self._deduct_credits(user_id, cost, mode)

        # Create interaction record
        interaction = SmartInteraction(
            user_id=user_id,
            operating_account_id=operating_account_id,
            kol_watchlist_id=kol_watchlist_id,
            target_tweet_id=tweet_id,
            target_tweet_url=target_tweet_url,
            target_tweet_content=tweet_content,
            target_author_id=author_id,
            target_author_name=author_name,
            relevance_score=relevance_score,
            relevance_reasoning=relevance_reasoning,
            generated_comments=json.dumps(generated_comments),
            mode=mode,
            is_approved=mode == InteractionMode.AUTO,  # Auto-approve in AUTO mode
            approved_at=datetime.now(timezone.utc) if mode == InteractionMode.AUTO else None,
            credits_used=cost,
        )

        self.db.add(interaction)
        await self.db.commit()
        await self.db.refresh(interaction)

        # Update watchlist stats if applicable
        if kol_watchlist_id:
            await self.db.execute(
                update(KOLWatchlist)
                .where(KOLWatchlist.id == kol_watchlist_id)
                .values(
                    tweets_checked=KOLWatchlist.tweets_checked + 1,
                    interactions_generated=KOLWatchlist.interactions_generated + 1,
                    last_checked_at=datetime.now(timezone.utc),
                )
            )
            await self.db.commit()

        logger.info(
            "Generated smart interaction",
            interaction_id=interaction.id,
            relevance_score=relevance_score,
            mode=mode.value,
        )

        return interaction

    def _parse_tweet_url(self, url: str) -> str | None:
        """Extract tweet ID from URL."""
        patterns = [
            r'twitter\.com/\w+/status/(\d+)',
            r'x\.com/\w+/status/(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def _evaluate_relevance(
        self,
        tweet_content: str,
        niche_tags: list[str],
        persona: str | None,
    ) -> tuple[float, str]:
        """Evaluate tweet relevance to account's niche."""
        try:
            prompt = RELEVANCE_CHECK_PROMPT.format(
                niche_tags=", ".join(niche_tags) if niche_tags else "General",
                persona=persona or "Professional account",
                tweet_content=tweet_content,
            )

            llm = self._get_llm()
            response, _ = await self._call_llm("", prompt)

            # Parse score and reason
            score_match = re.search(r'SCORE:\s*([\d.]+)', response)
            reason_match = re.search(r'REASON:\s*(.+)', response, re.IGNORECASE | re.DOTALL)

            score = float(score_match.group(1)) if score_match else 0.5
            reason = reason_match.group(1).strip() if reason_match else "Relevance analysis"

            return min(1.0, max(0.0, score)), reason

        except Exception as e:
            logger.warning(f"Relevance evaluation failed: {e}")
            return 0.5, f"Evaluation failed: {e}"

    async def _generate_comments(
        self,
        tweet_content: str,
        niche_tags: list[str],
        persona: str | None,
    ) -> dict[str, str]:
        """Generate comments for all 3 strategies."""
        comments = {}

        for strategy in CommentStrategy:
            try:
                prompt = get_comment_generation_prompt(
                    strategy=strategy,
                    tweet_content=tweet_content,
                    persona=persona,
                    niche_tags=niche_tags,
                )

                response, _ = await self._call_llm(COMMENT_GENERATION_SYSTEM, prompt)

                # Truncate to 280 chars
                comment = response.strip()[:280]
                comments[strategy.value] = comment

            except Exception as e:
                logger.warning(f"Comment generation failed for {strategy.value}: {e}")
                comments[strategy.value] = f"[Comment generation failed]"

        return comments

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
            # Token count estimated
            tokens = len(content.split()) * 2 + len(user_prompt.split()) * 2
            return content.strip(), tokens
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return "", 0

    # ==================== Approval Workflow ====================

    async def get_pending_interactions(
        self,
        user_id: int,
        operating_account_id: int | None = None,
    ) -> list[SmartInteraction]:
        """Get interactions pending approval."""
        query = select(SmartInteraction).where(
            SmartInteraction.user_id == user_id,
            SmartInteraction.is_approved == False,
            SmartInteraction.is_executed == False,
        )

        if operating_account_id:
            query = query.where(SmartInteraction.operating_account_id == operating_account_id)

        query = query.order_by(SmartInteraction.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def approve_interaction(
        self,
        interaction_id: int,
        user_id: int,
        selected_strategy: CommentStrategy,
        custom_comment: str | None = None,
    ) -> SmartInteraction | None:
        """Approve an interaction with a selected strategy.

        Args:
            interaction_id: The interaction to approve.
            user_id: The user approving.
            selected_strategy: Which comment strategy to use.
            custom_comment: Optional custom comment (overrides generated).

        Returns:
            Updated SmartInteraction.
        """
        result = await self.db.execute(
            select(SmartInteraction).where(
                SmartInteraction.id == interaction_id,
                SmartInteraction.user_id == user_id,
            )
        )
        interaction = result.scalar_one_or_none()

        if not interaction:
            return None

        if interaction.is_executed:
            raise ValueError("Interaction already executed")

        # Get the comment
        if custom_comment:
            selected_comment = custom_comment[:280]
        else:
            comments = json.loads(interaction.generated_comments or "{}")
            selected_comment = comments.get(selected_strategy.value, "")

        interaction.is_approved = True
        interaction.approved_at = datetime.now(timezone.utc)
        interaction.approved_by = user_id
        interaction.selected_strategy = selected_strategy
        interaction.selected_comment = selected_comment

        await self.db.commit()
        await self.db.refresh(interaction)

        # Update watchlist stats
        if interaction.kol_watchlist_id:
            await self.db.execute(
                update(KOLWatchlist)
                .where(KOLWatchlist.id == interaction.kol_watchlist_id)
                .values(interactions_approved=KOLWatchlist.interactions_approved + 1)
            )
            await self.db.commit()

        return interaction

    async def reject_interaction(
        self,
        interaction_id: int,
        user_id: int,
    ) -> bool:
        """Reject and delete a pending interaction."""
        result = await self.db.execute(
            select(SmartInteraction).where(
                SmartInteraction.id == interaction_id,
                SmartInteraction.user_id == user_id,
                SmartInteraction.is_executed == False,
            )
        )
        interaction = result.scalar_one_or_none()

        if not interaction:
            return False

        await self.db.delete(interaction)
        await self.db.commit()

        return True

    # ==================== Execution ====================

    async def execute_interaction(
        self,
        interaction_id: int,
        user_id: int,
    ) -> dict[str, Any]:
        """Execute an approved interaction (post the comment).

        Returns:
            Dict with execution results.
        """
        result = await self.db.execute(
            select(SmartInteraction).where(
                SmartInteraction.id == interaction_id,
                SmartInteraction.user_id == user_id,
            )
        )
        interaction = result.scalar_one_or_none()

        if not interaction:
            raise ValueError(f"Interaction {interaction_id} not found")

        if not interaction.is_approved:
            raise ValueError("Interaction not approved")

        if interaction.is_executed:
            raise ValueError("Interaction already executed")

        if not interaction.selected_comment:
            raise ValueError("No comment selected")

        # Post the reply
        try:
            client = self._get_twitter_client()

            result_data = await client.reply_to_tweet(
                tweet_id=interaction.target_tweet_id,
                text=interaction.selected_comment,
            )

            interaction.is_executed = True
            interaction.executed_at = datetime.now(timezone.utc)
            interaction.posted_tweet_id = result_data.get("tweet_id")

            await self.db.commit()

            # Update account stats
            account = await self.db.execute(
                select(OperatingAccount).where(
                    OperatingAccount.id == interaction.operating_account_id
                )
            )
            account = account.scalar_one_or_none()
            if account:
                account.replies_today += 1
                account.total_replies_posted += 1
                await self.db.commit()

            # Update watchlist stats
            if interaction.kol_watchlist_id:
                await self.db.execute(
                    update(KOLWatchlist)
                    .where(KOLWatchlist.id == interaction.kol_watchlist_id)
                    .values(
                        interactions_executed=KOLWatchlist.interactions_executed + 1,
                        last_interacted_at=datetime.now(timezone.utc),
                    )
                )
                await self.db.commit()

            return {
                "success": True,
                "interaction_id": interaction_id,
                "posted_tweet_id": interaction.posted_tweet_id,
                "executed_at": interaction.executed_at.isoformat(),
            }

        except Exception as e:
            logger.error(f"Interaction execution failed: {e}")
            interaction.error_message = str(e)
            await self.db.commit()

            return {
                "success": False,
                "interaction_id": interaction_id,
                "error": str(e),
            }

    # ==================== History & Stats ====================

    async def get_interaction_history(
        self,
        user_id: int,
        operating_account_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SmartInteraction], int]:
        """Get interaction history."""
        query = select(SmartInteraction).where(SmartInteraction.user_id == user_id)

        if operating_account_id:
            query = query.where(SmartInteraction.operating_account_id == operating_account_id)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0

        # Get paginated results
        query = query.order_by(SmartInteraction.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        interactions = list(result.scalars().all())

        return interactions, total

    async def _check_credits(self, user_id: int, cost: int) -> bool:
        """Check if user has enough credits."""
        user = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user.scalar_one_or_none()
        return user is not None and user.credits >= cost

    async def _deduct_credits(
        self,
        user_id: int,
        cost: int,
        mode: InteractionMode,
    ) -> None:
        """Deduct credits for interaction."""
        user = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user.scalar_one_or_none()
        if not user:
            return

        user.credits -= cost

        transaction_type = (
            TransactionType.SMART_INTERACTION_AUTO
            if mode == InteractionMode.AUTO
            else TransactionType.SMART_INTERACTION_REVIEW
        )

        transaction = CreditTransaction(
            user_id=user_id,
            amount=-cost,
            balance_after=user.credits,
            type=transaction_type,
            description=f"Smart interaction ({mode.value} mode)",
        )
        self.db.add(transaction)
        await self.db.commit()
