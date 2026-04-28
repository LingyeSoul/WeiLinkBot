"""WeiLinkBot CLI — command-line interface for bot management."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

app = typer.Typer(
    name="weilinkbot",
    help="WeiLinkBot — AI Chatbot Platform powered by WeChat iLink Bot SDK",
    no_args_is_help=True,
)
console = Console()


def _run_async(coro):
    """Run an async function from sync CLI context."""
    return asyncio.run(coro)


# ── Bot Commands ──────────────────────────────────────────────────

@app.command()
def start():
    """Start the bot — login via QR and begin message polling."""
    async def _start():
        from ..config import get_config
        from ..database import init_db, get_session_factory
        from ..services.llm_service import LLMService
        from ..services.bot_service import BotService

        config = get_config()
        await init_db()
        llm = LLMService(config.llm)
        bot = BotService(config, llm)

        console.print("[bold green]Starting bot...[/bold green]")
        await bot.start()

        # Keep running until interrupted
        try:
            while bot.state.value == "running" or bot.state.value == "starting":
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await bot.stop()
            console.print("[bold yellow]Bot stopped.[/bold yellow]")

    _run_async(_start())


@app.command()
def status():
    """Show bot and LLM configuration status."""
    from ..config import get_config
    config = get_config()

    table = Table(title="WeiLinkBot Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("LLM Provider", config.llm.provider)
    table.add_row("LLM Model", config.llm.model)
    table.add_row("LLM Base URL", config.llm.base_url)
    table.add_row("API Key Set", "Yes" if config.llm.api_key else "No")
    table.add_row("Max Tokens", str(config.llm.max_tokens))
    table.add_row("Temperature", str(config.llm.temperature))
    table.add_row("Bot Base URL", config.bot.base_url)
    table.add_row("Database", config.database.url)

    console.print(table)


# ── Serve Command ─────────────────────────────────────────────────

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Server host"),
    port: int = typer.Option(8000, help="Server port"),
    reload: bool = typer.Option(False, help="Enable auto-reload for development"),
):
    """Start the web dashboard and API server."""
    import uvicorn

    console.print(f"[bold blue]Starting WeiLinkBot dashboard on {host}:{port}...[/bold blue]")
    console.print(f"[dim]Open http://localhost:{port} in your browser[/dim]")

    uvicorn.run(
        "weilinkbot.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


# ── Config Commands ───────────────────────────────────────────────

config_app = typer.Typer(help="Manage configuration")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show():
    """Show current configuration."""
    status()


@config_app.command("set-llm")
def config_set_llm(
    provider: str = typer.Option("openai", help="Provider: openai | deepseek | custom"),
    api_key: str = typer.Option(..., prompt=True, hide_input=True, help="API key"),
    model: Optional[str] = typer.Option(None, help="Model name"),
    base_url: Optional[str] = typer.Option(None, help="Custom base URL"),
):
    """Configure LLM provider interactively."""
    from ..config import get_config, LLMService
    config = get_config()

    config.llm.provider = provider
    config.llm.api_key = api_key

    if provider == "deepseek":
        config.llm.base_url = "https://api.deepseek.com/v1"
        config.llm.model = model or "deepseek-chat"
    elif base_url:
        config.llm.base_url = base_url
        config.llm.model = model or config.llm.model
    elif model:
        config.llm.model = model

    console.print(f"[green]LLM configured:[/green]")
    console.print(f"  Provider: {config.llm.provider}")
    console.print(f"  Model:    {config.llm.model}")
    console.print(f"  Base URL: {config.llm.base_url}")


# ── History Commands ──────────────────────────────────────────────

history_app = typer.Typer(help="View conversation history")
app.add_typer(history_app, name="history")


@history_app.command("show")
def history_show(
    user_id: str = typer.Argument(..., help="User ID"),
    limit: int = typer.Option(20, help="Number of messages to show"),
):
    """Show conversation history for a user."""
    async def _show():
        from ..database import init_db, get_session_factory
        from ..services.conversation_service import ConversationService

        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as db:
            service = ConversationService(db)
            messages = await service.get_messages(user_id, limit=limit)

            if not messages:
                console.print(f"[yellow]No messages found for user {user_id}[/yellow]")
                return

            table = Table(title=f"Conversation: {user_id}")
            table.add_column("Role", style="cyan", width=10)
            table.add_column("Content", style="white")
            table.add_column("Tokens", style="dim", width=8)
            table.add_column("Time", style="dim", width=20)

            for msg in messages:
                content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                table.add_row(
                    msg.role,
                    content,
                    str(msg.tokens_used) if msg.tokens_used else "",
                    msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else "",
                )

            console.print(table)
            console.print(f"[dim]Showing {len(messages)} messages[/dim]")

    _run_async(_show())


@history_app.command("clear")
def history_clear(user_id: str = typer.Argument(..., help="User ID")):
    """Clear conversation history for a user."""
    async def _clear():
        from ..database import init_db, get_session_factory
        from ..services.conversation_service import ConversationService

        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as db:
            service = ConversationService(db)
            cleared = await service.clear_messages(user_id)
            if cleared:
                await db.commit()
                console.print(f"[green]Cleared conversation for {user_id}[/green]")
            else:
                console.print(f"[yellow]No conversation found for {user_id}[/yellow]")

    _run_async(_clear())


# ── Prompt Commands ───────────────────────────────────────────────

prompt_app = typer.Typer(help="Manage system prompts")
app.add_typer(prompt_app, name="prompts")


@prompt_app.command("list")
def prompt_list():
    """List all system prompts."""
    async def _list():
        from ..database import init_db, get_session_factory
        from ..models import SystemPrompt
        from sqlalchemy import select

        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(SystemPrompt).order_by(SystemPrompt.is_default.desc(), SystemPrompt.id)
            )
            prompts = result.scalars().all()

            if not prompts:
                console.print("[yellow]No prompts found[/yellow]")
                return

            table = Table(title="System Prompts")
            table.add_column("ID", style="cyan", width=4)
            table.add_column("Name", style="white")
            table.add_column("Default", style="green", width=8)
            table.add_column("Content Preview", style="dim")

            for p in prompts:
                preview = p.content[:80] + "..." if len(p.content) > 80 else p.content
                table.add_row(str(p.id), p.name, "Yes" if p.is_default else "", preview)

            console.print(table)

    _run_async(_list())


@prompt_app.command("create")
def prompt_create(
    name: str = typer.Option(..., prompt=True, help="Prompt name"),
    content: str = typer.Option(..., prompt=True, help="Prompt content"),
    default: bool = typer.Option(False, "--default", help="Set as default"),
):
    """Create a new system prompt."""
    async def _create():
        from ..database import init_db, get_session_factory
        from ..models import SystemPrompt
        from sqlalchemy import select, update

        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as db:
            if default:
                await db.execute(
                    update(SystemPrompt).where(SystemPrompt.is_default == True).values(is_default=False)
                )

            db.add(SystemPrompt(name=name, content=content, is_default=default))
            await db.commit()
            console.print(f"[green]Created prompt '{name}'[/green]")

    _run_async(_create())


@prompt_app.command("set-default")
def prompt_set_default(prompt_id: int = typer.Argument(..., help="Prompt ID")):
    """Set a prompt as the default."""
    async def _set():
        from ..database import init_db, get_session_factory
        from ..models import SystemPrompt
        from sqlalchemy import update

        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as db:
            await db.execute(
                update(SystemPrompt).where(SystemPrompt.is_default == True).values(is_default=False)
            )
            prompt = await db.get(SystemPrompt, prompt_id)
            if not prompt:
                console.print(f"[red]Prompt {prompt_id} not found[/red]")
                return
            prompt.is_default = True
            await db.commit()
            console.print(f"[green]Set '{prompt.name}' as default[/green]")

    _run_async(_set())


# ── Entry point ──────────────────────────────────────────────────

def main():
    app()


if __name__ == "__main__":
    main()
