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

- **微信接入** - 基于 [wechatbot-sdk](https://github.com/corespeed-io/wechatbot)，支持扫码登录和长轮询消息收发，QR 码前端渲染
- **多提供商管理** - 独立管理多个 LLM 提供商（OpenAI、DeepSeek 及任意兼容协议），API Key 加密存储
- **LLM 预设** - 保存多组模型配置并一键切换，支持文本/音频/图片能力标记与工具调用开关
- **SillyTavern 预设** - 导入/管理 SillyTavern prompt 预设，支持自定义系统提示词
- **世界书** - 导入/管理 SillyTavern World Book，基于关键词动态注入上下文
- **角色卡** - 创建和管理角色卡（描述、性格、场景、开场白、示例对话），支持头像上传
- **表情包系统** - 管理表情包收藏夹，支持上传/导入（ZIP/7Z/RAR）、目录扫描、按关键词搜索，内置 search_sticker / list_sticker_packs / send_sticker 三个 Agent 工具
- **记忆系统** - 基于 mem0ai + ChromaDB 的向量记忆，支持本地 ONNX / ModelScope / 远程 Embedding，HNSW 索引参数可调；支持批量摘要（轮数/超时双触发）、事实+摘要双维度存储、时间衰减与重排检索
- **Agent 状态机** - 基于显式状态机的 Agent 循环（INIT → INJECT → EXECUTE → COMPRESS → FINALIZE → DONE），支持原生 Function Calling 和 Prompt 回退，可调试、可扩展、可容错恢复
- **网络工具** - Bing 中国搜索、网页内容提取、网页交互（Browser Use）、无头浏览器渲染（Obscura），支持 JavaScript 执行和动态内容加载，工具执行超时保护与结果截断
- **工作区工具** - 沙盒化的文件操作（读/写/编辑/列表/搜索），支持可配置根目录、大小限制和扩展名过滤，新增 `workspace_edit` 支持精确文本替换编辑，每个工具可独立开关
- **技能系统** - 目录式技能管理（`workspace/skills/<name>/SKILL.md`），支持渐进式加载（摘要注入上下文、按需读取完整内容）、需求检查（CLI 工具/环境变量）、always-on 技能、禁用列表，兼容旧版平铺 `.md` 文件
- **MCP 集成** - 支持 stdio / SSE / Streamable HTTP 三种传输方式，自动发现并注册 MCP 工具、资源（Resources）和提示词（Prompts），支持工具过滤（enabledTools）、每服务器超时配置、瞬态错误自动重试、HTTP 连接预检
- **会话压缩** - 自动压缩旧消息为摘要，支持 Token 预算管理和消息数量限制，防止上下文窗口溢出；基于 tiktoken 的精确 Token 计数
- **并发控制** - 全局信号量限制 LLM 并发请求，每用户消息队列防止竞态条件
- **网页控制台** - 实时状态、会话查看、预设管理、用户控制、表情包管理、工作区配置、事件日志、统计面板
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

## 技能系统（Skills）

技能是 Markdown 文件，定义了 Agent 的专业行为。支持两种格式：

### 目录式技能（推荐）

```
workspace/skills/
├── translation/
│   └── SKILL.md
├── code-review/
│   └── SKILL.md
└── my-custom-skill/
    └── SKILL.md
```

每个 `SKILL.md` 支持 YAML frontmatter：

```markdown
---
name: translation
description: Translate between languages with style preservation.
metadata:
  nanobot:
    always: true              # 始终注入上下文（可选）
    requires:
      bins: ["trans"]         # 依赖的 CLI 工具（可选）
      env: ["DEEPL_API_KEY"]  # 依赖的环境变量（可选）
---

# Translation Skill

When translating, preserve the original tone and formatting...
```

### 渐进式加载

为节省 Token，技能系统采用渐进式加载策略：

1. **上下文注入**：`always` 技能注入完整内容；其他已启用技能仅注入摘要（名称 + 描述）
2. **按需加载**：Agent 可通过 `workspace_read` 工具在需要时读取完整技能内容
3. **需求检查**：缺少依赖（CLI 工具或环境变量）的技能会被自动标记为不可用

### 配置

在控制台的 Agent 设置中管理技能：

| 选项 | 说明 |
|------|------|
| `enabled_skills` | 启用的技能名称列表 |
| `disabled_skills` | 禁用的技能名称列表（从加载中排除） |

### 导入

支持单个 `.md` 文件或 `.zip` 压缩包导入。ZIP 包支持 `manifest.json` 元数据。

## MCP 集成（Model Context Protocol）

支持连接外部 MCP 服务器，将其工具、资源和提示词注册为原生 Agent 工具。

### 传输方式

| 方式 | 配置 | 适用场景 |
|------|------|----------|
| **stdio** | `command` + `args` | 本地进程（npx / uvx） |
| **SSE** | `url` | 远程 HTTP 端点（`/sse`） |
| **Streamable HTTP** | `url` | 远程 HTTP 端点（`/mcp/`） |

### 配置示例

通过控制台或 API 添加 MCP 服务器：

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

远程 MCP 服务器：

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

### 高级功能

| 功能 | 说明 |
|------|------|
| **工具过滤** | `enabled_tools` 指定注册的工具列表，`["*"]` 表示全部 |
| **超时控制** | `tool_timeout` 每个工具调用的超时秒数（默认 30） |
| **自动重试** | 瞬态连接错误（断开、重置）自动重试一次 |
| **资源注册** | MCP Resources 自动注册为只读工具 |
| **提示词注册** | MCP Prompts 自动注册为只读工具 |
| **连接预检** | HTTP 连接前先探测端口可达性，避免崩溃 |
| **Schema 兼容** | 自动规范化 nullable JSON Schema，兼容 OpenAI/Anthropic API |

### 工具命名

MCP 工具名称格式：`{server_name}__{tool_name}`

资源格式：`{server_name}__resource__{resource_name}`

提示词格式：`{server_name}__prompt__{prompt_name}`

## 工作区（Workspace）

工作区是 Agent 的沙盒化文件操作环境。

### 工具列表

| 工具 | 说明 |
|------|------|
| `workspace_read` | 读取文件内容（支持行范围） |
| `workspace_write` | 写入/追加文件内容 |
| `workspace_edit` | 精确文本替换编辑（比全文重写更高效） |
| `workspace_list` | 列出文件和目录（支持 glob 模式） |
| `workspace_grep` | 搜索文件内容（支持正则） |

### 安全沙盒

所有文件操作通过 `WorkspaceSandbox` 安全校验：

- **路径验证**：拒绝绝对路径、`..` 遍历、符号链接逃逸
- **扩展名过滤**：阻止可执行文件（`.exe`, `.bat`, `.dll` 等），允许 `.py`、`.js`、`.sh` 等脚本文件
- **大小限制**：读取上限 1MB，写入上限 512KB
- **结果限制**：目录列表最多 500 条，搜索最多 100 条

### 配置

```json
{
  "root": "workspace",
  "read_max_size": 1048576,
  "write_max_size": 524288,
  "blocked_extensions": [".exe", ".bat", ".dll", ...]
}
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

### 表情包

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/sticker-packs` | 获取表情包列表 |
| `POST` | `/api/sticker-packs` | 创建表情包 |
| `GET` | `/api/sticker-packs/{id}` | 获取表情包详情 |
| `PATCH` | `/api/sticker-packs/{id}` | 更新表情包 |
| `DELETE` | `/api/sticker-packs/{id}` | 删除表情包 |
| `POST` | `/api/sticker-packs/import` | 导入压缩包 |
| `POST` | `/api/sticker-packs/scan` | 目录扫描 |
| `POST` | `/api/sticker-packs/{id}/stickers` | 添加表情 |
| `PATCH` | `/api/sticker-packs/stickers/{id}` | 更新表情 |
| `DELETE` | `/api/sticker-packs/stickers/{id}` | 删除表情 |

### 工作区

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/agent/workspace/config` | 获取工作区配置 |
| `PUT` | `/api/agent/workspace/config` | 更新工作区配置 |
| `GET` | `/api/agent/workspace/files` | 列出工作区文件 |
| `GET` | `/api/agent/workspace/read` | 读取工作区文件 |
| `POST` | `/api/agent/workspace/upload` | 上传文件到工作区 |

### 技能管理

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/agent/skills` | 获取技能列表（含 source、available、always 标记） |
| `PUT` | `/api/agent/skills` | 更新已启用技能列表 |
| `POST` | `/api/agent/skills` | 创建技能 |
| `POST` | `/api/agent/skills/import` | 导入技能（.md 或 .zip） |
| `DELETE` | `/api/agent/skills/{name}` | 删除技能 |

### MCP 服务器

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/agent/mcp` | 获取 MCP 服务器列表（含连接状态） |
| `POST` | `/api/agent/mcp` | 创建 MCP 服务器配置 |
| `PUT` | `/api/agent/mcp/{id}` | 更新 MCP 服务器配置 |
| `DELETE` | `/api/agent/mcp/{id}` | 删除并断开连接 |
| `POST` | `/api/agent/mcp/{id}/reconnect` | 重新连接 |

### 记忆与 Agent

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/memories/status` | 记忆系统状态 |
| `GET` | `/api/memories/config` | 获取记忆配置 |
| `PUT` | `/api/memories/config` | 更新记忆配置 |
| `POST` | `/api/memories/config/test` | 测试 Embedding 连接 |
| `GET` | `/api/memories/{user_id}` | 获取用户记忆 |
| `GET` | `/api/memories/{user_id}/search` | 语义搜索记忆 |
| `GET` | `/api/memories/{user_id}/summaries` | 获取用户对话摘要 |
| `DELETE` | `/api/memories/summaries/{id}` | 删除单条摘要 |
| `DELETE` | `/api/memories/summaries/user/{user_id}` | 清空用户摘要 |
| `GET` | `/api/memories/export` | 导出记忆 JSON |
| `POST` | `/api/memories/import` | 导入记忆 JSON |
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
│   │   ├── agent.py        # Agent 配置 & 工作区 API
│   │   ├── sticker_packs.py # 表情包管理
│   │   ├── events.py       # SSE 事件流
│   │   ├── stats.py        # 统计
│   │   ├── settings.py     # 系统设置
│   │   └── ...
│   ├── services/           # 业务逻辑
│   │   ├── bot_service.py          # 机器人核心
│   │   ├── llm_service.py          # 多提供商 LLM 调用
│   │   ├── conversation_service.py # 会话管理
│   │   ├── memory_service.py       # 记忆系统 (mem0 + ChromaDB)
│   │   ├── memory_buffer.py        # 记忆消息缓冲（轮数/超时触发）
│   │   ├── agent_service.py        # Agent 高层接口
│   │   ├── agent_loop.py           # Agent 状态机循环
│   │   ├── consolidator.py         # 会话压缩 / 上下文整理
│   │   ├── message_queue.py        # 每用户消息队列 & 并发控制
│   │   ├── token_counter.py        # Token 计数（tiktoken）
│   │   ├── sticker_service.py      # 表情包管理服务
│   │   ├── workspace_service.py    # 工作区文件操作
│   │   ├── workspace_sandbox.py    # 工作区沙盒（路径/大小/扩展名限制）
│   │   ├── st_preset_service.py    # SillyTavern 预设
│   │   ├── world_book_service.py   # 世界书关键词注入
│   │   ├── character_service.py    # 角色卡管理
│   │   ├── local_embedding_service.py  # 本地 Embedding (ONNX/ModelScope)
│   │   ├── skill_service.py        # 技能系统
│   │   ├── mcp_service.py          # MCP 服务
│   │   ├── ws_service.py           # WebSocket 管理
│   │   └── tools/                  # Agent 工具
│   │       ├── base.py             # 工具基类
│   │       ├── registry.py         # 工具注册表
│   │       ├── sanitize.py         # 输入净化
│   │       ├── math_tool.py        # 数学计算
│   │       ├── time_tool.py        # 时间查询
│   │       ├── mcp_tool.py         # MCP 协议工具
│   │       ├── web_search_tool.py  # Bing 搜索
│   │       ├── web_fetch_tool.py   # 网页内容提取
│   │       ├── browser_tool.py     # 网页交互
│   │       ├── browser_use_tool.py # Browser Use 集成
│   │       ├── _obscura.py         # 无头浏览器渲染
│   │       ├── _url_validate.py    # URL 安全校验
│   │       ├── search_sticker_tool.py    # 搜索表情包
│   │       ├── list_sticker_packs_tool.py # 列出表情包收藏夹
│   │       ├── send_sticker_tool.py      # 发送表情包
│   │       ├── workspace_read_tool.py    # 读取工作区文件
│   │       ├── workspace_write_tool.py   # 写入工作区文件
│   │       ├── workspace_edit_tool.py    # 精确文本替换编辑
│   │       ├── workspace_list_tool.py    # 列出工作区文件
│   │       └── workspace_grep_tool.py    # 搜索工作区文件内容
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
| Token 计数 | tiktoken |
| MCP 客户端 | MCP Python SDK (stdio / SSE / Streamable HTTP) |
| 无头浏览器 | Obscura (Playwright 内核) |
| 表情包解压 | py7zr / rarfile / zipfile |
| 前端 | Alpine.js + Tailwind CSS + Jinja2 |
| CLI | Typer + Rich |
| 加密 | Cryptography (AES) |
| WebSocket | FastAPI WebSocket |
| 打包 | Nuitka / PyInstaller |

## 致谢

本项目中的技能系统（目录式结构、渐进式加载、需求检查）、MCP 集成（Streamable HTTP、资源/提示词注册、工具过滤、超时重试、Schema 规范化）及工作区改进参考了 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 的设计。感谢 nanobot 团队的优秀开源工作。

## 合规使用

本项目为个人本地学习工具，单微信绑定，非平台化服务。使用者应遵守相关法律法规，不得用于违法违规用途。

## 许可证

本项目采用 [AGPL-3.0](LICENSE) 许可证。

- 可自由使用、修改和分发
- 修改后的版本通过网络提供服务时，必须向用户公开源码
- 如需闭源商业使用，请联系我们获取商业授权
