"""AI Prompts for Growth & Engagement System (运营增长系统AI提示词).

Contains prompts for:
- Content rewriting in different tones
- Smart interaction comment generation
- Targeted comment generation
"""

from __future__ import annotations

from xspider.admin.models import CommentStrategy, RewriteTone


# ============================================================================
# Content Rewrite Prompts (内容改写提示词)
# ============================================================================


REWRITE_SYSTEM_PROMPT = """You are a professional social media content creator specializing in Twitter/X content optimization.

Your task is to rewrite the given content according to the specified tone while:
1. Preserving the core message and key information
2. Optimizing for Twitter's format (max 280 characters per tweet)
3. Adding engagement hooks appropriate for the tone
4. Including relevant hashtags when appropriate
5. Making the content more shareable and engaging

Output your rewritten content directly without any preamble or explanation."""


REWRITE_TONE_PROMPTS: dict[RewriteTone, str] = {
    RewriteTone.PROFESSIONAL: """Rewrite this content in a PROFESSIONAL tone:
- Use authoritative language and industry terminology
- Include data or statistics if relevant
- Present information with confidence and expertise
- Maintain a formal but accessible style
- Add credibility markers (e.g., "According to...", "Research shows...")

Content to rewrite:
{content}

Additional instructions (if any): {custom_instructions}

Rewrite the content professionally:""",

    RewriteTone.HUMOROUS: """Rewrite this content in a HUMOROUS tone:
- Add wit and clever wordplay
- Use relatable observations or light sarcasm
- Keep it fun while maintaining the core message
- Make it highly shareable and quotable
- Add appropriate emojis sparingly

Content to rewrite:
{content}

Additional instructions (if any): {custom_instructions}

Rewrite the content humorously:""",

    RewriteTone.CONTROVERSIAL: """Rewrite this content in a CONTROVERSIAL/PROVOCATIVE tone:
- Challenge conventional thinking
- Present a bold, contrarian viewpoint
- Use strong, confident language
- Spark discussion and debate
- Be thought-provoking without being offensive

Content to rewrite:
{content}

Additional instructions (if any): {custom_instructions}

Rewrite the content provocatively:""",

    RewriteTone.THREAD_STYLE: """Convert this content into a TWITTER THREAD format:
- Split into 3-5 connected tweets
- Start with an attention-grabbing hook (first tweet)
- Each tweet should flow naturally to the next
- Use numbering (1/, 2/, etc.)
- End with a call-to-action or key takeaway
- Each tweet max 280 characters

Content to convert:
{content}

Additional instructions (if any): {custom_instructions}

Create the thread (separate each tweet with ---):""",
}


def get_rewrite_prompt(
    tone: RewriteTone,
    content: str,
    custom_instructions: str | None = None,
) -> str:
    """Get the rewrite prompt for a given tone."""
    template = REWRITE_TONE_PROMPTS.get(tone, REWRITE_TONE_PROMPTS[RewriteTone.PROFESSIONAL])
    return template.format(
        content=content,
        custom_instructions=custom_instructions or "None",
    )


# ============================================================================
# Hashtag Generation Prompts (标签生成提示词)
# ============================================================================


HASHTAG_PROMPT = """Based on the following tweet content, generate 3-5 relevant hashtags.

Rules:
1. Use trending or popular hashtags in the content's niche
2. Include a mix of broad and specific hashtags
3. Keep hashtags concise and memorable
4. Return only the hashtags, separated by spaces

Tweet content:
{content}

Generate hashtags:"""


# ============================================================================
# Smart Interaction Prompts (智能互动提示词)
# ============================================================================


RELEVANCE_CHECK_PROMPT = """Evaluate how relevant this KOL's tweet is to the operating account's niche.

Operating Account Niche: {niche_tags}
Operating Account Persona: {persona}

KOL Tweet:
{tweet_content}

Rate the relevance from 0.0 to 1.0 and explain briefly.
Output format:
SCORE: [0.0-1.0]
REASON: [brief explanation]"""


