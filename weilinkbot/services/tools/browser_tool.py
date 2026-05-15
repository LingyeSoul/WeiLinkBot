"""browser_fetch / browser_eval — one-shot page rendering via Obscura CLI."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from .base import Tool, ToolExecutionError
from ._obscura import ensure_ready, is_available  # noqa: F401 — re-export for __init__.py
from ._url_validate import validate_url
from .sanitize import sanitize_external_text

logger = logging.getLogger(__name__)

# Tags that never carry reader-facing content
_STRIP_TAGS = frozenset({
    "script", "style", "noscript", "svg", "iframe", "object", "embed",
    "applet", "template", "dialog", "math", "canvas", "map", "audio", "video",
})
_MULTI_BLANK = re.compile(r"\n{3,}")


def _html_to_markdown(html: str) -> str:
    """Convert rendered HTML to structured markdown using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")
    lines: list[str] = []
    _node_to_md(soup.body or soup, lines, depth=0)
    text = "\n".join(lines)
    text = _MULTI_BLANK.sub("\n\n", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _node_to_md(node: Tag | NavigableString, lines: list[str], *, depth: int) -> None:
    if depth > 30 or sum(len(l) for l in lines) > 200_000:
        return
    if isinstance(node, NavigableString):
        t = str(node)
        if t.strip():
            lines.append(t.strip())
        return
    if not isinstance(node, Tag):
        return
    tag = node.name
    if tag in _STRIP_TAGS:
        return

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        text = node.get_text(strip=True)
        if text:
            lines.append("")
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        return
    if tag == "br":
        lines.append("")
        return
    if tag == "hr":
        lines.append("\n---\n")
        return
    if tag == "p":
        text = _inline_text(node)
        if text:
            lines.append("")
            lines.append(text)
        return
    if tag == "blockquote":
        inner: list[str] = []
        for child in node.children:
            _node_to_md(child, inner, depth=depth + 1)
        quoted = "\n".join(inner).strip()
        if quoted:
            lines.append("")
            for q_line in quoted.split("\n"):
                lines.append(f"> {q_line}")
        return
    if tag in ("ul", "ol"):
        lines.append("")
        for i, li in enumerate(node.find_all("li", recursive=False)):
            bullet = f"{i + 1}." if tag == "ol" else "-"
            text = _inline_text(li)
            if text:
                lines.append(f"  {bullet} {text}")
        return
    if tag == "table":
        lines.append("")
        for row in node.find_all("tr"):
            cells = [_inline_text(c) for c in row.find_all(["th", "td"])]
            if any(cells):
                lines.append(" | ".join(cells))
        lines.append("")
        return
    if tag in ("pre", "code"):
        text = node.get_text()
        if text.strip():
            lines.append("")
            lines.append("```")
            lines.append(text.strip())
            lines.append("```")
            lines.append("")
        return
    if tag == "a":
        text = _inline_text(node)
        href = node.get("href", "")
        if text:
            if href and href.startswith(("http://", "https://")) and len(text) < 80:
                lines.append(f"[{text}]({href})")
            else:
                lines.append(text)
        return
    if tag == "img":
        alt = node.get("alt", "").strip()
        if alt:
            lines.append(f"[Image: {alt}]")
        return

    # Generic container — recurse
    inline_parts: list[str] = []
    _BLOCK = frozenset({
        "p", "div", "section", "article", "main", "aside", "nav",
        "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "ul", "ol", "table", "form", "fieldset",
        "hr", "br", "figure", "figcaption", "details", "summary", "address",
    })
    for child in node.children:
        if isinstance(child, Tag) and child.name in _BLOCK:
            _flush(inline_parts, lines)
            _node_to_md(child, lines, depth=depth + 1)
        elif isinstance(child, NavigableString):
            inline_parts.append(str(child))
        else:
            inline_parts.append(_inline_text(child))  # type: ignore[arg-type]
    _flush(inline_parts, lines)


def _inline_text(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name in _STRIP_TAGS:
        return ""
    if node.name == "a":
        href = node.get("href", "")
        text = node.get_text()
        if href and href.startswith(("http://", "https://")) and len(text.strip()) < 80:
            return f"[{text.strip()}]({href})"
        return text
    if node.name == "img":
        alt = node.get("alt", "").strip()
        return f"[Image: {alt}]" if alt else ""
    return node.get_text()


def _flush(parts: list[str], lines: list[str]) -> None:
    if not parts:
        return
    merged = "".join(parts).strip()
    if merged:
        lines.append("")
        lines.append(merged)
    parts.clear()


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

    Executes JavaScript, renders dynamic content, and bypasses most anti-bot protections.
    """

    name = "browser_fetch"
    description = (
        "Fetch and render a web page using a real headless browser with JavaScript support. "
        "Executes JavaScript, renders dynamic/SPA content, "
        "and can bypass anti-bot protections. "
        "Returns the page content as clean readable text or markdown. "
        "Use this for searching the web, reading URLs, or fetching JavaScript-heavy sites and SPAs."
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
                    "'markdown' = structured markdown (rendered HTML converted locally), "
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

        # Obscura CLI only supports html/text/links — request html for markdown
        cli_dump = "html" if dump == "markdown" else dump
        cmd = [bin_path, "fetch", url, "--dump", cli_dump, "--wait-until", wait_until,
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

        if dump == "markdown":
            output = _html_to_markdown(output)
            output = sanitize_external_text(
                output,
                max_single=max_length + 500,
                context="browser-fetched page content",
            )
        elif dump in ("text", "links"):
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
