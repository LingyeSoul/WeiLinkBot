"""MCP client service — connects to external MCP servers and manages tools."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from .tools.registry import get_registry
from .tools.mcp_tool import MCPToolAdapter

logger = logging.getLogger(__name__)


class MCPServerConnection:
    """Holds an active MCP client session."""

    def __init__(self, server_id: int, server_name: str) -> None:
        self.server_id = server_id
        self.server_name = server_name
        self.status: str = "disconnected"
        self._exit_stack: AsyncExitStack | None = None
        self._session: Any = None
        self._connected_tools: list[str] = []

    @property
    def connected(self) -> bool:
        return self.status == "connected"


class MCPService:
    """Manages MCP server connections and tool registration."""

    def __init__(self) -> None:
        self._connections: dict[int, MCPServerConnection] = {}

    def get_status(self, server_id: int) -> str:
        conn = self._connections.get(server_id)
        return conn.status if conn else "disconnected"

    def get_all_statuses(self) -> dict[int, str]:
        return {sid: conn.status for sid, conn in self._connections.items()}

    async def connect_server(
        self, server_id: int, config: dict[str, Any]
    ) -> MCPServerConnection:
        """Connect to an MCP server and register its tools."""
        name = config["name"]
        transport = config["transport"]

        await self.disconnect_server(server_id)

        conn = MCPServerConnection(server_id, name)
        self._connections[server_id] = conn

        exit_stack = AsyncExitStack()
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.sse import sse_client

            if transport == "stdio":
                cmd = config.get("command", "")
                args = config.get("args", [])
                env = config.get("env", {})
                params = StdioServerParameters(
                    command=cmd, args=args, env=env or None
                )
                read_stream, write_stream = await exit_stack.enter_async_context(
                    stdio_client(params)
                )
            elif transport == "sse":
                url = config.get("url", "")
                read_stream, write_stream = await exit_stack.enter_async_context(
                    sse_client(url)
                )
            else:
                conn.status = "error"
                logger.error("Unknown MCP transport: %s", transport)
                return conn

            session = await exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()

            conn._exit_stack = exit_stack
            conn._session = session
            conn.status = "connected"

            # Discover and register tools
            tools_response = await session.list_tools()
            registry = get_registry()
            for tool_def in tools_response.tools:
                adapter = MCPToolAdapter(
                    server_name=name,
                    tool_name=tool_def.name,
                    description=tool_def.description or "",
                    parameters=getattr(
                        tool_def,
                        "inputSchema",
                        {"type": "object", "properties": {}},
                    ),
                    executor=self,
                )
                registry.register(adapter)
                conn._connected_tools.append(adapter.name)
                logger.info("Registered MCP tool: %s", adapter.name)

            logger.info(
                "Connected to MCP server '%s' (%s) — %d tools",
                name,
                transport,
                len(conn._connected_tools),
            )
            return conn

        except Exception as e:
            conn.status = "error"
            logger.error("Failed to connect to MCP server '%s': %s", name, e)
            try:
                await exit_stack.aclose()
            except Exception:
                pass
            return conn

    async def disconnect_server(self, server_id: int) -> None:
        conn = self._connections.pop(server_id, None)
        if not conn:
            return
        registry = get_registry()
        for tool_name in conn._connected_tools:
            registry.unregister(tool_name)
        conn._connected_tools.clear()
        if conn._exit_stack:
            try:
                await conn._exit_stack.aclose()
            except Exception:
                pass
        conn.status = "disconnected"
        logger.info("Disconnected MCP server: %s", conn.server_name)

    async def execute_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> str:
        """Execute a tool on the MCP server that owns it."""
        conn = None
        for c in self._connections.values():
            if c.server_name == server_name and c.connected:
                conn = c
                break
        if not conn or not conn._session:
            raise RuntimeError(f"MCP server '{server_name}' is not connected")

        result = await conn._session.call_tool(tool_name, arguments)
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else ""

    async def connect_all_enabled(self, servers: list[dict[str, Any]]) -> None:
        """Connect to all enabled MCP servers at startup."""
        for srv in servers:
            if srv.get("enabled"):
                await self.connect_server(srv["id"], srv)
