"""Intent and Sentiment Analyzer Service (意图与情感分析服务)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    IntentLabel,
    SentimentType,
    TweetCommenter,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class IntentResult:
    """Result of intent analysis."""

    intent_label: IntentLabel
    sentiment: SentimentType
    confidence: float
    keywords: list[str]
    is_high_intent: bool
    reasoning: str


class IntentAnalyzer:
    """
    Analyzer for comment intent and sentiment.

    Identifies purchase intent signals:
    - Looking for solution: "anyone know...", "recommendations for..."
    - Complaining: "frustrated with...", "hate using..."
    - Asking price: "how much...", "pricing..."
    - Interested: "looks great", "want to try"
    """

    # Intent signal patterns
    INTENT_PATTERNS = {
        IntentLabel.LOOKING_FOR_SOLUTION: [
            r"\b(looking for|searching for|need|want)\b.*(solution|tool|app|software|service|alternative)",
            r"\b(anyone know|does anyone|recommend|recommendations)\b",
            r"\b(how (do|can|to)|what('s| is) the best)\b",
            r"\b(help me find|trying to find)\b",
        ],
        IntentLabel.COMPLAINING: [
            r"\b(frustrated|annoyed|disappointed|hate|tired of)\b",
            r"\b(doesn't work|not working|broken|buggy)\b",
            r"\b(terrible|awful|worst|useless)\b",
            r"\b(switched from|leaving|done with)\b",
            r"\b(customer support|no response)\b",
        ],
        IntentLabel.ASKING_PRICE: [
            r"\b(how much|price|pricing|cost|costs)\b",
            r"\b(free (trial|version|tier)|discount|coupon)\b",
            r"\b(worth (it|the money)|affordable)\b",
            r"\b(budget|expensive|cheap)\b",
        ],
        IntentLabel.INTERESTED: [
            r"\b(looks (great|amazing|interesting|cool)|love this)\b",
            r"\b(want to try|might try|considering)\b",
            r"\b(sign me up|where (can|do) i)\b",
            r"\b(impressive|excited|can't wait)\b",
        ],
        IntentLabel.RECOMMENDING: [
            r"\b(i (use|recommend|suggest)|you should (try|use))\b",
            r"\b(check out|have you tried)\b",
            r"\b(best (tool|app|solution))\b",
        ],
        IntentLabel.SPAM: [
            r"\b(check my|visit my|link in bio|follow me)\b",
            r"\b(giveaway|free|win|claim)\b",
            r"\b(dm (me|for)|send me)\b.*\b(promo|deal)\b",
            r"[\U0001F4B0\U0001F4B8\U0001F4B5]",  # Money emojis
        ],
    }

    # Sentiment patterns
    POSITIVE_PATTERNS = [
        r"\b(love|great|amazing|awesome|excellent|fantastic|wonderful)\b",
        r"\b(thank|thanks|appreciate|grateful)\b",
        r"\b(best|perfect|brilliant)\b",
        r"[😀😃😄😁😊🥰😍🤩👍❤️🔥💯✨]",
    ]

    NEGATIVE_PATTERNS = [
        r"\b(hate|terrible|awful|worst|horrible|disgusting)\b",
        r"\b(disappointed|frustrated|angry|annoyed)\b",
        r"\b(broken|useless|waste|scam)\b",
        r"[😠😡🤬😤👎💩]",
    ]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def analyze_comment(
        self,
        commenter: TweetCommenter,
        use_llm: bool = False,
    ) -> IntentResult:
        """
        Analyze a comment for intent and sentiment.

        Args:
            commenter: The commenter with comment text
            use_llm: Whether to use LLM for deeper analysis

        Returns:
            IntentResult with intent, sentiment, and keywords
        """
        comment = commenter.comment_text.lower()
        keywords: list[str] = []

        # 1. Detect intent using patterns
        intent_label = IntentLabel.NEUTRAL
        max_matches = 0

        for label, patterns in self.INTENT_PATTERNS.items():
            matches = 0
            matched_keywords = []

            for pattern in patterns:
                found = re.findall(pattern, comment, re.IGNORECASE)
                if found:
                    matches += len(found)
                    matched_keywords.extend(
                        [f.strip() if isinstance(f, str) else f[0] for f in found]
                    )

            if matches > max_matches:
                max_matches = matches
                intent_label = label
                keywords = matched_keywords[:5]  # Keep top 5 keywords

        # 2. Detect sentiment
        positive_score = sum(
            len(re.findall(p, comment, re.IGNORECASE))
            for p in self.POSITIVE_PATTERNS
        )
        negative_score = sum(
            len(re.findall(p, comment, re.IGNORECASE))
            for p in self.NEGATIVE_PATTERNS
        )

        if positive_score > negative_score:
            sentiment = SentimentType.POSITIVE
        elif negative_score > positive_score:
            sentiment = SentimentType.NEGATIVE
        else:
            sentiment = SentimentType.NEUTRAL

        # 3. Calculate confidence
        confidence = min(1.0, max_matches * 0.25) if max_matches > 0 else 0.2

        # 4. Determine if high intent (purchase signal)
        high_intent_labels = {
            IntentLabel.LOOKING_FOR_SOLUTION,
            IntentLabel.ASKING_PRICE,
            IntentLabel.COMPLAINING,  # Complaining about competitors
        }
        is_high_intent = intent_label in high_intent_labels and confidence >= 0.5

        # 5. Generate reasoning
        reasoning_parts = []
        if intent_label != IntentLabel.NEUTRAL:
            reasoning_parts.append(f"Detected {intent_label.value} intent")
        if keywords:
            reasoning_parts.append(f"Keywords: {', '.join(keywords[:3])}")
        reasoning_parts.append(f"Sentiment: {sentiment.value}")

        # 6. Use LLM for deeper analysis if requested
        if use_llm and (is_high_intent or intent_label == IntentLabel.NEUTRAL):
            llm_result = await self._llm_analysis(commenter)
            if llm_result:
                # Merge LLM results
                if llm_result.get("intent"):
                    try:
                        intent_label = IntentLabel(llm_result["intent"])
                    except ValueError:
                        pass
                if llm_result.get("confidence", 0) > confidence:
                    confidence = llm_result["confidence"]
                if llm_result.get("keywords"):
                    keywords.extend(llm_result["keywords"])
                if llm_result.get("reasoning"):
                    reasoning_parts.append(f"LLM: {llm_result['reasoning']}")

        return IntentResult(
            intent_label=intent_label,
            sentiment=sentiment,
            confidence=confidence,
            keywords=list(set(keywords))[:5],
            is_high_intent=is_high_intent,
            reasoning="; ".join(reasoning_parts),
        )

    async def _llm_analysis(self, commenter: TweetCommenter) -> dict[str, Any] | None:
        """Use LLM for deeper intent analysis."""
        try:
            from xspider.ai.client import get_llm_client
            from xspider.core.config import get_settings

            settings = get_settings()
            if not settings.openai_api_key and not settings.anthropic_api_key:
                return None

            client = get_llm_client()

            prompt = f"""Analyze this Twitter comment for purchase intent and sentiment.

