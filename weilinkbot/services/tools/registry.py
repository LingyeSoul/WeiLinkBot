"""Tool registry — manages available tools for the Agent system."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .base import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Central registry of available Agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning("Overwriting existing tool: %s", tool.name)
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_tools(self, names: list[str] | None = None) -> list[Tool]:
        if names is None:
            return list(self._tools.values())
        return [self._tools[n] for n in names if n in self._tools]

    def get_openai_tools(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        return [t.to_openai_tool() for t in self.get_tools(names)]

    def get_prompt_description(self, names: list[str] | None = None) -> str:
        tools = self.get_tools(names)
        if not tools:
            return ""
        return "\n\n".join(t.to_prompt_description() for t in tools)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    @staticmethod
    def parse_prompt_tool_calls(text: str) -> list[dict[str, Any]]:
        """Parse tool calls from LLM text (prompt-based fallback).

        Looks for ```tool_call``` blocks containing JSON with:
        {"name": "...", "arguments": {...}}
        """
        results: list[dict[str, Any]] = []
        pattern = r"```tool_call\s*\n(.*?)\n```"
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                name = data.get("name", "")
                arguments = data.get("arguments", {})
                if name:
                    results.append({
                        "id": f"call_{hash(match.group(0)) & 0xFFFFFFFF:08x}",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    })
            except (json.JSONDecodeError, KeyError):
                continue
        return results


# Module-level singleton
_global_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    return _global_registry
