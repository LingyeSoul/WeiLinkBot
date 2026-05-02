"""Server settings API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as _Session

from ..database import get_db
from ..config import _get_sync_engine, get_config, save_config
from ..models import SystemSetting
from ..schemas import SettingsResponse, SettingsUpdate, MessageAction
from ..services.ws_service import get_ws_service


router = APIRouter()

PROMPT_SETTINGS_KEYS = [
    "disable_base_prompt_on_char",
    "disable_base_prompt_on_preset",
    "disable_base_prompt_on_worldbook",
]


async def _get_prompt_settings(db: AsyncSession) -> dict[str, bool]:
    """Get prompt-related settings from database."""
    result = {}
    for key in PROMPT_SETTINGS_KEYS:
        stmt = select(SystemSetting).where(SystemSetting.key == key)
        row = await db.scalar(stmt)
        result[key] = row.value.lower() == "true" if row else False
    return result


async def _get_max_history(db: AsyncSession) -> int:
    """Get global max_history setting from database."""
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == "max_history"))
    return int(row.value) if row else 20


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Get current server settings."""
    config = get_config()
    from .. import i18n
    prompt_settings = await _get_prompt_settings(db)
    max_history = await _get_max_history(db)
    return SettingsResponse(
        server_host=config.server.host,
        server_port=config.server.port,
        listen_lan=config.server.host == "0.0.0.0",
        language=i18n.get_lang(),
        max_history=max_history,
        disable_base_prompt_on_char=prompt_settings.get("disable_base_prompt_on_char", False),
        disable_base_prompt_on_preset=prompt_settings.get("disable_base_prompt_on_preset", False),
        disable_base_prompt_on_worldbook=prompt_settings.get("disable_base_prompt_on_worldbook", False),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    """Update server settings."""
    config = get_config()

    if data.server_port is not None:
        config.server.port = data.server_port
    if data.listen_lan is not None:
        config.server.host = "0.0.0.0" if data.listen_lan else "127.0.0.1"
    elif data.server_host is not None:
        config.server.host = data.server_host

    save_config()

    if data.language is not None:
        from .. import i18n
        with _Session(_get_sync_engine()) as _s:
            existing = _s.get(SystemSetting, "language")
            if existing:
                existing.value = data.language
            else:
                _s.add(SystemSetting(key="language", value=data.language, is_encrypted=False))
            _s.commit()
        i18n.set_lang(data.language)

    # Save max_history setting
    if data.max_history is not None:
        existing = await db.get(SystemSetting, "max_history")
        if existing:
            existing.value = str(data.max_history)
        else:
            db.add(SystemSetting(key="max_history", value=str(data.max_history), is_encrypted=False))

    # Save prompt settings
    for key in PROMPT_SETTINGS_KEYS:
        value = getattr(data, key, None)
        if value is not None:
            existing = await db.get(SystemSetting, key)
            if existing:
                existing.value = "true" if value else "false"
            else:
                db.add(SystemSetting(key=key, value="true" if value else "false", is_encrypted=False))
    await db.commit()

    from .. import i18n
    prompt_settings = await _get_prompt_settings(db)
    max_history = await _get_max_history(db)
    response = SettingsResponse(
        server_host=config.server.host,
        server_port=config.server.port,
        listen_lan=config.server.host == "0.0.0.0",
        language=i18n.get_lang(),
        max_history=max_history,
        disable_base_prompt_on_char=prompt_settings.get("disable_base_prompt_on_char", False),
        disable_base_prompt_on_preset=prompt_settings.get("disable_base_prompt_on_preset", False),
        disable_base_prompt_on_worldbook=prompt_settings.get("disable_base_prompt_on_worldbook", False),
    )
    await get_ws_service().broadcast("settings", response.model_dump(mode="json"))
    return response


@router.post("/restart-server", response_model=MessageAction)
async def restart_server():
    """Restart the server."""
    import os
    import sys
    import subprocess
    import threading
    import time

    if sys.platform == "win32":
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        try:
            subprocess.Popen(sys.argv, **kwargs)
        except FileNotFoundError:
            subprocess.Popen([sys.executable] + sys.argv, **kwargs)

        def _delayed_exit():
            time.sleep(0.5)
            os._exit(0)

        threading.Thread(target=_delayed_exit, daemon=True).start()
    else:
        os.execv(sys.executable, [sys.executable] + sys.argv)

    return MessageAction(message="Server restart initiated")