"""LLM client abstraction supporting OpenAI and Anthropic."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from xspider.ai.models import LLMProvider
from xspider.ai.prompts import SYSTEM_PROMPT
from xspider.core import AuditError, get_logger, get_settings

logger = get_logger(__name__)


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    provider: LLMProvider
    model: str

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Send a completion request to the LLM.

        Args:
            prompt: User prompt
            system_prompt: System prompt for context
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens in response

        Returns:
            LLM response text

        Raises:
            AuditError: If the API call fails
        """
        pass

    async def complete_json(
        self,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Send a completion request expecting JSON response.

        Args:
            prompt: User prompt
            system_prompt: System prompt for context
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens in response

        Returns:
            Parsed JSON response

        Raises:
            AuditError: If the API call or JSON parsing fails
        """
        response = await self.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        try:
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse JSON response",
                error=str(e),
                response=response[:500],
            )
            raise AuditError(
                f"Failed to parse LLM response as JSON: {e}",
                model=self.model,
            ) from e

    @abstractmethod
    async def close(self) -> None:
        """Close the client and release resources."""
        pass


class OpenAIClient(LLMClient):
    """OpenAI GPT client implementation."""

    provider = LLMProvider.OPENAI

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4-turbo-preview",
    ) -> None:
        """Initialize OpenAI client.

        Args:
            api_key: OpenAI API key (defaults to settings)
            model: Model name to use
        """
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise AuditError(
                "openai package not installed. Run: pip install openai"
            ) from e

        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key

        if not self.api_key:
            raise AuditError("OpenAI API key not configured")

        self.model = model
        self._client = AsyncOpenAI(api_key=self.api_key)

    async def complete(
        self,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Send a completion request to OpenAI."""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if content is None:
                raise AuditError("OpenAI returned empty response", model=self.model)

            logger.debug(
                "OpenAI completion",
                model=self.model,
                tokens_used=response.usage.total_tokens if response.usage else 0,
            )

            return content

        except Exception as e:
            if "AuditError" in type(e).__name__:
                raise
            logger.error("OpenAI API error", error=str(e))
            raise AuditError(f"OpenAI API error: {e}", model=self.model) from e

    async def close(self) -> None:
        """Close the OpenAI client."""
        await self._client.close()


class AnthropicClient(LLMClient):
    """Anthropic Claude client implementation."""

    provider = LLMProvider.ANTHROPIC

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-3-5-sonnet-20241022",
    ) -> None:
        """Initialize Anthropic client.

        Args:
            api_key: Anthropic API key (defaults to settings)
            model: Model name to use
        """
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise AuditError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from e

        settings = get_settings()
        self.api_key = api_key or settings.anthropic_api_key

        if not self.api_key:
            raise AuditError("Anthropic API key not configured")

        self.model = model
        self._client = AsyncAnthropic(api_key=self.api_key)

    async def complete(
        self,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Send a completion request to Anthropic."""
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )

            if not response.content:
                raise AuditError("Anthropic returned empty response", model=self.model)

            content = response.content[0]
            if content.type != "text":
                raise AuditError(
                    f"Unexpected content type: {content.type}",
                    model=self.model,
                )

            logger.debug(
                "Anthropic completion",
                model=self.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            return content.text

        except Exception as e:
            if "AuditError" in type(e).__name__:
                raise
            logger.error("Anthropic API error", error=str(e))
            raise AuditError(f"Anthropic API error: {e}", model=self.model) from e

    async def close(self) -> None:
        """Close the Anthropic client."""
        await self._client.close()


class KimiClient(LLMClient):
    """Kimi (Moonshot AI) client implementation using OpenAI-compatible API."""

    provider = LLMProvider.KIMI

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "moonshot-v1-8k",
        base_url: str = "https://api.moonshot.cn/v1",
    ) -> None:
        """Initialize Kimi client.

        Args:
            api_key: Kimi API key (defaults to settings)
            model: Model name (moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k)
            base_url: API base URL
        """
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise AuditError(
                "openai package not installed. Run: pip install openai"
            ) from e

        settings = get_settings()
        self.api_key = api_key or settings.kimi_api_key

        if not self.api_key:
            raise AuditError("Kimi API key not configured")

        self.model = model
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)

    async def complete(
        self,
        prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Send a completion request to Kimi."""
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content
            if content is None:
                raise AuditError("Kimi returned empty response", model=self.model)

            logger.debug(
                "Kimi completion",
                model=self.model,
                tokens_used=response.usage.total_tokens if response.usage else 0,
            )

            return content

        except Exception as e:
            if "AuditError" in type(e).__name__:
                raise
            logger.error("Kimi API error", error=str(e))
            raise AuditError(f"Kimi API error: {e}", model=self.model) from e

    async def close(self) -> None:
        """Close the Kimi client."""
        await self._client.close()


def create_llm_client(
    provider: LLMProvider | str = LLMProvider.OPENAI,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMClient:
    """Factory function to create an LLM client.

    Args:
        provider: LLM provider (openai, anthropic, or kimi)
        model: Model name (uses default for provider if not specified)
        api_key: API key (uses settings if not specified)

    Returns:
        Configured LLM client

    Raises:
        AuditError: If provider is not supported
    """
    if isinstance(provider, str):
        try:
            provider = LLMProvider(provider.lower())
        except ValueError:
            raise AuditError(f"Unsupported LLM provider: {provider}")

    if provider == LLMProvider.OPENAI:
        return OpenAIClient(
            api_key=api_key,
            model=model or "gpt-4-turbo-preview",
        )
    elif provider == LLMProvider.ANTHROPIC:
        return AnthropicClient(
            api_key=api_key,
            model=model or "claude-3-5-sonnet-20241022",
        )
    elif provider == LLMProvider.KIMI:
        return KimiClient(
            api_key=api_key,
            model=model or "moonshot-v1-8k",
        )
    else:
        raise AuditError(f"Unsupported LLM provider: {provider}")
