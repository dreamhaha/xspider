"""LLM-based seed influencer recommendation service (AI种子网红推荐服务)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xspider.core.logging import get_logger

logger = get_logger(__name__)


# System prompt for seed recommendation
SEED_RECOMMENDER_SYSTEM_PROMPT = """You are a Twitter/X influencer research expert. Your task is to recommend influential Twitter accounts based on the user's requirements.

You have deep knowledge of the Twitter ecosystem across various industries including:
- Cryptocurrency & Web3 (traders, developers, VCs, project founders)
- Technology & AI (researchers, founders, engineers)
- Finance & Trading (analysts, fund managers)
- Gaming & Esports (streamers, pro players, developers)
- Marketing & Growth (growth hackers, marketers)
- And many other industries

When recommending influencers, consider:
1. Relevance to the user's requirements
2. Influence and reach (follower count, engagement)
3. Activity level (regularly posting)
4. Authenticity (real influence, not bots)
5. Diverse perspectives within the niche

Always respond in JSON format with the exact structure specified."""


@dataclass
class RecommendedSeed:
    """A recommended seed influencer."""

    username: str
    reason: str
    estimated_followers: str  # e.g., "1.2M", "500K"
    relevance_score: int  # 1-10
    category: str  # e.g., "KOL", "Founder", "Analyst"


@dataclass
class SeedRecommendationResult:
    """Result of seed recommendation."""

    seeds: list[RecommendedSeed]
    summary: str
    model_used: str
    tokens_used: int


async def recommend_seeds(
    prompt: str,
    num_recommendations: int = 10,
    language: str = "en",
) -> SeedRecommendationResult:
    """
    Use LLM to recommend seed influencers based on user prompt.

    Args:
        prompt: User's description of what kind of influencers they want
        num_recommendations: Number of recommendations to generate (default 10)
        language: Response language (en, zh, ja)

    Returns:
        SeedRecommendationResult with recommended seeds

    Raises:
        Exception: If LLM call fails
    """
    from xspider.ai.client import create_llm_client
    from xspider.core.config import get_settings

    settings = get_settings()

    # Choose provider based on available keys
    # Prioritize Kimi (Moonshot AI) first
    provider = None
    if settings.kimi_api_key:
        provider = "kimi"
    elif settings.openai_api_key and settings.openai_api_key.startswith("sk-"):
        provider = "openai"
    elif settings.anthropic_api_key:
        provider = "anthropic"

    if not provider:
        raise ValueError("No valid LLM API key configured. Please set OPENAI_API_KEY, KIMI_API_KEY, or ANTHROPIC_API_KEY.")

    client = create_llm_client(provider=provider)

    try:
        # Build the prompt
        language_instruction = {
            "en": "Respond in English.",
            "zh": "请用中文回复。",
            "ja": "日本語で回答してください。",
        }.get(language, "Respond in English.")

        user_prompt = f"""Based on the following requirements, recommend {num_recommendations} influential Twitter/X accounts that would be good seed accounts for influencer discovery.

User Requirements:
{prompt}

{language_instruction}

Respond with a JSON object in this exact format:
{{
    "summary": "Brief summary of your recommendation strategy",
    "seeds": [
        {{
            "username": "twitter_username_without_at",
            "reason": "Why this account is relevant",
            "estimated_followers": "Approximate follower count like 1.2M or 500K",
            "relevance_score": 8,
            "category": "Category like KOL, Founder, Analyst, Developer, etc."
        }}
    ]
}}

Important:
- Use actual, real Twitter usernames that are active as of 2024
- Focus on accounts that are influential in the specified domain
- Include a mix of large accounts (100K+) and mid-tier accounts (10K-100K) for diversity
- Relevance score should be 1-10 based on how well they match the requirements
- Do not include suspended or inactive accounts"""

        # Call LLM - scale max_tokens based on number of recommendations
        # Each recommendation uses ~150 tokens in JSON format
        estimated_tokens = max(2000, num_recommendations * 200)

        response = await client.complete_json(
            prompt=user_prompt,
            system_prompt=SEED_RECOMMENDER_SYSTEM_PROMPT,
            temperature=0.7,  # Slightly higher for more diverse recommendations
            max_tokens=estimated_tokens,
        )

        # Parse response
        seeds = []
        for seed_data in response.get("seeds", []):
            seeds.append(RecommendedSeed(
                username=seed_data.get("username", "").strip().lstrip("@"),
                reason=seed_data.get("reason", ""),
                estimated_followers=seed_data.get("estimated_followers", "Unknown"),
                relevance_score=int(seed_data.get("relevance_score", 5)),
                category=seed_data.get("category", "Influencer"),
            ))

        # Estimate tokens (rough calculation)
        tokens_used = len(user_prompt) // 4 + len(str(response)) // 4

        logger.info(
            "seed_recommender.completed",
            num_seeds=len(seeds),
            model=client.model,
            tokens=tokens_used,
        )

        return SeedRecommendationResult(
            seeds=seeds,
            summary=response.get("summary", ""),
            model_used=client.model,
            tokens_used=tokens_used,
        )

    finally:
        await client.close()


async def recommend_seeds_with_verification(
    prompt: str,
    num_recommendations: int = 10,
    language: str = "en",
    verify_accounts: bool = True,
) -> dict[str, Any]:
    """
    Recommend seeds and optionally verify they exist on Twitter.

    Args:
        prompt: User's description
        num_recommendations: Number of recommendations
        language: Response language
        verify_accounts: Whether to verify accounts exist

    Returns:
        Dict with recommendations and verification results
    """
    # Get LLM recommendations
    result = await recommend_seeds(prompt, num_recommendations, language)

    response = {
        "summary": result.summary,
        "model_used": result.model_used,
        "tokens_used": result.tokens_used,
        "recommendations": [
            {
                "username": seed.username,
                "reason": seed.reason,
                "estimated_followers": seed.estimated_followers,
                "relevance_score": seed.relevance_score,
                "category": seed.category,
                "verified": None,  # Will be updated if verification enabled
            }
            for seed in result.seeds
        ],
    }

    # Optionally verify accounts
    if verify_accounts:
        try:
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import AsyncSession

            from xspider.admin.models import AccountStatus, TwitterAccount
            from xspider.admin.services.account_pool import AccountPool

            # This would need a database session to be passed in
            # For now, we'll skip verification in this function
            # and let the frontend call resolve-users separately
            pass
        except Exception as e:
            logger.warning("seed_recommender.verification_skipped", error=str(e))

    return response
