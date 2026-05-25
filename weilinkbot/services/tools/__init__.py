"""Agent tools package — register built-in tools."""

import logging

from .registry import get_registry, ToolRegistry
from .time_tool import GetCurrentTimeTool
from .math_tool import CalculateTool
from .base import Tool, ToolResult, ToolExecutionError

# Browser tools are optional — gracefully absent when Obscura is unavailable.
try:
    from .browser_tool import BrowserFetchTool, BrowserEvalTool, is_available as _browser_available
except Exception:
    BrowserFetchTool = None  # type: ignore[assignment,misc]
    BrowserEvalTool = None   # type: ignore[assignment,misc]
    _browser_available = None

try:
    from .browser_use_tool import BrowserUseTool, is_available as _browser_use_available
except Exception:
    BrowserUseTool = None  # type: ignore[assignment,misc]
    _browser_use_available = None

try:
    from .browser_download_tool import BrowserDownloadTool
except Exception:
    BrowserDownloadTool = None  # type: ignore[assignment,misc]

__all__ = [
    "get_registry",
    "ToolRegistry",
    "Tool",
    "ToolResult",
    "ToolExecutionError",
    "init_default_tools",
]


def init_default_tools() -> None:
    """Register all built-in tools into the global registry.

    Browser tools are registered only when the Obscura binary is available
    (auto-downloaded on first import).  If the download or binary is missing
    they are silently skipped.
    """
    registry = get_registry()
    registry.register(GetCurrentTimeTool())
    registry.register(CalculateTool())

    # Obscura browser tools — skip entirely if unavailable
    _log = logging.getLogger(__name__)
    if BrowserFetchTool is not None and _browser_available is not None:
        try:
            if _browser_available():
                registry.register(BrowserFetchTool())
                registry.register(BrowserEvalTool())
            else:
                _log.info("Browser tools disabled: Obscura binary not available")
        except Exception as exc:
            _log.warning("Browser tools disabled: %s", exc)

    # browser_use — requires websockets + Obscura binary
    if BrowserUseTool is not None and _browser_use_available is not None:
        try:
            if _browser_use_available():
                registry.register(BrowserUseTool())
            else:
                _log.info("browser_use disabled: websockets not installed")
        except Exception as exc:
            _log.warning("browser_use disabled: %s", exc)


def init_workspace_tools(workspace_service) -> None:
    """Register workspace tools into the global registry."""
    from .workspace_read_tool import WorkspaceReadTool
    from .workspace_list_tool import WorkspaceListTool
    from .workspace_grep_tool import WorkspaceGrepTool
    from .workspace_write_tool import WorkspaceWriteTool
    from .workspace_edit_tool import WorkspaceEditTool

    registry = get_registry()
    registry.register(WorkspaceReadTool(workspace_service))
    registry.register(WorkspaceListTool(workspace_service))
    registry.register(WorkspaceGrepTool(workspace_service))
    registry.register(WorkspaceWriteTool(workspace_service))
    registry.register(WorkspaceEditTool(workspace_service))

    # browser_download — requires Obscura + websockets + workspace
    _log = logging.getLogger(__name__)
    if BrowserDownloadTool is not None and _browser_use_available is not None:
        try:
            if _browser_use_available():
                registry.register(BrowserDownloadTool(workspace_service))
            else:
                _log.info("browser_download disabled: websockets not installed")
        except Exception as exc:
            _log.warning("browser_download disabled: %s", exc)

    # send_file — always available when workspace is enabled
    from .send_file_tool import SendFileTool
    registry.register(SendFileTool(workspace_service))


def init_sticker_tool(session_factory) -> None:
    """Register sticker tools (search, send, list) into the global registry."""
    from .search_sticker_tool import SearchStickerTool
    from .send_sticker_tool import SendStickerTool
    from .list_sticker_packs_tool import ListStickerPacksTool
    registry = get_registry()
    registry.register(SearchStickerTool(session_factory))
    registry.register(SendStickerTool(session_factory))
    registry.register(ListStickerPacksTool(session_factory))
