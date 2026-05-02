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
- **Memory System** — vector memory powered by mem0ai + ChromaDB, with local ONNX / ModelScope / remote embedding support and tunable HNSW parameters
- **Agent Tools** — LLM-driven agent loop with native function calling and prompt-based fallback, built-in math and time tools
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
       ┌──────┴──────┐
       │AgentService  │
       │(tool calling)│
       └─────────────┘
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
| `GET` | `/api/memories/config` | Get memory config |
| `PUT` | `/api/memories/config` | Update memory config |
| `POST` | `/api/memories/test` | Test memory connection |
| `GET` | `/api/memories/{user_id}` | Get user memories |
| `GET` | `/api/agent/config` | Get agent config |
| `PUT` | `/api/agent/config` | Update agent config |

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
│   │   ├── agent_service.py        # Agent tool calling loop
│   │   ├── st_preset_service.py    # SillyTavern presets
│   │   ├── world_book_service.py   # World book keyword injection
│   │   ├── character_service.py    # Character card management
│   │   ├── local_embedding_service.py  # Local embedding (ONNX/ModelScope)
│   │   ├── ws_service.py           # WebSocket management
│   │   └── tools/                  # Agent tools
│   │       ├── base.py             # Tool base class
│   │       ├── registry.py         # Tool registry
│   │       ├── math_tool.py        # Math calculations
│   │       └── time_tool.py        # Time queries
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
| Local Embedding | ONNX Runtime + ModelScope + Tokenizers |
| Frontend | Alpine.js + Tailwind CSS + Jinja2 |
| CLI | Typer + Rich |
| Encryption | Cryptography (AES) |
| WebSocket | FastAPI WebSocket |
| Packaging | Nuitka / PyInstaller |

## License

This project is licensed under the [AGPL-3.0](LICENSE).

- Free to use, modify, and distribute
- Modified versions provided as a network service must disclose source code to users
- For closed-source commercial use, please contact us for a commercial license
