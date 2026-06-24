"""workspace_shell tool — execute shell commands in the workspace."""

from __future__ import annotations
import logging
from typing import Any
from .base import Tool

logger = logging.getLogger(__name__)


class WorkspaceShellTool(Tool):
    name = "workspace_shell"
    description = (
        "Execute a shell command in the workspace directory. "
        "Use this to run Python scripts, install packages (pip install), "
        "use git, run build commands, and other development tasks. "
        "The command runs in the workspace root directory. "
        "Returns stdout, stderr, and exit code."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The shell command to execute. Examples: "
                    "'pip install requests', 'python main.py', 'git status', 'dir'"
                ),
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Defaults to 60.",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self, shell_sandbox, guard_engine=None) -> None:
        self._shell = shell_sandbox
        self._guard = guard_engine

    async def execute(self, *, command: str, timeout: int | None = None, **kwargs) -> str:
        # Pre-execution security guard
        if self._guard is not None:
            result = self._guard.guard("workspace_shell", {"command": command})
            if not result.is_safe:
                logger.warning(
                    "Tool guard blocked command: %s (severity=%s, findings=%d)",
                    command[:100], result.max_severity.value, len(result.findings),
                )
                return result.format_block_reason()

        result = await self._shell.execute(command, timeout=timeout)
        return result.format()
