<p align="center">
  <img src="static/icons/logo.svg" width="128" height="128" alt="WeiLinkBot Logo">
</p>

<h1 align="center">WeiLinkBot</h1>

<p align="center">
  English | <a href="README.md">中文</a>
</p>

<p align="center">
AI Chatbot Platform powered by WeChat iLink Bot SDK. Multi-provider LLM support, SillyTavern presets, character cards, world books, memory system, and agent tool calling — all managed through a web dashboard.
</p>

## Features

- **WeChat Integration** — via [wechatbot-sdk](https://github.com/corespeed-io/wechatbot), QR login, long-poll messaging
- **Multi-Provider Management** — manage multiple LLM providers (OpenAI, DeepSeek, or any OpenAI-compatible API) with encrypted API key storage
- **LLM Presets** — save and switch between model configurations, with text/audio/image capability flags and tool calling toggle
- **SillyTavern Presets** — import and manage SillyTavern prompt presets with custom system prompts
- **World Books** — import and manage SillyTavern World Books for keyword-based context injection
- **Character Cards** — create and manage character cards (description, personality, scenario, first message, example dialogue) with avatar upload
- **Memory System** — vector memory powered by mem0ai + ChromaDB, with local ONNX / ModelScope / remote embedding support and tunable HNSW parameters; batch summarization (turn-count + timeout dual-trigger), facts + summary dual-dimension storage, time-decay and reranking retrieval
- **Agent Tools** — LLM-driven agent loop with native function calling and prompt-based fallback, built-in math and time tools
- **Workspace Tools** — sandboxed file operations (read/write/edit/list/grep), new `workspace_edit` for precise text replacement, configurable root, size limits, and extension filtering, each tool independently toggleable
- **Skill System** — directory-based skill management (`workspace/skills/<name>/SKILL.md`), progressive loading (summary in context, full content on-demand), requirements checking (CLI bins / env vars), always-on skills, disabled list, backward-compatible with flat `.md` files
- **MCP Integration** — stdio / SSE / Streamable HTTP transports, auto-discovers and registers MCP tools, resources, and prompts, per-server `enabledTools` filtering, configurable timeouts, transient error auto-retry, HTTP reachability probe
- **Web Dashboard** — real-time status, conversation viewer, preset management, user controls, event log, statistics panel
- **WebSocket Real-time Push** — bot status, messages, and events pushed to the frontend via WebSocket
- **Multi-language** — Chinese (zh-CN) and English (en) UI switching
- **Per-user Customization** — individual system prompts, message history limits, blocklist
- **Persistent Storage** — SQLite + SQLAlchemy async engine with automatic migrations

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Configure

Copy the environment template and set your LLM API key:

```bash
cp .env.example .env
# Edit .env and set WEILINKBOT_LLM__API_KEY
```

Or edit `config.yaml` directly.

### 3. Start the Dashboard

```bash
weilinkbot serve
```

Open `http://localhost:8000` in your browser. Click **Start Bot** to begin.

### 4. CLI Usage

```bash
# Bot control
weilinkbot start              # Start bot in terminal
weilinkbot status             # Show configuration

# Manage prompts
weilinkbot prompts list       # List system prompts
weilinkbot prompts create     # Create a new prompt
weilinkbot prompts set-default 1  # Set default prompt

# View history
weilinkbot history show <user_id>     # View messages
weilinkbot history clear <user_id>    # Clear history

# Configure LLM
weilinkbot config set-llm --provider deepseek --api-key sk-xxx

# Start web dashboard
weilinkbot serve              # Start dashboard + API
weilinkbot serve --port 3000  # Custom port
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│   WeChat     │────▶│ wechatbot-sdk│────▶│   BotService      │
│  (iLink API) │◀────│ (long-poll)  │     │  (orchestrator)   │
└─────────────┘     └──────────────┘     └────────┬─────────┘
                                                   │
              ┌────────────────┬───────────┬───────┴──────┐
              ▼                ▼           ▼              ▼
       ┌─────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
       │ LLMService   │ │  SQLite   │ │ FastAPI   │ │ MemoryService│
       │ (multi-LLM)  │ │ (Alch)   │ │ Dashboard │ │ (mem0/Chroma)│
       └──────┬──────┘ └──────────┘ └──────────┘ └──────────────┘
              │
       ┌──────┴──────┐  ┌──────────────┐  ┌──────────────┐
       │ AgentLoop    │  │Consolidator   │  │StickerService │
       │ (state mach.)│  │(ctx compress) │  │(pack manage)  │
       └──────┬──────┘  └──────────────┘  └──────────────┘
              │
   ┌──────────┼──────────┬──────────┐
   ▼          ▼          ▼          ▼
Web Tools  Workspace  Stickers   Builtin
(search,   (read,     (search,   (math,
 fetch,    write,     list,      time)
 browser)  edit,      send)
           grep)
   │
   ▼
MCP Tools (stdio / SSE / HTTP,
 resources, prompts)
```

## Skills System

Skills are Markdown files that define specialized agent behavior. Two formats are supported:

### Directory-based Skills (Recommended)

```
workspace/skills/
├── translation/
│   └── SKILL.md
├── code-review/
│   └── SKILL.md
└── my-custom-skill/
    └── SKILL.md
```

Each `SKILL.md` supports YAML frontmatter:

```markdown
---
name: translation
description: Translate between languages with style preservation.
metadata:
  nanobot:
    always: true              # Always inject into context (optional)
    requires:
      bins: ["trans"]         # Required CLI tools (optional)
      env: ["DEEPL_API_KEY"]  # Required env vars (optional)
---

# Translation Skill

When translating, preserve the original tone and formatting...
```

### Progressive Loading

To save tokens, the skill system uses progressive loading:

1. **Context injection**: `always` skills get full content injected; other enabled skills only inject a summary (name + description)
2. **On-demand loading**: The agent reads full skill content via `workspace_read` when needed
3. **Requirements checking**: Skills with missing dependencies (CLI tools or env vars) are automatically marked unavailable

### Configuration

Manage skills in the Agent settings dashboard:

| Option | Description |
|--------|-------------|
| `enabled_skills` | List of enabled skill names |
| `disabled_skills` | List of skill names to exclude from loading |

### Import

Supports single `.md` files or `.zip` archives. ZIP packs support `manifest.json` metadata.

## MCP Integration (Model Context Protocol)

Connect external MCP servers and register their tools, resources, and prompts as native agent tools.

### Transports

| Mode | Config | Use Case |
|------|--------|----------|
| **stdio** | `command` + `args` | Local process (npx / uvx) |
| **SSE** | `url` | Remote HTTP endpoint (`/sse`) |
| **Streamable HTTP** | `url` | Remote HTTP endpoint (`/mcp/`) |

### Configuration Examples

Add via dashboard or API:

```json
{
  "name": "filesystem",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
  "enabled": true,
  "tool_timeout": 30,
  "enabled_tools": ["*"]
}
```

Remote MCP server:

```json
{
  "name": "my-remote-mcp",
  "transport": "streamableHttp",
  "url": "https://example.com/mcp/",
  "headers": { "Authorization": "Bearer xxxxx" },
  "tool_timeout": 60,
  "enabled_tools": ["search", "fetch"]
}
```

### Advanced Features

| Feature | Description |
|---------|-------------|
| **Tool filtering** | `enabled_tools` specifies which tools to register; `["*"]` = all |
| **Timeout control** | `tool_timeout` — per-call timeout in seconds (default 30) |
| **Auto-retry** | Transient connection errors (disconnect, reset) retry once |
| **Resource registration** | MCP Resources auto-registered as read-only tools |
| **Prompt registration** | MCP Prompts auto-registered as read-only tools |
| **Reachability probe** | TCP probe before HTTP connection to avoid crashes |
| **Schema normalization** | Auto-normalizes nullable JSON Schema for OpenAI/Anthropic API compat |

### Tool Naming

MCP tool name format: `{server_name}__{tool_name}`

Resource format: `{server_name}__resource__{resource_name}`

Prompt format: `{server_name}__prompt__{prompt_name}`

## Workspace

The workspace is the agent's sandboxed file operations environment.

### Tools

| Tool | Description |
|------|-------------|
| `workspace_read` | Read file content (supports line ranges) |
| `workspace_write` | Write/append file content |
| `workspace_edit` | Precise text replacement editing (more efficient than full rewrites) |
| `workspace_list` | List files and directories (supports glob patterns) |
| `workspace_grep` | Search file content (supports regex) |

### Security Sandbox

All file operations go through `WorkspaceSandbox` security validation:

- **Path validation**: Rejects absolute paths, `..` traversal, symlink escapes
- **Extension filtering**: Blocks executables (`.exe`, `.bat`, `.dll`, etc.), allows `.py`, `.js`, `.sh` scripts
- **Size limits**: Read max 1MB, write max 512KB
- **Result limits**: Directory listing max 500 entries, search max 100 results

### Configuration

```json
{
  "root": "workspace",
  "read_max_size": 1048576,
  "write_max_size": 524288,
  "blocked_extensions": [".exe", ".bat", ".dll", ...]
}
```

## LLM Providers

| Provider | Base URL | Example Models |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini |
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat |
| Custom | Any OpenAI-compatible URL | — |

API keys are managed centrally through Providers and stored with AES encryption.

## API Endpoints

### Bot Control

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/bot/status` | Bot status |
| `POST` | `/api/bot/start` | Start bot |
| `POST` | `/api/bot/stop` | Stop bot |

### Providers & Models

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/providers` | List providers |
| `POST` | `/api/providers` | Create provider |
| `PUT` | `/api/providers/{id}` | Update provider |
| `DELETE` | `/api/providers/{id}` | Delete provider |
| `GET` | `/api/models` | List LLM presets |
| `POST` | `/api/models` | Create LLM preset |
| `PUT` | `/api/models/{id}` | Update LLM preset |
| `DELETE` | `/api/models/{id}` | Delete LLM preset |
| `POST` | `/api/models/{id}/activate` | Activate preset |

### Conversations & Prompts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/conversations` | List conversations |
| `GET` | `/api/conversations/{user_id}` | Get messages |
| `DELETE` | `/api/conversations/{user_id}` | Clear history |
| `GET` | `/api/prompts` | List prompts |
| `POST` | `/api/prompts` | Create prompt |
| `PUT` | `/api/prompts/{id}` | Update prompt |
| `DELETE` | `/api/prompts/{id}` | Delete prompt |

### SillyTavern Compatibility

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/st-presets` | List ST presets |
| `POST` | `/api/st-presets` | Create ST preset |
| `PUT` | `/api/st-presets/{id}` | Update ST preset |
| `DELETE` | `/api/st-presets/{id}` | Delete ST preset |
| `POST` | `/api/st-presets/{id}/activate` | Activate ST preset |
| `POST` | `/api/st-presets/{id}/entries` | Add preset entry |
| `PUT` | `/api/st-presets/entries/{entry_id}` | Update preset entry |
| `DELETE` | `/api/st-presets/entries/{entry_id}` | Delete preset entry |
| `PUT` | `/api/st-presets/{id}/reorder` | Reorder entries |
| `GET` | `/api/world-books` | List world books |
| `POST` | `/api/world-books` | Create world book |
| `PUT` | `/api/world-books/{id}` | Update world book |
| `DELETE` | `/api/world-books/{id}` | Delete world book |
| `POST` | `/api/world-books/{id}/activate` | Activate world book |
| `POST` | `/api/world-books/{id}/entries` | Add world book entry |
| `PUT` | `/api/world-books/entries/{entry_id}` | Update world book entry |
| `DELETE` | `/api/world-books/entries/{entry_id}` | Delete world book entry |
| `PUT` | `/api/world-books/{id}/reorder` | Reorder entries |

### Character Cards

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/characters` | List character cards |
| `POST` | `/api/characters` | Create character card |
| `PUT` | `/api/characters/{id}` | Update character card |
| `DELETE` | `/api/characters/{id}` | Delete character card |
| `POST` | `/api/characters/{id}/activate` | Activate character card |

### Memory & Agent

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/memories/status` | Memory system status |
| `GET` | `/api/memories/config` | Get memory config |
| `PUT` | `/api/memories/config` | Update memory config |
| `POST` | `/api/memories/config/test` | Test embedding connection |
| `GET` | `/api/memories/{user_id}` | Get user memories |
| `GET` | `/api/memories/{user_id}/search` | Semantic search memories |
| `GET` | `/api/memories/{user_id}/summaries` | Get user conversation summaries |
| `DELETE` | `/api/memories/summaries/{id}` | Delete a summary |
| `DELETE` | `/api/memories/summaries/user/{user_id}` | Clear user summaries |
| `GET` | `/api/memories/export` | Export memories as JSON |
| `POST` | `/api/memories/import` | Import memories from JSON |
| `GET` | `/api/agent/config` | Get agent config |
| `PUT` | `/api/agent/config` | Update agent config |

### Skills

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/skills` | List skills (with source, available, always flags) |
| `PUT` | `/api/agent/skills` | Update enabled skills list |
| `POST` | `/api/agent/skills` | Create a skill |
| `POST` | `/api/agent/skills/import` | Import skill (.md or .zip) |
| `DELETE` | `/api/agent/skills/{name}` | Delete a skill |

### MCP Servers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/mcp` | List MCP servers (with connection status) |
| `POST` | `/api/agent/mcp` | Create MCP server config |
| `PUT` | `/api/agent/mcp/{id}` | Update MCP server config |
| `DELETE` | `/api/agent/mcp/{id}` | Delete and disconnect |
| `POST` | `/api/agent/mcp/{id}/reconnect` | Reconnect |

### Workspace

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/agent/workspace/config` | Get workspace config |
| `PUT` | `/api/agent/workspace/config` | Update workspace config |
| `GET` | `/api/agent/workspace/files` | List workspace files |
| `GET` | `/api/agent/workspace/read` | Read workspace file |
| `POST` | `/api/agent/workspace/upload` | Upload file to workspace |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/users` | List users |
| `PUT` | `/api/users/{user_id}` | Update user |
| `GET` | `/api/settings` | Get system settings |
| `PUT` | `/api/settings` | Update system settings |
| `GET` | `/api/stats` | Get statistics |
| `GET` | `/api/events` | SSE event stream |
| `WS` | `/ws` | WebSocket real-time push |

## Project Structure

```
WeiLinkBot/
├── weilinkbot/
│   ├── api/                # FastAPI routes
│   │   ├── bot.py          # Bot control
│   │   ├── providers.py    # Provider management
│   │   ├── models.py       # LLM preset management
│   │   ├── st_presets.py   # SillyTavern presets
│   │   ├── world_books.py  # World books
│   │   ├── characters.py   # Character cards
│   │   ├── memories.py     # Memory system
│   │   ├── agent.py        # Agent config
│   │   ├── events.py       # SSE event stream
│   │   ├── stats.py        # Statistics
│   │   ├── settings.py     # System settings
│   │   └── ...
│   ├── services/           # Business logic
│   │   ├── bot_service.py          # Bot core
│   │   ├── llm_service.py          # Multi-provider LLM calls
│   │   ├── conversation_service.py # Conversation management
│   │   ├── memory_service.py       # Memory system (mem0 + ChromaDB)
│   │   ├── memory_buffer.py        # Memory message buffer (turn/timeout trigger)
│   │   ├── agent_service.py        # Agent high-level interface
│   │   ├── agent_loop.py           # Agent state machine loop
│   │   ├── consolidator.py         # Session compression / context management
│   │   ├── skill_service.py        # Skill system (directory-based, progressive loading)
│   │   ├── mcp_service.py          # MCP client (stdio/SSE/HTTP, tools/resources/prompts)
│   │   ├── mcp_server_service.py   # MCP server CRUD
│   │   ├── workspace_service.py    # Workspace file operations
│   │   ├── workspace_sandbox.py    # Workspace sandbox (path/size/extension limits)
│   │   ├── st_preset_service.py    # SillyTavern presets
│   │   ├── world_book_service.py   # World book keyword injection
│   │   ├── character_service.py    # Character card management
│   │   ├── local_embedding_service.py  # Local embedding (ONNX/ModelScope)
│   │   ├── ws_service.py           # WebSocket management
│   │   └── tools/                  # Agent tools
│   │       ├── base.py             # Tool base class
│   │       ├── registry.py         # Tool registry
│   │       ├── mcp_tool.py         # MCP tool/resource/prompt adapters
│   │       ├── math_tool.py        # Math calculations
│   │       ├── time_tool.py        # Time queries
│   │       ├── workspace_read_tool.py    # Read workspace files
│   │       ├── workspace_write_tool.py   # Write workspace files
│   │       ├── workspace_edit_tool.py    # Precise text replacement editing
│   │       ├── workspace_list_tool.py    # List workspace files
│   │       └── workspace_grep_tool.py    # Search workspace file content
│   ├── frontend/           # Dashboard (Alpine.js + Tailwind CSS)
│   ├── locales/            # i18n files (zh-CN, en)
│   ├── cli/                # CLI commands (Typer)
│   ├── config.py           # Configuration (Pydantic Settings)
│   ├── crypto.py           # API key encryption (AES)
│   ├── database.py         # SQLAlchemy async setup
│   ├── i18n.py             # Internationalization
│   ├── models.py           # ORM models
│   └── schemas.py          # Pydantic schemas
├── config.yaml             # Default configuration
├── .env.example            # Environment template
└── pyproject.toml          # Project metadata
```

## Tech Stack

| Layer | Technology |
|------|------|
| Backend | FastAPI + Uvicorn |
| Database | SQLite + SQLAlchemy 2.0 (async) |
| LLM Client | OpenAI SDK |
| Memory | mem0ai + ChromaDB |
| MCP Client | MCP Python SDK (stdio / SSE / Streamable HTTP) |
| Local Embedding | ONNX Runtime + ModelScope + Tokenizers |
| Frontend | Alpine.js + Tailwind CSS + Jinja2 |
| CLI | Typer + Rich |
| Encryption | Cryptography (AES) |
| WebSocket | FastAPI WebSocket |
| Packaging | Nuitka / PyInstaller |

## Acknowledgments

The skill system (directory-based structure, progressive loading, requirements checking), MCP integration (Streamable HTTP, resource/prompt registration, tool filtering, timeout/retry, schema normalization), and workspace improvements in this project are inspired by [HKUDS/nanobot](https://github.com/HKUDS/nanobot). Thanks to the nanobot team for their excellent open-source work.

## Compliance

This project is a personal local learning tool, bound to a single WeChat account, and is not a platform service. Users must comply with all applicable laws and regulations and must not use this project for any illegal or unauthorized purposes.

## License

This project is licensed under the [AGPL-3.0](LICENSE).

- Free to use, modify, and distribute
- Modified versions provided as a network service must disclose source code to users
- For closed-source commercial use, please contact us for a commercial license
