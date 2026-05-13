"""browser_use — interactive browser control via Obscura CDP.

Provides the LLM with full browser automation: navigate, click, type,
scroll, extract text/links, execute JS, take screenshots.

Each action creates a direct CDP connection — no background threads or
long-lived server processes.  Page state is preserved across calls via
a persistent Obscura ``serve`` subprocess managed by the session manager.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from .base import Tool, ToolExecutionError
from ._url_validate import validate_url
from .sanitize import sanitize_external_text

logger = logging.getLogger(__name__)

try:
    import websockets
    import websockets.asyncio.client
    _HAS_CDP = True
except ImportError:
    _HAS_CDP = False
    logger.info("websockets not installed — browser_use tool disabled")


# ═══════════════════════════════════════════════════════════════════════════════
# CDP helpers
# ═══════════════════════════════════════════════════════════════════════════════


async def _cdp_call(ws_url: str, method: str, params: dict | None = None,
                    *, msg_id: int = 1, session_id: str | None = None) -> Any:
    """Send a single CDP command and return the result."""
    msg: dict[str, Any] = {"id": msg_id, "method": method}
    if params:
        msg["params"] = params
    if session_id:
        msg["sessionId"] = session_id

    async with asyncio.timeout(30):
        async with websockets.asyncio.client.connect(
            ws_url, max_size=2**22,
        ) as ws:
            await ws.send(json.dumps(msg))
            async for raw in ws:
                resp = json.loads(raw)
                if resp.get("id") == msg_id:
                    if "error" in resp:
                        raise RuntimeError(json.dumps(resp["error"]))
                    return resp.get("result", {})
    return {}


async def _get_browser_ws(server: str) -> str:
    """Get the browser WebSocket URL from the CDP HTTP API."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{server}/json/version", timeout=5)
        data = resp.json()
    ws_url = data.get("webSocketDebuggerUrl", "")
    if not ws_url:
        raise RuntimeError("No webSocketDebuggerUrl from CDP server")
    return ws_url


async def _create_page(browser_ws: str) -> str:
    """Create a new page and return its targetId."""
    result = await _cdp_call(browser_ws, "Target.createTarget", {"url": "about:blank"}, msg_id=1)
    return result["targetId"]


async def _attach(browser_ws: str, target_id: str) -> str:
    """Attach to a target and return the sessionId."""
    result = await _cdp_call(
        browser_ws, "Target.attachToTarget",
        {"targetId": target_id, "flatten": True}, msg_id=2,
    )
    sid = result.get("sessionId", "")
    if not sid:
        raise RuntimeError("Failed to attach to target")
    return sid


async def _cdp_session(browser_ws: str, session_id: str,
                       method: str, params: dict | None = None,
                       *, msg_id: int = 100) -> Any:
    """Send a CDP command to a specific session (keeps connection open for response)."""
    msg: dict[str, Any] = {"id": msg_id, "method": method, "sessionId": session_id}
    if params:
        msg["params"] = params

    async with asyncio.timeout(30):
        async with websockets.asyncio.client.connect(
            browser_ws, max_size=2**22,
        ) as ws:
            await ws.send(json.dumps(msg))
            async for raw in ws:
                resp = json.loads(raw)
                if resp.get("id") == msg_id:
                    if "error" in resp:
                        raise RuntimeError(json.dumps(resp["error"]))
                    return resp.get("result", {})
    return {}


async def _eval_js(browser_ws: str, session_id: str, expression: str) -> Any:
    """Evaluate JavaScript in the page and return the result value."""
    result = await _cdp_session(
        browser_ws, session_id,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True},
        msg_id=200,
    )
    if "exceptionDetails" in result:
        desc = result["exceptionDetails"].get("text", "JS error")
        raise RuntimeError(f"JS error: {desc}")
    return result.get("result", {}).get("value")


# ═══════════════════════════════════════════════════════════════════════════════
# Session state
# ═══════════════════════════════════════════════════════════════════════════════


