"""Agent tools package — register built-in tools."""

from .registry import get_registry, ToolRegistry
from .time_tool import GetCurrentTimeTool
from .math_tool import CalculateTool
from .base import Tool, ToolResult, ToolExecutionError

__all__ = [
    "get_registry",
    "ToolRegistry",
    "Tool",
    "ToolResult",
    "ToolExecutionError",
    "init_default_tools",
]


def init_default_tools() -> None:
    """Register all built-in tools into the global registry."""
    registry = get_registry()
    registry.register(GetCurrentTimeTool())
    registry.register(CalculateTool())
