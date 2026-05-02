"""Agent configuration API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..config import get_config, save_config
from ..schemas import AgentConfigResponse, AgentConfigUpdate
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
