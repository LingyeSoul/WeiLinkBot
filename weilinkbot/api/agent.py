"""Agent configuration API endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..config import get_config, save_config
from ..schemas import (
    AgentConfigResponse, AgentConfigUpdate,
    SkillInfo, SkillCreate, SkillsResponse, SkillsUpdate,
    MCPServerCreate, MCPServerUpdate, MCPServerResponse, MCPServersResponse,
)
from ..services.tools.registry import get_registry

router = APIRouter()


@router.get("/config", response_model=AgentConfigResponse)
async def get_agent_config():
    """Get current Agent configuration."""
    config = get_config()
    registry = get_registry()
    return AgentConfigResponse(
        max_tool_rounds=config.agent.max_tool_rounds,
        enabled_tools=config.agent.enabled_tools,
        available_tools=registry.list_names(),
    )


@router.put("/config", response_model=AgentConfigResponse)
async def update_agent_config(data: AgentConfigUpdate):
    """Update Agent configuration."""
    config = get_config()

    if data.max_tool_rounds is not None:
        config.agent.max_tool_rounds = data.max_tool_rounds
    if data.enabled_tools is not None:
        config.agent.enabled_tools = data.enabled_tools

    save_config()

    registry = get_registry()
    return AgentConfigResponse(
        max_tool_rounds=config.agent.max_tool_rounds,
        enabled_tools=config.agent.enabled_tools,
        available_tools=registry.list_names(),
    )


# ── Skills ─────────────────────────────────────────────────────

@router.get("/skills", response_model=SkillsResponse)
async def list_skills():
    """List all skills with enabled state."""
    from .deps import get_skill_service
    skill_service = get_skill_service()
    config = get_config()
    enabled_set = set(config.agent.enabled_skills)
    all_skills = skill_service.scan()
    return SkillsResponse(
        skills=[
            SkillInfo(name=s.name, description=s.description, enabled=s.name in enabled_set)
            for s in all_skills
        ]
    )


@router.put("/skills")
async def update_enabled_skills(data: SkillsUpdate):
    """Update the list of enabled skills."""
    config = get_config()
    config.agent.enabled_skills = data.enabled_skills
    save_config()
    return {"enabled_skills": config.agent.enabled_skills}


@router.post("/skills")
async def create_skill(data: SkillCreate):
    """Create or update a skill file."""
    from .deps import get_skill_service
    get_skill_service().save(data.name, data.content, data.description)
    return {"name": data.name}


@router.delete("/skills/{name}")
async def delete_skill(name: str):
    """Delete a skill file."""
    from .deps import get_skill_service
    deleted = get_skill_service().delete(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    config = get_config()
    if name in config.agent.enabled_skills:
        config.agent.enabled_skills.remove(name)
        save_config()
    return {"deleted": name}


# ── MCP Servers ────────────────────────────────────────────────

@router.get("/mcp", response_model=MCPServersResponse)
async def list_mcp_servers():
    """List all MCP server configs with connection status."""
    from .deps import get_mcp_service
    from ..database import get_session_factory
    from ..services.mcp_server_service import MCPServerService

    mcp_service = get_mcp_service()
    async with get_session_factory()() as db:
        servers = await MCPServerService(db).list_all()
    items = []
    for s in servers:
        status = mcp_service.get_status(s.id) if mcp_service else "disconnected"
        args = json.loads(s.args) if s.args else []
        env = json.loads(s.env) if s.env else {}
        items.append(MCPServerResponse(
            id=s.id, name=s.name, transport=s.transport,
            command=s.command, args=args, env=env, url=s.url,
            enabled=s.enabled, status=status,
        ))
    return MCPServersResponse(servers=items)


@router.post("/mcp", response_model=MCPServerResponse)
async def create_mcp_server(data: MCPServerCreate):
    """Create an MCP server configuration."""
    from ..database import get_session_factory
    from ..services.mcp_server_service import MCPServerService

    async with get_session_factory()() as db:
        server = await MCPServerService(db).create(data.model_dump())
    return MCPServerResponse(
        id=server.id, name=server.name, transport=server.transport,
        command=server.command, args=data.args, env=data.env,
        url=server.url, enabled=server.enabled, status="disconnected",
    )


@router.put("/mcp/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(server_id: int, data: MCPServerUpdate):
    """Update an MCP server configuration."""
    from ..database import get_session_factory
    from ..services.mcp_server_service import MCPServerService

    async with get_session_factory()() as db:
        server = await MCPServerService(db).update(
            server_id, data.model_dump(exclude_unset=True)
        )
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    args = json.loads(server.args) if server.args else []
    env = json.loads(server.env) if server.env else {}
    from .deps import get_mcp_service as _gmcp
    _mcp_svc = _gmcp()
    status = _mcp_svc.get_status(server_id) if _mcp_svc else "disconnected"
    return MCPServerResponse(
        id=server.id, name=server.name, transport=server.transport,
        command=server.command, args=args, env=env, url=server.url,
        enabled=server.enabled, status=status,
    )


@router.delete("/mcp/{server_id}")
async def delete_mcp_server(server_id: int):
    """Delete an MCP server config and disconnect if connected."""
    from .deps import get_mcp_service
    from ..database import get_session_factory
    from ..services.mcp_server_service import MCPServerService

    mcp_service = get_mcp_service()
    if mcp_service:
        await mcp_service.disconnect_server(server_id)
    async with get_session_factory()() as db:
        deleted = await MCPServerService(db).delete(server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"deleted": server_id}


@router.post("/mcp/{server_id}/reconnect")
async def reconnect_mcp_server(server_id: int):
    """Reconnect to an MCP server."""
    from .deps import get_mcp_service
    from ..database import get_session_factory
    from ..services.mcp_server_service import MCPServerService

    mcp_service = get_mcp_service()
    if not mcp_service:
        raise HTTPException(status_code=503, detail="MCP service not available")

    async with get_session_factory()() as db:
        server = await MCPServerService(db).get(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    config = {
        "id": server.id, "name": server.name, "transport": server.transport,
        "command": server.command,
        "args": json.loads(server.args) if server.args else [],
        "env": json.loads(server.env) if server.env else {},
        "url": server.url,
        "enabled": server.enabled,
    }
    conn = await mcp_service.connect_server(server.id, config)
    return {"id": server_id, "status": conn.status}
