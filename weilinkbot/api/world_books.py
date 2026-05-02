"""World Book (Lorebook) CRUD and SillyTavern JSON import/export."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..i18n import t
from ..schemas import WorldBookCreate, WorldBookUpdate, WorldBookResponse, MessageAction
from ..services.world_book_service import WorldBookService
from ..services.ws_service import get_ws_service


router = APIRouter()


async def _broadcast_world_books(db: AsyncSession):
    """Broadcast updated world books list to all WebSocket clients."""
    service = WorldBookService(db)
    books = await service.list_world_books()
    await get_ws_service().broadcast(
        "world_books",
        [WorldBookResponse.model_validate(b).model_dump(mode="json") for b in books],
    )


_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


def _content_disposition(filename: str) -> str:
    """Build Content-Disposition header with RFC 5987 encoding for non-ASCII filenames."""
    ascii_name = filename.encode("ascii", "ignore").decode("ascii")
    if ascii_name == filename:
        return f'attachment; filename="{filename}"'
    encoded = quote(filename)
    return f"attachment; filename=\"{ascii_name or 'file'}\"; filename*=UTF-8''{encoded}"


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


@router.get("", response_model=list[WorldBookResponse])
async def list_world_books(db: AsyncSession = Depends(get_db)):
    """List all world books."""
    service = WorldBookService(db)
    return await service.list_world_books()


@router.post("", response_model=WorldBookResponse, status_code=201)
async def create_world_book(
    data: WorldBookCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new world book."""
    service = WorldBookService(db)
    existing = await service.get_world_book_by_name(data.name)
    if existing:
        raise HTTPException(status_code=409, detail=t("api.wb_exists"))
    wb = await service.create_world_book(data.model_dump())
    await _broadcast_world_books(db)
    return wb


@router.get("/{wb_id}", response_model=WorldBookResponse)
async def get_world_book(wb_id: int, db: AsyncSession = Depends(get_db)):
    """Get a world book by ID with its entries."""
    service = WorldBookService(db)
    wb = await service.get_world_book(wb_id)
    if not wb:
        raise HTTPException(status_code=404, detail=t("api.wb_not_found"))
    return wb


@router.put("/{wb_id}", response_model=WorldBookResponse)
async def update_world_book(
    wb_id: int,
    data: WorldBookUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a world book."""
    service = WorldBookService(db)
    if data.name is not None:
        existing = await service.get_world_book_by_name(data.name)
        if existing and existing.id != wb_id:
            raise HTTPException(status_code=409, detail=t("api.wb_exists"))
    wb = await service.update_world_book(wb_id, data.model_dump(exclude_unset=True))
    if not wb:
        raise HTTPException(status_code=404, detail=t("api.wb_not_found"))
    await _broadcast_world_books(db)
    return wb


@router.delete("/{wb_id}", response_model=MessageAction)
async def delete_world_book(wb_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a world book and its entries."""
    service = WorldBookService(db)
    if not await service.delete_world_book(wb_id):
        raise HTTPException(status_code=404, detail=t("api.wb_not_found"))
    await _broadcast_world_books(db)
    return MessageAction(message=t("api.wb_deleted"))


@router.post("/{wb_id}/activate", response_model=MessageAction)
async def activate_world_book(wb_id: int, db: AsyncSession = Depends(get_db)):
    """Activate a world book."""
    service = WorldBookService(db)
    wb = await service.activate_world_book(wb_id)
    if not wb:
        raise HTTPException(status_code=404, detail=t("api.wb_not_found"))
    await _broadcast_world_books(db)
    return MessageAction(message=t("api.activated_wb", name=wb.name))


@router.post("/deactivate", response_model=MessageAction)
async def deactivate_world_book(db: AsyncSession = Depends(get_db)):
    """Deactivate current world book."""
    service = WorldBookService(db)
    await service.deactivate_world_book()
    await _broadcast_world_books(db)
    return MessageAction(message=t("api.wb_deactivated"))


@router.get("/active/entries")
async def get_active_entries(db: AsyncSession = Depends(get_db)):
    """Get entries from the active world book."""
    service = WorldBookService(db)
    wb = await service.get_active_world_book()
    if not wb:
        return []
    return wb.entries


@router.get("/{wb_id}/export")
async def export_world_book(wb_id: int, db: AsyncSession = Depends(get_db)):
    """Export a world book as JSON file."""
    service = WorldBookService(db)
    wb = await service.get_world_book(wb_id)
    if not wb:
        raise HTTPException(status_code=404, detail=t("api.wb_not_found"))
    disposition = _content_disposition(f"{wb.name}.json")
    return Response(content=wb.raw_json, media_type="application/json", headers={"Content-Disposition": disposition})


@router.post("/import", response_model=WorldBookResponse, status_code=201)
async def import_world_book(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Import a world book from a JSON file."""
    file_data = await _read_upload_with_limit(file)
    filename = file.filename or "unknown"
    if not filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail=t("api.unsupported_format"))
    try:
        raw_json = file_data.decode("utf-8")
        json_data = json.loads(raw_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=t("api.invalid_json", e=e))

    name = json_data.get("name", json_data.get("title", Path(filename).stem))
    service = WorldBookService(db)
    existing = await service.get_world_book_by_name(name)
    if existing:
        wb = await service.update_world_book(existing.id, {"name": name, "raw_json": raw_json})
    else:
        wb = await service.create_world_book({"name": name, "raw_json": raw_json})
    await _broadcast_world_books(db)
    return wb