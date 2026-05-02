"""Character card CRUD API endpoints."""

from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..i18n import t
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
from ..services.ws_service import get_ws_service


def _content_disposition(filename: str) -> str:
    """Build Content-Disposition header with RFC 5987 encoding for non-ASCII filenames."""
    ascii_name = filename.encode("ascii", "ignore").decode("ascii")
    if ascii_name == filename:
        return f'attachment; filename="{filename}"'
    encoded = quote(filename)
    return f"attachment; filename=\"{ascii_name or 'file'}\"; filename*=UTF-8''{encoded}"


router = APIRouter()


async def _broadcast_characters(db):
    """Broadcast updated characters list to all WebSocket clients."""
    service = CharacterService(db)
    chars = await service.list_characters()
    await get_ws_service().broadcast(
        "characters",
        [CharacterCardResponse.model_validate(c).model_dump(mode="json") for c in chars],
    )


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
        raise HTTPException(status_code=409, detail=t("api.char_exists"))
    card = await service.create_character(data.model_dump())
    await _broadcast_characters(db)
    return card


@router.get("/{char_id}", response_model=CharacterCardResponse)
async def get_character(char_id: int, db: AsyncSession = Depends(get_db)):
    """Get a character card by ID."""
    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail=t("api.char_not_found"))
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
            raise HTTPException(status_code=409, detail=t("api.char_exists"))
    card = await service.update_character(char_id, data.model_dump(exclude_unset=True))
    if not card:
        raise HTTPException(status_code=404, detail=t("api.char_not_found"))
    await _broadcast_characters(db)
    return card


@router.delete("/{char_id}", response_model=MessageAction)
async def delete_character(char_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a character card."""
    service = CharacterService(db)
    if not await service.delete_character(char_id):
        raise HTTPException(status_code=404, detail=t("api.char_not_found"))
    await _broadcast_characters(db)
    return MessageAction(message=t("api.char_deleted"))


@router.post("/{char_id}/activate", response_model=MessageAction)
async def activate_character(char_id: int, db: AsyncSession = Depends(get_db)):
    """Activate a character card (sets its prompt as the global default)."""
    service = CharacterService(db)
    card = await service.activate_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail=t("api.char_not_found"))
    await _broadcast_characters(db)
    return MessageAction(message=t("api.activated_char", name=card.name))


@router.post("/deactivate", response_model=MessageAction)
async def deactivate_character(db: AsyncSession = Depends(get_db)):
    """Deactivate current character card and restore default prompt."""
    service = CharacterService(db)
    await service.deactivate_character()
    await _broadcast_characters(db)
    return MessageAction(message=t("api.char_deactivated"))


@router.get("/{char_id}/export/json")
async def export_character_json(char_id: int, db: AsyncSession = Depends(get_db)):
    """Export a character card as SillyTavern JSON file."""
    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail=t("api.char_not_found"))
    data = export_st_json(card)
    disposition = _content_disposition(f"{card.name}.json")
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": disposition},
    )


@router.get("/{char_id}/export/png")
async def export_character_png(char_id: int, db: AsyncSession = Depends(get_db)):
    """Export a character card as PNG with embedded character data."""
    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail=t("api.char_not_found"))
    base_png = None
    if card.avatar_path:
        try:
            base_png = Path(card.avatar_path).read_bytes()
        except Exception:
            pass
    data = export_st_png(card, base_png)
    disposition = _content_disposition(f"{card.name}.png")
    return Response(
        content=data,
        media_type="image/png",
        headers={"Content-Disposition": disposition},
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
            raise HTTPException(status_code=400, detail=t("api.no_char_in_png"))
    elif filename.lower().endswith(".json"):
        try:
            json_data = json.loads(file_data)
            parsed = parse_st_json(json_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=t("api.invalid_json", e=e))
    else:
        raise HTTPException(status_code=400, detail=t("api.unsupported_format"))

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

    await _broadcast_characters(db)
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
        raise HTTPException(status_code=400, detail=t("api.image_only"))

    service = CharacterService(db)
    card = await service.get_character(char_id)
    if not card:
        raise HTTPException(status_code=404, detail=t("api.char_not_found"))
    file_data = await _read_upload_with_limit(file)
    await service.save_avatar(char_id, file_data, file.filename or "avatar.png")
    await _broadcast_characters(db)
    return MessageAction(message=t("api.avatar_uploaded"))


_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


async def _read_upload_with_limit(file: UploadFile) -> bytes:
    """Read uploaded file with a size limit to prevent memory exhaustion."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(8192):
        total += len(chunk)
        if total > _MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail=t("api.file_too_large"))
        chunks.append(chunk)
    return b"".join(chunks)
