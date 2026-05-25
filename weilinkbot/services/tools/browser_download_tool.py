"""browser_download — download files via Obscura headless browser to workspace."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import Tool, ToolExecutionError
from ._url_validate import validate_url

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB

try:
    from .browser_use_tool import _cdp_download, _mgr, _HAS_CDP
except ImportError:
    _HAS_CDP = False


class BrowserDownloadTool(Tool):
    name = "browser_download"
    description = (
        "Download a file from a URL using the headless browser and save it "
        "to the workspace. The browser handles redirects, cookies, and "
        "Content-Disposition headers automatically. Returns the relative "
        "path of the downloaded file within the workspace. "
        "Use send_file afterward to deliver the file to the user."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to download from.",
            },
            "filename": {
                "type": "string",
                "description": (
                    "Optional custom filename to save as. "
                    "If omitted, the server-suggested filename is used."
                ),
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for the download (10-300, default 120).",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_service) -> None:
        self._ws = workspace_service

    async def execute(
        self,
        *,
        url: str,
        filename: str | None = None,
        timeout: int = 120,
        **kwargs,
    ) -> str:
        if not _HAS_CDP:
            raise ToolExecutionError(
                "browser_download unavailable: websockets not installed "
                "(pip install websockets)"
            )

        validate_url(url)
        timeout = max(10, min(int(timeout), 300))

        # Determine download directory (absolute path on disk)
        try:
            from ...config import get_config
            download_rel = get_config().browser.download_dir
        except Exception:
            download_rel = "downloads"

        download_abs = self._ws.sandbox.resolve(download_rel)
        download_abs.mkdir(parents=True, exist_ok=True)
        download_dir_str = str(download_abs)

        # Create a temporary CDP session for the download
        sid = await _mgr.create_session()
        try:
            info = _mgr.get(sid)
            suggested = await _cdp_download(
                info["browser_ws"],
                info["session_id"],
                url,
                download_dir_str,
                timeout=timeout,
            )
        except Exception:
            raise
        finally:
            try:
                await _mgr.close_session(sid)
            except Exception:
                pass

        # Resolve final filename
        final_name = filename or suggested or "downloaded_file"
        # Sanitize: strip path separators from the filename
        final_name = Path(final_name).name
        if not final_name:
            final_name = "downloaded_file"

        downloaded_path = download_abs / final_name

        # Wait briefly for the file to be fully flushed
        import asyncio
        for _ in range(10):
            if downloaded_path.exists():
                break
            await asyncio.sleep(0.3)

        if not downloaded_path.exists():
            raise ToolExecutionError(
                f"Download failed: file not found at {downloaded_path}. "
                "The URL may not trigger a direct file download."
            )

        # Validate extension
        try:
            self._ws.sandbox.check_extension(downloaded_path)
        except Exception as e:
            downloaded_path.unlink(missing_ok=True)
            raise ToolExecutionError(f"Downloaded file has blocked extension: {e}")

        # Check file size
        file_size = downloaded_path.stat().st_size
        if file_size > _MAX_FILE_SIZE:
            downloaded_path.unlink(missing_ok=True)
            raise ToolExecutionError(
                f"Downloaded file too large: {file_size:,} bytes "
                f"(max {_MAX_FILE_SIZE:,} bytes)"
            )

        # Return relative path within workspace
        rel = downloaded_path.relative_to(self._ws.sandbox.root).as_posix()
        logger.info("Downloaded '%s' (%d bytes) from %s", rel, file_size, url)
        return (
            f"Downloaded successfully.\n"
            f"File: {rel}\n"
            f"Size: {file_size:,} bytes"
        )
