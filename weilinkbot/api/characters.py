"""Character card CRUD API endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import CharacterCard
from ..schemas import (
    CharacterCardCreate,
    CharacterCardUpdate,
    CharacterCardResponse,
    MessageAction,
)
from ..services.character_service import (
    CharacterService,
    parse_png_character,
    parse_st_json,
    export_st_json,
    export_st_png,
)

router = APIRouter()


@router.get("", response_model=list[CharacterCardResponse])
async def list_characters(db: AsyncSession = Depends(get_db)):
    """List all character cards."""
    service = CharacterService(db)
    return await service.list_characters()


@router.post("", response_model=CharacterCardResponse, status_code=201)
async def create_character(
    data: CharacterCardCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new character card."""
    service = CharacterService(db)
    existing = await service.get_character_by_name(data.name)
    if existing:
        raise HTTPException(status_code=409, detail="Character name already exists")
    card = await service.create_character(data.model_dump())
    return card


@router.get("/{char_id}", response_model=CharacterCardResponse)
async def get_character(char_id: int, db: AsyncSession = Depends(get_db)):
    """Get a character card by ID."""
    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail="Character not found")
    return card


@router.put("/{char_id}", response_model=CharacterCardResponse)
async def update_character(
    char_id: int,
    data: CharacterCardUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a character card."""
    service = CharacterService(db)
    if data.name is not None:
        existing = await service.get_character_by_name(data.name)
        if existing and existing.id != char_id:
            raise HTTPException(status_code=409, detail="Character name already exists")
    card = await service.update_character(char_id, data.model_dump(exclude_unset=True))
    if not card:
        raise HTTPException(status_code=404, detail="Character not found")
    return card


@router.delete("/{char_id}", response_model=MessageAction)
async def delete_character(char_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a character card."""
    service = CharacterService(db)
    if not await service.delete_character(char_id):
        raise HTTPException(status_code=404, detail="Character not found")
    return MessageAction(message="Character deleted")


@router.post("/{char_id}/activate", response_model=MessageAction)
async def activate_character(char_id: int, db: AsyncSession = Depends(get_db)):
    """Activate a character card (sets its prompt as the global default)."""
    service = CharacterService(db)
    card = await service.activate_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail="Character not found")
    return MessageAction(message=f"Activated character: {card.name}")


@router.post("/deactivate", response_model=MessageAction)
async def deactivate_character(db: AsyncSession = Depends(get_db)):
    """Deactivate current character card and restore default prompt."""
    service = CharacterService(db)
    await service.deactivate_character()
    return MessageAction(message="Character deactivated")


@router.get("/{char_id}/export/json")
async def export_character_json(char_id: int, db: AsyncSession = Depends(get_db)):
    """Export a character card as SillyTavern JSON file."""
    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail="Character not found")
    data = export_st_json(card)
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{card.name}.json"'},
    )


@router.get("/{char_id}/export/png")
async def export_character_png(char_id: int, db: AsyncSession = Depends(get_db)):
    """Export a character card as PNG with embedded character data."""
    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail="Character not found")
    base_png = None
    if card.avatar_path:
        try:
            base_png = Path(card.avatar_path).read_bytes()
        except Exception:
            pass
    data = export_st_png(card, base_png)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{card.name}.png"'},
    )


@router.post("/import", response_model=CharacterCardResponse, status_code=201)
async def import_character(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Import a character card from a JSON or PNG file."""
    file_data = await _read_upload_with_limit(file)
    filename = file.filename or "unknown"

    if filename.lower().endswith(".png"):
        parsed = parse_png_character(file_data)
        if not parsed:
            raise HTTPException(status_code=400, detail="No character data found in PNG file")
    elif filename.lower().endswith(".json"):
        try:
            json_data = json.loads(file_data)
            parsed = parse_st_json(json_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format. Use .json or .png")

    # Validate imported data through Pydantic schema
    validated = CharacterCardCreate(**parsed)

    service = CharacterService(db)
    existing = await service.get_character_by_name(validated.name)
    if existing:
        card = await service.update_character(existing.id, validated.model_dump())
    else:
        card = await service.create_character(validated.model_dump())

    # If PNG, save avatar
    if filename.lower().endswith(".png") and card:
        await service.save_avatar(card.id, file_data, filename)

    return card


@router.post("/{char_id}/avatar", response_model=MessageAction)
async def upload_avatar(
    char_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload an avatar image for a character card."""
    # Validate content type
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail="Character not found")
    file_data = await _read_upload_with_limit(file)
    await service.save_avatar(char_id, file_data, file.filename or "avatar.png")
    return MessageAction(message="Avatar uploaded")


_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


async def _read_upload_with_limit(file: UploadFile) -> bytes:
    """Read uploaded file with a size limit to prevent memory exhaustion."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(8192):
        total += len(chunk)
        if total > _MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
        chunks.append(chunk)
    return b"".join(chunks)
