"""MCP server configuration CRUD service."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MCPServer

logger = logging.getLogger(__name__)


class MCPServerService:
    """Async CRUD for mcp_servers table."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def list_all(self) -> list[MCPServer]:
        result = await self._db.execute(select(MCPServer).order_by(MCPServer.id))
        return list(result.scalars().all())

    async def get(self, server_id: int) -> MCPServer | None:
        return await self._db.get(MCPServer, server_id)

    async def create(self, data: dict[str, Any]) -> MCPServer:
        server = MCPServer(
            name=data["name"],
            transport=data["transport"],
            command=data.get("command"),
            args=json.dumps(data.get("args", [])),
            env=json.dumps(data.get("env", {})),
            url=data.get("url"),
            enabled=data.get("enabled", True),
        )
        self._db.add(server)
        await self._db.commit()
        await self._db.refresh(server)
        logger.info("Created MCP server: %s (%s)", server.name, server.transport)
        return server

    async def update(self, server_id: int, data: dict[str, Any]) -> MCPServer | None:
        server = await self.get(server_id)
        if not server:
            return None
        for field in ("name", "transport", "command", "url", "enabled"):
            if field in data and data[field] is not None:
                setattr(server, field, data[field])
        if "args" in data and data["args"] is not None:
            server.args = json.dumps(data["args"])
        if "env" in data and data["env"] is not None:
            server.env = json.dumps(data["env"])
        await self._db.commit()
        await self._db.refresh(server)
        logger.info("Updated MCP server: id=%d", server_id)
        return server

    async def delete(self, server_id: int) -> bool:
        server = await self.get(server_id)
        if not server:
            return False
        await self._db.delete(server)
        await self._db.commit()
        logger.info("Deleted MCP server: id=%d", server_id)
        return True
