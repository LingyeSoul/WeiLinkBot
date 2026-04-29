"""LLM provider abstraction — thin wrapper over OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, RateLimitError

from .. import __version__
from ..config import LLMConfig, LLM_PRESETS
from ..i18n import t

logger = logging.getLogger(__name__)

# Max retry attempts for transient errors
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0
DEFAULT_USER_AGENT = f"WeiLinkBot/{__version__}"


class LLMService:
    """Unified LLM chat service supporting any OpenAI-compatible provider.

    Providers: OpenAI, DeepSeek, custom (any base_url override).
    """

    def __init__(self, config: LLMConfig) -> None:
        config.api_key = config.api_key.strip()
        self._config = config
        self._build_client()

    def _build_client(self) -> None:
        """Build/rebuild the OpenAI client from current config."""
        self._client = AsyncOpenAI(
            api_key=self._config.api_key or "not-set",
            base_url=self._config.base_url,
            default_headers={"User-Agent": DEFAULT_USER_AGENT},
        )

    @property
    def config(self) -> LLMConfig:
        return self._config

    def update_config(self, config: LLMConfig) -> None:
        """Hot-swap LLM configuration without restart."""
        # Trim whitespace from API key to prevent auth failures
        config.api_key = config.api_key.strip()
        self._config = config
        self._build_client()
        logger.info("LLM config updated: model=%s provider=%s base_url=%s",
                     config.model, config.provider, config.base_url)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> tuple[str, int]:
        """Send a chat completion request.

        Args:
            messages: OpenAI-format message list [{"role": ..., "content": ...}]
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            (response_text, total_tokens)

        Raises:
            RuntimeError: After all retries exhausted
        """
        if not self._config.api_key:
            return t("llm.error.no_key"), 0

        kwargs = {
            "model": self._config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self._config.temperature,
            "max_tokens": max_tokens or self._config.max_tokens,
        }

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                text = response.choices[0].message.content or ""
                tokens = response.usage.total_tokens if response.usage else 0
                logger.debug("LLM response: %d chars, %d tokens", len(text), tokens)
                return text, tokens

            except (APIConnectionError, APITimeoutError) as e:
                last_error = e
                logger.warning("LLM connection error (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BASE_DELAY * attempt)

            except RateLimitError as e:
                last_error = e
                logger.warning("LLM rate limited (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BASE_DELAY * attempt * 2)

            except Exception as e:
                logger.error("LLM unexpected error: %s", e)
                return t("llm.error.request_failed", e=e), 0

        logger.error("LLM failed after %d retries: %s", MAX_RETRIES, last_error)
        return t("llm.error.unavailable", retries=MAX_RETRIES), 0

    @staticmethod
    async def chat_with_config(
        config: LLMConfig,
        messages: list[dict[str, Any]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> tuple[str, int]:
        """Send a chat request using an arbitrary LLMConfig (e.g. preprocessing model).

        Supports multimodal content parts in messages.
        """
        if not config.api_key:
            return t("llm.error.no_key"), 0

        client = AsyncOpenAI(
            api_key=config.api_key.strip() or "not-set",
            base_url=config.base_url,
            default_headers={"User-Agent": DEFAULT_USER_AGENT},
        )

        kwargs = {
            "model": config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else config.temperature,
            "max_tokens": max_tokens or config.max_tokens,
        }

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await client.chat.completions.create(**kwargs)
                text = response.choices[0].message.content or ""
                tokens = response.usage.total_tokens if response.usage else 0
                return text, tokens

            except (APIConnectionError, APITimeoutError) as e:
                last_error = e
                logger.warning("Preprocess LLM connection error (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BASE_DELAY * attempt)

            except RateLimitError as e:
                last_error = e
                logger.warning("Preprocess LLM rate limited (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BASE_DELAY * attempt * 2)

            except Exception as e:
                logger.error("Preprocess LLM unexpected error: %s", e)
                return "", 0

        logger.error("Preprocess LLM failed after %d retries: %s", MAX_RETRIES, last_error)
        return "", 0

    @staticmethod
    def apply_preset(provider: str, config: LLMConfig) -> LLMConfig:
        """Apply a provider preset to config, preserving api_key."""
        preset = LLM_PRESETS.get(provider)
        if preset:
            config.provider = provider
            config.base_url = preset["base_url"]
            config.model = preset["model"]
        return config
