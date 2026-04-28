# WeiLinkBot

AI Chatbot Platform powered by WeChat iLink Bot SDK. Connect LLMs (OpenAI, DeepSeek, etc.) to WeChat with a web dashboard for management.

## Features

- **WeChat Integration** — via [wechatbot-sdk](https://github.com/corespeed-io/wechatbot), QR login, long-poll messaging
- **Multi-LLM Support** — OpenAI, DeepSeek, or any OpenAI-compatible API
- **Web Dashboard** — real-time status, conversation viewer, prompt management, user controls
- **CLI Tools** — start/stop bot, manage prompts, view history
- **Persistent Storage** — SQLite database for conversations, prompts, and user configs
- **Per-user Customization** — individual system prompts, message history limits, blocklist

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
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   WeChat     │────▶│ wechatbot-sdk│────▶│ BotService   │
│  (iLink API) │◀────│ (long-poll)  │     │ (orchestrator│
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                │
                    ┌───────────────────────────┼──────────┐
                    ▼                           ▼          ▼
             ┌─────────────┐          ┌──────────┐  ┌──────────┐
             │ LLMService   │          │  SQLite   │  │ FastAPI  │
             │ (OpenAI API) │          │ (SQLAlch) │  │ Dashboard│
             └─────────────┘          └──────────┘  └──────────┘
```

## LLM Providers

| Provider | Base URL | Example Models |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini |
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat |
| Custom | Any OpenAI-compatible URL | — |

Set via environment variables:

```bash
WEILINKBOT_LLM__PROVIDER=openai
WEILINKBOT_LLM__API_KEY=sk-...
WEILINKBOT_LLM__MODEL=gpt-4o-mini
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/bot/status` | Bot status |
| `POST` | `/api/bot/start` | Start bot |
| `POST` | `/api/bot/stop` | Stop bot |
| `GET` | `/api/conversations` | List conversations |
| `GET` | `/api/conversations/{user_id}` | Get messages |
| `DELETE` | `/api/conversations/{user_id}` | Clear history |
| `GET` | `/api/prompts` | List prompts |
| `POST` | `/api/prompts` | Create prompt |
| `PUT` | `/api/prompts/{id}` | Update prompt |
| `DELETE` | `/api/prompts/{id}` | Delete prompt |
| `GET` | `/api/config` | Get LLM config |
| `PUT` | `/api/config` | Update LLM config |
| `GET` | `/api/users` | List users |
| `PUT` | `/api/users/{user_id}` | Update user |

## Project Structure

```
WeiLinkBot/
├── weilinkbot/
│   ├── api/           # FastAPI routes
│   ├── cli/           # CLI commands (Typer)
│   ├── frontend/      # Dashboard (Alpine.js + Tailwind)
│   ├── services/      # Bot, LLM, Conversation services
│   ├── config.py      # Configuration loading
│   ├── database.py    # SQLAlchemy async setup
│   ├── models.py      # ORM models
│   └── schemas.py     # Pydantic schemas
├── config.yaml        # Default configuration
├── .env.example       # Environment template
└── pyproject.toml     # Project metadata
```

## License

GPL-3.0
