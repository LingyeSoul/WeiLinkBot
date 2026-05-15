"""workspace_edit tool — edit files in the workspace by replacing text."""

from __future__ import annotations

import re
from typing import Any

from .base import Tool

# Matches read_file output line prefix: "  1 | content" or "123 | content"
_LINE_PREFIX = re.compile(r"^\s*\d+ \| ")


class WorkspaceEditTool(Tool):
    name = "workspace_edit"
    description = (
        "Edit a file in the workspace by replacing old_text with new_text. "
        "More efficient than full rewrites for small changes. "
        "If old_text matches multiple times, provide more context or set replace_all=true."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file within the workspace.",
            },
            "old_text": {
                "type": "string",
                "description": "The exact text to find and replace.",
            },
            "new_text": {
                "type": "string",
                "description": "The replacement text.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "If true, replace all occurrences. Default false.",
            },
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_service) -> None:
        self._ws = workspace_service

    async def execute(
        self, *, path: str, old_text: str, new_text: str,
        replace_all: bool = False, **kwargs,
    ) -> str:
        try:
            content = self._ws.read_file(path)
        except Exception as e:
            return f"Error: Cannot read file '{path}': {e}"

        # Strip line numbers from read_file output: "  1 | content"
        lines = []
        for line in content.split("\n"):
            m = _LINE_PREFIX.match(line)
            lines.append(line[m.end():] if m else line)
        file_content = "\n".join(lines)

        count = file_content.count(old_text)
        if count == 0:
            return f"Error: old_text not found in '{path}'. Check the file content with workspace_read first."
        if count > 1 and not replace_all:
            return (
                f"Warning: old_text appears {count} times in '{path}'. "
                "Provide more context to make it unique, or set replace_all=true."
            )

        if replace_all:
            new_content = file_content.replace(old_text, new_text)
        else:
            new_content = file_content.replace(old_text, new_text, 1)

        bytes_written = self._ws.write_file(path, new_content)
        replaced = count if replace_all else 1
        return f"Edited '{path}': replaced {replaced} occurrence(s), wrote {bytes_written} bytes."
