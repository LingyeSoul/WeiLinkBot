"""web_search tool — search the web using Bing China (cn.bing.com)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base import Tool, ToolExecutionError
from .sanitize import sanitize_external_text, build_results_header

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_BING_URL = "https://cn.bing.com/search"


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
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    async def execute(
        self,
        *,
        query: str,
        max_results: int = 5,
        **kwargs,
    ) -> str:
        if not query.strip():
            raise ToolExecutionError("Search query cannot be empty")

        max_results = max(1, min(max_results, 10))

        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15.0, headers=_HEADERS,
            ) as client:
                resp = await client.get(
                    _BING_URL, params={"q": query, "ensearch": "0"},
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("Bing returned HTTP %s", e.response.status_code)
            raise ToolExecutionError(f"Search failed: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error("Bing search request failed: %s", e)
            raise ToolExecutionError(f"Search failed: {e}")

        results = _parse_results(resp.text, max_results)

        if not results:
            return "No search results found."

        parts: list[str] = [build_results_header()]
        for i, r in enumerate(results, 1):
            title = sanitize_external_text(
                r["title"], max_single=200, context=f"result #{i} title",
            )
            href = r["url"]
            body = sanitize_external_text(
                r["snippet"], max_single=600, context=f"result #{i} snippet",
            )
            parts.append(f"[{i}] {title}\n    URL: {href}\n    {body}")

        return "\n\n".join(parts)


def _parse_results(html: str, max_results: int) -> list[dict[str, str]]:
    """Extract search results from Bing SERP HTML."""
    soup = BeautifulSoup(html, "lxml")
    results: list[dict[str, str]] = []

    for item in soup.select("li.b_algo")[:max_results]:
        anchor = item.select_one("h2 a")
        if not anchor:
            continue

        title = anchor.get_text(strip=True)
        url = anchor.get("href", "")
        if not url.startswith(("http://", "https://")):
            continue

        snippet_el = item.select_one(".b_caption p")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        # Skip ad / empty results
        if not title:
            continue

        results.append({"title": title, "url": url, "snippet": snippet})

    return results
