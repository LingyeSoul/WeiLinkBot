"""Memory management API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..config import get_config, save_config
from ..database import get_session_factory
from ..models import Conversation, UserConfig
from ..schemas import MemoryConfigUpdate, MemoryConfigUpdateResponse, MemoryConfigTestResponse
from .deps import get_memory_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_memory():
    mem = get_memory_service()
    if mem is None or not mem.available:
        raise HTTPException(
            status_code=503,
            detail="Memory module is not configured or available"
        )
    return mem


@router.get("/status")
async def memory_status():
    mem = get_memory_service()
    available = mem is not None and mem.available
    config = get_config()
    return {
        "available": available,
        "embedding_model": config.memory.embedding.model,
        "embedding_provider": config.memory.embedding.provider,
        "embedding_base_url": config.memory.embedding.base_url,
        "embedding_api_key_set": bool(config.memory.embedding.api_key),
        "llm_model": config.memory.llm.model or config.llm.model,
        "llm_api_key_set": bool(config.memory.llm.api_key or config.llm.api_key),
        "top_k": config.memory.top_k,
    }


@router.get("/config")
async def get_memory_config():
    """Get memory/embedding configuration."""
    config = get_config()
    mem_cfg = config.memory
    return {
        "enabled": mem_cfg.enabled,
        "embedding": {
            "provider": mem_cfg.embedding.provider,
            "base_url": mem_cfg.embedding.base_url,
            "model": mem_cfg.embedding.model,
            "api_key_set": bool(mem_cfg.embedding.api_key),
        },
        "llm": {
            "provider": mem_cfg.llm.provider,
            "base_url": mem_cfg.llm.base_url,
            "model": mem_cfg.llm.model,
            "api_key_set": bool(mem_cfg.llm.api_key),
        },
        "top_k": mem_cfg.top_k,
        "db_path": mem_cfg.db_path,
    }


@router.put("/config", response_model=MemoryConfigUpdateResponse)
async def update_memory_config(data: MemoryConfigUpdate):
    """Update memory/embedding configuration. Reinitializes the memory service."""
    mem = get_memory_service()
    if mem is None:
        raise HTTPException(status_code=503, detail="Memory service not initialized")

    kwargs = {}
    if data.enabled is not None:
        kwargs["memory_enabled"] = data.enabled
    if data.embedding_provider is not None:
        kwargs["embedding_provider"] = data.embedding_provider
    if data.embedding_api_key is not None:
        kwargs["embedding_api_key"] = data.embedding_api_key
    if data.embedding_base_url is not None:
        kwargs["embedding_base_url"] = data.embedding_base_url
    if data.embedding_model is not None:
        kwargs["embedding_model"] = data.embedding_model
    if data.llm_provider is not None:
        kwargs["llm_provider"] = data.llm_provider
    if data.llm_api_key is not None:
        kwargs["llm_api_key"] = data.llm_api_key
    if data.llm_base_url is not None:
        kwargs["llm_base_url"] = data.llm_base_url
    if data.llm_model is not None:
        kwargs["llm_model"] = data.llm_model
    if data.top_k is not None:
        kwargs["top_k"] = data.top_k

    result = mem.update_config(**kwargs)
    save_config()

    config = get_config()
    return MemoryConfigUpdateResponse(
        available=mem.available,
        embedding_model=config.memory.embedding.model,
        embedding_provider=config.memory.embedding.provider,
        embedding_base_url=config.memory.embedding.base_url,
        embedding_api_key_set=bool(config.memory.embedding.api_key),
        llm_model=config.memory.llm.model or config.llm.model,
        llm_api_key_set=bool(config.memory.llm.api_key or config.llm.api_key),
        top_k=config.memory.top_k,
        init_error=result.get("init_error") if result else mem.init_error,
    )


@router.post("/config/test", response_model=MemoryConfigTestResponse)
async def test_connection(data: MemoryConfigUpdate | None = None):
    mem = get_memory_service()
    if mem is None:
        raise HTTPException(status_code=503, detail="Memory service not initialized")

    if data is None:
        data = MemoryConfigUpdate()

    result = mem.test_connection(
        provider=data.embedding_provider,
        model=data.embedding_model,
        base_url=data.embedding_base_url,
        api_key=data.embedding_api_key,
    )
    return MemoryConfigTestResponse(**result)


@router.get("/users")
async def memory_users():
    """List users that have memories, with counts."""
    mem = _require_memory()
    session_factory = get_session_factory()

    # Get all user_ids from conversations
    async with session_factory() as db:
        result = await db.execute(select(Conversation.user_id))
        user_ids = [row[0] for row in result.all()]

    # Batch-fetch all UserConfig for nicknames
    nickname_map: dict[str, str | None] = {}
    async with session_factory() as db:
        result = await db.execute(select(UserConfig))
        for cfg in result.scalars().all():
            nickname_map[cfg.user_id] = cfg.nickname

    users = []
    for uid in user_ids:
        memories = await mem.get_all(uid)
        count = len(memories) if isinstance(memories, list) else 0
        if count > 0:
            users.append({
                "user_id": uid,
                "nickname": nickname_map.get(uid),
                "count": count,
            })

    users.sort(key=lambda x: x["count"], reverse=True)
    return {"users": users, "total_users": len(users)}


@router.get("/{user_id}")
async def get_user_memories(user_id: str):
    """Get all memories for a user."""
    mem = _require_memory()
    memories = await mem.get_all(user_id)
    return {"user_id": user_id, "memories": memories}


@router.get("/{user_id}/search")
async def search_user_memories(
    user_id: str,
    query: str = Query(..., min_length=1),
):
    """Semantic search within a user's memories."""
    mem = _require_memory()
    results = await mem.search(user_id, query)
    return {"user_id": user_id, "query": query, "results": results}


@router.delete("/user/{user_id}")
async def delete_user_memories(user_id: str):
    """Clear all memories for a user."""
    mem = _require_memory()
    success = await mem.delete_all(user_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete memories")
    return {"success": True}


@router.put("/{memory_id}")
async def update_memory(memory_id: str, body: dict):
    """Update a memory's text."""
    mem = _require_memory()
    new_text = body.get("text", "").strip()
    if not new_text:
        raise HTTPException(status_code=400, detail="'text' is required")
    success = await mem.update(memory_id, new_text)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update memory")
    return {"success": True}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str):
    """Delete a single memory."""
    mem = _require_memory()
    success = await mem.delete(memory_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete memory")
    return {"success": True}
