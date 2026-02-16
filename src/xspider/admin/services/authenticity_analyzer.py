"""Service for analyzing commenter authenticity using AI and heuristics."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AuthenticityLabel,
    DMStatus,
    MonitoredInfluencer,
    MonitoredTweet,
    TweetCommenter,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AuthenticityResult:
    """Result of authenticity analysis."""

    authenticity_score: float  # 0-100
    primary_label: AuthenticityLabel
    labels: list[AuthenticityLabel]
    reasoning: str
    is_bot: bool
    is_suspicious: bool
    is_real_user: bool


class AuthenticityAnalyzer:
    """
    Analyzer for determining commenter authenticity.

    Uses a combination of:
    1. Heuristic rules (account age, follower ratio, tweet frequency, etc.)
    2. Content analysis (bio, tweet patterns)
    3. Optional LLM analysis for deep inspection
    """

    # Thresholds for heuristic analysis
    NEW_ACCOUNT_DAYS = 30
    LOW_ACTIVITY_TWEETS = 10
    HIGH_FOLLOWER_COUNT = 10000
    SUSPICIOUS_FOLLOWER_RATIO = 0.01  # Following 100x more than followers
    BOT_INDICATORS = [
        r"\b(bot|automated|auto[- ]?reply)\b",
        r"\d{6,}$",  # Username ending in many numbers
        r"^[a-z]{2,4}\d{8,}$",  # Pattern like xy12345678
    ]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def analyze_commenter(
        self,
        commenter: TweetCommenter,
        use_llm: bool = False,
    ) -> AuthenticityResult:
        """
        Analyze a single commenter's authenticity.

        Args:
            commenter: The commenter to analyze
            use_llm: Whether to use LLM for deeper analysis

        Returns:
            AuthenticityResult with score, labels, and reasoning
        """
        labels: list[AuthenticityLabel] = []
        reasoning_parts: list[str] = []
        score = 50.0  # Start at neutral

        # 1. Check if verified
        if commenter.verified:
            labels.append(AuthenticityLabel.VERIFIED)
            score += 30
            reasoning_parts.append("Verified account (+30)")

        # 2. Check account age
        if commenter.account_created_at:
            account_age = datetime.now(timezone.utc) - commenter.account_created_at.replace(
                tzinfo=timezone.utc
            )
            if account_age < timedelta(days=self.NEW_ACCOUNT_DAYS):
                labels.append(AuthenticityLabel.NEW_ACCOUNT)
                score -= 15
                reasoning_parts.append(f"New account ({account_age.days} days old, -15)")
            elif account_age > timedelta(days=365):
                score += 10
                reasoning_parts.append("Established account (>1 year, +10)")

        # 3. Check activity level
        if commenter.tweet_count < self.LOW_ACTIVITY_TWEETS:
            labels.append(AuthenticityLabel.LOW_ACTIVITY)
            score -= 10
            reasoning_parts.append(f"Low activity ({commenter.tweet_count} tweets, -10)")
        elif commenter.tweet_count > 1000:
            score += 5
            reasoning_parts.append(f"Active account ({commenter.tweet_count} tweets, +5)")

        # 4. Check follower/following ratio
        if commenter.followers_count > 0:
            ratio = commenter.following_count / commenter.followers_count
            if ratio > 100:  # Following way more than followers
                score -= 20
                reasoning_parts.append(f"Suspicious follow ratio (1:{int(ratio)}, -20)")
            elif commenter.followers_count > self.HIGH_FOLLOWER_COUNT:
                labels.append(AuthenticityLabel.INFLUENCER)
                score += 15
                reasoning_parts.append(f"High follower count ({commenter.followers_count}, +15)")
        elif commenter.following_count > 100:
            # No followers but following many
            score -= 15
            reasoning_parts.append("No followers but following many (-15)")

        # 5. Check for bot indicators in username
        for pattern in self.BOT_INDICATORS:
            if re.search(pattern, commenter.screen_name.lower()):
                labels.append(AuthenticityLabel.BOT)
                score -= 25
                reasoning_parts.append("Bot-like username pattern (-25)")
                break

        # 6. Check bio
        if commenter.bio:
            bio_lower = commenter.bio.lower()
            # Bot indicators in bio
            if any(word in bio_lower for word in ["bot", "automated", "auto-reply"]):
                if AuthenticityLabel.BOT not in labels:
                    labels.append(AuthenticityLabel.BOT)
                score -= 20
                reasoning_parts.append("Bot indicators in bio (-20)")
            # Spam indicators
            elif any(
                word in bio_lower
                for word in ["follow back", "f4f", "follow4follow", "dm for promo"]
            ):
                labels.append(AuthenticityLabel.SUSPICIOUS)
                score -= 10
                reasoning_parts.append("Spam-like bio content (-10)")
            else:
                # Has a real bio
                score += 5
                reasoning_parts.append("Has meaningful bio (+5)")
        else:
            # No bio
            score -= 5
            reasoning_parts.append("No bio (-5)")

        # 7. Check comment content
        comment_lower = commenter.comment_text.lower()
        # Generic/spam comments
        generic_patterns = [
            r"^(nice|great|good|awesome|amazing|love it|thanks)[\s!.]*$",
            r"^(follow me|check my|visit my|link in bio)",
            r"(giveaway|free|win|claim|airdrop)",
        ]
        for pattern in generic_patterns:
            if re.search(pattern, comment_lower):
                score -= 10
                reasoning_parts.append("Generic/spam-like comment (-10)")
                if AuthenticityLabel.SUSPICIOUS not in labels:
                    labels.append(AuthenticityLabel.SUSPICIOUS)
                break

        # 8. Check engagement on comment
        if commenter.comment_like_count > 10:
            score += 5
            reasoning_parts.append(f"Comment has engagement ({commenter.comment_like_count} likes, +5)")

        # 9. Use LLM for deeper analysis if requested
        if use_llm:
            llm_result = await self._llm_analysis(commenter)
            if llm_result:
                score = (score + llm_result["score"]) / 2  # Average with heuristic score
                reasoning_parts.append(f"LLM analysis: {llm_result['reasoning']}")
                for label in llm_result.get("labels", []):
                    if label not in labels:
                        labels.append(label)

        # Normalize score to 0-100
        score = max(0, min(100, score))

        # Determine primary label
        if AuthenticityLabel.BOT in labels:
            primary_label = AuthenticityLabel.BOT
        elif AuthenticityLabel.SUSPICIOUS in labels:
            primary_label = AuthenticityLabel.SUSPICIOUS
        elif AuthenticityLabel.VERIFIED in labels:
            primary_label = AuthenticityLabel.VERIFIED
        elif AuthenticityLabel.INFLUENCER in labels:
            primary_label = AuthenticityLabel.INFLUENCER
        elif score >= 70:
            primary_label = AuthenticityLabel.REAL_USER
            if AuthenticityLabel.REAL_USER not in labels:
                labels.append(AuthenticityLabel.REAL_USER)
        elif score >= 50:
            primary_label = AuthenticityLabel.REAL_USER
            labels.append(AuthenticityLabel.REAL_USER)
        else:
            primary_label = AuthenticityLabel.SUSPICIOUS
            if AuthenticityLabel.SUSPICIOUS not in labels:
                labels.append(AuthenticityLabel.SUSPICIOUS)

        # Add high engagement label if applicable
        if commenter.followers_count > 1000 and commenter.tweet_count > 500:
            if AuthenticityLabel.HIGH_ENGAGEMENT not in labels:
                labels.append(AuthenticityLabel.HIGH_ENGAGEMENT)

        # Determine boolean flags
        is_bot = AuthenticityLabel.BOT in labels
        is_suspicious = AuthenticityLabel.SUSPICIOUS in labels or score < 40
        is_real_user = score >= 50 and not is_bot

        return AuthenticityResult(
            authenticity_score=round(score, 2),
            primary_label=primary_label,
            labels=labels,
            reasoning="; ".join(reasoning_parts),
            is_bot=is_bot,
            is_suspicious=is_suspicious,
            is_real_user=is_real_user,
        )

    async def _llm_analysis(self, commenter: TweetCommenter) -> dict[str, Any] | None:
        """Use LLM for deeper authenticity analysis."""
        try:
            from xspider.ai.client import get_llm_client
            from xspider.core.config import get_settings

            settings = get_settings()
            if not settings.openai_api_key and not settings.anthropic_api_key:
                return None

            client = get_llm_client()

            prompt = f"""Analyze this Twitter user for authenticity. Determine if they are a real user, bot, or suspicious account.

