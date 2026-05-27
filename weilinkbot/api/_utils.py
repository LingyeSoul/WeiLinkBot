"""Shared API utilities — deduplicates common patterns across route modules."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from ..i18n import t


def content_disposition(filename: str) -> str:
    """Build Content-Disposition header with RFC 5987 encoding for non-ASCII filenames."""
    ascii_name = filename.encode("ascii", "ignore").decode("ascii")
    if ascii_name == filename:
        return f'attachment; filename="{filename}"'
    encoded = quote(filename)
    return f"attachment; filename=\"{ascii_name or 'file'}\"; filename*=UTF-8''{encoded}"


_DEFAULT_UPLOAD_LIMIT = 10 * 1024 * 1024  # 10 MB


async def read_upload_with_limit(file: UploadFile, limit: int = _DEFAULT_UPLOAD_LIMIT) -> bytes:
    """Read uploaded file with a size limit to prevent memory exhaustion."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(8192):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=t("api.file_too_large"))
        chunks.append(chunk)
    return b"".join(chunks)
