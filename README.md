<p align="center">
  <img src="static/icons/logo.svg" width="128" height="128" alt="WeiLinkBot Logo">
</p>

<h1 align="center">WeiLinkBot</h1>

<p align="center">
  <a href="README_EN.md">English</a> | 中文
</p>

<p align="center">
基于 WeChat iLink Bot SDK 的 AI 聊天机器人平台，可将 OpenAI、DeepSeek 等大模型接入微信，并通过网页控制台进行管理。
</p>

## 功能特性

- **微信接入** - 基于 [wechatbot-sdk](https://github.com/corespeed-io/wechatbot)，支持扫码登录和长轮询消息收发
- **多模型支持** - 支持 OpenAI、DeepSeek，以及任意兼容 OpenAI 协议的接口
- **网页控制台** - 实时状态、会话查看、提示词管理、用户控制
- **命令行工具** - 启动/停止机器人、管理提示词、查看历史消息
- **持久化存储** - 使用 SQLite 保存会话、提示词和用户配置
- **按用户定制** - 支持独立系统提示词、消息历史长度限制、黑名单

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

在浏览器中打开 `http://localhost:8000`，然后点击“启动机器人”开始运行。

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

## 大模型提供商

| 提供商 | 基础地址 | 示例模型 |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini |
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat |
| 自定义 | 任意兼容 OpenAI 协议的地址 | — |

可通过环境变量配置：

```bash
WEILINKBOT_LLM__PROVIDER=openai
WEILINKBOT_LLM__API_KEY=sk-...
WEILINKBOT_LLM__MODEL=gpt-4o-mini
```

## API 接口

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/api/bot/status` | 机器人状态 |
| `POST` | `/api/bot/start` | 启动机器人 |
| `POST` | `/api/bot/stop` | 停止机器人 |
| `GET` | `/api/conversations` | 获取会话列表 |
| `GET` | `/api/conversations/{user_id}` | 获取消息记录 |
| `DELETE` | `/api/conversations/{user_id}` | 清空历史记录 |
| `GET` | `/api/prompts` | 获取提示词列表 |
| `POST` | `/api/prompts` | 创建提示词 |
| `PUT` | `/api/prompts/{id}` | 更新提示词 |
| `DELETE` | `/api/prompts/{id}` | 删除提示词 |
| `GET` | `/api/config` | 获取大模型配置 |
| `PUT` | `/api/config` | 更新大模型配置 |
| `GET` | `/api/users` | 获取用户列表 |
| `PUT` | `/api/users/{user_id}` | 更新用户信息 |

## 项目结构

```
WeiLinkBot/
├── weilinkbot/
│   ├── api/           # FastAPI 路由
│   ├── cli/           # 命令行命令（Typer）
│   ├── frontend/      # 控制台前端（Alpine.js + Tailwind）
│   ├── services/      # 机器人、大模型、会话服务
│   ├── config.py      # 配置加载
│   ├── database.py    # SQLAlchemy 异步初始化
│   ├── models.py      # ORM 模型
│   └── schemas.py     # Pydantic 数据结构
├── config.yaml        # 默认配置
├── .env.example       # 环境变量模板
└── pyproject.toml     # 项目元数据
```

## 许可证

GPL-3.0
