"""Character card CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
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


@router.post("/import", response_model=CharacterCardResponse, status_code=201)
async def import_character(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Import a character card from a JSON or PNG file."""
    file_data = await file.read()
    filename = file.filename or "unknown"

    if filename.lower().endswith(".png"):
        parsed = parse_png_character(file_data)
        if not parsed:
            raise HTTPException(status_code=400, detail="No character data found in PNG file")
    elif filename.lower().endswith(".json"):
        try:
            json_data = __import__("json").loads(file_data)
            parsed = parse_st_json(json_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format. Use .json or .png")

    service = CharacterService(db)
    existing = await service.get_character_by_name(parsed["name"])
    if existing:
        card = await service.update_character(existing.id, parsed)
    else:
        card = await service.create_character(parsed)

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
    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail="Character not found")
    file_data = await file.read()
    await service.save_avatar(char_id, file_data, file.filename or "avatar.png")
    return MessageAction(message="Avatar uploaded")
