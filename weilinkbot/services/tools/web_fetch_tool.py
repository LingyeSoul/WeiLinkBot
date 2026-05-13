"""web_fetch tool — fetch a URL and extract readable main content."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from .base import Tool, ToolExecutionError
from ._url_validate import validate_url
from .sanitize import sanitize_external_text

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# Elements that never carry reader-facing content
_STRIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "object", "embed",
               "applet", "template", "dialog", "math", "canvas", "map", "audio", "video"}

# Boilerplate selectors to remove before content extraction
_BOILERPLATE_SELECTORS = [
    "nav", "header", "footer", "aside",
    ".sidebar", "#sidebar", ".nav", "#nav", ".navigation",
    ".menu", "#menu", ".header", "#header", ".footer", "#footer",
    ".ad", ".ads", ".adsbygoogle", '[class*="advert"]', '[class*="sponsor"]',
    ".cookie", ".popup", ".modal", ".overlay", ".banner",
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    ".breadcrumb", ".share", ".social", ".comment", "#comments",
    ".related", ".recommend", ".widget",
]

# Selectors that likely contain the main article content (priority order)
_CONTENT_SELECTORS = [
    "article", "main", '[role="main"]',
    ".post-content", ".article-content", ".entry-content",
    ".post-body", ".article-body", ".entry-body",
    ".content", "#content", ".main-content", "#main-content",
    ".page-content", ".story-body", ".text-content",
    ".RichContent-inner",  # zhihu
    ".article-detail",  # common CN news
    "#js_content",  # weixin
    ".markdown-body",  # github
    ".topic-content",  # v2ex
]

_MAX_RECURSION_DEPTH = 20


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Fetch a web page URL and extract its main readable content as clean text. "
        "Strips navigation, ads, scripts, and other boilerplate. "
        "Use this to read the actual content of a web page found via search."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the web page to fetch.",
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
        max_length: int = 8000,
        **kwargs,
    ) -> str:
        validate_url(url)
        max_length = max(1000, min(max_length, 20_000))

        html = await _fetch(url)
        title, text = _extract_content(html, max_length)

        if not text.strip():
            return f"Page fetched successfully but no readable content was found.\nURL: {url}"

        header = f"Title: {title}\nURL: {url}\n\n" if title else f"URL: {url}\n\n"
        return sanitize_external_text(
            header + text,
            max_single=max_length + 500,
            context="web page content",
        )


# ── URL validation ────────────────────────────────────────────────────────────

# validate_url is imported from _url_validate (with SSRF protection)


# ── HTTP fetch ────────────────────────────────────────────────────────────────

async def _fetch(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=20.0,
            headers=_HEADERS,
        ) as client:
            # Manual redirect loop to validate each redirect target
            current_url = url
            for _ in range(5):
                resp = await client.get(current_url)
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location", "")
                    if not location:
                        break
                    # Resolve relative redirects
                    from urllib.parse import urljoin
                    current_url = urljoin(current_url, location)
                    validate_url(current_url)
                    continue
                resp.raise_for_status()
                return resp.text
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPStatusError as e:
        raise ToolExecutionError(f"HTTP {e.response.status_code} when fetching {url}")
    except httpx.TimeoutException:
        raise ToolExecutionError(f"Timeout fetching {url} (>20s)")
    except Exception as e:
        logger.error("Failed to fetch %s: %s", url, e)
        raise ToolExecutionError(f"Failed to fetch URL: {e}")


# ── Content extraction ────────────────────────────────────────────────────────

def _extract_content(html: str, max_length: int) -> tuple[str, str]:
    """Return (title, main_text) extracted from *html*."""
    soup = BeautifulSoup(html, "lxml")

    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    # 1. Remove elements that are never content
    for tag_name in _STRIP_TAGS:
        for el in soup.find_all(tag_name):
            el.decompose()

    # 2. Remove boilerplate (nav, ads, footer, etc.)
    for selector in _BOILERPLATE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    # 3. Find the main content node
    content_node = _find_main_content(soup)

    # 4. Convert to readable text
    lines: list[str] = []
    _node_to_text(content_node, lines, depth=0, char_budget=max_length + 2000)

    text = "\n".join(lines)
    text = _cleanup_text(text)

    if len(text) > max_length:
        cut = text.rfind("\n", 0, max_length)
        if cut < max_length // 2:
            cut = max_length
        text = text[:cut].rstrip() + "\n\n[Content truncated…]"

    return title, text


def _find_main_content(soup: BeautifulSoup) -> Tag:
    """Locate the main content node using selector heuristics."""
    for selector in _CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node and len(node.get_text(strip=True)) > 100:
            return node

    # Fallback: pick the <div>/<section> with the most text
    best, best_len = soup.body or soup, 0
    for div in soup.find_all(["div", "section"]):
        text_len = len(div.get_text(strip=True))
        if text_len > best_len:
            best, best_len = div, text_len

    return best


# ── HTML → text conversion ───────────────────────────────────────────────────

def _node_to_text(
    node: Tag | NavigableString,
    lines: list[str],
    *,
    depth: int,
    char_budget: int,
) -> None:
    """Recursively convert an HTML node tree into flat text lines."""
    if sum(len(l) for l in lines) >= char_budget:
        return
    if depth > _MAX_RECURSION_DEPTH:
        return

    if isinstance(node, NavigableString):
        t = str(node)
        if t.strip():
            lines.append(t.strip())
        return

    if not isinstance(node, Tag):
        return

    tag = node.name

    # Skip invisible / already-removed tags
    if tag in _STRIP_TAGS:
        return

    # Headings → markdown-style
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        text = node.get_text(strip=True)
        if text:
            lines.append("")
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        return

    # Line breaks
    if tag == "br":
        lines.append("")
        return

    # Horizontal rule
    if tag == "hr":
        lines.append("\n---\n")
        return

    # Paragraphs
    if tag == "p":
        text = _collect_inline_text(node)
        if text:
            lines.append("")
            lines.append(text)
        return

    # Blockquotes
    if tag == "blockquote":
        inner_lines: list[str] = []
        for child in node.children:
            _node_to_text(child, inner_lines, depth=depth + 1, char_budget=char_budget)
        quoted = "\n".join(inner_lines).strip()
        if quoted:
            lines.append("")
            for q_line in quoted.split("\n"):
                lines.append(f"> {q_line}")
        return

    # Lists
    if tag in ("ul", "ol"):
        lines.append("")
        for i, li in enumerate(node.find_all("li", recursive=False)):
            bullet = f"{i + 1}." if tag == "ol" else "-"
            text = _collect_inline_text(li)
            if text:
                lines.append(f"  {bullet} {text}")
        return

    # Tables → simple pipe format
    if tag == "table":
        lines.append("")
        rows = node.find_all("tr")
        for row in rows:
            cells = [_collect_inline_text(c) for c in row.find_all(["th", "td"])]
            if any(cells):
                lines.append(" | ".join(cells))
        lines.append("")
        return

    # Pre / code blocks
    if tag in ("pre", "code"):
        text = node.get_text()
        if text.strip():
            lines.append("")
            lines.append("```")
            lines.append(text.strip())
            lines.append("```")
            lines.append("")
        return

    # Links — keep text with URL if short
    if tag == "a":
        text = _collect_inline_text(node)
        href = node.get("href", "")
        if text:
            if href and href.startswith(("http://", "https://")) and len(text) < 80:
                lines.append(f"[{text}]({href})")
            else:
                lines.append(text)
        return

    # Images — alt text only
    if tag == "img":
        alt = node.get("alt", "").strip()
        if alt:
            lines.append(f"[Image: {alt}]")
        return

    # Generic container — recurse into block children,
    # collect inline children into a single paragraph.
    has_block = False
    inline_parts: list[str] = []
    for child in node.children:
        if isinstance(child, Tag) and child.name in _BLOCK_TAGS:
            _flush_inline(inline_parts, lines)
            _node_to_text(child, lines, depth=depth + 1, char_budget=char_budget)
            has_block = True
        elif isinstance(child, NavigableString):
            inline_parts.append(str(child))
        else:
            inline_parts.append(_collect_inline_text(child))

    if not has_block:
        # Pure inline container (span, em, strong, etc.) — handled by caller
        pass
    else:
        _flush_inline(inline_parts, lines)


_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "aside", "nav", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
    "ul", "ol", "table", "form", "fieldset", "hr", "br",
    "figure", "figcaption", "details", "summary", "address",
})


def _collect_inline_text(node: Tag | NavigableString) -> str:
    """Extract text from an inline-element subtree, preserving inter-word spaces."""
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


def _flush_inline(parts: list[str], lines: list[str]) -> None:
    """Join accumulated inline text fragments and append as a paragraph."""
    if not parts:
        return
    merged = "".join(parts).strip()
    if merged:
        lines.append("")
        lines.append(merged)
    parts.clear()


# ── Post-processing ───────────────────────────────────────────────────────────

_MULTI_BLANK = re.compile(r"\n{3,}")


def _cleanup_text(text: str) -> str:
    """Collapse excessive blank lines and strip trailing whitespace per line."""
    text = _MULTI_BLANK.sub("\n\n", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()
