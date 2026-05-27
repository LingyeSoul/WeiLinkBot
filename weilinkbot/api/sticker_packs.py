"""Sticker pack CRUD API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..i18n import t
from ..schemas import (
    StickerPackCreate,
    StickerPackUpdate,
    StickerPackResponse,
    StickerPackDetailResponse,
    StickerResponse,
    StickerUpdate,
    MessageAction,
)
from ..services.sticker_service import StickerService
from ..services.ws_service import get_ws_service


router = APIRouter()

_MAX_UPLOAD_SIZE = 128 * 1024 * 1024  # 128 MB per single sticker
_MAX_ARCHIVE_SIZE = 128 * 1024 * 1024  # 128 MB for archives


from ._utils import read_upload_with_limit as _read_upload_with_limit


async def _broadcast_packs(db):
    service = StickerService(db)
    packs = await service.list_packs()
    await get_ws_service().broadcast("sticker_packs", packs)


# -- Pack endpoints --------------------------------------------------------

@router.get("", response_model=list[StickerPackResponse])
async def list_packs(db: AsyncSession = Depends(get_db)):
    service = StickerService(db)
    return await service.list_packs()


@router.post("", response_model=StickerPackResponse, status_code=201)
async def create_pack(data: StickerPackCreate, db: AsyncSession = Depends(get_db)):
    service = StickerService(db)
    pack = await service.create_pack(data.name, data.description)
    await _broadcast_packs(db)
    return {**pack.__dict__, "sticker_count": 0, "cover_sticker_id": None}


@router.get("/{pack_id}", response_model=StickerPackDetailResponse)
async def get_pack(pack_id: int, db: AsyncSession = Depends(get_db)):
    service = StickerService(db)
    pack = await service.get_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=t("api.pack_not_found"))
    return pack


@router.patch("/{pack_id}", response_model=StickerPackResponse)
async def update_pack(pack_id: int, data: StickerPackUpdate, db: AsyncSession = Depends(get_db)):
    service = StickerService(db)
    pack = await service.update_pack(pack_id, **data.model_dump(exclude_unset=True))
    if not pack:
        raise HTTPException(status_code=404, detail=t("api.pack_not_found"))
    await _broadcast_packs(db)
    packs = await service.list_packs()
    return next(p for p in packs if p["id"] == pack_id)


@router.delete("/{pack_id}", response_model=MessageAction)
async def delete_pack(pack_id: int, db: AsyncSession = Depends(get_db)):
    service = StickerService(db)
    if not await service.delete_pack(pack_id):
        raise HTTPException(status_code=404, detail=t("api.pack_not_found"))
    await _broadcast_packs(db)
    return MessageAction(message=t("api.pack_deleted"))


@router.post("/import", response_model=StickerPackResponse, status_code=201)
async def import_archive(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or "unknown.zip"
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in (".zip", ".7z", ".rar")):
        raise HTTPException(status_code=400, detail=t("api.unsupported_archive"))

    file_data = await _read_upload_with_limit(file, _MAX_ARCHIVE_SIZE)
    service = StickerService(db)
    try:
        pack = await service.import_archive(file_data, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not pack:
        raise HTTPException(status_code=400, detail=t("api.no_images_in_archive"))

    await _broadcast_packs(db)
    packs = await service.list_packs()
    return next(p for p in packs if p["id"] == pack.id)


@router.post("/scan", response_model=list[StickerPackResponse], status_code=201)
async def scan_directory(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Scan a local directory and import images as sticker packs."""
    path = body.get("path", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail=t("api.path_required"))

    service = StickerService(db)
    try:
        packs = await service.scan_directory(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not packs:
        raise HTTPException(status_code=400, detail=t("api.no_images_in_path"))

    await _broadcast_packs(db)
    all_packs = await service.list_packs()
    pack_ids = {p.id for p in packs}
    return [p for p in all_packs if p["id"] in pack_ids]


# -- Sticker endpoints -----------------------------------------------------

@router.get("/{pack_id}/stickers", response_model=list[StickerResponse])
async def list_stickers(pack_id: int, db: AsyncSession = Depends(get_db)):
    service = StickerService(db)
    pack = await service.get_pack(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=t("api.pack_not_found"))
    return pack.stickers


@router.post("/{pack_id}/stickers", response_model=StickerResponse, status_code=201)
async def add_sticker(
    pack_id: int,
    file: UploadFile = File(...),
    text_description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=t("api.image_only"))

    file_data = await _read_upload_with_limit(file, _MAX_UPLOAD_SIZE)
    service = StickerService(db)
    sticker = await service.add_sticker(pack_id, file_data, file.filename or "sticker.png", text_description)
    if not sticker:
        raise HTTPException(status_code=400, detail=t("api.sticker_add_failed"))

    await _broadcast_packs(db)
    return sticker


@router.patch("/stickers/{sticker_id}", response_model=StickerResponse)
async def update_sticker(sticker_id: int, data: StickerUpdate, db: AsyncSession = Depends(get_db)):
    service = StickerService(db)
    sticker = await service.update_sticker(sticker_id, **data.model_dump(exclude_unset=True))
    if not sticker:
        raise HTTPException(status_code=404, detail=t("api.sticker_not_found"))
    await _broadcast_packs(db)
    return sticker


@router.delete("/stickers/{sticker_id}", response_model=MessageAction)
async def delete_sticker(sticker_id: int, db: AsyncSession = Depends(get_db)):
    service = StickerService(db)
    if not await service.delete_sticker(sticker_id):
        raise HTTPException(status_code=404, detail=t("api.sticker_not_found"))
    await _broadcast_packs(db)
    return MessageAction(message=t("api.sticker_deleted"))


@router.get("/stickers/{sticker_id}/file")
async def serve_sticker_file(sticker_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select as _select
    from ..models import Sticker as _Sticker
    from ..services.sticker_service import STICKERS_DIR
    result = await db.execute(_select(_Sticker.file_path).where(_Sticker.id == sticker_id))
    rel_path = result.scalar_one_or_none()
    if not rel_path:
        raise HTTPException(status_code=404, detail=t("api.sticker_not_found"))
    full_path = STICKERS_DIR / rel_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=t("api.sticker_not_found"))
    return FileResponse(str(full_path))
