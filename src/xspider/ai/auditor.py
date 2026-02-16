"""Content auditor for analyzing Twitter user relevance to target industries."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from xspider.ai.client import LLMClient, create_llm_client
from xspider.ai.models import (
    AuditRequest,
    AuditResult,
    BatchAuditResult,
    LLMProvider,
    TweetContent,
)
from xspider.ai.prompts import build_audit_prompt
from xspider.core import AuditError, get_logger

if TYPE_CHECKING:
    from xspider.storage import Audit, Database, User

logger = get_logger(__name__)


@dataclass
class AuditorConfig:
    """Configuration for content auditor."""

    provider: LLMProvider = LLMProvider.OPENAI
    model: str | None = None
    api_key: str | None = None
    max_tweets_per_user: int = 20
    batch_size: int = 10
    max_concurrent: int = 5
    retry_attempts: int = 3
    retry_delay: float = 1.0


@dataclass
class ContentAuditor:
    """AI-powered content auditor for Twitter users.

    Analyzes user profiles and tweets to determine relevance
    to a target industry using LLM-based classification.
    """

    config: AuditorConfig = field(default_factory=AuditorConfig)
    _client: LLMClient | None = field(default=None, init=False)

    async def __aenter__(self) -> "ContentAuditor":
        """Async context manager entry."""
        self._client = create_llm_client(
            provider=self.config.provider,
            model=self.config.model,
            api_key=self.config.api_key,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def client(self) -> LLMClient:
        """Get the LLM client, ensuring it's initialized."""
        if self._client is None:
            raise AuditError("Auditor not initialized. Use async context manager.")
        return self._client

    async def audit_user(
        self,
        request: AuditRequest,
    ) -> AuditResult:
        """Audit a single user's content for industry relevance.

        Args:
            request: Audit request containing user info and tweets

        Returns:
            AuditResult with relevance assessment

        Raises:
            AuditError: If audit fails after retries
        """
        prompt = build_audit_prompt(
            username=request.username,
            bio=request.bio,
            tweets=request.tweet_texts,
            industry=request.industry,
        )

        last_error: Exception | None = None

        for attempt in range(self.config.retry_attempts):
            try:
                response = await self.client.complete_json(prompt=prompt)

                result = AuditResult(
                    is_relevant=response.get("is_relevant", False),
                    relevance_score=response.get("relevance_score", 1),
                    topics=response.get("topics", []),
                    tags=response.get("tags", []),
                    reasoning=response.get("reasoning", ""),
                )

                logger.info(
                    "User audited",
                    user_id=request.user_id,
                    username=request.username,
                    is_relevant=result.is_relevant,
                    relevance_score=result.relevance_score,
                )

                return result

            except AuditError as e:
                last_error = e
                logger.warning(
                    "Audit attempt failed",
                    user_id=request.user_id,
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))

        raise AuditError(
            f"Audit failed after {self.config.retry_attempts} attempts: {last_error}",
            user_id=request.user_id,
            model=self.client.model,
        )

    async def audit_batch(
        self,
        requests: list[AuditRequest],
    ) -> BatchAuditResult:
        """Audit multiple users concurrently.

        Args:
            requests: List of audit requests

        Returns:
            BatchAuditResult with all results and errors
        """
        results: dict[str, AuditResult] = {}
        errors: dict[str, str] = {}

        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        async def audit_with_semaphore(request: AuditRequest) -> tuple[str, AuditResult | str]:
            async with semaphore:
                try:
                    result = await self.audit_user(request)
                    return (request.user_id, result)
                except AuditError as e:
                    return (request.user_id, str(e))

        tasks = [audit_with_semaphore(req) for req in requests]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                logger.error("Unexpected error in batch audit", error=str(item))
                continue

            user_id, result = item
            if isinstance(result, AuditResult):
                results[user_id] = result
            else:
                errors[user_id] = result

        return BatchAuditResult(
            total=len(requests),
            successful=len(results),
            failed=len(errors),
            results=results,
            errors=errors,
        )

    async def audit_and_save(
        self,
        db: "Database",
        user: "User",
        tweets: list[dict],
        industry: str,
    ) -> "Audit":
        """Audit a user and save results to database.

        Args:
            db: Database instance
            user: User model to audit
            tweets: List of tweet dictionaries
            industry: Target industry

        Returns:
            Saved Audit model

        Raises:
            AuditError: If audit or save fails
        """
        from xspider.storage import Audit

        tweet_contents = [
            TweetContent(
                text=t.get("text", ""),
                created_at=t.get("created_at"),
                engagement=t.get("likes", 0) + t.get("retweets", 0) + t.get("replies", 0),
            )
            for t in tweets
            if t.get("text")
        ]

        request = AuditRequest(
            user_id=user.id,
            username=user.username,
            bio=user.bio,
            tweets=tweet_contents,
            industry=industry,
            max_tweets=self.config.max_tweets_per_user,
        )

        result = await self.audit_user(request)

        audit = Audit(
            user_id=user.id,
            industry=industry,
            is_relevant=result.is_relevant,
            relevance_score=float(result.relevance_score),
            topics=json.dumps(result.topics),
            tags=json.dumps(result.tags),
            reasoning=result.reasoning,
            model_used=self.client.model,
            tweets_analyzed=len(tweet_contents),
            audited_at=datetime.utcnow(),
        )

        async with db.session() as session:
            session.add(audit)
            await session.commit()
            await session.refresh(audit)

        logger.info(
            "Audit saved",
            user_id=user.id,
            is_relevant=result.is_relevant,
            relevance_score=result.relevance_score,
        )

        return audit

    async def get_relevant_users(
        self,
        db: "Database",
        industry: str,
        min_score: int = 6,
        limit: int = 100,
    ) -> list["Audit"]:
        """Get users relevant to an industry from database.

        Args:
            db: Database instance
            industry: Target industry
            min_score: Minimum relevance score
            limit: Maximum results to return

        Returns:
            List of Audit models
        """
        from sqlalchemy import select

        from xspider.storage import Audit

        async with db.session() as session:
            stmt = (
                select(Audit)
                .where(Audit.industry == industry)
                .where(Audit.is_relevant == True)
                .where(Audit.relevance_score >= min_score)
                .order_by(Audit.relevance_score.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())


async def audit_user_content(
    user_id: str,
    username: str,
    bio: str | None,
    tweets: list[str],
    industry: str,
    provider: LLMProvider | str = LLMProvider.OPENAI,
    model: str | None = None,
) -> AuditResult:
    """Convenience function to audit a single user.

    Args:
        user_id: User ID
        username: Twitter username
        bio: User bio
        tweets: List of tweet texts
        industry: Target industry
        provider: LLM provider
        model: Model name

    Returns:
        AuditResult
    """
    config = AuditorConfig(
        provider=LLMProvider(provider) if isinstance(provider, str) else provider,
        model=model,
    )

    tweet_contents = [TweetContent(text=t) for t in tweets if t.strip()]

    request = AuditRequest(
        user_id=user_id,
        username=username,
        bio=bio,
        tweets=tweet_contents,
        industry=industry,
    )

    async with ContentAuditor(config=config) as auditor:
        return await auditor.audit_user(request)
