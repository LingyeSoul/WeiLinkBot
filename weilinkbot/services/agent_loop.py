"""State-machine-driven agent loop.

Replaces the linear for-loop in AgentService with an explicit state machine
for better debuggability, extensibility, and fault recovery.

States:
    INIT     -> validate context, resolve tools
    INJECT   -> inject safety prompt, skill prompts
    EXECUTE  -> call LLM, process tool calls
    COMPRESS -> truncate tool results if needed
    FINALIZE -> force final text response
    DONE     -> return result

Inspired by nanobot's TurnState architecture.
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum, auto
from typing import Any, Optional

from .event_log import get_event_log
from .llm_service import LLMService
from .tools.base import ToolResult
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent loop state enumeration."""
    INIT = auto()
    INJECT = auto()
    EXECUTE = auto()
    COMPRESS = auto()
    FINALIZE = auto()
    DONE = auto()


# State transition table: current_state -> [valid next states]
_TRANSITIONS: dict[AgentState, list[AgentState]] = {
    AgentState.INIT:     [AgentState.INJECT, AgentState.DONE],
    AgentState.INJECT:   [AgentState.EXECUTE],
    AgentState.EXECUTE:  [AgentState.COMPRESS, AgentState.FINALIZE, AgentState.DONE],
    AgentState.COMPRESS: [AgentState.EXECUTE, AgentState.FINALIZE],
    AgentState.FINALIZE: [AgentState.DONE],
    AgentState.DONE:     [],  # terminal
}


class AgentContext:
    """Mutable context carried through the state machine."""

    __slots__ = (
        "messages", "tools", "tool_defs", "total_tokens",
        "consecutive_failures", "fail_limit", "round", "max_rounds",
        "last_text", "last_tool_calls", "last_reasoning_content",
        "supports_tools", "anti_injection_active", "config",
    )

    def __init__(
        self,
        messages: list[dict[str, Any]],
        supports_tools: bool,
        config: Any,
    ) -> None:
        self.messages = messages
        self.tools: list[str] = []
        self.tool_defs: list[dict] = []
        self.total_tokens = 0
        self.consecutive_failures = 0
        self.fail_limit = config.agent.consecutive_fail_limit
        self.round = 0
        self.max_rounds = config.agent.max_tool_rounds
        self.last_text = ""
        self.last_tool_calls: list[dict] | None = None
        self.last_reasoning_content: str | None = None
        self.supports_tools = supports_tools
        self.anti_injection_active = False
        self.config = config


