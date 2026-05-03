"""web_search tool — search the web using DuckDuckGo."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .base import Tool, ToolExecutionError
from .sanitize import sanitize_external_text, build_results_header

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web for up-to-date information. "
        "Returns a list of search results with titles, URLs, and snippets. "
        "Use this when you need current information, facts, or answers not in your training data."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-10, default 5).",
            },
            "region": {
                "type": "string",
                "description": "Search region, e.g. 'cn-zh' for Chinese, 'wt-wt' for global. Default 'wt-wt'.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    async def execute(
        self,
        *,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
        **kwargs,
    ) -> str:
        if not query.strip():
            raise ToolExecutionError("Search query cannot be empty")

        max_results = max(1, min(max_results, 10))

        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                raise ToolExecutionError(
                    "web_search tool requires the 'ddgs' package. "
                    "Install it with: pip install ddgs"
                )

        def _search() -> list[dict]:
            with DDGS() as ddgs:
                return ddgs.text(
                    query=query,
                    region=region,
                    max_results=max_results,
                )

        try:
            results = await asyncio.to_thread(_search)
        except Exception as e:
            logger.error("DuckDuckGo search failed: %s", e)
            raise ToolExecutionError(f"Search failed: {e}")

        if not results:
            return "No search results found."

        parts: list[str] = [build_results_header()]
        for i, r in enumerate(results, 1):
            title = sanitize_external_text(
                r.get("title", "No title"),
                max_single=200,
                context=f"result #{i} title",
            )
            href = r.get("href", "")
            body = sanitize_external_text(
                r.get("body", "No description"),
                max_single=600,
                context=f"result #{i} snippet",
            )
            parts.append(f"[{i}] {title}\n    URL: {href}\n    {body}")

        return "\n\n".join(parts)
