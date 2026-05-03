"""workspace_list tool — list files and directories in the workspace."""

from __future__ import annotations
from typing import Any
from .base import Tool


class WorkspaceListTool(Tool):
    name = "workspace_list"
    description = (
        "List files and directories in the workspace. "
        "Supports glob patterns (e.g. '*.md', '**/*.txt'). "
        "Defaults to listing the workspace root."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative directory path within the workspace. Defaults to root.",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files. Defaults to '*'.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, workspace_service) -> None:
        self._ws = workspace_service

    async def execute(self, *, path: str = "", pattern: str = "*", **kwargs) -> str:
        entries = self._ws.list_files(path, pattern)
        if not entries:
            return "No files found."
        lines = []
        for e in entries:
            kind = "DIR " if e.is_dir else "FILE"
            size = f" ({e.size} bytes)" if e.size is not None else ""
            lines.append(f"[{kind}] {e.path}{size}")
        return "\n".join(lines)
