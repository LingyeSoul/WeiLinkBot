"""MCP tool/resource/prompt adapters — wraps MCP capabilities into the Tool base class."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from .base import Tool

logger = logging.getLogger(__name__)

_TRANSIENT_EXC_NAMES: frozenset[str] = frozenset((
    "ClosedResourceError", "BrokenResourceError", "EndOfStream",
    "BrokenPipeError", "ConnectionResetError", "ConnectionRefusedError",
    "ConnectionAbortedError", "ConnectionError",
))


def _is_transient(exc: BaseException) -> bool:
    return type(exc).__name__ in _TRANSIENT_EXC_NAMES


def _extract_nullable_branch(options: Any) -> tuple[dict[str, Any], bool] | None:
    """Return the single non-null branch for nullable unions."""
    if not isinstance(options, list):
        return None
    non_null: list[dict[str, Any]] = []
    saw_null = False
    for option in options:
        if not isinstance(option, dict):
            return None
        if option.get("type") == "null":
            saw_null = True
            continue
        non_null.append(option)
    if saw_null and len(non_null) == 1:
        return non_null[0], True
    return None


def _normalize_schema_for_openai(schema: Any) -> dict[str, Any]:
    """Normalize nullable JSON Schema patterns for model API compatibility."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    normalized = dict(schema)

    raw_type = normalized.get("type")
    if isinstance(raw_type, list):
        non_null = [item for item in raw_type if item != "null"]
        if "null" in raw_type and len(non_null) == 1:
            normalized["type"] = non_null[0]
            normalized["nullable"] = True

    for key in ("oneOf", "anyOf"):
        nullable_branch = _extract_nullable_branch(normalized.get(key))
        if nullable_branch is not None:
            branch, _ = nullable_branch
            merged = {k: v for k, v in normalized.items() if k != key}
            merged.update(branch)
            normalized = merged
            normalized["nullable"] = True
            break

    if "properties" in normalized and isinstance(normalized["properties"], dict):
        normalized["properties"] = {
            name: _normalize_schema_for_openai(prop) if isinstance(prop, dict) else prop
            for name, prop in normalized["properties"].items()
        }

    if "items" in normalized and isinstance(normalized["items"], dict):
        normalized["items"] = _normalize_schema_for_openai(normalized["items"])

    if normalized.get("type") != "object":
        return normalized

    normalized.setdefault("properties", {})
    normalized.setdefault("required", [])
    return normalized


class MCPToolAdapter(Tool):
    """Adapts an MCP server tool to the WeiLinkBot Tool interface."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        parameters: dict[str, Any],
        executor: Any,
        tool_timeout: int = 30,
    ) -> None:
        self.name = f"{server_name}__{tool_name}"
        self.description = description
        self.parameters = _normalize_schema_for_openai(parameters)
        self._executor = executor
        self._server_name = server_name
        self._tool_name = tool_name
        self._tool_timeout = tool_timeout

    async def execute(self, **kwargs) -> str:
        for attempt in range(2):
            try:
                result = await asyncio.wait_for(
                    self._executor.execute_tool(
                        self._server_name, self._tool_name, kwargs
                    ),
                    timeout=self._tool_timeout,
                )
                return result
            except asyncio.TimeoutError:
                logger.warning("MCP tool '%s' timed out after %ds", self.name, self._tool_timeout)
                return f"(MCP tool call timed out after {self._tool_timeout}s)"
            except Exception as exc:
                if _is_transient(exc) and attempt == 0:
                    logger.warning("MCP tool '%s' transient error, retrying: %s", self.name, type(exc).__name__)
                    await asyncio.sleep(1)
                    continue
                logger.error("MCP tool '%s' failed: %s: %s", self.name, type(exc).__name__, exc)
                return f"(MCP tool call failed: {type(exc).__name__})"
        return "(MCP tool call failed)"


class MCPResourceAdapter(Tool):
    """Wraps an MCP resource as a read-only tool."""

    def __init__(
        self,
        server_name: str,
        resource: Any,
        executor: Any,
        tool_timeout: int = 30,
    ) -> None:
        self._uri = resource.uri
        self.name = f"{server_name}__resource__{resource.name}"
        desc = resource.description or resource.name
        self.description = f"[MCP Resource] {desc}\nURI: {self._uri}"
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        self._executor = executor
        self._server_name = server_name
        self._tool_timeout = tool_timeout

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs) -> str:
        for attempt in range(2):
            try:
                return await asyncio.wait_for(
                    self._executor.read_resource(self._server_name, self._uri),
                    timeout=self._tool_timeout,
                )
            except asyncio.TimeoutError:
                return f"(MCP resource read timed out after {self._tool_timeout}s)"
            except Exception as exc:
                if _is_transient(exc) and attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return f"(MCP resource read failed: {type(exc).__name__})"
        return "(MCP resource read failed)"


class MCPPromptAdapter(Tool):
    """Wraps an MCP prompt as a read-only tool."""

    def __init__(
        self,
        server_name: str,
        prompt: Any,
        executor: Any,
        tool_timeout: int = 30,
    ) -> None:
        self._prompt_name = prompt.name
        self.name = f"{server_name}__prompt__{prompt.name}"
        desc = prompt.description or prompt.name
        self.description = f"[MCP Prompt] {desc}"

        properties: dict[str, Any] = {}
        required: list[str] = []
        for arg in prompt.arguments or []:
            prop: dict[str, Any] = {"type": "string"}
            if getattr(arg, "description", None):
                prop["description"] = arg.description
            properties[arg.name] = prop
            if arg.required:
                required.append(arg.name)
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "required": required,
        }
        self._executor = executor
        self._server_name = server_name
        self._tool_timeout = tool_timeout

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs) -> str:
        for attempt in range(2):
            try:
                return await asyncio.wait_for(
                    self._executor.get_prompt(
                        self._server_name, self._prompt_name, kwargs
                    ),
                    timeout=self._tool_timeout,
                )
            except asyncio.TimeoutError:
                return f"(MCP prompt timed out after {self._tool_timeout}s)"
            except Exception as exc:
                if _is_transient(exc) and attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return f"(MCP prompt failed: {type(exc).__name__})"
        return "(MCP prompt failed)"
