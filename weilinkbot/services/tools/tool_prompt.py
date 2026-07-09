"""Tool-aware system prompt injection.

Generates a system prompt block that guides the LLM to proactively use
available tools when user questions could benefit from them. Works with
both native function calling and prompt-based fallback modes.

Controlled by config.agent.tool_prompt_injection (on/off switch).
"""

from __future__ import annotations

from typing import Any

# ── Tool Category Definitions ────────────────────────────────────────

# Each category groups tools by purpose, with guidance on when to use them.
# The LLM sees these categories + guidance instead of raw tool names.

_TOOL_CATEGORIES: dict[str, dict[str, Any]] = {
    "browser": {
        "label": "浏览器工具",
        "label_en": "Browser Tools",
        "tools": ["browser_fetch", "browser_eval", "browser_use"],
        "trigger_zh": (
            "当用户提问涉及当前事件、实时数据、最新新闻、事实核查、"
            "或你不确定的领域知识时，必须使用 browser_fetch 通过 Bing 搜索获取最新信息。"
            "不要凭训练数据猜测事实性问题。\n"
            "搜索方法：将查询词 URL 编码后拼接到 Bing 搜索地址，"
            "即 https://www.bing.com/search?q=查询词，然后用 browser_fetch 抓取该 URL。"
            "示例：搜索「Python 3.13 新特性」→ "
            "browser_fetch(\"https://www.bing.com/search?q=Python+3.13+%E6%96%B0%E7%89%B9%E6%80%A7\")。\n"
            "当用户提供了URL链接并要求分析其内容，或需要获取特定网页的详细信息时，"
            "使用 browser_fetch 抓取页面内容。browser_eval 适合提取页面中的结构化数据，"
            "browser_use 适合需要交互操作（点击、滚动、截图等）的场景。"
        ),
        "trigger_en": (
            "When the user asks about current events, real-time data, latest news, "
            "fact-checking, or domain knowledge you're uncertain about, "
            "you MUST use browser_fetch to search via Bing and get up-to-date information. "
            "Do NOT guess factual questions from training data.\n"
            "How to search: URL-encode the query and append it to the Bing search URL: "
            "https://www.bing.com/search?q=<query>, then call browser_fetch on that URL. "
            "Example: search 'Python 3.13 new features' → "
            "browser_fetch(\"https://www.bing.com/search?q=Python+3.13+new+features\").\n"
            "When the user provides a URL and asks you to analyze its content, "
            "use browser_fetch to retrieve page content. Use browser_eval to extract "
            "structured data from pages, and browser_use for interactive operations "
            "(click, scroll, screenshot, etc.)."
        ),
    },
    "workspace": {
        "label": "工作区文件",
        "label_en": "Workspace Files",
        "tools": [
            "workspace_read", "workspace_write", "workspace_edit",
            "workspace_list", "workspace_grep", "workspace_shell",
        ],
        "trigger_zh": (
            "当用户要求读取、搜索、创建或编辑工作区中的文件时，"
            "使用 workspace 系列工具进行文件操作。"
            "加载技能(skill)完整内容也应使用 workspace_read。\n"
            "当用户要求运行代码、安装依赖、执行脚本、使用 git 等开发操作时，"
            "使用 workspace_shell 执行命令。"
        ),
        "trigger_en": (
            "When the user asks to read, search, create, or edit files "
            "in the workspace, use the workspace_* tools for file operations. "
            "Loading full skill content should also use workspace_read.\n"
            "When the user asks to run code, install dependencies, execute scripts, "
            "or use git, use workspace_shell to execute commands."
        ),
    },
    "utility": {
        "label": "实用工具",
        "label_en": "Utility Tools",
        "tools": ["get_current_time", "calculate"],
        "trigger_zh": (
            "当用户询问当前时间/日期，或需要数学计算时，"
            "使用 get_current_time 或 calculate 工具而非凭记忆回答。"
        ),
        "trigger_en": (
            "When the user asks about the current time/date, or needs "
            "mathematical calculations, use get_current_time or calculate "
            "tools instead of answering from memory."
        ),
    },
    "sticker": {
        "label": "表情贴纸",
        "label_en": "Stickers",
        "tools": ["search_sticker", "send_sticker", "list_sticker_packs"],
        "trigger_zh": (
            "当用户要求发送表情包/贴纸，或对话中有适合用表情回应的场景时，"
            "使用 sticker 工具搜索和发送贴纸。"
        ),
        "trigger_en": (
            "When the user asks for stickers/emojis, or when the conversation "
            "context calls for an expressive response, use sticker tools "
            "to search and send stickers."
        ),
    },
    "file_transfer": {
        "label": "文件传输",
        "label_en": "File Transfer",
        "tools": ["browser_download", "send_file"],
        "trigger_zh": (
            "当用户要求下载网络文件（如图片、文档、PDF等）或发送文件时，"
            "先使用 browser_download 将文件下载到工作区，"
            "再使用 send_file 将文件发送给用户。"
            "这是一个两步操作：下载 + 发送。"
        ),
        "trigger_en": (
            "When the user asks to download files from the web (images, documents, "
            "PDFs, etc.) or send files, first use browser_download to save the file "
            "to the workspace, then use send_file to deliver it to the user. "
            "This is a two-step workflow: download then send."
        ),
    },
    "segmented_reply": {
        "label": "分段回复",
        "label_en": "Segmented Reply",
        "tools": ["send_messages"],
        "trigger_zh": (
            "默认情况下，请使用 send_messages 工具发送回复："
            "尽可能把回复按句子拆分，每一句话作为 messages 数组中的一个独立元素依次发出，"
            "营造类似真人逐条发送消息的效果（上限约 10 条）。"
            "只有当回复只有简短的一两句话、确实无需拆分时，才可直接作为普通文本回复。"
            "调用后内容会立即发送给用户，不要在后续回复中重复这些内容。"
        ),
        "trigger_en": (
            "By default, send your reply via the send_messages tool: split it "
            "into individual sentences as much as possible, with each sentence "
            "as a separate element in the messages array sent one after another, "
            "to simulate a human typing multiple messages (max ~10 segments). "
            "Only reply as plain text when the response is a single short "
            "sentence that needs no splitting. The content is sent immediately; "
            "do not repeat it in your follow-up response."
        ),
    },
}