Comment: "{commenter.comment_text}"

User Bio: {commenter.bio or 'N/A'}
Followers: {commenter.followers_count}

Classify the intent as one of:
- looking_for_solution: Actively seeking a product/service
- complaining: Complaining about a competitor or current solution
- asking_price: Inquiring about pricing
- interested: Showing interest but not actively seeking
- recommending: Recommending something to others
- neutral: No clear intent
- spam: Promotional spam

Respond in JSON format:
{{
    "intent": "<intent_label>",
    "confidence": <0.0-1.0>,
    "keywords": ["keyword1", "keyword2"],
    "sentiment": "positive|negative|neutral",
    "reasoning": "<brief explanation>"
}}
"""

            response = await client.complete_json(prompt)
            return response

        except Exception as e:
            logger.warning("LLM intent analysis failed", error=str(e))
            return None

    async def analyze_and_save(
        self,
        commenter: TweetCommenter,
        use_llm: bool = False,
    ) -> TweetCommenter:
        """Analyze intent and save results to commenter."""
        result = await self.analyze_comment(commenter, use_llm=use_llm)

        commenter.intent_label = result.intent_label
        commenter.sentiment = result.sentiment
        commenter.intent_confidence = result.confidence
        commenter.intent_keywords = json.dumps(result.keywords)
        commenter.is_high_intent = result.is_high_intent

        await self.db.commit()
        await self.db.refresh(commenter)

        return commenter

    async def analyze_tweet_commenters(
        self,
        tweet_id: int,
        use_llm: bool = False,
        only_real_users: bool = True,
    ) -> dict[str, int]:
        """Analyze intent for all commenters of a tweet."""
        query = select(TweetCommenter).where(
            TweetCommenter.tweet_id == tweet_id,
            TweetCommenter.intent_label.is_(None),  # Not yet analyzed
        )

        if only_real_users:
            query = query.where(TweetCommenter.is_real_user == True)  # noqa: E712

        result = await self.db.execute(query)
        commenters = list(result.scalars().all())

        stats = {label.value: 0 for label in IntentLabel}
        stats["total"] = 0
        stats["high_intent"] = 0

        for commenter in commenters:
            try:
                await self.analyze_and_save(commenter, use_llm=use_llm)
                stats[commenter.intent_label.value] += 1
                stats["total"] += 1
                if commenter.is_high_intent:
                    stats["high_intent"] += 1
            except Exception as e:
                logger.error(
                    "Failed to analyze intent",
                    commenter_id=commenter.id,
                    error=str(e),
                )

        logger.info(
            "Analyzed tweet commenters intent",
            tweet_id=tweet_id,
            stats=stats,
        )

        return stats

    async def get_high_intent_commenters(
        self,
        tweet_id: int | None = None,
        influencer_id: int | None = None,
        intent_labels: list[IntentLabel] | None = None,
        min_confidence: float = 0.5,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[TweetCommenter], int]:
        """Get high intent commenters with filters."""
        from sqlalchemy import func

        from xspider.admin.models import MonitoredTweet

        query = select(TweetCommenter).where(
            TweetCommenter.is_high_intent == True  # noqa: E712
        )

        if tweet_id:
            query = query.where(TweetCommenter.tweet_id == tweet_id)

        if influencer_id:
            # Join with tweets to filter by influencer
            subquery = select(MonitoredTweet.id).where(
                MonitoredTweet.influencer_id == influencer_id
            )
            query = query.where(TweetCommenter.tweet_id.in_(subquery))

        if intent_labels:
            query = query.where(TweetCommenter.intent_label.in_(intent_labels))

        query = query.where(TweetCommenter.intent_confidence >= min_confidence)

        # Count
        count_subquery = query.subquery()
        count_result = await self.db.execute(
            select(func.count()).select_from(count_subquery)
        )
        total = count_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(TweetCommenter.intent_confidence.desc())
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        commenters = list(result.scalars().all())

        return commenters, total

    async def get_intent_summary(self, tweet_id: int) -> dict[str, Any]:
        """Get intent analysis summary for a tweet."""
        from sqlalchemy import func

        total_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.intent_label.isnot(None),
            )
        )
        total = total_result.scalar() or 0

        # Count by intent label
        label_distribution = {}
        for label in IntentLabel:
            label_result = await self.db.execute(
                select(func.count(TweetCommenter.id)).where(
                    TweetCommenter.tweet_id == tweet_id,
                    TweetCommenter.intent_label == label,
                )
            )
            count = label_result.scalar() or 0
            if count > 0:
                label_distribution[label.value] = count

        # Count by sentiment
        sentiment_distribution = {}
        for sentiment in SentimentType:
            sent_result = await self.db.execute(
                select(func.count(TweetCommenter.id)).where(
                    TweetCommenter.tweet_id == tweet_id,
                    TweetCommenter.sentiment == sentiment,
                )
            )
            count = sent_result.scalar() or 0
            if count > 0:
                sentiment_distribution[sentiment.value] = count

        # High intent count
        high_intent_result = await self.db.execute(
            select(func.count(TweetCommenter.id)).where(
                TweetCommenter.tweet_id == tweet_id,
                TweetCommenter.is_high_intent == True,  # noqa: E712
            )
        )
        high_intent_count = high_intent_result.scalar() or 0

        return {
            "tweet_id": tweet_id,
            "total_analyzed": total,
            "high_intent_count": high_intent_count,
            "high_intent_rate": (high_intent_count / total * 100) if total > 0 else 0,
            "intent_distribution": label_distribution,
            "sentiment_distribution": sentiment_distribution,
        }
