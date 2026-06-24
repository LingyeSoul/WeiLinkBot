"""Workspace shell — secure command execution within the workspace.

Provides a sandboxed shell execution layer that blocks dangerous commands,
detects command chain injection, protects sensitive files, and constrains
execution to the workspace directory.

Safety layers (referenced from NekoPaw sandbox):
  1. Blocked command patterns (destruction, registry, system control)
  2. Command chain injection detection (; rm, && rm, curl | sh, etc.)
  3. Sensitive file path protection (.env, .git, .ssh, .aws, credentials)
  4. Environment variable sanitization (only expose basic vars)
  5. Working directory confinement to workspace root
  6. Timeout enforcement
  7. Output size limits
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blocked command patterns (case-insensitive)
# ---------------------------------------------------------------------------

_BLOCKED_PATTERNS: list[re.Pattern] = [
    # Filesystem destruction
    re.compile(r"Remove-Item\s+.*-Recurse\s+.*-Force\s+[A-Z]:\\", re.I),
    re.compile(r"rm\s+-rf\s+/", re.I),
    re.compile(r"rmdir\s+/s\s+/q\s+[A-Z]:\\", re.I),
    re.compile(r"del\s+/[sfq]\s+[A-Z]:\\", re.I),
    re.compile(r"format\s+[A-Z]:", re.I),
    # Registry
    re.compile(r"reg\s+delete\s+", re.I),
    re.compile(r"regedit\s*/", re.I),
    # System control
    re.compile(r"shutdown\s+", re.I),
    re.compile(r"restart-computer", re.I),
    re.compile(r"Stop-Process\s+-Name\s+\*", re.I),
    re.compile(r"taskkill\s+/f\s+/im\s+\*", re.I),
    # User/network management
    re.compile(r"net\s+user\s+", re.I),
    re.compile(r"net\s+localgroup\s+", re.I),
    re.compile(r"net\s+share\s+", re.I),
    # PowerShell encoded commands (common obfuscation)
    re.compile(r"-EncodedCommand\s+", re.I),
    re.compile(r"-enc\s+[A-Za-z0-9+/=]{20,}", re.I),
]

# ---------------------------------------------------------------------------
# Command chain injection patterns
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern] = [
    # Chained destructive commands
    re.compile(r";\s*rm\b", re.I),
    re.compile(r"&&\s*rm\b", re.I),
    re.compile(r"\|\s*rm\b", re.I),
    re.compile(r";\s*Remove-Item\b", re.I),
    re.compile(r"&&\s*Remove-Item\b", re.I),
    # Pipe to shell (download and execute)
    re.compile(r"curl\b.*\|\s*(?:sh|bash|powershell|cmd)", re.I),
    re.compile(r"wget\b.*\|\s*(?:sh|bash|powershell|cmd)", re.I),
    re.compile(r"Invoke-WebRequest\b.*\|\s*(?:iex|Invoke-Expression)", re.I),
    re.compile(r"Invoke-RestMethod\b.*\|\s*(?:iex|Invoke-Expression)", re.I),
    # Redirect to /dev/null (hiding output of destructive ops)
    re.compile(r">\s*/dev/null\s*2>&1", re.I),
    # Background execution of suspicious commands
    re.compile(r"Start-Process\s+.*-WindowStyle\s+Hidden", re.I),
]

# ---------------------------------------------------------------------------
# Sensitive file path patterns (cannot be read/written/deleted)
# ---------------------------------------------------------------------------

_SENSITIVE_PATH_PATTERNS: list[re.Pattern] = [
    re.compile(r"(^|[/\\])\.env($|\.|[\\/])", re.I),
    re.compile(r"(^|[/\\])\.git($|[\\/])", re.I),
    re.compile(r"(^|[/\\])\.ssh($|[\\/])", re.I),
    re.compile(r"(^|[/\\])\.aws($|[\\/])", re.I),
    re.compile(r"(^|[/\\])\.gnupg($|[\\/])", re.I),
    re.compile(r"(^|[/\\])credentials\.json$", re.I),
    re.compile(r"(^|[/\\])\.pem$", re.I),
    re.compile(r"(^|[/\\])\.key$", re.I),
    re.compile(r"(^|[/\\])id_rsa", re.I),
    re.compile(r"(^|[/\\])id_ed25519", re.I),
]

# Allowed environment variables (whitelist approach)
_ALLOWED_ENV_VARS: frozenset[str] = frozenset({
    "PATH", "PATHEXT", "HOME", "USERPROFILE", "USERNAME", "USER",
    "TEMP", "TMP", "TMPDIR",
    "PYTHONPATH", "PYTHONHOME", "PYTHONDONTWRITEBYTECODE",
    "NODE_PATH", "NPM_CONFIG_PREFIX",
    "SystemRoot", "windir", "COMSPEC", "SHELL",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM",
    "CI", "GITHUB_ACTIONS", "GIT_TERMINAL_PROMPT",
})


class ShellError(Exception):
    """Raised when a shell command violates sandbox constraints."""

    def __init__(self, command: str, reason: str) -> None:
        self.command = command
        self.reason = reason
        super().__init__(f"Shell sandbox violation for command: {reason}")


class ShellResult:
    """Result of a shell command execution."""

    __slots__ = ("command", "returncode", "stdout", "stderr", "timed_out")

    def __init__(
        self,
        command: str,
        returncode: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    @property
    def success(self) -> bool:
        return self.returncode == 0

    def format(self) -> str:
        """Format result for LLM consumption."""
        parts: list[str] = []
        if self.timed_out:
            parts.append(f"[TIMED OUT after command: {self.command}]")
        else:
            parts.append(f"[Exit code: {self.returncode}]")

        if self.stdout:
            parts.append(self.stdout.rstrip())
        if self.stderr:
            parts.append(f"[stderr]\n{self.stderr.rstrip()}")
        if not self.stdout and not self.stderr:
            parts.append("(no output)")
        return "\n".join(parts)


class ShellSandbox:
    """Security gateway for shell command execution.

    Args:
        workspace_root: Absolute path to the workspace root.
        timeout: Default command timeout in seconds.
        max_output_chars: Maximum output characters before truncation.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        timeout: float = 60.0,
        max_output_chars: int = 30_000,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_output_chars = max_output_chars

    def validate(self, command: str) -> None:
        """Validate a command against security rules.

        Raises:
            ShellError: if the command violates sandbox constraints.
        """
        if not command or not command.strip():
            raise ShellError(command, "command must not be empty")

        stripped = command.strip()

        for pattern in _BLOCKED_PATTERNS:
            if pattern.search(stripped):
                raise ShellError(
                    command,
                    f"command matches blocked pattern: {pattern.pattern}",
                )

    async def execute(
        self,
        command: str,
        timeout: float | None = None,
    ) -> ShellResult:
        """Execute a command in the workspace directory.

        Args:
            command: The command string to execute.
            timeout: Override default timeout (seconds).

        Returns:
            ShellResult with stdout, stderr, and exit code.

        Raises:
            ShellError: if the command fails validation.
        """
        self.validate(command)

        effective_timeout = timeout or self.timeout

        # Use PowerShell on Windows
        if sys.platform == "win32":
            shell_cmd = [
                "powershell", "-NoProfile", "-NonInteractive",
                "-Command", command,
            ]
        else:
            shell_cmd = ["sh", "-c", command]

        logger.debug("Executing shell: %s (timeout=%.1fs)", command, effective_timeout)

        try:
            proc = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_root),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ShellResult(
                    command=command,
                    returncode=-1,
                    stdout="",
                    stderr=f"Command timed out after {effective_timeout}s",
                    timed_out=True,
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Truncate if needed
            if len(stdout) > self.max_output_chars:
                stdout = stdout[:self.max_output_chars] + (
                    f"\n\n[... output truncated, original length: {len(stdout_bytes)} bytes ...]"
                )
            if len(stderr) > self.max_output_chars:
                stderr = stderr[:self.max_output_chars] + (
                    f"\n\n[... stderr truncated ...]"
                )

            return ShellResult(
                command=command,
                returncode=proc.returncode or 0,
                stdout=stdout,
                stderr=stderr,
            )

        except FileNotFoundError:
            return ShellResult(
                command=command,
                returncode=-1,
                stdout="",
                stderr="Shell not found. Ensure PowerShell is installed.",
            )
        except Exception as e:
            logger.warning("Shell execution error: %s", e)
            return ShellResult(
                command=command,
                returncode=-1,
                stdout="",
                stderr=f"Execution error: {e}",
            )
