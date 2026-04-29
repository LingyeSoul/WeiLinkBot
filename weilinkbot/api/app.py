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
from ..models import SystemPrompt, LLMPreset
from ..services.llm_service import LLMService
from ..services.bot_service import BotService
from .deps import set_llm_service, set_bot_service

from . import bot as bot_routes
from . import conversations as conv_routes
from . import prompts as prompt_routes
from . import config as config_routes
from . import users as user_routes
from . import models as model_routes
from . import stats as stats_routes
from . import characters as char_routes

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

    # Create default system prompt if none exists, and default LLM preset
    session_factory = get_session_factory()
    async with session_factory() as db:
        from sqlalchemy import select, func

        # System prompt
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

        # LLM preset — create from config if none exist
        preset_count_stmt = select(func.count()).select_from(LLMPreset)
        result = await db.execute(preset_count_stmt)
        preset_count = result.scalar()
        if preset_count == 0 and config.llm.api_key:
            db.add(LLMPreset(
                name=f"{config.llm.provider}/{config.llm.model}",
                provider=config.llm.provider,
                api_key=config.llm.api_key,
                base_url=config.llm.base_url,
                model=config.llm.model,
                max_tokens=config.llm.max_tokens,
                temperature=config.llm.temperature,
                is_active=True,
            ))
            await db.commit()
            logger.info("Created default LLM preset from config")

    # Load active preset from DB (if any), otherwise use config
    active_config = config.llm
    async with session_factory() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(LLMPreset).where(LLMPreset.is_active == True)
        )
        active_preset = result.scalar_one_or_none()
        if active_preset:
            from ..config import LLMConfig
            active_config = LLMConfig(
                provider=active_preset.provider,
                api_key=active_preset.api_key,
                base_url=active_preset.base_url,
                model=active_preset.model,
                max_tokens=active_preset.max_tokens,
                temperature=active_preset.temperature,
            )
            logger.info("Loaded active preset: %s (%s)", active_preset.name, active_preset.model)

    # Init LLM service (from active preset or config)
    llm_service = LLMService(active_config)
    set_llm_service(llm_service)
    logger.info("LLM service initialized (model=%s)", active_config.model)

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

    # Serve character avatars
    characters_dir = Path("data/characters")
    characters_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/characters", StaticFiles(directory=str(characters_dir)), name="characters")

    # Register API routes
    app.include_router(bot_routes.router, prefix="/api/bot", tags=["Bot"])
    app.include_router(conv_routes.router, prefix="/api/conversations", tags=["Conversations"])
    app.include_router(prompt_routes.router, prefix="/api/prompts", tags=["Prompts"])
    app.include_router(config_routes.router, prefix="/api/config", tags=["Config"])
    app.include_router(user_routes.router, prefix="/api/users", tags=["Users"])
    app.include_router(model_routes.router, prefix="/api/models", tags=["Models"])
    app.include_router(stats_routes.router, prefix="/api/stats", tags=["Stats"])
    app.include_router(char_routes.router, prefix="/api/characters", tags=["Characters"])

    # Version endpoint
    @app.get("/api/version", include_in_schema=False)
    async def get_version():
        from .. import __version__
        return {"version": __version__}

    # Serve dashboard
    @app.get("/", include_in_schema=False)
    async def dashboard():
        index_path = _TEMPLATES_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"message": "WeiLinkBot API is running. Frontend not found."}

    return app