COMMENT_GENERATION_SYSTEM = """You are a social media engagement expert. Generate authentic, engaging comments that add value to conversations.

Your comments should:
1. Feel natural and human-written
2. Add genuine value to the conversation
3. Match the tone of the account's persona
4. Encourage further engagement
5. Stay within 280 characters

Never use:
- Generic responses like "Great post!"
- Excessive emojis
- Obvious self-promotion
- Spammy language"""


COMMENT_STRATEGY_PROMPTS: dict[CommentStrategy, str] = {
    CommentStrategy.SUPPLEMENT: """Generate a SUPPLEMENTARY comment that adds valuable insight:
- Share additional information or a unique perspective
- Reference relevant data, examples, or experiences
- Build on the original point constructively
- Position yourself as knowledgeable in the field

Account Persona: {persona}
Account Niche: {niche_tags}

Original Tweet:
{tweet_content}

Generate a supplementary comment (max 280 chars):""",

    CommentStrategy.QUESTION: """Generate an ENGAGING QUESTION comment:
- Ask a thought-provoking question related to the topic
- Encourage the author or others to share more
- Show genuine curiosity and interest
- Questions that drive engagement and discussion

Account Persona: {persona}
Account Niche: {niche_tags}

Original Tweet:
{tweet_content}

Generate an engaging question (max 280 chars):""",

    CommentStrategy.HUMOR_MEME: """Generate a HUMOROUS/WITTY comment:
- Add a relevant joke, pun, or witty observation
- Keep it light-hearted and positive
- Make it relatable and shareable
- Appropriate humor that enhances engagement

Account Persona: {persona}
Account Niche: {niche_tags}

Original Tweet:
{tweet_content}

Generate a witty comment (max 280 chars):""",
}


def get_comment_generation_prompt(
    strategy: CommentStrategy,
    tweet_content: str,
    persona: str | None = None,
    niche_tags: list[str] | None = None,
) -> str:
    """Get the comment generation prompt for a given strategy."""
    template = COMMENT_STRATEGY_PROMPTS.get(
        strategy,
        COMMENT_STRATEGY_PROMPTS[CommentStrategy.SUPPLEMENT],
    )
    return template.format(
        tweet_content=tweet_content,
        persona=persona or "Professional account in the tech industry",
        niche_tags=", ".join(niche_tags) if niche_tags else "General",
    )


# ============================================================================
# Targeted Comment Prompts (指定评论提示词)
# ============================================================================


TARGETED_COMMENT_PROMPT = """Generate a targeted comment for the following tweet.

Account Persona: {persona}
Account Niche: {niche_tags}

Target Tweet:
{tweet_content}

Comment Direction/Instructions: {comment_direction}

Strategy: {strategy}

Requirements:
1. Follow the comment direction provided
2. Stay authentic to the account's persona
3. Add value to the conversation
4. Keep within 280 characters
5. Be engaging but not spammy

Generate the targeted comment:"""


MATRIX_SUPPORT_COMMENT_PROMPT = """Generate a supportive follow-up comment for a matrix commenting strategy.

This comment will be posted by a secondary account to support the main account's comment.

Main Account Comment: {main_comment}

Target Tweet:
{tweet_content}

Your role: {role}

Requirements:
1. Support or build on the main comment naturally
2. Add a unique perspective or agreement
3. Don't be too obvious as a "supporter"
4. Keep it authentic and engaging
5. Max 280 characters

Generate the supportive comment:"""


def get_targeted_comment_prompt(
    tweet_content: str,
    comment_direction: str | None,
    strategy: CommentStrategy | None,
    persona: str | None = None,
    niche_tags: list[str] | None = None,
) -> str:
    """Get the targeted comment prompt."""
    return TARGETED_COMMENT_PROMPT.format(
        tweet_content=tweet_content,
        comment_direction=comment_direction or "Generate an engaging, relevant comment",
        strategy=strategy.value if strategy else "supplement",
        persona=persona or "Professional account",
        niche_tags=", ".join(niche_tags) if niche_tags else "General",
    )


def get_matrix_support_prompt(
    tweet_content: str,
    main_comment: str,
    role: str = "supportive colleague",
) -> str:
    """Get the matrix support comment prompt."""
    return MATRIX_SUPPORT_COMMENT_PROMPT.format(
        tweet_content=tweet_content,
        main_comment=main_comment,
        role=role,
    )