class AgentLoop:
    """State-machine-driven agent loop.

    Usage:
        loop = AgentLoop(llm_service, registry, config)
        text, tokens = await loop.execute(context_messages, supports_tools=True)
    """

    def __init__(
        self,
        llm_service: LLMService,
        registry: ToolRegistry,
        config: Any,
    ) -> None:
        self._llm = llm_service
        self._registry = registry
        self._config = config

    async def execute(
        self,
        context: list[dict[str, Any]],
        supports_tools: bool = True,
    ) -> tuple[str, int, Optional[str]]:
        """Run the agent loop state machine."""
        ctx = AgentContext(list(context), supports_tools, self._config)
        state = AgentState.INIT

        while state != AgentState.DONE:
            logger.debug("Agent state: %s (round %d)", state.name, ctx.round)
            next_state = await self._transition(state, ctx)
            if next_state not in _TRANSITIONS.get(state, []):
                logger.error(
                    "Invalid state transition: %s -> %s (allowed: %s)",
                    state.name, next_state.name,
                    [s.name for s in _TRANSITIONS.get(state, [])],
                )
                state = AgentState.DONE
                break
            state = next_state

        return ctx.last_text, ctx.total_tokens, ctx.last_reasoning_content

    async def _transition(
        self,
        state: AgentState,
        ctx: AgentContext,
    ) -> AgentState:
        """Execute a state and return the next state."""
        handler = {
            AgentState.INIT: self._handle_init,
            AgentState.INJECT: self._handle_inject,
            AgentState.EXECUTE: self._handle_execute,
            AgentState.COMPRESS: self._handle_compress,
            AgentState.FINALIZE: self._handle_finalize,
        }.get(state)

        if handler is None:
            return AgentState.DONE

        return await handler(ctx)

    # ── State Handlers ──────────────────────────────────────────────

    async def _handle_init(self, ctx: AgentContext) -> AgentState:
        """INIT: Resolve tools and check if agent loop is needed."""
        enabled = list(self._config.agent.enabled_tools)
        if self._config.workspace.enabled:
            enabled.extend(
                t for t in self._config.agent.enabled_workspace_tools
                if t not in enabled
            )
        if self._config.sticker.enabled:
            enabled.extend(
                t for t in self._config.agent.enabled_sticker_tools
                if t not in enabled
            )

        if not enabled:
            # No tools — skip agent loop entirely
            text, tokens, _, reasoning = await self._llm.chat(ctx.messages)
            ctx.total_tokens = tokens
            ctx.last_text = text
            ctx.last_reasoning_content = reasoning
            return AgentState.DONE

        ctx.tools = enabled
        if ctx.supports_tools:
            ctx.tool_defs = self._registry.get_openai_tools(enabled)
        return AgentState.INJECT

    async def _handle_inject(self, ctx: AgentContext) -> AgentState:
        """INJECT: Add safety prompt and tool-aware guidance."""
        from .agent_service import _EXTERNAL_CONTENT_TOOLS, _inject_safety_prompt_static

        # Anti-injection safety prompt for external content tools
        if _EXTERNAL_CONTENT_TOOLS & set(ctx.tools):
            ctx.messages = _inject_safety_prompt_static(ctx.messages)
            ctx.anti_injection_active = True

        # Tool-aware prompt injection (guides LLM to proactively use tools)
        if ctx.config.agent.tool_prompt_injection and ctx.tools:
            from .tools.tool_prompt import build_tool_prompt
            tool_prompt = build_tool_prompt(ctx.tools)
            if tool_prompt:
                if ctx.messages and ctx.messages[0].get("role") == "system":
                    ctx.messages[0] = {
                        **ctx.messages[0],
                        "content": ctx.messages[0]["content"] + "\n\n" + tool_prompt,
                    }
                else:
                    ctx.messages.insert(0, {"role": "system", "content": tool_prompt})

        return AgentState.EXECUTE

    async def _handle_execute(self, ctx: AgentContext) -> AgentState:
        """EXECUTE: Call LLM and process tool calls."""
        if ctx.supports_tools:
            return await self._execute_native(ctx)
        return await self._execute_prompt(ctx)

    async def _execute_tool_calls(self, ctx: AgentContext, tool_calls: list[dict]) -> AgentState | None:
        """Execute tool calls with failure tracking. Returns AgentState if early exit, None to continue."""
        for tc in tool_calls:
            result = await self._execute_tool(
                tc["id"], tc["function"]["name"], tc["function"]["arguments"],
            )
            ctx.messages.append(result.to_tool_message())
            if not result.success:
                ctx.consecutive_failures += 1
            else:
                ctx.consecutive_failures = 0
            if ctx.consecutive_failures >= ctx.fail_limit:
                ctx.messages.append({
                    "role": "system",
                    "content": (
                        f"工具调用已连续失败 {ctx.consecutive_failures} 次。"
                        "请停止重复尝试同一工具，改用其他策略（如换一个工具、"
                        "换一种参数、或直接基于已有信息回复用户）。"
                    ),
                })
                return AgentState.FINALIZE
        return None

    async def _handle_silent_ai(self, ctx: AgentContext) -> None:
        """If LLM returned empty text after tool rounds, nudge it to respond."""
        if ctx.last_text.strip() or ctx.round == 0:
            return
        ctx.messages.append({
            "role": "system",
            "content": (
                "工具执行已完成。请根据工具返回的结果，"
                "给用户一个最终回复。不要返回空内容。"
            ),
        })
        text, tokens, _, reasoning = await self._llm.chat(ctx.messages)
        ctx.total_tokens += tokens
        ctx.last_text = text
        ctx.last_reasoning_content = reasoning

    async def _execute_native(self, ctx: AgentContext) -> AgentState:
        """Execute one round of native function calling."""
        text, tokens, tool_calls, reasoning = await self._llm.chat(
            ctx.messages, tools=ctx.tool_defs,
        )
        ctx.total_tokens += tokens
        ctx.last_text = text
        ctx.last_reasoning_content = reasoning

        if not tool_calls:
            await self._handle_silent_ai(ctx)
            if not ctx.last_text.strip() and ctx.round > 0:
                return AgentState.DONE
            return AgentState.DONE

        # Append assistant message with tool_calls
        assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
        if text:
            assistant_msg["content"] = text
        ctx.messages.append(assistant_msg)

        early_exit = await self._execute_tool_calls(ctx, tool_calls)
        if early_exit:
            return early_exit

        logger.info("Agent round %d: %d tool calls executed", ctx.round + 1, len(tool_calls))
        ctx.round += 1

        if ctx.round >= ctx.max_rounds:
            return AgentState.FINALIZE

        return AgentState.COMPRESS

    async def _execute_prompt(self, ctx: AgentContext) -> AgentState:
        """Execute one round of prompt-based fallback tool calling."""
        if ctx.round == 0:
            # Inject tool descriptions on first round
            tools_desc = self._registry.get_prompt_description(ctx.tools)
            tool_injection = (
                "\n\n## Available Tools\n"
                f"{tools_desc}\n\n"
                "To use a tool, output a ```tool_call``` block like this:\n"
                '```tool_call\n{"name": "tool_name", "arguments": {"arg": "value"}}\n```\n'
                "You may call one tool at a time. After receiving the tool result, "
                "continue your response normally."
            )
            if ctx.messages and ctx.messages[0].get("role") == "system":
                ctx.messages[0] = {**ctx.messages[0], "content": ctx.messages[0]["content"] + tool_injection}

        text, tokens, _, reasoning = await self._llm.chat(ctx.messages)
        ctx.total_tokens += tokens
        ctx.last_text = text
        ctx.last_reasoning_content = reasoning

        tool_calls = ToolRegistry.parse_prompt_tool_calls(text)
        if not tool_calls:
            await self._handle_silent_ai(ctx)
            if not ctx.last_text.strip() and ctx.round > 0:
                return AgentState.DONE
            return AgentState.DONE

        ctx.messages.append({"role": "assistant", "content": text})

        early_exit = await self._execute_tool_calls(ctx, tool_calls)
        if early_exit:
            return early_exit

        logger.info("Agent prompt round %d: %d tool calls", ctx.round + 1, len(tool_calls))
        ctx.round += 1

        if ctx.round >= ctx.max_rounds:
            return AgentState.FINALIZE

        return AgentState.COMPRESS

    async def _handle_compress(self, ctx: AgentContext) -> AgentState:
        """COMPRESS: Check if messages need truncation before next round."""
        # Estimate total message size to prevent unbounded growth
        total_chars = sum(len(str(m.get("content", ""))) for m in ctx.messages)
        max_chars = self._config.agent.max_tool_result_chars * self._config.agent.max_tool_rounds

        if total_chars > max_chars:
            logger.warning(
                "Agent context too large (%d chars), forcing finalization",
                total_chars,
            )
            return AgentState.FINALIZE

        return AgentState.EXECUTE

    async def _handle_finalize(self, ctx: AgentContext) -> AgentState:
        """FINALIZE: Force a final text-only response."""
        text, tokens, _, reasoning = await self._llm.chat(ctx.messages)
        ctx.total_tokens += tokens
        ctx.last_text = text
        ctx.last_reasoning_content = reasoning
        return AgentState.DONE

    async def _execute_tool(
        self,
        call_id: str,
        name: str,
        arguments: str | dict,
    ) -> ToolResult:
        """Execute a single tool call (delegates to registry)."""
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

        timeout = self._config.agent.tool_timeout_seconds
        max_chars = self._config.agent.max_tool_result_chars

        try:
            output = await asyncio.wait_for(
                tool.execute(**arguments), timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Tool %s timed out after %.0fs", name, timeout)
            await get_event_log().push(
                "warning", "agent", "agent.tool_timeout",
                f"Tool {name} timed out after {timeout}s",
                {"tool": name, "arguments": arguments},
            )
            return ToolResult(
                tool_call_id=call_id, tool_name=name, output="",
                success=False, error=f"Tool timed out after {timeout}s",
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

        original_len = len(output)
        if original_len > max_chars:
            output = output[:max_chars] + (
                f"\n\n[... output truncated, original length: {original_len} chars ...]"
            )

        await get_event_log().push(
            "info", "agent", "agent.tool_call",
            f"Tool: {name}({json.dumps(arguments, ensure_ascii=False)}) → {output[:100]}",
            {"tool": name, "arguments": arguments, "result": output[:200]},
        )
        return ToolResult(
            tool_call_id=call_id, tool_name=name, output=output, success=True,
        )
