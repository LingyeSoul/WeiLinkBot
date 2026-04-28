"""FastAPI application factory with lifespan management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from ..config import get_config, AppConfig
from ..database import init_db, get_session_factory
from ..models import SystemPrompt
from ..services.llm_service import LLMService
from ..services.bot_service import BotService
from .deps import set_llm_service, set_bot_service

from . import bot as bot_routes
from . import conversations as conv_routes
from . import prompts as prompt_routes
from . import config as config_routes
from . import users as user_routes

logger = logging.getLogger(__name__)

# Paths to frontend files
_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
_TEMPLATES_DIR = _FRONTEND_DIR / "templates"
_STATIC_DIR = _FRONTEND_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    config = get_config()

    # Init database
    await init_db()
    logger.info("Database initialized")

    # Create default system prompt if none exists
    session_factory = get_session_factory()
    async with session_factory() as db:
        from sqlalchemy import select, func
        count_stmt = select(func.count()).select_from(SystemPrompt)
        result = await db.execute(count_stmt)
        count = result.scalar()
        if count == 0:
            db.add(SystemPrompt(
                name="Default",
                content="You are a helpful AI assistant. Reply concisely and helpfully.",
                is_default=True,
            ))
            await db.commit()
            logger.info("Created default system prompt")

    # Init LLM service
    llm_service = LLMService(config.llm)
    set_llm_service(llm_service)
    logger.info("LLM service initialized (model=%s)", config.llm.model)

    # Init Bot service
    bot_service = BotService(config, llm_service)
    set_bot_service(bot_service)
    logger.info("Bot service initialized")

    yield

    # Shutdown: stop bot if running
    if bot_service.state.value == "running":
        await bot_service.stop()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="WeiLinkBot",
        description="AI Chatbot Platform powered by WeChat iLink Bot SDK",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Mount static files
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Register API routes
    app.include_router(bot_routes.router, prefix="/api/bot", tags=["Bot"])
    app.include_router(conv_routes.router, prefix="/api/conversations", tags=["Conversations"])
    app.include_router(prompt_routes.router, prefix="/api/prompts", tags=["Prompts"])
    app.include_router(config_routes.router, prefix="/api/config", tags=["Config"])
    app.include_router(user_routes.router, prefix="/api/users", tags=["Users"])

    # Serve dashboard
    @app.get("/", include_in_schema=False)
    async def dashboard():
        index_path = _TEMPLATES_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"message": "WeiLinkBot API is running. Frontend not found."}

    return app
