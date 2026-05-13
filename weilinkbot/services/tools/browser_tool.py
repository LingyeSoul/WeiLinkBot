"""browser_fetch / browser_eval — one-shot page rendering via Obscura CLI."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .base import Tool, ToolExecutionError
from ._obscura import ensure_ready, is_available  # noqa: F401 — re-export for __init__.py
from ._url_validate import validate_url
from .sanitize import sanitize_external_text

logger = logging.getLogger(__name__)


def _apply_config_defaults(*, timeout: int, stealth: bool) -> tuple[int, bool]:
    try:
        from ...config import get_config
        browser_cfg = get_config().browser
        if timeout == 30 and browser_cfg.default_timeout != 30:
            timeout = browser_cfg.default_timeout
        if not stealth and browser_cfg.stealth:
            stealth = True
    except Exception:
        pass
    return timeout, stealth


# ── browser_fetch ─────────────────────────────────────────────────────────────


class BrowserFetchTool(Tool):
    """Fetch a web page using a real headless browser (Obscura).

    Unlike ``web_fetch`` (plain HTTP), this tool executes JavaScript,
    renders dynamic content, and bypasses most anti-bot protections.
    """

    name = "browser_fetch"
    description = (
        "Fetch and render a web page using a real headless browser with JavaScript support. "
        "Unlike web_fetch (plain HTTP), this executes JavaScript, renders dynamic/SPA content, "
        "and can bypass anti-bot protections. "
        "Returns the page content as clean readable text or markdown. "
        "Use this for JavaScript-heavy sites, SPAs, or when web_fetch returns empty/broken content."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the web page to fetch.",
            },
            "dump": {
                "type": "string",
                "enum": ["text", "html", "links", "markdown"],
                "description": (
                    "Output format. "
                    "'text' (default) = readable plain text, "
                    "'markdown' = structured markdown via CDP, "
                    "'html' = raw rendered HTML, "
                    "'links' = extracted links only."
                ),
            },
            "eval": {
                "type": "string",
                "description": (
                    "A JavaScript expression to evaluate after the page loads. "
                    "Example: 'document.title'"
                ),
            },
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle0"],
                "description": "When to consider the page loaded (default: 'load'). Use 'networkidle0' for SPAs.",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum seconds to wait for page load (5–60, default 30).",
            },
            "stealth": {
                "type": "boolean",
                "description": "Enable anti-fingerprinting and tracker blocking (default: false).",
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum characters to return (1000–20000, default 8000).",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    async def execute(
        self,
        *,
        url: str,
        dump: str = "text",
        eval: str | None = None,
        wait_until: str = "load",
        timeout: int = 30,
        stealth: bool = False,
        max_length: int = 8000,
        **kwargs,
    ) -> str:
        validate_url(url)
        timeout, stealth = _apply_config_defaults(timeout=timeout, stealth=stealth)
        timeout = max(5, min(timeout, 60))
        max_length = max(1000, min(max_length, 20_000))

        bin_path = ensure_ready()

        cmd = [bin_path, "fetch", url, "--dump", dump, "--wait-until", wait_until,
               "--timeout", str(timeout), "--quiet"]
        if stealth:
            cmd.append("--stealth")
        if eval:
            cmd.extend(["--eval", eval])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 10,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise ToolExecutionError(f"Browser fetch timed out after {timeout + 10}s")
        except FileNotFoundError:
            raise ToolExecutionError(f"Obscura binary not found at: {bin_path}")

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise ToolExecutionError(
                f"Obscura exited with code {proc.returncode}: {err[:300]}"
            )

        output = stdout.decode(errors="replace").strip()

        if not output:
            return f"Page fetched but produced no content.\nURL: {url}"

        if dump in ("text", "links", "markdown"):
            output = sanitize_external_text(
                output,
                max_single=max_length + 500,
                context="browser-fetched page content",
            )
        else:
            if len(output) > max_length:
                output = output[:max_length] + "\n\n[Content truncated…]"

        return f"URL: {url}\nFormat: {dump}\n\n" + output


# ── browser_eval ──────────────────────────────────────────────────────────────


class BrowserEvalTool(Tool):
    """Execute JavaScript in a headless browser and return the result."""

    name = "browser_eval"
    description = (
        "Load a web page in a headless browser and execute a JavaScript expression to extract data. "
        "The page is fully rendered (JS executed) before evaluation. "
        "Use this to scrape structured data from dynamic websites."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to load.",
            },
            "expression": {
                "type": "string",
                "description": (
                    "JavaScript expression to evaluate. Must return a JSON-serializable value. "
                    "Examples: document.title, document.querySelector('#price')?.textContent"
                ),
            },
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle0"],
                "description": "When to evaluate (default: 'networkidle0' for best dynamic content).",
            },
            "timeout": {
                "type": "integer",
                "description": "Maximum seconds to wait (5–60, default 30).",
            },
            "stealth": {
                "type": "boolean",
                "description": "Enable anti-fingerprinting (default: false).",
            },
        },
        "required": ["url", "expression"],
        "additionalProperties": False,
    }

    async def execute(
        self,
        *,
        url: str,
        expression: str,
        wait_until: str = "networkidle0",
        timeout: int = 30,
        stealth: bool = False,
        **kwargs,
    ) -> str:
        validate_url(url)
        timeout, stealth = _apply_config_defaults(timeout=timeout, stealth=stealth)
        timeout = max(5, min(timeout, 60))

        bin_path = ensure_ready()
        cmd = [bin_path, "fetch", url, "--eval", expression,
               "--wait-until", wait_until, "--timeout", str(timeout), "--quiet"]
        if stealth:
            cmd.append("--stealth")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 10,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise ToolExecutionError(f"Browser eval timed out after {timeout + 10}s")
        except FileNotFoundError:
            raise ToolExecutionError(f"Obscura binary not found at: {bin_path}")

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise ToolExecutionError(
                f"Obscura exited with code {proc.returncode}: {err[:300]}"
            )

        output = stdout.decode(errors="replace").strip()

        if not output:
            return f"Expression evaluated to empty result.\nURL: {url}\nExpression: {expression}"

        return sanitize_external_text(
            f"URL: {url}\nExpression: {expression}\nResult:\n{output}",
            max_single=10_000,
            context="browser eval result",
        )
