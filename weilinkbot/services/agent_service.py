"""Agent service — orchestrates LLM + tool calling loop."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import AgentConfig
from .llm_service import LLMService
from .tools.base import ToolResult
from .tools.registry import ToolRegistry
from .event_log import get_event_log

logger = logging.getLogger(__name__)


class AgentService:
    """Runs the LLM ↔ tool-calling loop.

    Supports two modes:
      - Native function calling (when the model supports `tools` parameter)
      - Prompt-based fallback (injects tool descriptions into system prompt)
    """

    def __init__(
        self,
        llm_service: LLMService,
        registry: ToolRegistry,
        agent_config: AgentConfig,
    ) -> None:
        self._llm = llm_service
        self._registry = registry
        self._config = agent_config

    async def run(
        self,
        context: list[dict[str, Any]],
        supports_tools: bool = True,
    ) -> tuple[str, int]:
        """Execute the agent loop.

        Args:
            context: OpenAI-format messages (already built by ConversationService).
            supports_tools: Whether the active model supports native function calling.

        Returns:
            (response_text, total_tokens)
        """
        enabled = self._config.enabled_tools
        if not enabled:
            text, tokens, _ = await self._llm.chat(context)
            return text, tokens

        if supports_tools:
            return await self._run_native(context, enabled)
        return await self._run_prompt(context, enabled)

    # ── Native function calling mode ──────────────────────────────

    async def _run_native(
        self,
        context: list[dict[str, Any]],
        enabled_tools: list[str],
    ) -> tuple[str, int]:
        tools = self._registry.get_openai_tools(enabled_tools)
        messages = list(context)
        total_tokens = 0

        for _round in range(self._config.max_tool_rounds):
            text, tokens, tool_calls = await self._llm.chat(messages, tools=tools)
            total_tokens += tokens

            if not tool_calls:
                return text, total_tokens

            # Append assistant message with tool_calls
            assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
            if text:
                assistant_msg["content"] = text
            messages.append(assistant_msg)

            # Execute each tool call and append results
            for tc in tool_calls:
                result = await self._execute_tool(
                    tc["id"], tc["function"]["name"], tc["function"]["arguments"],
                )
                messages.append(result.to_tool_message())

            logger.info("Agent round %d: %d tool calls executed", _round + 1, len(tool_calls))

        # Max rounds reached — make one final call without tools
        text, tokens, _ = await self._llm.chat(messages)
        total_tokens += tokens
        return text, total_tokens

    # ── Prompt-based fallback mode ────────────────────────────────

    async def _run_prompt(
        self,
        context: list[dict[str, Any]],
        enabled_tools: list[str],
    ) -> tuple[str, int]:
        tools_desc = self._registry.get_prompt_description(enabled_tools)
        messages = list(context)
        tool_injection = (
            "\n\n## Available Tools\n"
            f"{tools_desc}\n\n"
            "To use a tool, output a ```tool_call``` block like this:\n"
            '```tool_call\n{"name": "tool_name", "arguments": {"arg": "value"}}\n```\n'
            "You may call one tool at a time. After receiving the tool result, continue your response normally."
        )

        # Inject into system prompt
        if messages and messages[0].get("role") == "system":
            messages[0] = {**messages[0], "content": messages[0]["content"] + tool_injection}

        total_tokens = 0

        for _round in range(self._config.max_tool_rounds):
            text, tokens, _ = await self._llm.chat(messages)
            total_tokens += tokens

            tool_calls = ToolRegistry.parse_prompt_tool_calls(text)
            if not tool_calls:
                return text, total_tokens

            # Append assistant message (with tool_call blocks still in it)
            messages.append({"role": "assistant", "content": text})

            # Execute each tool call and append results
            for tc in tool_calls:
                result = await self._execute_tool(
                    tc["id"], tc["function"]["name"], tc["function"]["arguments"],
                )
                messages.append(result.to_tool_message())

            logger.info("Agent prompt round %d: %d tool calls", _round + 1, len(tool_calls))

        text, tokens, _ = await self._llm.chat(messages)
        total_tokens += tokens
        return text, total_tokens

    # ── Tool execution ────────────────────────────────────────────

    async def _execute_tool(
        self,
        call_id: str,
        name: str,
        arguments: str | dict,
    ) -> ToolResult:
        tool = self._registry.get(name)
        if not tool:
            return ToolResult(
                tool_call_id=call_id, tool_name=name, output="",
                success=False, error=f"Unknown tool: {name}",
            )

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return ToolResult(
                    tool_call_id=call_id, tool_name=name, output="",
                    success=False, error="Invalid JSON arguments",
                )

        try:
            output = await tool.execute(**arguments)
            await get_event_log().push(
                "info", "agent", "agent.tool_call",
                f"Tool: {name}({json.dumps(arguments, ensure_ascii=False)}) → {output[:100]}",
                {"tool": name, "arguments": arguments, "result": output[:200]},
            )
            return ToolResult(
                tool_call_id=call_id, tool_name=name, output=output, success=True,
            )
        except Exception as e:
            logger.warning("Tool %s execution error: %s", name, e)
            await get_event_log().push(
                "warning", "agent", "agent.tool_error",
                f"Tool {name} error: {e}",
                {"tool": name, "arguments": arguments, "error": str(e)},
            )
            return ToolResult(
                tool_call_id=call_id, tool_name=name, output="",
                success=False, error=str(e),
            )
