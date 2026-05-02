"""ST Preset CRUD and SillyTavern JSON import/export."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..i18n import t
from ..schemas import STPresetCreate, STPresetUpdate, STPresetResponse, MessageAction
from ..services.st_preset_service import STPresetService, parse_st_entries
from ..services.ws_service import get_ws_service


router = APIRouter()


async def _broadcast_st_presets(db: AsyncSession):
    """Broadcast updated ST presets list to all WebSocket clients."""
    service = STPresetService(db)
    presets = await service.list_presets()
    await get_ws_service().broadcast(
        "st_presets",
        [STPresetResponse.model_validate(p).model_dump(mode="json") for p in presets],
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


@router.get("", response_model=list[STPresetResponse])
async def list_st_presets(db: AsyncSession = Depends(get_db)):
    """List all ST presets."""
    service = STPresetService(db)
    return await service.list_presets()


@router.post("", response_model=STPresetResponse, status_code=201)
async def create_st_preset(
    data: STPresetCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new ST preset."""
    service = STPresetService(db)
    existing = await service.get_preset_by_name(data.name)
    if existing:
        raise HTTPException(status_code=409, detail=t("api.preset_exists"))
    preset = await service.create_preset(data.model_dump())
    await _broadcast_st_presets(db)
    return preset


@router.get("/{preset_id}", response_model=STPresetResponse)
async def get_st_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Get an ST preset by ID."""
    service = STPresetService(db)
    preset = await service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    return preset


@router.put("/{preset_id}", response_model=STPresetResponse)
async def update_st_preset(
    preset_id: int,
    data: STPresetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an ST preset."""
    service = STPresetService(db)
    if data.name is not None:
        existing = await service.get_preset_by_name(data.name)
        if existing and existing.id != preset_id:
            raise HTTPException(status_code=409, detail=t("api.preset_exists"))
    preset = await service.update_preset(preset_id, data.model_dump(exclude_unset=True))
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    await _broadcast_st_presets(db)
    return preset


@router.delete("/{preset_id}", response_model=MessageAction)
async def delete_st_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an ST preset."""
    service = STPresetService(db)
    preset = await service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    if preset.is_active:
        raise HTTPException(status_code=400, detail=t("api.cannot_delete_active"))
    if not await service.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    await _broadcast_st_presets(db)
    return MessageAction(message=t("api.preset_deleted"))


@router.post("/{preset_id}/activate", response_model=MessageAction)
async def activate_st_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Activate an ST preset."""
    service = STPresetService(db)
    preset = await service.activate_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    await _broadcast_st_presets(db)
    return MessageAction(message=t("api.activated_preset", name=preset.name))


@router.post("/deactivate", response_model=MessageAction)
async def deactivate_st_preset(db: AsyncSession = Depends(get_db)):
    """Deactivate current ST preset."""
    service = STPresetService(db)
    await service.deactivate_preset()
    await _broadcast_st_presets(db)
    return MessageAction(message=t("api.preset_deactivated"))


@router.get("/{preset_id}/entries")
async def get_st_preset_entries(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Get parsed entries for a preset."""
    service = STPresetService(db)
    preset = await service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    return parse_st_entries(preset.raw_json)


@router.patch("/{preset_id}/entries/{entry_index}")
async def toggle_st_preset_entry(
    preset_id: int,
    entry_index: int,
    enabled: bool,
    db: AsyncSession = Depends(get_db),
):
    """Toggle a single entry's enabled state."""
    service = STPresetService(db)
    entries = await service.toggle_entry(preset_id, entry_index, enabled)
    if entries is None:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    await _broadcast_st_presets(db)
    return entries


@router.get("/{preset_id}/export")
async def export_st_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Export an ST preset as JSON file."""
    service = STPresetService(db)
    preset = await service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    disposition = _content_disposition(f"{preset.name}.json")
    return Response(content=preset.raw_json, media_type="application/json", headers={"Content-Disposition": disposition})


@router.post("/import", response_model=STPresetResponse, status_code=201)
async def import_st_preset(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Import an ST preset from a JSON file."""
    file_data = await _read_upload_with_limit(file)
    filename = file.filename or "unknown"
    if not filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail=t("api.unsupported_format"))
    try:
        raw_json = file_data.decode("utf-8")
        json_data = json.loads(raw_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=t("api.invalid_json", e=e))

    name = json_data.get("name", Path(filename).stem)
    service = STPresetService(db)
    existing = await service.get_preset_by_name(name)
    if existing:
        preset = await service.update_preset(existing.id, {"name": name, "raw_json": raw_json})
    else:
        preset = await service.create_preset({"name": name, "raw_json": raw_json})
    await _broadcast_st_presets(db)
    return preset