class _SessionManager:
    """Manages the Obscura CDP server process and browser sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, str]] = {}  # id → {browser_ws, target_id, session_id}
        self._server_proc: asyncio.subprocess.Process | None = None
        self._server_url: str | None = None

    async def _ensure_server(self) -> str:
        """Start the Obscura CDP server if not running. Returns server address."""
        if self._server_proc and self._server_proc.returncode is None:
            return self._server_url

        from ._obscura import ensure_ready
        bin_path = ensure_ready()

        from ...config import get_config
        port = get_config().browser.serve_port

        cmd = [bin_path, "serve", "--port", str(port)]
        if get_config().browser.stealth:
            cmd.append("--stealth")

        self._server_proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        self._server_url = f"127.0.0.1:{port}"

        import httpx
        deadline = asyncio.get_event_loop().time() + 15
        async with httpx.AsyncClient() as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    resp = await client.get(
                        f"http://{self._server_url}/json/version", timeout=2,
                    )
                    if resp.status_code == 200:
                        return self._server_url
                except Exception:
                    pass
                await asyncio.sleep(0.5)

        raise RuntimeError("Obscura CDP server failed to start within 15s")

    async def create_session(self, stealth: bool = False) -> str:
        """Create a new browser session. Returns session_id."""
        server = await self._ensure_server()

        try:
            from ...config import get_config
            if get_config().browser.stealth:
                stealth = True
        except Exception:
            pass

        browser_ws = await _get_browser_ws(server)
        target_id = await _create_page(browser_ws)
        session_id = await _attach(browser_ws, target_id)

        sid = str(uuid.uuid4())[:8]
        self._sessions[sid] = {
            "browser_ws": browser_ws,
            "target_id": target_id,
            "session_id": session_id,
        }
        return sid

    async def close_session(self, session_id: str) -> None:
        info = self._sessions.pop(session_id, None)
        if not info:
            raise RuntimeError(f"Session '{session_id}' not found")
        if not self._sessions and self._server_proc:
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()
            self._server_proc = None

    def get(self, session_id: str) -> dict[str, str]:
        info = self._sessions.get(session_id)
        if not info:
            raise RuntimeError(
                f"Session '{session_id}' not found. "
                f"Active: {list(self._sessions.keys()) or 'none'}"
            )
        return info


_mgr = _SessionManager()


# ═══════════════════════════════════════════════════════════════════════════════
# Action helpers (async, run via asyncio.run)
# ═══════════════════════════════════════════════════════════════════════════════


async def _do_navigate(info: dict, url: str) -> str:
    validate_url(url)
    await _cdp_session(
        info["browser_ws"], info["session_id"],
        "Page.navigate", {"url": url}, msg_id=300,
    )
    await asyncio.sleep(1)
    title = await _eval_js(info["browser_ws"], info["session_id"], "document.title")
    return f"Navigated to: {url}\nTitle: {title or '(untitled)'}"


async def _do_eval(info: dict, expression: str) -> str:
    result = await _eval_js(info["browser_ws"], info["session_id"], expression)
    return str(result) if result is not None else "(null)"


async def _do_get_text(info: dict) -> str:
    ws, sid = info["browser_ws"], info["session_id"]
    try:
        result = await _cdp_session(ws, sid, "LP.getMarkdown", msg_id=310)
        md = result.get("markdown", "")
        if md.strip():
            return md
    except Exception:
        pass
    text = await _eval_js(ws, sid, "document.body.innerText")
    return text or "(empty page)"


async def _do_get_links(info: dict) -> str:
    links = await _eval_js(
        info["browser_ws"], info["session_id"],
        "JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map("
        "  a => ({text: a.textContent.trim(), url: a.href})"
        "))",
    )
    return json.dumps(json.loads(links) if links else [], ensure_ascii=False, indent=2)


async def _do_get_html(info: dict) -> str:
    return await _eval_js(info["browser_ws"], info["session_id"],
                          "document.documentElement.outerHTML") or ""


async def _do_screenshot(info: dict) -> str:
    result = await _cdp_session(
        info["browser_ws"], info["session_id"],
        "Page.captureScreenshot", {"format": "png"}, msg_id=320,
    )
    return result.get("data", "")


async def _do_click(info: dict, selector: str) -> str:
    ws, sid = info["browser_ws"], info["session_id"]
    sel_js = json.dumps(selector)
    box = await _eval_js(ws, sid,
        f"(el => el ? (() => {{"
        f"  const r = el.getBoundingClientRect();"
        f"  return {{x: r.x + r.width/2, y: r.y + r.height/2}};"
        f"}})() : null)(document.querySelector({sel_js}))"
    )
    if not box:
        raise RuntimeError(f"Element not found: {selector}")
    x, y = box["x"], box["y"]
    await _cdp_session(ws, sid, "Input.dispatchMouseEvent",
                       {"type": "mousePressed", "x": x, "y": y,
                        "button": "left", "clickCount": 1}, msg_id=330)
    await _cdp_session(ws, sid, "Input.dispatchMouseEvent",
                       {"type": "mouseReleased", "x": x, "y": y,
                        "button": "left", "clickCount": 1}, msg_id=331)
    return f"Clicked: {selector}"


async def _do_type(info: dict, selector: str, text: str) -> str:
    ws, sid = info["browser_ws"], info["session_id"]
    sel_js = json.dumps(selector)
    await _eval_js(ws, sid,
        f"(el => {{ if(el) {{ el.focus(); el.value = ''; }} }})"
        f"(document.querySelector({sel_js}))"
    )
    await _cdp_session(ws, sid, "Input.insertText",
                       {"text": text}, msg_id=340)
    return f"Typed into {selector}: {text}"


async def _do_scroll(info: dict, direction: str) -> str:
    js = {
        "top":    "window.scrollTo(0, 0)",
        "bottom": "window.scrollTo(0, document.body.scrollHeight)",
        "up":     "window.scrollBy(0, -500)",
        "down":   "window.scrollBy(0, 500)",
    }.get(direction, "window.scrollBy(0, 500)")
    await _eval_js(info["browser_ws"], info["session_id"], js)
    return f"Scrolled {direction}"


# ═══════════════════════════════════════════════════════════════════════════════
# Tool
# ═══════════════════════════════════════════════════════════════════════════════


class BrowserUseTool(Tool):
    name = "browser_use"
    description = (
        "Interactive browser control via a persistent headless browser session. "
        "Supports navigate, click, type, scroll, get_text, get_links, get_html, "
        "screenshot, eval, wait, and close_session.\n\n"
        "Workflow: create_session → navigate → interact → close_session.\n"
        "Use CSS selectors for click/type. "
        "get_text returns readable markdown of the current page."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create_session", "navigate", "click", "type",
                    "scroll", "get_text", "get_links", "get_html",
                    "screenshot", "eval", "wait", "close_session",
                ],
                "description": "The browser action to perform.",
            },
            "session_id": {
                "type": "string",
                "description": "Session ID (required for all actions except create_session).",
            },
            "url": {
                "type": "string",
                "description": "URL to navigate to (navigate).",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector for the target element (click, type).",
            },
            "text": {
                "type": "string",
                "description": "Text to type into the element (type).",
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down", "top", "bottom"],
                "description": "Scroll direction (scroll, default: down).",
            },
            "expression": {
                "type": "string",
                "description": "JavaScript expression to evaluate (eval).",
            },
            "seconds": {
                "type": "integer",
                "description": "Seconds to wait, 1–30 (wait).",
            },
            "stealth": {
                "type": "boolean",
                "description": "Enable anti-fingerprinting (create_session).",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    async def execute(self, *, action: str, **kwargs) -> str:
        if not _HAS_CDP:
            raise ToolExecutionError(
                "browser_use unavailable: install websockets (pip install websockets)"
            )

        try:
            from ...config import get_config
            max_chars = get_config().agent.max_tool_result_chars
        except Exception:
            max_chars = 30_000

        result = await self._dispatch(action, kwargs)

        if action in ("navigate", "get_text", "eval", "get_html"):
            result = sanitize_external_text(
                result, max_single=max_chars, context=f"browser {action}",
            )
        elif action == "screenshot" and len(result) > 50_000:
            result = f"[Screenshot: {len(result)} chars base64 — too large for context. Use get_text instead.]"

        return result

    async def _dispatch(self, action: str, kw: dict) -> str:
        """Execute an action and return the result string."""
        if action == "create_session":
            sid = await _mgr.create_session(kw.get("stealth", False))
            return (
                f"Session: {sid}\n"
                "Use this session_id for all subsequent actions. Call close_session when done."
            )

        if action == "close_session":
            sid = self._require(kw, "session_id")
            await _mgr.close_session(sid)
            return f"Session {sid} closed"

        info = _mgr.get(self._require(kw, "session_id"))

        if action == "navigate":
            return await _do_navigate(info, self._require(kw, "url"))
        if action == "click":
            return await _do_click(info, self._require(kw, "selector"))
        if action == "type":
            return await _do_type(info, self._require(kw, "selector"),
                                  self._require(kw, "text"))
        if action == "scroll":
            return await _do_scroll(info, kw.get("direction", "down"))
        if action == "get_text":
            return await _do_get_text(info)
        if action == "get_links":
            return await _do_get_links(info)
        if action == "get_html":
            return await _do_get_html(info)
        if action == "screenshot":
            return await _do_screenshot(info)
        if action == "eval":
            return await _do_eval(info, self._require(kw, "expression"))
        if action == "wait":
            sec = min(max(int(kw.get("seconds", 3)), 1), 30)
            await asyncio.sleep(sec)
            return f"Waited {sec}s"

        raise ToolExecutionError(
            f"Unknown action: {action}. "
            f"Valid: create_session, navigate, click, type, scroll, "
            f"get_text, get_links, get_html, screenshot, eval, wait, close_session"
        )

    def _require(self, kw: dict, key: str) -> Any:
        val = kw.get(key)
        if not val:
            raise ToolExecutionError(f"'{key}' is required for this action")
        return val


def is_available() -> bool:
    """Check if browser_use can be used."""
    return _HAS_CDP
