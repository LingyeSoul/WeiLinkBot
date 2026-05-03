"""workspace_write tool — write content to a file in the workspace."""

from __future__ import annotations
from typing import Any
from .base import Tool


class WorkspaceWriteTool(Tool):
    name = "workspace_write"
    description = (
        "Write content to a file in the workspace. "
        "Creates parent directories if needed. "
        "Use append=true to add to an existing file."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path for the file within the workspace.",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file.",
            },
            "append": {
                "type": "boolean",
                "description": "If true, append to existing content. If false (default), overwrite.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_service) -> None:
        self._ws = workspace_service

    async def execute(self, *, path: str, content: str, append: bool = False, **kwargs) -> str:
        bytes_written = self._ws.write_file(path, content, append=append)
        return f"Written {bytes_written} bytes to {path}"
