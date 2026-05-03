"""workspace_grep tool — search file contents in the workspace."""

from __future__ import annotations
from typing import Any
from .base import Tool


class WorkspaceGrepTool(Tool):
    name = "workspace_grep"
    description = (
        "Search for text patterns across files in the workspace. "
        "Returns matching lines with file paths and line numbers."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text or regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Limit search to a subdirectory. Defaults to entire workspace.",
            },
            "regex": {
                "type": "boolean",
                "description": "Whether to treat query as a regex pattern. Defaults to false.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_service) -> None:
        self._ws = workspace_service

    async def execute(self, *, query: str, path: str = "", regex: bool = False, **kwargs) -> str:
        matches = self._ws.grep_files(query, rel_path=path, use_regex=regex)
        if not matches:
            return "No matches found."
        lines = []
        for m in matches:
            lines.append(f"{m.path}:{m.line}: {m.content}")
        return "\n".join(lines)
