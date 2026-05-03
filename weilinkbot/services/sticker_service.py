"""Sticker pack CRUD, archive import, and keyword search."""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import StickerPack, Sticker

logger = logging.getLogger(__name__)

STICKERS_DIR = Path("data/stickers/packs")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_ARCHIVE_SIZE = 128 * 1024 * 1024  # 128 MB


class StickerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Pack CRUD ──────────────────────────────────────────────

    async def create_pack(self, name: str, description: str = "") -> StickerPack:
        pack = StickerPack(name=name, description=description)
        self.db.add(pack)
        await self.db.flush()
        return pack

    async def list_packs(self) -> list[dict]:
        """Return all packs with sticker_count."""
        stmt = (
            select(
                StickerPack,
                func.coalesce(func.count(Sticker.id), 0).label("sticker_count"),
            )
            .outerjoin(Sticker)
            .group_by(StickerPack.id)
            .order_by(StickerPack.created_at.desc())
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        packs = []
        for pack, count in rows:
            packs.append({
                "id": pack.id,
                "name": pack.name,
                "description": pack.description,
                "cover_path": pack.cover_path,
                "sticker_count": count,
                "created_at": pack.created_at,
                "updated_at": pack.updated_at,
            })
        return packs

    async def get_pack(self, pack_id: int) -> Optional[StickerPack]:
        stmt = select(StickerPack).where(StickerPack.id == pack_id).options(selectinload(StickerPack.stickers))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_pack(self, pack_id: int, **fields) -> Optional[StickerPack]:
        pack = await self.get_pack(pack_id)
        if not pack:
            return None
        for k, v in fields.items():
            if v is not None and hasattr(pack, k):
                setattr(pack, k, v)
        await self.db.flush()
        return pack

    async def delete_pack(self, pack_id: int) -> bool:
        pack = await self.get_pack(pack_id)
        if not pack:
            return False
        pack_dir = STICKERS_DIR / str(pack_id)
        if pack_dir.exists():
            shutil.rmtree(pack_dir, ignore_errors=True)
        await self.db.delete(pack)
        await self.db.flush()
        return True

    # ── Sticker CRUD ───────────────────────────────────────────

    async def add_sticker(
        self, pack_id: int, file_data: bytes, original_filename: str, text_description: str = ""
    ) -> Optional[Sticker]:
        pack = await self.get_pack(pack_id)
        if not pack:
            return None

        ext = Path(original_filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            return None

        stmt = select(func.coalesce(func.max(Sticker.sort_order), 0)).where(Sticker.pack_id == pack_id)
        result = await self.db.execute(stmt)
        next_order = result.scalar() + 1

        sticker = Sticker(
            pack_id=pack_id,
            file_path="",
            original_filename=original_filename,
            text_description=text_description,
            sort_order=next_order,
        )
        self.db.add(sticker)
        await self.db.flush()

        pack_dir = STICKERS_DIR / str(pack_id)
        pack_dir.mkdir(parents=True, exist_ok=True)
        file_path = pack_dir / f"{sticker.id}{ext}"
        file_path.write_bytes(file_data)

        sticker.file_path = f"data/stickers/packs/{pack_id}/{sticker.id}{ext}"

        if not pack.cover_path:
            pack.cover_path = sticker.file_path

        await self.db.flush()
        return sticker

    async def update_sticker(self, sticker_id: int, **fields) -> Optional[Sticker]:
        stmt = select(Sticker).where(Sticker.id == sticker_id)
        result = await self.db.execute(stmt)
        sticker = result.scalar_one_or_none()
        if not sticker:
            return None
        for k, v in fields.items():
            if v is not None and hasattr(sticker, k):
                setattr(sticker, k, v)
        await self.db.flush()
        return sticker

    async def delete_sticker(self, sticker_id: int) -> bool:
        stmt = select(Sticker).where(Sticker.id == sticker_id)
        result = await self.db.execute(stmt)
        sticker = result.scalar_one_or_none()
        if not sticker:
            return False
        if sticker.file_path:
            fp = Path(sticker.file_path)
            if fp.exists():
                fp.unlink(missing_ok=True)
        await self.db.delete(sticker)
        await self.db.flush()
        return True

    # ── Archive Import ─────────────────────────────────────────

    async def import_archive(self, file_data: bytes, filename: str) -> Optional[StickerPack]:
        """Import a ZIP/7Z/RAR archive as a new sticker pack."""
        if len(file_data) > MAX_ARCHIVE_SIZE:
            raise ValueError("Archive too large (max 50 MB)")

        pack_name = Path(filename).stem
        tmpdir = tempfile.mkdtemp(prefix="sticker_import_")
        try:
            extracted = self._extract_archive(file_data, filename, tmpdir)
            if not extracted:
                raise ValueError("No valid images found in archive")

            pack = await self.create_pack(pack_name)
            for img_path in extracted:
                img_data = img_path.read_bytes()
                await self.add_sticker(pack.id, img_data, img_path.name)

            return pack
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _extract_archive(self, file_data: bytes, filename: str, tmpdir: str) -> list[Path]:
        lower = filename.lower()
        if lower.endswith(".zip"):
            return self._extract_zip(file_data, tmpdir)
        elif lower.endswith(".7z"):
            return self._extract_7z(file_data, tmpdir)
        elif lower.endswith(".rar"):
            return self._extract_rar(file_data, tmpdir)
        raise ValueError(f"Unsupported archive format: {filename}")

    def _extract_zip(self, file_data: bytes, tmpdir: str) -> list[Path]:
        import io
        with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
            zf.extractall(tmpdir)
        return self._collect_images(tmpdir)

    def _extract_7z(self, file_data: bytes, tmpdir: str) -> list[Path]:
        import io
        try:
            import py7zr
        except ImportError:
            raise ValueError("py7zr not installed — cannot extract .7z files")
        with py7zr.SevenZipFile(io.BytesIO(file_data), mode="r") as sz:
            sz.extractall(tmpdir)
        return self._collect_images(tmpdir)

    def _extract_rar(self, file_data: bytes, tmpdir: str) -> list[Path]:
        import io
        try:
            import rarfile
        except ImportError:
            raise ValueError("rarfile not installed — cannot extract .rar files")
        with rarfile.RarFile(io.BytesIO(file_data)) as rf:
            rf.extractall(tmpdir)
        return self._collect_images(tmpdir)

    def _collect_images(self, tmpdir: str) -> list[Path]:
        images = []
        for p in sorted(Path(tmpdir).rglob("*")):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(p)
        return images

    # ── Search (for Agent tool) ────────────────────────────────

    async def search_stickers(self, keyword: str, limit: int = 3) -> list[dict]:
        """Search stickers by text_description keyword match."""
        stmt = (
            select(Sticker, StickerPack.name.label("pack_name"))
            .join(StickerPack)
            .where(Sticker.text_description.ilike(f"%{keyword}%"))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        return [
            {
                "sticker_id": sticker.id,
                "file_path": sticker.file_path,
                "text_description": sticker.text_description,
                "pack_name": pack_name,
            }
            for sticker, pack_name in rows
        ]

    # ── Directory Scan ────────────────────────────────────────

    async def scan_directory(self, path: str) -> list[StickerPack]:
        """Scan a local directory and import images as sticker packs.

        Smart mode: if the directory contains subdirectories with images,
        each subdirectory becomes a separate pack. Otherwise, the directory
        itself becomes one pack.
        """
        root = Path(path)
        if not root.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        # Collect subdirectories that contain images
        subdirs_with_images: list[Path] = []
        for child in sorted(root.iterdir()):
            if child.is_dir():
                has_images = any(
                    f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
                    for f in child.rglob("*")
                )
                if has_images:
                    subdirs_with_images.append(child)

        if subdirs_with_images:
            # Subdirectory mode: each subdirectory is a pack
            packs = []
            for subdir in subdirs_with_images:
                pack = await self._import_dir_as_pack(subdir)
                if pack:
                    packs.append(pack)
            return packs
        else:
            # Single directory mode: the directory itself is a pack
            pack = await self._import_dir_as_pack(root)
            return [pack] if pack else []

    async def _import_dir_as_pack(self, directory: Path) -> Optional[StickerPack]:
        """Import all images in a directory as a new sticker pack."""
        images = [
            p for p in sorted(directory.rglob("*"))
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        ]
        if not images:
            return None

        pack = await self.create_pack(directory.name)
        for img_path in images:
            img_data = img_path.read_bytes()
            await self.add_sticker(pack.id, img_data, img_path.name)
        return pack
