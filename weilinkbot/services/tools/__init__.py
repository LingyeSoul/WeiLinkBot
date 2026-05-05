"""Agent tools package — register built-in tools."""

from .registry import get_registry, ToolRegistry
from .time_tool import GetCurrentTimeTool
from .math_tool import CalculateTool
from .web_search_tool import WebSearchTool
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
    registry.register(WebSearchTool())


def init_workspace_tools(workspace_service) -> None:
    """Register workspace tools into the global registry."""
    from .workspace_read_tool import WorkspaceReadTool
    from .workspace_list_tool import WorkspaceListTool
    from .workspace_grep_tool import WorkspaceGrepTool
    from .workspace_write_tool import WorkspaceWriteTool

    registry = get_registry()
    registry.register(WorkspaceReadTool(workspace_service))
    registry.register(WorkspaceListTool(workspace_service))
    registry.register(WorkspaceGrepTool(workspace_service))
    registry.register(WorkspaceWriteTool(workspace_service))


def init_sticker_tool(session_factory) -> None:
    """Register sticker tools (search, send, list) into the global registry."""
    from .search_sticker_tool import SearchStickerTool
    from .send_sticker_tool import SendStickerTool
    from .list_sticker_packs_tool import ListStickerPacksTool
    registry = get_registry()
    registry.register(SearchStickerTool(session_factory))
    registry.register(SendStickerTool(session_factory))
    registry.register(ListStickerPacksTool(session_factory))
