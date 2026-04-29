"""Bot service — orchestrates WeChatBot SDK, LLM, and conversation services."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from wechatbot import WeChatBot, IncomingMessage, Credentials
from sqlalchemy import select, update

from ..config import AppConfig, LLMConfig
from ..database import get_session_factory
from ..models import LLMPreset
from .llm_service import LLMService
from .conversation_service import ConversationService
from ..i18n import t

logger = logging.getLogger(__name__)


class BotState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


# ── Magic Commands ────────────────────────────────────────────────

COMMANDS = {
    "/help": "Show this help message",
    "/status": "Show bot status and current model",
    "/model": "List available models",
    "/model <name>": "Switch to a model",
    "/clear": "Clear your conversation history",
    "/prompt": "Show current system prompt",
    "/reset": "Reset to default system prompt",
    "/char": "List character cards",
    "/char <name>": "Switch to a character card",
    "/char info": "Show current character details",
    "/char off": "Disable character card",
}


class BotService:
    """Manages WeChatBot lifecycle and message processing pipeline."""

    def __init__(self, config: AppConfig, llm_service: LLMService) -> None:
        self._config = config
        self._llm = llm_service
        self._state = BotState.STOPPED
        self._task: Optional[asyncio.Task] = None
        self._error: Optional[str] = None
        self._login_url: Optional[str] = None
        self._credentials: Optional[Credentials] = None
        self._bot: Optional[WeChatBot] = None
        self._start_time: Optional[float] = None
        self._message_count: int = 0
        # Session-level token tracking (model -> tokens, reset on each start)
        self._session_tokens: dict[str, int] = {}
        self._session_requests: dict[str, int] = {}

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def login_url(self) -> Optional[str]:
        return self._login_url

    @property
    def credentials(self) -> Optional[Credentials]:
        return self._credentials

    @property
    def llm(self) -> LLMService:
        return self._llm

    @property
    def uptime_seconds(self) -> Optional[float]:
        if self._start_time and self._state == BotState.RUNNING:
            return time.time() - self._start_time
        return None

    @property
    def message_count(self) -> int:
        return self._message_count

    @property
    def session_token_stats(self) -> dict:
        """Current session token usage, grouped by model."""
        models = []
        total_tokens = 0
        total_requests = 0
        all_models = set(self._session_tokens.keys()) | set(self._session_requests.keys())
        for m in sorted(all_models, key=lambda k: self._session_tokens.get(k, 0), reverse=True):
            t = self._session_tokens.get(m, 0)
            r = self._session_requests.get(m, 0)
            models.append({"model": m, "tokens": t, "requests": r})
            total_tokens += t
            total_requests += r
        return {"models": models, "total_tokens": total_tokens, "total_requests": total_requests}

    async def start(self) -> None:
        """Start the bot (login + begin polling)."""
        if self._state in (BotState.RUNNING, BotState.STARTING):
            logger.warning("Bot is already %s", self._state.value)
            return

        self._state = BotState.STARTING
        self._error = None
        self._login_url = None

        self._task = asyncio.create_task(self._run())
        logger.info("Bot start task created")

    async def _run(self) -> None:
        """Internal: login and start long-poll loop."""
        try:
            cred_path = str(Path(self._config.bot.cred_path).expanduser())

            self._bot = WeChatBot(
                base_url=self._config.bot.base_url,
                cred_path=cred_path,
                on_qr_url=self._on_qr_url,
                on_scanned=lambda: logger.info("QR scanned — confirm in WeChat"),
                on_expired=lambda: logger.warning("QR expired"),
                on_error=lambda err: logger.error("Bot error: %s", err),
            )

            self._bot.on_message(self._handle_message)

            logger.info("Logging in...")
            self._credentials = await self._bot.login()
            self._login_url = None
            self._state = BotState.RUNNING
            self._start_time = time.time()
            self._message_count = 0
            self._session_tokens.clear()
            self._session_requests.clear()
            logger.info(
                "Bot running — user_id=%s account_id=%s",
                self._credentials.user_id,
                self._credentials.account_id,
            )

            await self._bot.start()

        except Exception as e:
            self._state = BotState.ERROR
            self._error = str(e)
            logger.exception("Bot crashed: %s", e)

        finally:
            if self._state != BotState.ERROR:
                self._state = BotState.STOPPED
            self._start_time = None
            logger.info("Bot stopped (state=%s)", self._state.value)

    async def stop(self) -> None:
        """Stop the bot gracefully."""
        if self._bot:
            self._bot.stop()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._state = BotState.STOPPED
        self._login_url = None
        logger.info("Bot stop requested")

    def _on_qr_url(self, url: str) -> None:
        self._login_url = url
        logger.info("Scan this QR URL in WeChat: %s", url)

    # ── Message Handler ──────────────────────────────────────────

    async def _handle_message(self, msg: IncomingMessage) -> None:
        """Core message pipeline: command check → LLM → reply."""
        user_id = msg.user_id
        text = msg.text.strip()

        # Check for magic commands first
        if text.startswith("/"):
            await self._handle_command(msg, text)
            return

        # Normal LLM flow
        self._message_count += 1
        session_factory = get_session_factory()
        async with session_factory() as db:
            conv_service = ConversationService(db)
            try:
                if await conv_service.is_blocked(user_id):
                    logger.info("Blocked user %s — ignoring", user_id)
                    return

                try:
                    await self._bot.send_typing(user_id)
                except Exception:
                    pass

                await conv_service.add_message(user_id, "user", text)
                await db.commit()

                context = await conv_service.build_context(user_id)
                context.append({"role": "user", "content": text})

                logger.info("LLM request for user %s: %s...", user_id, text[:50])
                response_text, tokens = await self._llm.chat(context)

                # Track session token usage
                model_name = self._llm.config.model
                self._session_tokens[model_name] = self._session_tokens.get(model_name, 0) + tokens
                self._session_requests[model_name] = self._session_requests.get(model_name, 0) + 1

                await conv_service.add_message(
                    user_id, "assistant", response_text, tokens, model_name
                )
                await db.commit()

                await self._bot.reply(msg, response_text)
                logger.info("Replied to user %s (%d tokens)", user_id, tokens)

            except Exception as e:
                logger.exception("Error handling message from %s: %s", user_id, e)
                try:
                    await db.rollback()
                    await self._bot.reply(msg, t("bot.error.process"))
                except Exception:
                    pass

    # ── Command Router ───────────────────────────────────────────

    async def _handle_command(self, msg: IncomingMessage, text: str) -> None:
        """Route /commands to their handlers."""
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        handlers = {
            "/help": self._cmd_help,
            "/status": self._cmd_status,
            "/model": lambda m, a: self._cmd_model(m, a),
            "/clear": self._cmd_clear,
            "/prompt": self._cmd_prompt,
            "/reset": self._cmd_reset,
            "/char": lambda m, a: self._cmd_char(m, a),
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                await handler(msg, args)
            except Exception as e:
                logger.exception("Command %s error: %s", cmd, e)
                await self._bot.reply(msg, t("bot.error.command", e=e))
        else:
            await self._bot.reply(
                msg,
                t("bot.error.unknown_cmd", cmd=cmd) + "\n\n" + self._format_help()
            )

    def _format_help(self) -> str:
        lines = [t("bot.help.title")]
        for cmd, desc in COMMANDS.items():
            lines.append(f"  {cmd} — {desc}")
        return "\n".join(lines)

    # ── Command Handlers ─────────────────────────────────────────

    async def _cmd_help(self, msg: IncomingMessage, args: str) -> None:
        await self._bot.reply(msg, self._format_help())

    async def _cmd_status(self, msg: IncomingMessage, args: str) -> None:
        uptime = self.uptime_seconds
        uptime_str = self._format_uptime(uptime) if uptime else "N/A"
        model = self._llm.config.model
        provider = self._llm.config.provider
        session_stats = self.session_token_stats

        session_factory = get_session_factory()
        async with session_factory() as db:
            from ..models import Conversation
            conv_result = await db.execute(select(Conversation))
            conv_count = len(conv_result.scalars().all())

            conv_service = ConversationService(db)
            history_stats = await conv_service.get_token_stats()

        lines = [
            t("bot.status.title"),
            "─" * 30,
            f"{t('bot.status.status')} {self._state.value}",
            f"{t('bot.status.uptime')} {uptime_str}",
            f"{t('bot.status.model')} {model}",
            f"{t('bot.status.provider')} {provider}",
            f"{t('bot.status.messages_session')} {self._message_count}",
            f"{t('bot.status.active_convs')} {conv_count}",
        ]
        if self._credentials:
            lines.append(f"{t('bot.status.user_id')} {self._credentials.user_id}")

        # Current session token usage
        lines.append("")
        lines.append(t("bot.status.session"))
        lines.append("─" * 30)
        if session_stats["models"]:
            for m in session_stats["models"]:
                lines.append(f"  {m['model']}: {m['tokens']:,} tokens ({m['requests']} reqs)")
            lines.append(f"  {t('bot.status.total')} {session_stats['total_tokens']:,} tokens ({session_stats['total_requests']} reqs)")
        else:
            lines.append(t("bot.status.no_requests"))

        # All-time token usage
        if history_stats["models"]:
            lines.append("")
            lines.append(t("bot.status.all_time"))
            lines.append("─" * 30)
            for m in history_stats["models"]:
                lines.append(f"  {m['model']}: {m['tokens']:,} tokens ({m['requests']} reqs)")
            lines.append(f"  {t('bot.status.total')} {history_stats['total_tokens']:,} tokens ({history_stats['total_requests']} reqs)")

        await self._bot.reply(msg, "\n".join(lines))

    async def _cmd_model(self, msg: IncomingMessage, args: str) -> None:
        session_factory = get_session_factory()
        async with session_factory() as db:
            if not args:
                # List all models
                result = await db.execute(
                    select(LLMPreset).order_by(LLMPreset.is_active.desc(), LLMPreset.id)
                )
                presets = result.scalars().all()
                if not presets:
                    await self._bot.reply(msg, t("bot.model.no_models"))
                    return

                current = self._llm.config.model
                lines = [f"{t('bot.model.current')} {current}", "", t("bot.model.available")]
                for p in presets:
                    marker = t("bot.model.active_marker") if p.is_active else ""
                    lines.append(f"  {p.name} — {p.model} ({p.provider}){marker}")
                lines.append("")
                lines.append(t("bot.model.switch_hint"))
                await self._bot.reply(msg, "\n".join(lines))
                return

            # Switch to specified model
            target = args.strip()
            # Try by name first, then by model name
            result = await db.execute(
                select(LLMPreset).where(LLMPreset.name == target)
            )
            preset = result.scalar_one_or_none()

            if not preset:
                # Try matching by model field
                result = await db.execute(
                    select(LLMPreset).where(LLMPreset.model == target)
                )
                preset = result.scalar_one_or_none()

            if not preset:
                await self._bot.reply(
                    msg,
                    t("bot.model.not_found", target=target)
                )
                return

            # Deactivate all, activate target
            await db.execute(
                update(LLMPreset).where(LLMPreset.is_active == True).values(is_active=False)
            )
            preset.is_active = True
            await db.commit()

            # Hot-swap LLM config
            config = LLMConfig(
                provider=preset.provider,
                api_key=preset.api_key,
                base_url=preset.base_url,
                model=preset.model,
                max_tokens=preset.max_tokens,
                temperature=preset.temperature,
            )
            self._llm.update_config(config)

            await self._bot.reply(
                msg,
                t("bot.model.switched") + f" {preset.name}\n"
                f"Model: {preset.model}\n"
                f"Provider: {preset.provider}"
            )

    async def _cmd_clear(self, msg: IncomingMessage, args: str) -> None:
        session_factory = get_session_factory()
        async with session_factory() as db:
            conv_service = ConversationService(db)
            cleared = await conv_service.clear_messages(msg.user_id)
            await db.commit()
            if cleared:
                await self._bot.reply(msg, t("bot.clear.done"))
            else:
                await self._bot.reply(msg, t("bot.clear.empty"))

    async def _cmd_prompt(self, msg: IncomingMessage, args: str) -> None:
        session_factory = get_session_factory()
        async with session_factory() as db:
            conv_service = ConversationService(db)
            user_config = await conv_service._get_user_config(msg.user_id)
            prompt_text = await conv_service._get_system_prompt(user_config)

            # Truncate if too long for WeChat
            if len(prompt_text) > 500:
                prompt_text = prompt_text[:500] + "..."

            source = "custom" if (user_config and user_config.custom_prompt_id) else "default"
            await self._bot.reply(msg, t("bot.prompt.header", source=source) + f"\n\n{prompt_text}")

    async def _cmd_reset(self, msg: IncomingMessage, args: str) -> None:
        session_factory = get_session_factory()
        async with session_factory() as db:
            conv_service = ConversationService(db)
            config = await conv_service.get_or_create_user_config(msg.user_id)
            config.custom_prompt_id = None
            await db.commit()
            await self._bot.reply(msg, t("bot.reset.done"))

    async def _cmd_char(self, msg: IncomingMessage, args: str) -> None:
        """Handle /char commands for character card management."""
        from .character_service import CharacterService

        session_factory = get_session_factory()
        async with session_factory() as db:
            service = CharacterService(db)

            if not args or args.strip() == "list":
                chars = await service.list_characters()
                if not chars:
                    await self._bot.reply(msg, t("bot.char.no_chars"))
                    return

                lines = [t("bot.char.title")]
                for c in chars:
                    marker = t("bot.model.active_marker") if c.is_active else ""
                    desc_preview = c.description[:30] + "..." if len(c.description) > 30 else c.description
                    lines.append(f"  {'*' if c.is_active else 'o'} {c.name} - {desc_preview}{marker}")
                lines.append("")
                lines.append(t("bot.char.switch_hint"))
                lines.append(t("bot.char.info_hint"))
                lines.append(t("bot.char.off_hint"))
                await self._bot.reply(msg, "\n".join(lines))

            elif args.strip() == "info":
                card = await service.get_active_character()
                if not card:
                    await self._bot.reply(msg, t("bot.char.no_active"))
                    return

                lines = [
                    f"{t('bot.char.current')} {card.name}",
                    "-" * 30,
                ]
                if card.description:
                    lines.append(f"{t('bot.char.description')} {card.description[:200]}")
                if card.personality:
                    lines.append(f"{t('bot.char.personality')} {card.personality[:200]}")
                if card.scenario:
                    lines.append(f"{t('bot.char.scenario')} {card.scenario[:200]}")
                if card.first_mes:
                    lines.append(f"{t('bot.char.first_mes')} {card.first_mes[:200]}")
                await self._bot.reply(msg, "\n".join(lines))

            elif args.strip() == "off":
                await service.deactivate_character()
                await db.commit()
                await self._bot.reply(msg, t("bot.char.deactivated"))

            elif args.strip() == "help":
                help_text = (
                    t("bot.char.help_title") + "\n"
                    "  /char - List all characters\n"
                    "  /char <name> - Switch to character\n"
                    "  /char info - Show current character\n"
                    "  /char off - Deactivate character\n"
                    "  /char help - This help"
                )
                await self._bot.reply(msg, help_text)

            else:
                name = args.strip()
                card = await service.get_character_by_name(name)
                if not card:
                    await self._bot.reply(msg, t("bot.char.not_found", name=name))
                    return

                card = await service.activate_character(card.id)
                await db.commit()

                reply = t("bot.char.switched") + f" {card.name}"
                if card.first_mes:
                    reply += f"\n\n{card.first_mes}"
                await self._bot.reply(msg, reply)

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h {m}m"
