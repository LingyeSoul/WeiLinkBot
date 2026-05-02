"""Base class for Agent tools."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result returned by a tool execution."""
    tool_call_id: str
    tool_name: str
    output: str
    success: bool = True
    error: str | None = None

    def to_tool_message(self) -> dict[str, Any]:
        """Convert to an OpenAI tool message for the conversation context."""
        content = self.output if self.success else f"Error: {self.error}"
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": content,
        }


class Tool(ABC):
    """Abstract base class for all Agent tools.

    Subclasses must define:
        name: Unique tool identifier (snake_case)
        description: Human-readable description for the LLM
        parameters: JSON Schema dict describing the tool's parameters
    """

    name: str
    description: str
    parameters: dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool and return a text result.

        Args:
            **kwargs: Parsed arguments matching the parameters schema.

        Returns:
            A text result to be sent back to the LLM.

        Raises:
            ToolExecutionError: If execution fails.
        """

    def to_openai_tool(self) -> dict[str, Any]:
        """Serialize to OpenAI function-calling tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_prompt_description(self) -> str:
        """Serialize to a text description for prompt-based tool calling fallback."""
        params = json.dumps(self.parameters, ensure_ascii=False, indent=2)
        return f"### {self.name}\n{self.description}\nParameters:\n{params}"


class ToolExecutionError(Exception):
    """Raised when a tool execution fails."""
