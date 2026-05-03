"""Workspace service — business logic layer on top of WorkspaceSandbox.

Provides safe, higher-level file operations (read, write, list, grep)
that enforce all sandbox constraints before touching the filesystem.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .workspace_sandbox import SandboxError, WorkspaceSandbox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileInfo:
    """Metadata returned by :meth:`WorkspaceService.list_files`."""

    name: str
    path: str        # relative to workspace root, forward slashes
    is_dir: bool
    size: int | None  # None for directories


@dataclass(frozen=True)
class GrepMatch:
    """A single search hit returned by :meth:`WorkspaceService.grep_files`."""

    path: str    # relative path, forward slashes
    line: int    # 1-based line number
    content: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class WorkspaceService:
    """High-level, sandbox-enforced file operations.

    Every public method resolves and validates paths through the underlying
    :class:`WorkspaceSandbox` before performing any I/O.
    """

    def __init__(self, sandbox: WorkspaceSandbox) -> None:
        self.sandbox = sandbox

    # ------------------------------------------------------------------
    # read_file
    # ------------------------------------------------------------------

    def read_file(
        self,
        rel_path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> str:
        """Read a file and return its content with 1-based line numbers.

        Args:
            rel_path: Path relative to the workspace root.
            offset:   0-based line offset (skip the first *offset* lines).
            limit:    Maximum number of lines to return (``None`` = all).

        Returns:
            Formatted string, one line per row::

                   1 | first line
                   2 | second line

        Raises:
            SandboxError: path violation, blocked extension, missing file,
                          or content exceeds read size limit.
        """
        abs_path = self.sandbox.resolve(rel_path)

        if not abs_path.exists():
            raise SandboxError(rel_path, "file does not exist")
        if not abs_path.is_file():
            raise SandboxError(rel_path, "path is not a file")

        self.sandbox.check_extension(abs_path)
        self.sandbox.check_read_size(abs_path.stat().st_size)

        text = abs_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        if limit is not None:
            lines = lines[offset : offset + limit]
        else:
            lines = lines[offset:]

        width = len(str(offset + len(lines)))
        return "\n".join(
            f"{offset + i + 1:>{width}} | {line}"
            for i, line in enumerate(lines)
        )

    # ------------------------------------------------------------------
    # write_file
    # ------------------------------------------------------------------

    def write_file(
        self,
        rel_path: str,
        content: str,
        append: bool = False,
    ) -> int:
        """Write *content* to a file, creating parent directories as needed.

        Args:
            rel_path: Destination path relative to the workspace root.
            content:  UTF-8 text to write.
            append:   If ``True``, append to the existing file instead of
                      overwriting.

        Returns:
            Number of bytes written (UTF-8 encoded length of *content*).

        Raises:
            SandboxError: path violation, blocked extension, or content
                          exceeds write size limit.
        """
        abs_path = self.sandbox.resolve(rel_path)

        self.sandbox.check_extension(abs_path)
        self.sandbox.check_write_size(len(content.encode("utf-8")))

        abs_path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        with abs_path.open(mode, encoding="utf-8") as fh:
            fh.write(content)

        written = len(content.encode("utf-8"))
        logger.debug(
            "wrote %d bytes to %s (append=%s)", written, abs_path, append,
        )
        return written

    # ------------------------------------------------------------------
    # list_files
    # ------------------------------------------------------------------

    def list_files(
        self,
        rel_path: str = "",
        pattern: str = "*",
    ) -> list[FileInfo]:
        """List files and directories matching *pattern*.

        Args:
            rel_path: Directory to list (defaults to workspace root).
            pattern:  Glob pattern (default ``"*"``).

        Returns:
            Up to ``sandbox.list_max_entries`` :class:`FileInfo` entries.
            Hidden files (names starting with ``.``) are excluded.

        Raises:
            SandboxError: path violation.
        """
        abs_dir = self.sandbox.resolve(rel_path) if rel_path else self.sandbox.root
        results: list[FileInfo] = []
        max_entries = self.sandbox.list_max_entries

        for entry in sorted(abs_dir.glob(pattern)):
            # Skip hidden files and directories.
            if entry.name.startswith("."):
                continue

            # Build a relative path using forward slashes.
            rel = entry.relative_to(self.sandbox.root).as_posix()

            if entry.is_dir():
                results.append(FileInfo(
                    name=entry.name,
                    path=rel,
                    is_dir=True,
                    size=None,
                ))
            elif entry.is_file():
                results.append(FileInfo(
                    name=entry.name,
                    path=rel,
                    is_dir=False,
                    size=entry.stat().st_size,
                ))

            if len(results) >= max_entries:
                break

        return results

    # ------------------------------------------------------------------
    # grep_files
    # ------------------------------------------------------------------

    def grep_files(
        self,
        query: str,
        rel_path: str = "",
        use_regex: bool = False,
    ) -> list[GrepMatch]:
        """Search files recursively for *query*.

        Args:
            query:    Plain text or regex pattern to search for.
            rel_path: Subdirectory to confine the search to (default:
                      workspace root).
            use_regex: Treat *query* as a regular expression.

        Returns:
            Up to ``sandbox.grep_max_results`` :class:`GrepMatch` entries.
            For plain-text searches the comparison is case-insensitive.
            Files with blocked extensions or exceeding ``read_max_size``
            are silently skipped.

        Raises:
            SandboxError: if *rel_path* itself is invalid.
            re.error:     if *use_regex* is ``True`` and *query* is invalid.
        """
        base = self.sandbox.resolve(rel_path) if rel_path else self.sandbox.root
        max_results = self.sandbox.grep_max_results

        # Compile the search pattern once.
        if use_regex:
            regex = re.compile(query)
        else:
            regex = re.compile(re.escape(query), re.IGNORECASE)

        results: list[GrepMatch] = []
        limit_reached = False

        for file_path in base.rglob("*"):
            # Only process regular files.
            if not file_path.is_file():
                continue

            # Skip blocked extensions.
            try:
                self.sandbox.check_extension(file_path)
            except SandboxError:
                continue

            # Skip files that exceed the read size limit.
            try:
                size = file_path.stat().st_size
            except OSError:
                continue
            if size > self.sandbox.read_max_size:
                continue

            # Build relative path for result reporting.
            rel = file_path.relative_to(self.sandbox.root).as_posix()

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    results.append(GrepMatch(
                        path=rel,
                        line=lineno,
                        content=line,
                    ))
                    if len(results) >= max_results:
                        limit_reached = True
                        break

            if limit_reached:
                break

        return results
