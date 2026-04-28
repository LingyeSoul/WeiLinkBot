"""Bot service — orchestrates WeChatBot SDK, LLM, and conversation services."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from pathlib import Path
from typing import Optional

from wechatbot import WeChatBot, IncomingMessage, Credentials

from ..config import AppConfig
from ..database import get_session_factory
from .llm_service import LLMService
from .conversation_service import ConversationService

logger = logging.getLogger(__name__)


class BotState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


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
            # Expand ~ to actual home directory (avoids literal ~ folder on Windows)
            cred_path = str(Path(self._config.bot.cred_path).expanduser())

            self._bot = WeChatBot(
                base_url=self._config.bot.base_url,
                cred_path=cred_path,
                on_qr_url=self._on_qr_url,
                on_scanned=lambda: logger.info("QR scanned — confirm in WeChat"),
                on_expired=lambda: logger.warning("QR expired"),
                on_error=lambda err: logger.error("Bot error: %s", err),
            )

            # Register message handler
            self._bot.on_message(self._handle_message)

            # Login
            logger.info("Logging in...")
            self._credentials = await self._bot.login()
            self._login_url = None
            self._state = BotState.RUNNING
            logger.info(
                "Bot running — user_id=%s account_id=%s",
                self._credentials.user_id,
                self._credentials.account_id,
            )

            # Start long-poll (blocks until stop() is called)
            await self._bot.start()

        except Exception as e:
            self._state = BotState.ERROR
            self._error = str(e)
            logger.exception("Bot crashed: %s", e)

        finally:
            if self._state != BotState.ERROR:
                self._state = BotState.STOPPED
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
        """Callback when QR code URL is available."""
        self._login_url = url
        logger.info("Scan this QR URL in WeChat: %s", url)

    async def _handle_message(self, msg: IncomingMessage) -> None:
        """Core message pipeline: user check → context → LLM → save → reply."""
        user_id = msg.user_id

        # Create a new DB session for this message (we're in an async task, not a request)
        session_factory = get_session_factory()
        async with session_factory() as db:
            conv_service = ConversationService(db)

            try:
                # 1. Check blocklist
                if await conv_service.is_blocked(user_id):
                    logger.info("Blocked user %s — ignoring", user_id)
                    return

                # 2. Show typing
                try:
                    await self._bot.send_typing(user_id)
                except Exception:
                    pass  # Non-critical

                # 3. Save user message
                await conv_service.add_message(user_id, "user", msg.text)
                await db.commit()

                # 4. Build LLM context
                context = await conv_service.build_context(user_id)
                context.append({"role": "user", "content": msg.text})

                # 5. Call LLM
                logger.info("LLM request for user %s: %s...", user_id, msg.text[:50])
                response_text, tokens = await self._llm.chat(context)

                # 6. Save assistant message
                await conv_service.add_message(
                    user_id, "assistant", response_text, tokens, self._llm.config.model
                )
                await db.commit()

                # 7. Reply via WeChat
                await self._bot.reply(msg, response_text)
                logger.info("Replied to user %s (%d tokens)", user_id, tokens)

            except Exception as e:
                logger.exception("Error handling message from %s: %s", user_id, e)
                try:
                    await db.rollback()
                    # Try to send error message to user
                    await self._bot.reply(msg, "[Error] Failed to process your message. Please try again.")
                except Exception:
                    pass
