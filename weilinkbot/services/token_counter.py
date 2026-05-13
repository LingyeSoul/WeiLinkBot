"""Token counting utility using tiktoken with lazy encoder caching."""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Model name -> encoding name mapping
_MODEL_ENCODING_MAP: dict[str, str] = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "deepseek": "cl100k_base",
    "qwen": "cl100k_base",
}

_DEFAULT_ENCODING = "cl100k_base"


@lru_cache(maxsize=8)
def _get_encoding(model: str):
    """Get tiktoken encoding for a model, cached."""
    import tiktoken

    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        pass

    model_lower = model.lower()
    for prefix, enc_name in _MODEL_ENCODING_MAP.items():
        if prefix in model_lower:
            return tiktoken.get_encoding(enc_name)

    return tiktoken.get_encoding(_DEFAULT_ENCODING)


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Count tokens in a text string."""
    if not text:
        return 0
    try:
        enc = _get_encoding(model)
        return len(enc.encode(text))
    except Exception:
        # Fallback: rough estimate (1 token ≈ 4 chars for English, 2 for CJK)
        return max(1, len(text) // 3)


def count_message_tokens(
    messages: list[dict[str, str]],
    model: str = "gpt-4o-mini",
) -> int:
    """Count total tokens in an OpenAI-format message list.

    Accounts for message framing overhead per OpenAI's token counting guide.
    """
    if not messages:
        return 0

    try:
        enc = _get_encoding(model)
    except Exception:
        return sum(count_tokens(m.get("content", ""), model) for m in messages)

    total = 0
    for msg in messages:
        # Per-message overhead: 4 tokens for framing (<|start|>, role, \n, <|end|>)
        total += 4
        content = msg.get("content", "")
        if content:
            total += len(enc.encode(str(content)))
        # Tool calls add tokens too
        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            total += len(enc.encode(func.get("name", "")))
            total += len(enc.encode(func.get("arguments", "")))
    # Every reply is primed with <|start|>assistant<|message|>
    total += 2
    return total


def truncate_messages_to_budget(
    messages: list[dict[str, str]],
    token_budget: int,
    model: str = "gpt-4o-mini",
    preserve_system: bool = True,
) -> list[dict[str, str]]:
    """Truncate messages to fit within a token budget.

    Strategy:
    - Always keep the system message (first message if role=system)
    - Remove oldest non-system messages first
    - Ensure the result starts with a user message after system messages
    """
    if not messages or token_budget <= 0:
        return messages

    total = count_message_tokens(messages, model)
    if total <= token_budget:
        return messages

    # Separate system messages from conversation messages
    system_msgs: list[dict[str, str]] = []
    conversation_msgs: list[dict[str, str]] = []

    for msg in messages:
        if preserve_system and msg.get("role") == "system" and not system_msgs:
            system_msgs.append(msg)
        else:
            conversation_msgs.append(msg)

    system_tokens = count_message_tokens(system_msgs, model) if system_msgs else 0
    available_budget = token_budget - system_tokens - 6  # 6 tokens safety margin

    if available_budget <= 0:
        logger.warning(
            "System prompt (%d tokens) exceeds token budget (%d). "
            "Returning system prompt only.",
            system_tokens, token_budget,
        )
        return system_msgs

    # Trim from oldest, keeping conversation starts at a user message
    kept: list[dict[str, str]] = []
    running_tokens = 0

    for msg in reversed(conversation_msgs):
        msg_tokens = count_message_tokens([msg], model)
        if running_tokens + msg_tokens > available_budget:
            break
        kept.insert(0, msg)
        running_tokens += msg_tokens

    # Ensure conversation starts with a user message (avoid orphan tool results)
    while kept and kept[0].get("role") != "user":
        kept.pop(0)

    result = system_msgs + kept

    final_tokens = count_message_tokens(result, model)
    logger.debug(
        "Context truncated: %d -> %d tokens (budget: %d, kept %d/%d messages)",
        total, final_tokens, token_budget, len(kept), len(conversation_msgs),
    )

    return result
