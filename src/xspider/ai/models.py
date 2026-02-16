"""Pydantic models for AI content audit results."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    KIMI = "kimi"  # Moonshot AI


class AuditResult(BaseModel):
    """Result of AI content audit for a single user."""

    is_relevant: bool = Field(
        description="Whether the user's content is relevant to the target industry"
    )
    relevance_score: int = Field(
        ge=1,
        le=10,
        description="Relevance score from 1 (not relevant) to 10 (highly relevant)",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="Main topics discussed by the user",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags categorizing the user's content focus",
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of the relevance assessment",
    )

    @field_validator("relevance_score", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> int:
        """Ensure relevance score is within valid range."""
        if isinstance(v, (int, float)):
            return max(1, min(10, int(v)))
        return 5

    @field_validator("topics", "tags", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list[str]:
        """Ensure topics and tags are lists of strings."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(item) for item in v if item]
        return []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "is_relevant": self.is_relevant,
            "relevance_score": self.relevance_score,
            "topics": self.topics,
            "tags": self.tags,
            "reasoning": self.reasoning,
        }


class TweetContent(BaseModel):
    """Simplified tweet content for audit."""

    text: str
    created_at: str | None = None
    engagement: int = Field(
        default=0,
        description="Total engagement (likes + retweets + replies)",
    )


class AuditRequest(BaseModel):
    """Request for content audit."""

    user_id: str
    username: str
    bio: str | None = None
    tweets: list[TweetContent] = Field(default_factory=list)
    industry: str = Field(
        description="Target industry to assess relevance against"
    )
    max_tweets: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of tweets to analyze",
    )

    @property
    def tweet_texts(self) -> list[str]:
        """Get list of tweet texts for analysis."""
        return [t.text for t in self.tweets[: self.max_tweets] if t.text.strip()]


class BatchAuditResult(BaseModel):
    """Results from batch audit operation."""

    total: int = Field(description="Total users processed")
    successful: int = Field(description="Successfully audited users")
    failed: int = Field(description="Failed audits")
    results: dict[str, AuditResult] = Field(
        default_factory=dict,
        description="Mapping of user_id to AuditResult",
    )
    errors: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of user_id to error message",
    )
