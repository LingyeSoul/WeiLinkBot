<p align="center">
  <img src="static/icons/logo.svg" width="128" height="128" alt="WeiLinkBot Logo">
</p>

<h1 align="center">WeiLinkBot</h1>

<p align="center">
  <a href="README_EN.md">English</a> | 中文
</p>

<p align="center">
基于 WeChat iLink Bot SDK 的 AI 聊天机器人平台，支持多模型提供商、SillyTavern 预设、角色卡、世界书、记忆系统及 Agent 工具调用，并通过网页控制台进行管理。
</p>

## 功能特性

- **微信接入** - 基于 [wechatbot-sdk](https://github.com/corespeed-io/wechatbot)，支持扫码登录和长轮询消息收发
- **多提供商管理** - 独立管理多个 LLM 提供商（OpenAI、DeepSeek 及任意兼容协议），API Key 加密存储
- **LLM 预设** - 保存多组模型配置并一键切换，支持文本/音频/图片能力标记与工具调用开关
- **SillyTavern 预设** - 导入/管理 SillyTavern prompt 预设，支持自定义系统提示词
- **世界书** - 导入/管理 SillyTavern World Book，基于关键词动态注入上下文
- **角色卡** - 创建和管理角色卡（描述、性格、场景、开场白、示例对话），支持头像上传
- **记忆系统** - 基于 mem0ai + ChromaDB 的向量记忆，支持本地 ONNX / ModelScope / 远程 Embedding，HNSW 索引参数可调
- **Agent 工具** - LLM 驱动的 Agent 循环，支持原生 Function Calling 和 Prompt 回退，内置数学计算、时间查询等工具
- **网页控制台** - 实时状态、会话查看、预设管理、用户控制、事件日志、统计面板
- **WebSocket 实时推送** - 机器人状态、消息等事件通过 WebSocket 实时推送至前端
- **多语言** - 支持中文（zh-CN）和英文（en）界面切换
- **按用户定制** - 支持独立系统提示词、消息历史长度限制、黑名单
- **持久化存储** - 使用 SQLite + SQLAlchemy 异步引擎，数据自动迁移

## 快速开始

### 1. 安装

```bash
pip install -e .
```

### 2. 配置

复制环境变量模板并配置你的大模型 API Key：

```bash
cp .env.example .env
# 编辑 .env 并设置 WEILINKBOT_LLM__API_KEY
```

也可以直接编辑 `config.yaml`。

### 3. 启动控制台

```bash
weilinkbot serve
```

在浏览器中打开 `http://localhost:8000`，然后点击"启动机器人"开始运行。

### 4. 命令行用法

```bash
# 机器人控制
weilinkbot start              # 在终端中启动机器人
weilinkbot status             # 查看当前配置

# 管理提示词
weilinkbot prompts list       # 列出系统提示词
weilinkbot prompts create     # 创建新提示词
weilinkbot prompts set-default 1  # 设置默认提示词

# 查看历史
weilinkbot history show <user_id>     # 查看消息记录
weilinkbot history clear <user_id>     # 清空历史记录

# 配置大模型
weilinkbot config set-llm --provider deepseek --api-key sk-xxx

# 启动网页控制台
weilinkbot serve              # 启动控制台 + API
weilinkbot serve --port 3000  # 指定端口
```

## 架构

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

## LLM 提供商

| 提供商 | 基础地址 | 示例模型 |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini |
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat |
| 自定义 | 任意兼容 OpenAI 协议的地址 | — |

支持通过 Provider 统一管理多个提供商的 API Key 和 Base URL，API Key 使用 AES 加密存储。

## API 接口

### 机器人控制

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/bot/status` | 机器人状态 |
| `POST` | `/api/bot/start` | 启动机器人 |
| `POST` | `/api/bot/stop` | 停止机器人 |

### 提供商与模型

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/providers` | 获取提供商列表 |
| `POST` | `/api/providers` | 创建提供商 |
| `PUT` | `/api/providers/{id}` | 更新提供商 |
| `DELETE` | `/api/providers/{id}` | 删除提供商 |
| `GET` | `/api/models` | 获取 LLM 预设列表 |
| `POST` | `/api/models` | 创建 LLM 预设 |
| `PUT` | `/api/models/{id}` | 更新 LLM 预设 |
| `DELETE` | `/api/models/{id}` | 删除 LLM 预设 |
| `POST` | `/api/models/{id}/activate` | 激活预设 |

### 会话与提示词

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/conversations` | 获取会话列表 |
| `GET` | `/api/conversations/{user_id}` | 获取消息记录 |
| `DELETE` | `/api/conversations/{user_id}` | 清空历史记录 |
| `GET` | `/api/prompts` | 获取提示词列表 |
| `POST` | `/api/prompts` | 创建提示词 |
| `PUT` | `/api/prompts/{id}` | 更新提示词 |
| `DELETE` | `/api/prompts/{id}` | 删除提示词 |

### SillyTavern 兼容

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/st-presets` | 获取 ST 预设列表 |
| `POST` | `/api/st-presets` | 创建 ST 预设 |
| `PUT` | `/api/st-presets/{id}` | 更新 ST 预设 |
| `DELETE` | `/api/st-presets/{id}` | 删除 ST 预设 |
| `POST` | `/api/st-presets/{id}/activate` | 激活 ST 预设 |
| `POST` | `/api/st-presets/{id}/entries` | 添加预设条目 |
| `PUT` | `/api/st-presets/entries/{entry_id}` | 更新预设条目 |
| `DELETE` | `/api/st-presets/entries/{entry_id}` | 删除预设条目 |
| `PUT` | `/api/st-presets/{id}/reorder` | 重排序条目 |
| `GET` | `/api/world-books` | 获取世界书列表 |
| `POST` | `/api/world-books` | 创建世界书 |
| `PUT` | `/api/world-books/{id}` | 更新世界书 |
| `DELETE` | `/api/world-books/{id}` | 删除世界书 |
| `POST` | `/api/world-books/{id}/activate` | 激活世界书 |
| `POST` | `/api/world-books/{id}/entries` | 添加世界书条目 |
| `PUT` | `/api/world-books/entries/{entry_id}` | 更新世界书条目 |
| `DELETE` | `/api/world-books/entries/{entry_id}` | 删除世界书条目 |
| `PUT` | `/api/world-books/{id}/reorder` | 重排序条目 |

### 角色卡

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/characters` | 获取角色卡列表 |
| `POST` | `/api/characters` | 创建角色卡 |
| `PUT` | `/api/characters/{id}` | 更新角色卡 |
| `DELETE` | `/api/characters/{id}` | 删除角色卡 |
| `POST` | `/api/characters/{id}/activate` | 激活角色卡 |

### 记忆与 Agent

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/memories/config` | 获取记忆配置 |
| `PUT` | `/api/memories/config` | 更新记忆配置 |
| `POST` | `/api/memories/test` | 测试记忆连接 |
| `GET` | `/api/memories/{user_id}` | 获取用户记忆 |
| `GET` | `/api/agent/config` | 获取 Agent 配置 |
| `PUT` | `/api/agent/config` | 更新 Agent 配置 |

### 系统

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/users` | 获取用户列表 |
| `PUT` | `/api/users/{user_id}` | 更新用户信息 |
| `GET` | `/api/settings` | 获取系统设置 |
| `PUT` | `/api/settings` | 更新系统设置 |
| `GET` | `/api/stats` | 获取统计信息 |
| `GET` | `/api/events` | SSE 事件流 |
| `WS` | `/ws` | WebSocket 实时推送 |

## 项目结构

```
WeiLinkBot/
├── weilinkbot/
│   ├── api/                # FastAPI 路由
│   │   ├── bot.py          # 机器人控制
│   │   ├── providers.py    # 提供商管理
│   │   ├── models.py       # LLM 预设管理
│   │   ├── st_presets.py   # SillyTavern 预设
│   │   ├── world_books.py  # 世界书
│   │   ├── characters.py   # 角色卡
│   │   ├── memories.py     # 记忆系统
│   │   ├── agent.py        # Agent 配置
│   │   ├── events.py       # SSE 事件流
│   │   ├── stats.py        # 统计
│   │   ├── settings.py     # 系统设置
│   │   └── ...
│   ├── services/           # 业务逻辑
│   │   ├── bot_service.py          # 机器人核心
│   │   ├── llm_service.py          # 多提供商 LLM 调用
│   │   ├── conversation_service.py # 会话管理
│   │   ├── memory_service.py       # 记忆系统 (mem0 + ChromaDB)
│   │   ├── agent_service.py        # Agent 工具调用循环
│   │   ├── st_preset_service.py    # SillyTavern 预设
│   │   ├── world_book_service.py   # 世界书关键词注入
│   │   ├── character_service.py    # 角色卡管理
│   │   ├── local_embedding_service.py  # 本地 Embedding (ONNX/ModelScope)
│   │   ├── ws_service.py           # WebSocket 管理
│   │   └── tools/                  # Agent 工具
│   │       ├── base.py             # 工具基类
│   │       ├── registry.py         # 工具注册表
│   │       ├── math_tool.py        # 数学计算
│   │       └── time_tool.py        # 时间查询
│   ├── frontend/           # 控制台前端（Alpine.js + Tailwind）
│   ├── locales/            # 多语言文件（zh-CN, en）
│   ├── cli/                # 命令行命令（Typer）
│   ├── config.py           # 配置加载（Pydantic Settings）
│   ├── crypto.py           # API Key 加解密（AES）
│   ├── database.py         # SQLAlchemy 异步初始化
│   ├── i18n.py             # 国际化
│   ├── models.py           # ORM 模型
│   └── schemas.py          # Pydantic 数据结构
├── config.yaml             # 默认配置
├── .env.example            # 环境变量模板
└── pyproject.toml          # 项目元数据
```

## 技术栈

| 层 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 数据库 | SQLite + SQLAlchemy 2.0 (async) |
| LLM 调用 | OpenAI SDK |
| 记忆系统 | mem0ai + ChromaDB |
| 本地 Embedding | ONNX Runtime + ModelScope + Tokenizers |
| 前端 | Alpine.js + Tailwind CSS + Jinja2 |
| CLI | Typer + Rich |
| 加密 | Cryptography (AES) |
| WebSocket | FastAPI WebSocket |
| 打包 | Nuitka / PyInstaller |

## 许可证

本项目采用 [AGPL-3.0](LICENSE) 许可证。

- 可自由使用、修改和分发
- 修改后的版本通过网络提供服务时，必须向用户公开源码
- 如需闭源商业使用，请联系我们获取商业授权
