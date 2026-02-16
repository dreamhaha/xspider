"""Prompt templates for AI content audit."""

from __future__ import annotations

from string import Template

SYSTEM_PROMPT = """You are an expert content analyst specializing in social media profile analysis and industry classification. Your task is to analyze Twitter/X user content and determine their relevance to a specific industry.

You must respond with valid JSON only, no additional text or markdown formatting."""

AUDIT_PROMPT_TEMPLATE = Template("""Analyze the following Twitter/X user profile and their recent tweets to determine their relevance to the **${industry}** industry.

## User Profile
- Username: @${username}
- Bio: ${bio}

## Recent Tweets
${tweets}

## Instructions
Evaluate whether this user creates content relevant to the ${industry} industry. Consider:
1. Direct involvement in the industry (founder, employee, investor, builder)
2. Content topics and themes
3. Technical discussions or product updates
4. Community engagement patterns
5. Professional background indicators

## Required JSON Response Format
{
    "is_relevant": true/false,
    "relevance_score": 1-10,
    "topics": ["topic1", "topic2", "topic3"],
    "tags": ["tag1", "tag2", "tag3"],
    "reasoning": "Brief explanation of your assessment"
}

Guidelines for scoring:
- 1-3: Not relevant (unrelated industry, personal content only)
- 4-5: Marginally relevant (occasional mentions, tangential connection)
- 6-7: Moderately relevant (regular engagement, some expertise)
- 8-9: Highly relevant (active contributor, clear expertise)
- 10: Core industry figure (thought leader, major project/company)

Return ONLY the JSON object, no additional text.""")


def build_audit_prompt(
    username: str,
    bio: str | None,
    tweets: list[str],
    industry: str,
) -> str:
    """Build the audit prompt with user content.

    Args:
        username: Twitter username
        bio: User bio/description
        tweets: List of tweet texts
        industry: Target industry for relevance assessment

    Returns:
        Formatted prompt string
    """
    bio_text = bio if bio else "No bio available"

    if tweets:
        tweets_text = "\n".join(
            f"{i+1}. {tweet.strip()}"
            for i, tweet in enumerate(tweets)
            if tweet.strip()
        )
    else:
        tweets_text = "No tweets available for analysis"

    return AUDIT_PROMPT_TEMPLATE.substitute(
        industry=industry,
        username=username,
        bio=bio_text,
        tweets=tweets_text,
    )


BATCH_SUMMARY_PROMPT_TEMPLATE = Template("""Summarize the following audit results for ${count} users analyzed for relevance to the ${industry} industry.

## Audit Results
${results}

Provide a brief summary including:
1. Overall relevance distribution
2. Common topics identified
3. Key patterns observed
4. Notable findings

Format as a concise paragraph.""")


def build_batch_summary_prompt(
    industry: str,
    results: list[dict],
) -> str:
    """Build prompt for summarizing batch audit results.

    Args:
        industry: Target industry
        results: List of audit result dictionaries

    Returns:
        Formatted prompt string
    """
    results_text = "\n".join(
        f"- @{r.get('username', 'unknown')}: score={r.get('relevance_score', 0)}, "
        f"relevant={r.get('is_relevant', False)}, topics={r.get('topics', [])}"
        for r in results
    )

    return BATCH_SUMMARY_PROMPT_TEMPLATE.substitute(
        count=len(results),
        industry=industry,
        results=results_text,
    )