def _build_tool_guidance(
    available_tools: set[str],
    language: str = "zh",
) -> str:
    """Build tool usage guidance for categories that have active tools.

    Args:
        available_tools: Set of tool names currently enabled.
        language: 'zh' for Chinese, 'en' for English, 'both' for bilingual.

    Returns:
        Formatted guidance text, or empty string if no matching categories.
    """
    active_categories: list[dict[str, Any]] = []
    for cat in _TOOL_CATEGORIES.values():
        if any(t in available_tools for t in cat["tools"]):
            active_categories.append(cat)

    if not active_categories:
        return ""

    lines: list[str] = []
    use_zh = language in ("zh", "both")
    use_en = language in ("en", "both")

    for cat in active_categories:
        label = cat["label"] if use_zh else cat["label_en"]
        if use_zh and use_en:
            label = f"{cat['label']} / {cat['label_en']}"
        tools_str = ", ".join(t for t in cat["tools"] if t in available_tools)
        lines.append(f"**{label}** ({tools_str})")
        if use_zh:
            lines.append(cat["trigger_zh"])
        if use_en:
            lines.append(cat["trigger_en"])
        lines.append("")

    return "\n".join(lines)


# ── Main Prompt Builder ──────────────────────────────────────────────

_ZH_TEMPLATE = """\
## 工具使用指南

你拥有以下可用工具。当用户的问题可以通过工具获得更准确、更及时的回答时，
你应该主动调用工具，而不是仅凭训练数据回答。

{guidance}

### 核心原则

1. **时效性问题必须搜索** — 涉及"今天"、"最新"、"目前"、"现在"等时间敏感的问题，
   必须先搜索再回答，不可凭记忆。
2. **事实性问题优先验证** — 对不确定的事实，使用搜索工具验证后再给出答案。
3. **文件操作走工具** — 读写工作区文件必须使用对应工具，不要模拟文件内容。
4. **URL 内容需抓取** — 用户提供的链接需要通过抓取工具获取内容，不可猜测页面内容。
5. **工具失败要告知** — 如果工具调用失败，如实告知用户，不要编造结果。\
"""

_EN_TEMPLATE = """\
## Tool Usage Guide

You have the following tools available. When a user's question can be answered more
accurately or with more current information by using a tool, you SHOULD proactively
call the tool rather than answering from training data alone.

{guidance}

### Core Principles

1. **Time-sensitive questions require search** — Questions involving "today", "latest",
   "currently", "now" or other time-sensitive terms MUST use search first.
2. **Verify factual claims** — For uncertain facts, use search tools to verify before answering.
3. **File operations use tools** — Reading/writing workspace files MUST use the corresponding
   tools; do not simulate file contents.
4. **URLs need fetching** — Content from user-provided links must be fetched via tools;
   do not guess page contents.
5. **Report tool failures** — If a tool call fails, inform the user honestly;
   do not fabricate results.\
"""


def build_tool_prompt(
    available_tools: list[str] | set[str],
    language: str = "zh",
) -> str:
    """Build the tool-aware system prompt injection block.

    Args:
        available_tools: List or set of currently enabled tool names.
        language: 'zh' (default), 'en', or 'both'.

    Returns:
        The complete tool prompt block to inject into the system message.
        Returns empty string if no tools are available.
    """
    tool_set = set(available_tools)
    if not tool_set:
        return ""

    guidance = _build_tool_guidance(tool_set, language)
    if not guidance:
        return ""

    if language == "en":
        return _EN_TEMPLATE.format(guidance=guidance)
    # Default to Chinese (zh or both)
    return _ZH_TEMPLATE.format(guidance=guidance)
