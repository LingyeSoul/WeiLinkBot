"""workspace_read tool — read file content from the workspace."""

from __future__ import annotations
from typing import Any
from .base import Tool


class WorkspaceReadTool(Tool):
    name = "workspace_read"
    description = (
        "Read the content of a file in the workspace. "
        "Returns the file content with line numbers. "
        "Use offset and limit to read specific sections of large files."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file within the workspace.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (0-based). Defaults to 0.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Defaults to all.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_service) -> None:
        self._ws = workspace_service

    async def execute(self, *, path: str, offset: int = 0, limit: int | None = None, **kwargs) -> str:
        return self._ws.read_file(path, offset=offset, limit=limit)
