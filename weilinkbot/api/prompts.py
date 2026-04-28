"""System prompt CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import SystemPrompt
from ..schemas import (
    SystemPromptCreate,
    SystemPromptUpdate,
    SystemPromptResponse,
    MessageAction,
)

router = APIRouter()


@router.get("", response_model=list[SystemPromptResponse])
async def list_prompts(db: AsyncSession = Depends(get_db)):
    """List all system prompts."""
    stmt = select(SystemPrompt).order_by(SystemPrompt.is_default.desc(), SystemPrompt.id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=SystemPromptResponse, status_code=201)
async def create_prompt(
    data: SystemPromptCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new system prompt."""
    # Check name uniqueness
    existing = await db.execute(
        select(SystemPrompt).where(SystemPrompt.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Prompt name already exists")

    prompt = SystemPrompt(name=data.name, content=data.content, is_default=data.is_default)

    # If setting as default, unset others
    if data.is_default:
        await _unset_all_defaults(db)

    db.add(prompt)
    await db.flush()
    return prompt


@router.get("/{prompt_id}", response_model=SystemPromptResponse)
async def get_prompt(prompt_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single system prompt by ID."""
    prompt = await db.get(SystemPrompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt


@router.put("/{prompt_id}", response_model=SystemPromptResponse)
async def update_prompt(
    prompt_id: int,
    data: SystemPromptUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a system prompt."""
    prompt = await db.get(SystemPrompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    if data.name is not None:
        # Check uniqueness
        existing = await db.execute(
            select(SystemPrompt).where(
                SystemPrompt.name == data.name, SystemPrompt.id != prompt_id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Prompt name already exists")
        prompt.name = data.name

    if data.content is not None:
        prompt.content = data.content

    if data.is_default is not None and data.is_default:
        await _unset_all_defaults(db)
        prompt.is_default = True
    elif data.is_default is not None:
        prompt.is_default = data.is_default

    await db.flush()
    return prompt


@router.delete("/{prompt_id}", response_model=MessageAction)
async def delete_prompt(prompt_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a system prompt."""
    prompt = await db.get(SystemPrompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    await db.delete(prompt)
    await db.flush()
    return MessageAction(message=f"Deleted prompt '{prompt.name}'")


@router.post("/{prompt_id}/default", response_model=MessageAction)
async def set_default_prompt(prompt_id: int, db: AsyncSession = Depends(get_db)):
    """Set a prompt as the default."""
    prompt = await db.get(SystemPrompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    await _unset_all_defaults(db)
    prompt.is_default = True
    await db.flush()
    return MessageAction(message=f"Set '{prompt.name}' as default")


async def _unset_all_defaults(db: AsyncSession) -> None:
    """Remove default flag from all prompts."""
    from sqlalchemy import update
    await db.execute(
        update(SystemPrompt).where(SystemPrompt.is_default == True).values(is_default=False)
    )
