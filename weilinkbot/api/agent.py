"""Agent configuration API endpoints."""

from __future__ import annotations

import json
import zipfile
import io
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File

logger = logging.getLogger(__name__)

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


@router.post("/skills/import")
async def import_skills(file: UploadFile = File(...)):
    """Import skills from a .md file or .zip archive containing .md files."""
    from .deps import get_skill_service

    skill_service = get_skill_service()
    filename = (file.filename or "").lower()
    raw = await file.read()

    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    imported: list[str] = []

    if filename.endswith(".md"):
        # Single markdown file
        name = filename.rsplit("/", 1)[-1]
        if name.endswith(".md"):
            name = name[:-3]
        content = raw.decode("utf-8", errors="replace")
        skill_service.save(name, content)
        imported.append(name)

    elif filename.endswith(".zip"):
        # Zip archive — import all .md files inside
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for entry in zf.namelist():
                    if entry.endswith("/") or not entry.lower().endswith(".md"):
                        continue
                    entry_name = entry.rsplit("/", 1)[-1]
                    if not entry_name.lower().endswith(".md"):
                        continue
                    skill_name = entry_name[:-3]
                    try:
                        content = zf.read(entry).decode("utf-8", errors="replace")
                    except Exception:
                        continue
                    try:
                        skill_service.save(skill_name, content)
                        imported.append(skill_name)
                    except ValueError:
                        logger.warning("Skipping invalid skill name from zip: %s", entry)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format. Use .md or .zip")

    return {"imported": imported, "count": len(imported)}


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


# ── Workspace ──────────────────────────────────────────────────

@router.get("/workspace/config")
async def get_workspace_config():
    """Get workspace configuration."""
    cfg = get_config()
    ws = cfg.workspace
    return {
        "enabled": ws.enabled,
        "root": ws.root,
        "blocked_extensions": list(ws.blocked_extensions),
        "read_max_size": ws.read_max_size,
        "write_max_size": ws.write_max_size,
        "list_max_entries": ws.list_max_entries,
        "grep_max_results": ws.grep_max_results,
        "enabled_workspace_tools": list(cfg.agent.enabled_workspace_tools),
    }


@router.put("/workspace/config")
async def update_workspace_config(body: dict):
    """Update workspace configuration."""
    cfg = get_config()
    ws = cfg.workspace
    for field in ("enabled", "root", "read_max_size", "write_max_size", "list_max_entries", "grep_max_results"):
        if field in body:
            setattr(ws, field, body[field])
    if "blocked_extensions" in body:
        ws.blocked_extensions = body["blocked_extensions"]
    if "enabled_workspace_tools" in body:
        cfg.agent.enabled_workspace_tools = body["enabled_workspace_tools"]
    save_config()
    return {"ok": True}


@router.get("/workspace/files")
async def list_workspace_files(path: str = "", pattern: str = "*"):
    """List files in the workspace."""
    from .deps import get_workspace_service
    ws = get_workspace_service()
    if not ws:
        raise HTTPException(503, "Workspace not available")
    try:
        entries = ws.list_files(path, pattern)
        return [{"name": e.name, "path": e.path, "is_dir": e.is_dir, "size": e.size} for e in entries]
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/workspace/read")
async def read_workspace_file(path: str, offset: int = 0, limit: int | None = None):
    """Read a file from the workspace."""
    from .deps import get_workspace_service
    ws = get_workspace_service()
    if not ws:
        raise HTTPException(503, "Workspace not available")
    try:
        content = ws.read_file(path, offset=offset, limit=limit)
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/workspace/upload")
async def upload_workspace_file(file: UploadFile = File(...), path: str = ""):
    """Upload a file to the workspace."""
    from .deps import get_workspace_service
    ws = get_workspace_service()
    if not ws:
        raise HTTPException(503, "Workspace not available")

    target = f"{path}/{file.filename}" if path else file.filename
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    try:
        written = ws.write_file(target, text)
        return {"path": target, "bytes": written}
    except Exception as e:
        raise HTTPException(400, str(e))
