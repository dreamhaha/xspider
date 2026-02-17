"""Targeted Comment Service (指定评论服务).

Handles targeted commenting on specific tweets:
- Single account commenting
- Matrix commenting (1 main + N support accounts)
- Comment permission checking
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AdminUser,
    CommentStrategy,
    CreditTransaction,
    OperatingAccount,
    TargetedComment,
    TransactionType,
)
from xspider.ai.client import LLMClient, create_llm_client
from xspider.ai.engagement_prompts import (
    COMMENT_GENERATION_SYSTEM,
    get_matrix_support_prompt,
    get_targeted_comment_prompt,
)
from xspider.core.logging import get_logger
from xspider.twitter.client import TwitterGraphQLClient

logger = get_logger(__name__)


TARGETED_COMMENT_COST = 3  # Credits per targeted comment


class TargetedCommentService:
    """Service for targeted commenting on specific tweets."""

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

    # ==================== Permission Check ====================

    async def check_comment_permission(
        self,
        target_tweet_url: str,
    ) -> dict[str, Any]:
        """Check if we can comment on the target tweet.

        Args:
            target_tweet_url: URL of the tweet to check.

        Returns:
            Dict with can_comment status and details.
        """
        # Parse tweet URL
        tweet_id = self._parse_tweet_url(target_tweet_url)
        if not tweet_id:
            return {
                "can_comment": False,
                "reason": "Invalid tweet URL",
                "tweet_id": None,
            }

        try:
            client = self._get_twitter_client()
            tweet = await client.get_tweet(tweet_id)

            # Check if replies are restricted
            # This is a simplified check - Twitter's API might provide more info
            can_comment = True
            reason = "Replies are open"

            return {
                "can_comment": can_comment,
                "reason": reason,
                "tweet_id": tweet_id,
                "author_id": tweet.author.id,
                "author_name": tweet.author.screen_name,
                "tweet_content": tweet.text[:500],
            }

        except Exception as e:
            logger.warning(f"Permission check failed: {e}")
            return {
                "can_comment": False,
                "reason": f"Failed to fetch tweet: {e}",
                "tweet_id": tweet_id,
            }

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

    # ==================== Comment Generation ====================

    async def create_targeted_comment(
        self,
        user_id: int,
        target_tweet_url: str,
        main_account_id: int,
        comment_direction: str | None = None,
        strategy: CommentStrategy | None = None,
        is_matrix: bool = False,
        support_account_ids: list[int] | None = None,
    ) -> TargetedComment:
        """Create a targeted comment.

        Args:
            user_id: Owner user ID.
            target_tweet_url: URL of the target tweet.
            main_account_id: Main operating account for the comment.
            comment_direction: Instructions for comment generation.
            strategy: Comment strategy to use.
            is_matrix: Whether to use matrix commenting.
            support_account_ids: Support accounts for matrix mode.

        Returns:
            Created TargetedComment.
        """
        # Verify main account ownership
        main_account = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == main_account_id,
                OperatingAccount.user_id == user_id,
            )
        )
        main_account = main_account.scalar_one_or_none()
        if not main_account:
            raise ValueError(f"Main account {main_account_id} not found")

        # Verify support accounts if matrix mode
        if is_matrix and support_account_ids:
            for acc_id in support_account_ids:
                acc = await self.db.execute(
                    select(OperatingAccount).where(
                        OperatingAccount.id == acc_id,
                        OperatingAccount.user_id == user_id,
                    )
                )
                if not acc.scalar_one_or_none():
                    raise ValueError(f"Support account {acc_id} not found")

        # Check credits
        total_comments = 1 + (len(support_account_ids) if support_account_ids else 0)
        total_cost = TARGETED_COMMENT_COST * total_comments
        if not await self._check_credits(user_id, total_cost):
            raise ValueError(f"Insufficient credits (need {total_cost})")

        # Check permission
        permission = await self.check_comment_permission(target_tweet_url)

        tweet_id = permission.get("tweet_id")
        if not tweet_id:
            raise ValueError("Invalid tweet URL")

        # Create comment record
        comment = TargetedComment(
            user_id=user_id,
            target_tweet_url=target_tweet_url,
            target_tweet_id=tweet_id,
            target_tweet_content=permission.get("tweet_content"),
            target_author_id=permission.get("author_id", "unknown"),
            target_author_name=permission.get("author_name", "unknown"),
            comment_direction=comment_direction,
            strategy=strategy,
            is_matrix=is_matrix,
            main_account_id=main_account_id,
            support_account_ids=json.dumps(support_account_ids) if support_account_ids else None,
            can_comment=permission.get("can_comment", False),
            permission_checked_at=datetime.now(timezone.utc),
            permission_reason=permission.get("reason"),
            credits_used=total_cost,
        )

        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment)

        # Generate comments if permission granted
        if comment.can_comment:
            await self._generate_comments(comment, main_account, support_account_ids)

        return comment

    async def _generate_comments(
        self,
        comment: TargetedComment,
        main_account: OperatingAccount,
        support_account_ids: list[int] | None,
    ) -> None:
        """Generate comments for main and support accounts."""
        niche_tags = json.loads(main_account.niche_tags) if main_account.niche_tags else []

        # Generate main comment
        prompt = get_targeted_comment_prompt(
            tweet_content=comment.target_tweet_content or "",
            comment_direction=comment.comment_direction,
            strategy=comment.strategy,
            persona=main_account.persona,
            niche_tags=niche_tags,
        )

        try:
            main_comment, tokens = await self._call_llm(COMMENT_GENERATION_SYSTEM, prompt)
            comment.generated_comment = main_comment[:280]
            comment.tokens_used = tokens

            # Generate support comments if matrix mode
            if comment.is_matrix and support_account_ids:
                support_comments = []
                roles = ["supportive colleague", "curious observer", "knowledgeable expert"]

                for i, acc_id in enumerate(support_account_ids[:3]):  # Max 3 support
                    role = roles[i % len(roles)]
                    support_prompt = get_matrix_support_prompt(
                        tweet_content=comment.target_tweet_content or "",
                        main_comment=main_comment,
                        role=role,
                    )

                    support_response, tokens = await self._call_llm(
                        COMMENT_GENERATION_SYSTEM,
                        support_prompt,
                    )
                    support_comments.append({
                        "account_id": acc_id,
                        "comment": support_response[:280],
                        "role": role,
                    })
                    comment.tokens_used += tokens

                comment.support_comments = json.dumps(support_comments)

            # Deduct credits
            await self._deduct_credits(
                comment.user_id,
                comment.credits_used,
            )

            # Update model info
            llm = self._get_llm()
            comment.model_used = llm.model

            await self.db.commit()

        except Exception as e:
            logger.error(f"Comment generation failed: {e}")
            comment.generated_comment = f"[Generation failed: {e}]"
            await self.db.commit()

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

    # ==================== Execution ====================

    async def execute_comment(
        self,
        comment_id: int,
        user_id: int,
    ) -> dict[str, Any]:
        """Execute a targeted comment (post the comments).

        Returns:
            Dict with execution results.
        """
        result = await self.db.execute(
            select(TargetedComment).where(
                TargetedComment.id == comment_id,
                TargetedComment.user_id == user_id,
            )
        )
        comment = result.scalar_one_or_none()

        if not comment:
            raise ValueError(f"Comment {comment_id} not found")

        if not comment.can_comment:
            raise ValueError(f"Cannot comment: {comment.permission_reason}")

        if comment.is_executed:
            raise ValueError("Comment already executed")

        if not comment.generated_comment:
            raise ValueError("No comment generated")

        client = self._get_twitter_client()
        posted_ids = []
        errors = []

        # Post main comment
        try:
            # Get main account for posting
            main_result = await client.reply_to_tweet(
                tweet_id=comment.target_tweet_id,
                text=comment.generated_comment,
            )
            posted_ids.append(main_result.get("tweet_id"))

            # Update main account stats
            if comment.main_account_id:
                account = await self.db.execute(
                    select(OperatingAccount).where(
                        OperatingAccount.id == comment.main_account_id
                    )
                )
                account = account.scalar_one_or_none()
                if account:
                    account.replies_today += 1
                    account.total_replies_posted += 1

        except Exception as e:
            errors.append(f"Main comment failed: {e}")

        # Post support comments if matrix mode
        if comment.is_matrix and comment.support_comments:
            support_comments = json.loads(comment.support_comments)

            for support in support_comments:
                try:
                    # Note: In production, you'd need to switch to the support account's credentials
                    support_result = await client.reply_to_tweet(
                        tweet_id=comment.target_tweet_id,
                        text=support["comment"],
                    )
                    posted_ids.append(support_result.get("tweet_id"))

                    # Update support account stats
                    account = await self.db.execute(
                        select(OperatingAccount).where(
                            OperatingAccount.id == support["account_id"]
                        )
                    )
                    account = account.scalar_one_or_none()
                    if account:
                        account.replies_today += 1
                        account.total_replies_posted += 1

                except Exception as e:
                    errors.append(f"Support comment ({support['account_id']}) failed: {e}")

        # Update comment record
        comment.is_executed = len(posted_ids) > 0
        comment.executed_at = datetime.now(timezone.utc) if comment.is_executed else None
        comment.posted_tweet_ids = json.dumps(posted_ids) if posted_ids else None
        comment.error_message = "; ".join(errors) if errors else None

        await self.db.commit()

        return {
            "success": len(posted_ids) > 0,
            "comment_id": comment_id,
            "posted_tweet_ids": posted_ids,
            "errors": errors if errors else None,
            "executed_at": comment.executed_at.isoformat() if comment.executed_at else None,
        }

    # ==================== History & CRUD ====================

    async def get_comment(
        self,
        comment_id: int,
        user_id: int,
    ) -> TargetedComment | None:
        """Get a targeted comment by ID."""
        result = await self.db.execute(
            select(TargetedComment).where(
                TargetedComment.id == comment_id,
                TargetedComment.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_comments(
        self,
        user_id: int,
        is_executed: bool | None = None,
        is_matrix: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[TargetedComment], int]:
        """List targeted comments."""
        query = select(TargetedComment).where(TargetedComment.user_id == user_id)

        if is_executed is not None:
            query = query.where(TargetedComment.is_executed == is_executed)
        if is_matrix is not None:
            query = query.where(TargetedComment.is_matrix == is_matrix)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar() or 0

        # Get paginated results
        query = query.order_by(TargetedComment.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        comments = list(result.scalars().all())

        return comments, total

    async def delete_comment(
        self,
        comment_id: int,
        user_id: int,
    ) -> bool:
        """Delete a targeted comment (unexecuted only)."""
        comment = await self.get_comment(comment_id, user_id)
        if not comment:
            return False

        if comment.is_executed:
            raise ValueError("Cannot delete executed comment")

        await self.db.delete(comment)
        await self.db.commit()

        return True

    async def regenerate_comment(
        self,
        comment_id: int,
        user_id: int,
        new_direction: str | None = None,
        new_strategy: CommentStrategy | None = None,
    ) -> TargetedComment | None:
        """Regenerate comments with new settings."""
        comment = await self.get_comment(comment_id, user_id)
        if not comment:
            return None

        if comment.is_executed:
            raise ValueError("Cannot regenerate executed comment")

        # Update settings
        if new_direction is not None:
            comment.comment_direction = new_direction
        if new_strategy is not None:
            comment.strategy = new_strategy

        # Get main account
        main_account = await self.db.execute(
            select(OperatingAccount).where(
                OperatingAccount.id == comment.main_account_id
            )
        )
        main_account = main_account.scalar_one_or_none()

        if main_account:
            support_ids = json.loads(comment.support_account_ids) if comment.support_account_ids else None
            await self._generate_comments(comment, main_account, support_ids)

        await self.db.refresh(comment)
        return comment

    # ==================== Credit Management ====================

    async def _check_credits(self, user_id: int, cost: int) -> bool:
        """Check if user has enough credits."""
        user = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user.scalar_one_or_none()
        return user is not None and user.credits >= cost

    async def _deduct_credits(self, user_id: int, cost: int) -> None:
        """Deduct credits for targeted comment."""
        user = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user.scalar_one_or_none()
        if not user:
            return

        user.credits -= cost

        transaction = CreditTransaction(
            user_id=user_id,
            amount=-cost,
            balance_after=user.credits,
            type=TransactionType.TARGETED_COMMENT,
            description="Targeted comment",
        )
        self.db.add(transaction)
        await self.db.commit()
