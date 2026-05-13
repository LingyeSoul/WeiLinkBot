"""Shared Obscura binary resolution — used by browser_tool and browser_use_tool."""

from __future__ import annotations

import io
import logging
import platform
import shutil
import struct
import zipfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

_GITHUB_REPO = "h4ckf0r0day/obscura"
_GITHUB_API_URL = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"

_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "obscura"
_VERSION_FILE = _DATA_DIR / ".version"

_ASSET_MAP = {
    ("Windows", 64): "obscura-x86_64-windows.zip",
    ("Linux", 64):   "obscura-x86_64-linux.tar.gz",
    ("Darwin", 64):  "obscura-aarch64-macos.tar.gz",
    ("Darwin", 32):  "obscura-x86_64-macos.tar.gz",
}

# ── module-level cache ────────────────────────────────────────────────────────

_BINARY_PATH: str | None = None
_BINARY_READY: bool | None = None


def _platform_asset() -> tuple[str, str]:
    """Return (asset filename, expected binary name after extraction)."""
    system = platform.system()
    bits = struct.calcsize("P") * 8
    if system == "Windows":
        return _ASSET_MAP[("Windows", 64)], "obscura.exe"
    if system == "Linux":
        return _ASSET_MAP[("Linux", 64)], "obscura"
    if system == "Darwin":
        key = ("Darwin", bits) if bits == 32 else ("Darwin", 64)
        return _ASSET_MAP[key], "obscura"
    raise RuntimeError(f"Unsupported platform: {system}")


def _ssl_verify_chain() -> list[bool | str]:
    """Build SSL verify chain: certifi (if available) → system default."""
    chain: list[bool | str] = []
    try:
        import certifi
        chain.append(certifi.where())
    except ImportError:
        pass
    chain.append(True)
    return chain


def _http_get(url: str, *, timeout: float = 30) -> httpx.Response:
    """GET with SSL fallback. Returns the first successful response."""
    last_exc: Exception | None = None
    for verify in _ssl_verify_chain():
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, verify=verify) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"HTTP GET failed for {url}: {last_exc}")


def _fetch_latest_version() -> str:
    """Query GitHub releases API for the latest obscura version tag."""
    resp = _http_get(_GITHUB_API_URL)
    data = resp.json()
    tag: str = data["tag_name"]
    logger.info("Latest Obscura release: %s", tag)
    return tag


def _installed_version() -> str | None:
    """Return the version tag of the locally installed binary, or ``None``."""
    if _VERSION_FILE.exists():
        return _VERSION_FILE.read_text().strip()
    return None


def _download_binary() -> Path:
    """Download and extract the Obscura binary into ``data/obscura/``."""
    asset, binary_name = _platform_asset()
    target = _DATA_DIR / binary_name

    # Fetch latest version from GitHub
    try:
        latest = _fetch_latest_version()
    except Exception as exc:
        # Fallback: if binary already exists, accept it regardless of version
        logger.warning("Failed to check latest Obscura version: %s", exc)
        if target.exists():
            return target
        raise

    installed = _installed_version()

    # Binary exists and version is current → skip download
    if target.exists() and installed == latest:
        return target

    if installed and installed != latest:
        logger.info("Obscura update available: %s → %s", installed, latest)

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    url = (
        f"https://github.com/{_GITHUB_REPO}/releases/download/"
        f"{latest}/{asset}"
    )
    logger.info("Downloading Obscura %s from %s …", latest, url)
    resp = _http_get(url, timeout=120)
    data = resp.content

    try:
        if asset.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    if Path(name).name == binary_name:
                        # Zip Slip protection: ensure extraction stays within _DATA_DIR
                        target_path = (_DATA_DIR / name).resolve()
                        if not str(target_path).startswith(str(_DATA_DIR.resolve())):
                            raise RuntimeError(f"Archive entry '{name}' would extract outside target directory")
                        zf.extract(name, _DATA_DIR)
                        extracted = _DATA_DIR / name
                        if extracted != target:
                            extracted.rename(target)
                        break
                else:
                    raise RuntimeError(f"Binary {binary_name} not found in archive")
        else:
            import tarfile
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                for member in tf.getmembers():
                    if member.name == binary_name:
                        member.name = binary_name
                        tf.extract(member, _DATA_DIR)
                        break
                else:
                    raise RuntimeError(f"Binary {binary_name} not found in archive")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Downloaded file is not a valid zip: {exc}") from exc

    if not target.exists():
        raise RuntimeError(f"Extraction succeeded but binary not found at {target}")

    # Record installed version
    _VERSION_FILE.write_text(latest)
    logger.info("Obscura %s saved to %s", latest, target)
    return target


def resolve_binary() -> str | None:
    """Locate the Obscura binary, downloading if necessary.

    Resolution order: config override → auto-download → system PATH.
    Returns the absolute path, or ``None`` if unavailable.
    """
    try:
        from ...config import get_config
        cfg_path = get_config().browser.binary_path
        if cfg_path:
            p = Path(cfg_path)
            if p.exists():
                return str(p)
    except Exception:
        pass

    try:
        return str(_download_binary())
    except Exception as exc:
        logger.warning("Obscura auto-download failed: %s", exc)

    found = shutil.which("obscura")
    if found:
        return found

    return None


def ensure_ready() -> str:
    """Return the binary path or raise ``ToolExecutionError``."""
    from .base import ToolExecutionError

    global _BINARY_PATH, _BINARY_READY

    if _BINARY_READY is True:
        assert _BINARY_PATH is not None
        return _BINARY_PATH

    path = resolve_binary()
    if path is None:
        _BINARY_READY = False
        raise ToolExecutionError(
            "Obscura browser is not available. "
            "Automatic download failed and no binary found on PATH."
        )
    _BINARY_PATH = path
    _BINARY_READY = True
    return path


def is_available() -> bool:
    """Check availability without raising."""
    global _BINARY_READY
    if _BINARY_READY is None:
        try:
            ensure_ready()
        except Exception:
            _BINARY_READY = False
    return _BINARY_READY is True
