"""MCP client service — connects to external MCP servers and manages tools, resources, prompts."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import AsyncExitStack, suppress
from typing import Any

from .tools.registry import get_registry
from .tools.mcp_tool import MCPToolAdapter, MCPResourceAdapter, MCPPromptAdapter

logger = logging.getLogger(__name__)

# Transient connection errors that warrant a retry
_TRANSIENT_EXC_NAMES: frozenset[str] = frozenset((
    "ClosedResourceError", "BrokenResourceError", "EndOfStream",
    "BrokenPipeError", "ConnectionResetError", "ConnectionRefusedError",
    "ConnectionAbortedError", "ConnectionError",
))

_SANITIZE_RE = re.compile(r"_+")


def _sanitize_name(name: str) -> str:
    """Sanitize tool name for model API compatibility."""
    return _SANITIZE_RE.sub("_", re.sub(r"[^a-zA-Z0-9_-]", "_", name))


def _is_transient(exc: BaseException) -> bool:
    return type(exc).__name__ in _TRANSIENT_EXC_NAMES


async def _probe_http_url(url: str, timeout: float = 3.0) -> bool:
    """Quick TCP probe to check if an HTTP MCP server is reachable."""
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


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
        """Connect to an MCP server and register its tools, resources, prompts."""
        name = config["name"]
        transport = config["transport"]
        tool_timeout = config.get("tool_timeout", 30)
        enabled_tools = set(config.get("enabled_tools", ["*"]))
        allow_all = "*" in enabled_tools

        await self.disconnect_server(server_id)

        conn = MCPServerConnection(server_id, name)
        self._connections[server_id] = conn

        exit_stack = AsyncExitStack()
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

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
                if not await _probe_http_url(url):
                    conn.status = "error"
                    logger.warning("MCP server '%s': %s unreachable", name, url)
                    return conn
                from mcp.client.sse import sse_client
                read_stream, write_stream = await exit_stack.enter_async_context(
                    sse_client(url)
                )
            elif transport == "streamableHttp":
                url = config.get("url", "")
                if not await _probe_http_url(url):
                    conn.status = "error"
                    logger.warning("MCP server '%s': %s unreachable", name, url)
                    return conn
                from mcp.client.streamable_http import streamable_http_client
                read_stream, write_stream, _ = await exit_stack.enter_async_context(
                    streamable_http_client(url)
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

            registry = get_registry()
            registered_count = 0

            # ── Discover and register tools ──
            tools_response = await session.list_tools()
            for tool_def in tools_response.tools:
                wrapped_name = _sanitize_name(f"mcp_{name}_{tool_def.name}")
                # Filter by enabled_tools
                if not allow_all and tool_def.name not in enabled_tools and wrapped_name not in enabled_tools:
                    continue
                adapter = MCPToolAdapter(
                    server_name=name,
                    tool_name=tool_def.name,
                    description=tool_def.description or "",
                    parameters=getattr(
                        tool_def, "inputSchema",
                        {"type": "object", "properties": {}},
                    ),
                    executor=self,
                    tool_timeout=tool_timeout,
                )
                registry.register(adapter)
                conn._connected_tools.append(adapter.name)
                registered_count += 1

            # ── Discover and register resources ──
            try:
                resources_result = await session.list_resources()
                for resource in resources_result.resources:
                    adapter = MCPResourceAdapter(
                        server_name=name,
                        resource=resource,
                        executor=self,
                        tool_timeout=tool_timeout,
                    )
                    registry.register(adapter)
                    conn._connected_tools.append(adapter.name)
                    registered_count += 1
            except Exception as e:
                logger.debug("MCP server '%s': resources not supported: %s", name, e)

            # ── Discover and register prompts ──
            try:
                prompts_result = await session.list_prompts()
                for prompt in prompts_result.prompts:
                    adapter = MCPPromptAdapter(
                        server_name=name,
                        prompt=prompt,
                        executor=self,
                        tool_timeout=tool_timeout,
                    )
                    registry.register(adapter)
                    conn._connected_tools.append(adapter.name)
                    registered_count += 1
            except Exception as e:
                logger.debug("MCP server '%s': prompts not supported: %s", name, e)

            logger.info(
                "Connected to MCP server '%s' (%s) — %d capabilities",
                name, transport, registered_count,
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

    async def read_resource(self, server_name: str, uri: str) -> str:
        """Read a resource from the MCP server."""
        conn = None
        for c in self._connections.values():
            if c.server_name == server_name and c.connected:
                conn = c
                break
        if not conn or not conn._session:
            raise RuntimeError(f"MCP server '{server_name}' is not connected")

        result = await conn._session.read_resource(uri)
        parts = []
        for block in result.contents:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(f"[Binary: {len(getattr(block, 'blob', ''))} bytes]")
        return "\n".join(parts) if parts else ""

    async def get_prompt(
        self, server_name: str, prompt_name: str, arguments: dict | None = None
    ) -> str:
        """Get a prompt from the MCP server."""
        conn = None
        for c in self._connections.values():
            if c.server_name == server_name and c.connected:
                conn = c
                break
        if not conn or not conn._session:
            raise RuntimeError(f"MCP server '{server_name}' is not connected")

        result = await conn._session.get_prompt(prompt_name, arguments=arguments or {})
        parts = []
        for message in result.messages:
            content = message.content
            if hasattr(content, "text"):
                parts.append(content.text)
            elif isinstance(content, list):
                for block in content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
                    else:
                        parts.append(str(block))
            else:
                parts.append(str(content))
        return "\n".join(parts) if parts else ""

    async def connect_all_enabled(self, servers: list[dict[str, Any]]) -> None:
        """Connect to all enabled MCP servers at startup."""
        for srv in servers:
            if srv.get("enabled"):
                await self.connect_server(srv["id"], srv)
