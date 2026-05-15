"""Workspace sandbox — security gateway for all workspace file operations.

Every read / write / list / grep must pass through WorkspaceSandbox
to ensure paths stay inside the workspace root and size limits are respected.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCKED_EXTENSIONS: frozenset[str] = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr",
    ".dll", ".so", ".dylib",
    ".vbs", ".vbe",
    ".jar", ".class", ".elf", ".appimage",
})

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SandboxError(Exception):
    """Raised when a file operation violates sandbox constraints.

    Attributes:
        path:  The path that triggered the violation (may be relative or absolute).
        reason: Human-readable explanation of the violation.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Sandbox violation for {path!r}: {reason}")


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


class WorkspaceSandbox:
    """Security gateway that validates and constrains all workspace I/O.

    Args:
        root: Absolute path to the workspace root directory.
              Created on disk if it does not already exist.
        blocked_extensions: File suffixes that must never be accessed.
        read_max_size: Maximum bytes allowed for a single read.
        write_max_size: Maximum bytes allowed for a single write.
        list_max_entries: Maximum entries returned by a directory listing.
        grep_max_results: Maximum results returned by a grep operation.
    """

    def __init__(
        self,
        root: str | Path,
        blocked_extensions: frozenset[str] | None = None,
        read_max_size: int = 10 * 1024 * 1024,        # 10 MB
        write_max_size: int = 10 * 1024 * 1024,       # 10 MB
        list_max_entries: int = 5000,
        grep_max_results: int = 1000,
    ) -> None:
        self.root: Path = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.blocked_extensions = blocked_extensions or BLOCKED_EXTENSIONS
        self.read_max_size = read_max_size
        self.write_max_size = write_max_size
        self.list_max_entries = list_max_entries
        self.grep_max_results = grep_max_results

        logger.debug(
            "WorkspaceSandbox initialised: root=%s  blocked_ext=%d  "
            "read_max=%d  write_max=%d  list_max=%d  grep_max=%d",
            self.root,
            len(self.blocked_extensions),
            self.read_max_size,
            self.write_max_size,
            self.list_max_entries,
            self.grep_max_results,
        )

    # ------------------------------------------------------------------
    # Path resolution & validation
    # ------------------------------------------------------------------

    def resolve(self, rel_path: str | Path) -> Path:
        """Resolve *rel_path* to an absolute path inside the workspace root.

        Security checks performed (in order):

        1. Reject empty / whitespace-only paths.
        2. Reject absolute paths (Unix ``/``, Windows drive ``C:\\``,
           UNC ``\\\\``).
        3. Reject paths that contain ``..`` components.
        4. ``Path.resolve()`` to canonical absolute, then verify the result
           is a descendant of ``self.root``.
           Because ``resolve()`` follows symlinks, a symlink that points
           outside the workspace will resolve to an external path and fail
           the ``relative_to`` containment check — so symlink escapes are
           caught here without a separate step.

        Returns:
            The validated absolute :class:`Path`.

        Raises:
            SandboxError: if any check fails.
        """
        raw = str(rel_path)

        # 1. Empty / whitespace
        if not raw or not raw.strip():
            raise SandboxError(raw, "path must not be empty")

        # 2. Absolute paths
        #    Detect Unix-style (/foo), Windows drive-style (C:\foo, C:/foo),
        #    and UNC paths (\\server\share).
        if os.path.isabs(raw):
            raise SandboxError(raw, "absolute paths are not allowed")

        # 3. Parent traversal
        #    Split on both separators so Linux and Windows are covered.
        parts = Path(raw).parts
        if ".." in parts:
            raise SandboxError(raw, "path must not contain '..'")

        # 4. Resolve to canonical absolute path and containment check.
        #    Path.resolve(strict=False) follows symlinks that exist; if the
        #    ultimate target does not exist the partial resolution is still
        #    returned and is safe to compare.
        candidate = (self.root / raw).resolve()

        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise SandboxError(
                str(candidate),
                "resolved path escapes workspace root",
            )

        return candidate

    # ------------------------------------------------------------------
    # Extension / size checks
    # ------------------------------------------------------------------

    def check_extension(self, path: str | Path) -> None:
        """Raise :class:`SandboxError` if *path*'s suffix is blocked."""
        suffix = Path(path).suffix.lower()
        if suffix in self.blocked_extensions:
            raise SandboxError(str(path), f"file extension {suffix!r} is blocked")

    def check_read_size(self, size: int) -> None:
        """Raise :class:`SandboxError` if *size* exceeds the read limit."""
        if size > self.read_max_size:
            raise SandboxError(
                "",
                f"read size {size} exceeds limit {self.read_max_size}",
            )

    def check_write_size(self, size: int) -> None:
        """Raise :class:`SandboxError` if *size* exceeds the write limit."""
        if size > self.write_max_size:
            raise SandboxError(
                "",
                f"write size {size} exceeds limit {self.write_max_size}",
            )
