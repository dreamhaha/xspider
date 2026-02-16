"""AI module - LLM-powered content audit and analysis."""

from xspider.ai.auditor import (
    AuditorConfig,
    ContentAuditor,
    audit_user_content,
)
from xspider.ai.client import (
    AnthropicClient,
    LLMClient,
    OpenAIClient,
    create_llm_client,
)
from xspider.ai.models import (
    AuditRequest,
    AuditResult,
    BatchAuditResult,
    LLMProvider,
    TweetContent,
)
from xspider.ai.prompts import (
    AUDIT_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
    build_audit_prompt,
    build_batch_summary_prompt,
)

__all__ = [
    # Models
    "LLMProvider",
    "AuditResult",
    "AuditRequest",
    "BatchAuditResult",
    "TweetContent",
    # Client
    "LLMClient",
    "OpenAIClient",
    "AnthropicClient",
    "create_llm_client",
    # Prompts
    "SYSTEM_PROMPT",
    "AUDIT_PROMPT_TEMPLATE",
    "build_audit_prompt",
    "build_batch_summary_prompt",
    # Auditor
    "AuditorConfig",
    "ContentAuditor",
    "audit_user_content",
]
