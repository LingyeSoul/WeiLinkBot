"""FastAPI application factory with lifespan management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from ..config import get_config, AppConfig
from ..database import init_db, get_session_factory
from ..models import SystemPrompt, LLMPreset, get_preset_api_key, encrypt_preset_api_key
from ..services.llm_service import LLMService
from ..services.bot_service import BotService
from .deps import set_llm_service, set_bot_service, set_memory_service

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

    # Init i18n — read saved language from DB if available
    from .. import i18n
    saved_lang = None
    try:
        from ..config import _get_sync_engine
        from ..models import SystemSetting
        from sqlalchemy import select as _select
        from sqlalchemy.orm import Session as _Session
        with _Session(_get_sync_engine()) as _s:
            row = _s.execute(
                _select(SystemSetting.value).where(SystemSetting.key == "language")
            ).scalar_one_or_none()
            if row:
                saved_lang = row
    except Exception:
        pass
    i18n.init(lang=saved_lang)
    logger.info("i18n initialized (lang=%s)", i18n.get_lang())

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
            enc_key, enc_flag = encrypt_preset_api_key(config.llm.api_key)
            db.add(LLMPreset(
                name=f"{config.llm.provider}/{config.llm.model}",
                provider=config.llm.provider,
                api_key=enc_key,
                api_key_encrypted=enc_flag,
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
                api_key=get_preset_api_key(active_preset),
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

    # Init Memory service
    from ..services.memory_service import MemoryService
    memory_service = MemoryService(config)
    set_memory_service(memory_service)
    logger.info("Memory service initialized (available=%s)", memory_service.available)

    # Init Bot service
    bot_service = BotService(config, llm_service, memory_service=memory_service)
    set_bot_service(bot_service)
    logger.info("Bot service initialized")

    yield

    # Shutdown: stop bot if running
    if bot_service.state.value == "running":
        await bot_service.stop()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from .. import __version__

    app = FastAPI(
        title="WeiLinkBot",
        description="AI Chatbot Platform powered by WeChat iLink Bot SDK",
        version=__version__,
        lifespan=lifespan,
    )

    # Mount static files
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Serve locale translation files
    from ..i18n import LOCALES_DIR
    import json as _json

    @app.get("/locales/{lang}.json", include_in_schema=False)
    async def serve_locale(lang: str):
        locale_file = LOCALES_DIR / f"{lang}.json"
        if not locale_file.exists():
            raise HTTPException(status_code=404, detail="Locale not found")
        from fastapi.responses import JSONResponse
        data = _json.loads(locale_file.read_text("utf-8"))
        return JSONResponse(content=data)

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

    from . import memories as memory_routes
    app.include_router(memory_routes.router, prefix="/api/memories", tags=["Memories"])

    # Version endpoint
    @app.get("/api/version", include_in_schema=False)
    async def get_version():
        from .. import __version__
        return {"version": __version__}

    # Language API — allow frontend to control global language
    @app.get("/api/lang", include_in_schema=False)
    async def get_language():
        from .. import i18n
        return {"lang": i18n.get_lang(), "available": i18n.get_available_langs()}

    @app.put("/api/lang", include_in_schema=False)
    async def set_language(body: dict):
        from .. import i18n
        from ..config import _get_sync_engine
        from ..models import SystemSetting
        from sqlalchemy.orm import Session as _Session
        lang = body.get("lang")
        if not lang:
            raise HTTPException(status_code=400, detail="'lang' is required")
        if not i18n.set_lang(lang):
            raise HTTPException(status_code=400, detail=f"Unsupported language: {lang}")
        # Persist to DB
        with _Session(_get_sync_engine()) as _s:
            existing = _s.get(SystemSetting, "language")
            if existing:
                existing.value = lang
            else:
                _s.add(SystemSetting(key="language", value=lang, is_encrypted=False))
            _s.commit()
        return {"lang": i18n.get_lang()}

    # GitHub avatar proxy (cached locally)
    _avatar_cache: dict[str, tuple[float, bytes]] = {}

    @app.get("/api/avatar/github/{username}", include_in_schema=False)
    async def github_avatar(username: str):
        import time
        import asyncio
        import urllib.request

        cache_ttl = 3600  # 1 hour
        now = time.time()

        if username in _avatar_cache:
            ts, data = _avatar_cache[username]
            if now - ts < cache_ttl:
                return Response(content=data, media_type="image/png")

        def _fetch():
            req = urllib.request.Request(
                f"https://github.com/{username}.png?size=80",
                headers={"User-Agent": "WeiLinkBot"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()

        try:
            data = await asyncio.to_thread(_fetch)
            _avatar_cache[username] = (now, data)
            return Response(content=data, media_type="image/png")
        except Exception:
            pass

        # Fallback: 1x1 transparent PNG
        fallback = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return Response(content=fallback, media_type="image/png")

    # Serve dashboard
    @app.get("/", include_in_schema=False)
    async def dashboard():
        index_path = _TEMPLATES_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"message": "WeiLinkBot API is running. Frontend not found."}

    return app