User Profile:
- Username: @{commenter.screen_name}
- Display Name: {commenter.display_name or 'N/A'}
- Bio: {commenter.bio or 'No bio'}
- Followers: {commenter.followers_count}
- Following: {commenter.following_count}
- Total Tweets: {commenter.tweet_count}
- Account Age: {commenter.account_created_at or 'Unknown'}
- Verified: {commenter.verified}

Their Comment:
"{commenter.comment_text}"

Respond in JSON format:
{{
    "score": <0-100, where 100 is definitely real>,
    "labels": ["real_user" | "bot" | "suspicious" | "new_account" | "low_activity" | "influencer"],
    "reasoning": "<brief explanation>"
}}
"""

            response = await client.complete_json(prompt)
            if response:
                # Convert label strings to enum values
                labels = []
                for label_str in response.get("labels", []):
                    try:
                        labels.append(AuthenticityLabel(label_str))
                    except ValueError:
                        pass
                response["labels"] = labels
                return response

        except Exception as e:
            logger.warning("LLM analysis failed", error=str(e))

        return None

    async def analyze_and_save(
        self,
        commenter: TweetCommenter,
        use_llm: bool = False,
    ) -> TweetCommenter:
        """Analyze a commenter and save the results to database."""
        result = await self.analyze_commenter(commenter, use_llm=use_llm)

        # Update commenter with analysis results
        commenter.is_analyzed = True
        commenter.authenticity_score = result.authenticity_score
        commenter.primary_label = result.primary_label
        commenter.labels = json.dumps([label.value for label in result.labels])
        commenter.analysis_reasoning = result.reasoning
        commenter.is_bot = result.is_bot
        commenter.is_suspicious = result.is_suspicious
        commenter.is_real_user = result.is_real_user
        commenter.analyzed_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(commenter)

        return commenter

    async def analyze_tweet_commenters(
        self,
        tweet_id: int,
        use_llm: bool = False,
        force_reanalyze: bool = False,
    ) -> int:
        """
        Analyze all commenters for a tweet.

        Returns the number of commenters analyzed.
        """
        query = select(TweetCommenter).where(TweetCommenter.tweet_id == tweet_id)

        if not force_reanalyze:
            query = query.where(TweetCommenter.is_analyzed == False)  # noqa: E712

        result = await self.db.execute(query)
        commenters = list(result.scalars().all())

        analyzed_count = 0
        for commenter in commenters:
            try:
                await self.analyze_and_save(commenter, use_llm=use_llm)
                analyzed_count += 1
            except Exception as e:
                logger.error(
                    "Failed to analyze commenter",
                    commenter_id=commenter.id,
                    error=str(e),
                )

        # Mark tweet as analyzed
        tweet_result = await self.db.execute(
            select(MonitoredTweet).where(MonitoredTweet.id == tweet_id)
        )
        tweet = tweet_result.scalar_one_or_none()
        if tweet:
            tweet.commenters_analyzed = True
            await self.db.commit()

        # Update influencer stats
        if tweet:
            influencer_result = await self.db.execute(
                select(MonitoredInfluencer).where(
                    MonitoredInfluencer.id == tweet.influencer_id
                )
            )
            influencer = influencer_result.scalar_one_or_none()
            if influencer:
                influencer.commenters_analyzed += analyzed_count
                await self.db.commit()

        logger.info(
            "Analyzed tweet commenters",
            tweet_id=tweet_id,
            analyzed_count=analyzed_count,
        )

        return analyzed_count
