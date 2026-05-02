"""MCP tool adapter — wraps an MCP server tool into the Tool base class."""

from __future__ import annotations

from typing import Any

from .base import Tool


class MCPToolAdapter(Tool):
    """Adapts an MCP server tool to the WeiLinkBot Tool interface."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        parameters: dict[str, Any],
        executor: Any,
    ) -> None:
        self.name = f"{server_name}__{tool_name}"
        self.description = description
        self.parameters = parameters
        self._executor = executor
        self._server_name = server_name
        self._tool_name = tool_name

    async def execute(self, **kwargs) -> str:
        return await self._executor.execute_tool(
            self._server_name, self._tool_name, kwargs
        )
