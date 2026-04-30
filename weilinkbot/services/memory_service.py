"""Memory service — wraps mem0 for long-term user memory."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[misc]

from ..config import AppConfig

logger = logging.getLogger(__name__)


class MemoryService:
    """Async wrapper around mem0 for user memory management.

    Degrades to no-op when memory is not configured.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._mem0 = None
        self._available = False
        self._init_error: Optional[str] = None
        self._init()

    def _init(self) -> None:
        """Initialize mem0 client if configuration is valid."""
        mem_cfg = self._config.memory
        if not mem_cfg.enabled:
            logger.info("Memory module disabled (memory.enabled=false)")
            self._init_error = "Memory module disabled (memory.enabled=false)"
            return

        # Resolve embedding credentials (fall back to main LLM config)
        emb_key = mem_cfg.embedding.api_key or self._config.llm.api_key
        emb_url = mem_cfg.embedding.base_url or self._config.llm.base_url
        emb_model = mem_cfg.embedding.model

        if not emb_key or not emb_model:
            logger.warning(
                "Memory module disabled: embedding model not configured. "
                "Set memory.embedding.model and ensure an API key is available."
            )
            self._init_error = (
                "Memory module disabled: embedding model not configured. "
                "Set memory.embedding.model and ensure an API key is available."
            )
            return

        # Resolve LLM credentials for memory extraction (fall back to main LLM config)
        llm_key = mem_cfg.llm.api_key or self._config.llm.api_key
        llm_model = mem_cfg.llm.model or self._config.llm.model
        if not llm_key or not llm_model:
            logger.warning(
                "Memory module disabled: LLM for memory extraction not configured. "
                "Set memory.llm.api_key (or config.llm.api_key) and memory.llm.model."
            )
            self._init_error = (
                "Memory module disabled: LLM for memory extraction not configured. "
                "Set memory.llm.api_key (or config.llm.api_key) and memory.llm.model."
            )
            return

        try:
            from mem0 import Memory

            # Build mem0 config
            mem0_config: dict = {
                "version": "v1.1",
                "embedder": {
                    "provider": mem_cfg.embedding.provider,
                    "config": {
                        "model": emb_model,
                        "api_key": emb_key,
                    },
                },
                "vector_store": {
                    "provider": "chroma",
                    "config": {
                        "collection_name": "weilinkbot_memory",
                        "path": mem_cfg.db_path,
                    },
                },
            }

            # Add embedding base_url if provided (for custom endpoints)
            if emb_url:
                mem0_config["embedder"]["config"]["openai_base_url"] = emb_url

            # Configure LLM for memory extraction (fall back to main LLM)
            llm_url = mem_cfg.llm.base_url or self._config.llm.base_url

            if llm_key and llm_model:
                llm_config: dict = {
                    "provider": mem_cfg.llm.provider or "openai",
                    "config": {
                        "model": llm_model,
                        "api_key": llm_key,
                    },
                }
                if llm_url:
                    llm_config["config"]["openai_base_url"] = llm_url
                mem0_config["llm"] = llm_config

            self._mem0 = Memory.from_config(mem0_config)
            self._available = True
            self._init_error = None
            logger.info(
                "Memory module initialized (embedding=%s, db=%s)",
                emb_model, mem_cfg.db_path,
            )
        except Exception as exc:
            logger.exception("Failed to initialize mem0 — memory module disabled")
            self._mem0 = None
            self._available = False
            self._init_error = str(exc)

    def update_config(self, **kwargs) -> dict:
        """Update memory/embedding config and reinitialize mem0.

        Supported kwargs: memory_enabled, embedding_provider, embedding_api_key,
        embedding_base_url, embedding_model, llm_provider, llm_api_key,
        llm_base_url, llm_model, top_k, db_path.
        """
        mem_cfg = self._config.memory

        def _set_if_provided(field: str, target: object, attr: str) -> None:
            """Set a config field when the caller provides any value (including empty string)."""
            val = kwargs.get(field)
            if val is not None:
                setattr(target, attr, val)

        def _set_if_nonempty(field: str, target: object, attr: str) -> None:
            """Only overwrite a config field when the caller provides a non-empty value."""
            val = kwargs.get(field)
            if val is not None and str(val).strip():
                setattr(target, attr, val)

        if "memory_enabled" in kwargs:
            mem_cfg.enabled = kwargs["memory_enabled"]
        _set_if_nonempty("embedding_provider", mem_cfg.embedding, "provider")
        _set_if_nonempty("embedding_api_key", mem_cfg.embedding, "api_key")
        _set_if_provided("embedding_base_url", mem_cfg.embedding, "base_url")
        _set_if_nonempty("embedding_model", mem_cfg.embedding, "model")
        _set_if_nonempty("llm_provider", mem_cfg.llm, "provider")
        _set_if_nonempty("llm_api_key", mem_cfg.llm, "api_key")
        _set_if_provided("llm_base_url", mem_cfg.llm, "base_url")
        _set_if_nonempty("llm_model", mem_cfg.llm, "model")
        if "top_k" in kwargs:
            mem_cfg.top_k = kwargs["top_k"]
        if "db_path" in kwargs:
            mem_cfg.db_path = kwargs["db_path"]

        # Auto-enable if embedding AND LLM are both fully configured
        emb_ready = mem_cfg.embedding.model and (
            mem_cfg.embedding.api_key or self._config.llm.api_key
        )
        llm_ready = (mem_cfg.llm.model or self._config.llm.model) and (
            mem_cfg.llm.api_key or self._config.llm.api_key
        )
        if emb_ready and llm_ready:
            mem_cfg.enabled = True

        # Tear down and reinitialize
        self._mem0 = None
        self._available = False
        self._init_error = None
        self._init()
        logger.info("Memory service reconfigured (available=%s)", self._available)
        return {"available": self._available, "init_error": self._init_error}

    @property
    def available(self) -> bool:
        return self._available

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error

    def test_connection(
        self,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Test embedding API connectivity. Returns {success, message, latency_ms}."""
        import time

        if httpx is None:
            return {
                "success": False,
                "message": "httpx is not installed (required for connection test)",
                "latency_ms": None,
            }

        mem_cfg = self._config.memory
        emb_provider = provider or mem_cfg.embedding.provider
        emb_model = model or mem_cfg.embedding.model
        emb_url = base_url or mem_cfg.embedding.base_url
        emb_key = api_key or mem_cfg.embedding.api_key or self._config.llm.api_key

        if not emb_model:
            return {"success": False, "message": "No embedding model configured", "latency_ms": None}
        if not emb_key:
            return {"success": False, "message": "No API key configured", "latency_ms": None}

        if emb_provider == "openai" or not emb_provider:
            api_url = (emb_url or "https://api.openai.com/v1").rstrip("/") + "/embeddings"
        else:
            if not emb_url:
                return {
                    "success": False,
                    "message": f"Base URL required for provider '{emb_provider}'",
                    "latency_ms": None,
                }
            api_url = emb_url.rstrip("/") + "/embeddings"

        try:
            start = time.monotonic()
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {emb_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": emb_model,
                        "input": "test",
                    },
                )
            latency_ms = round((time.monotonic() - start) * 1000, 1)

            if resp.status_code == 200:
                return {
                    "success": True,
                    "message": f"Connection successful (model: {emb_model}, latency: {latency_ms}ms)",
                    "latency_ms": latency_ms,
                }
            else:
                # Don't expose API key in error message
                try:
                    error_detail = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    error_detail = resp.text[:200]
                return {
                    "success": False,
                    "message": f"API returned {resp.status_code}: {error_detail}",
                    "latency_ms": latency_ms,
                }
        except httpx.ConnectError:
            return {"success": False, "message": f"Cannot connect to {api_url}", "latency_ms": None}
        except httpx.TimeoutException:
            return {"success": False, "message": f"Connection timed out ({api_url})", "latency_ms": None}
        except Exception as exc:
            return {
                "success": False,
                "message": f"Connection test failed: {type(exc).__name__}",
                "latency_ms": None,
            }

    async def search(self, user_id: str, query: str) -> list[str]:
        """Search memories for a user. Returns list of memory strings.

        Returns empty list on any error or when unavailable.
        """
        if not self._available:
            return []

        try:
            top_k = self._config.memory.top_k
            results = await asyncio.to_thread(
                self._mem0.search, query, filters={"user_id": user_id}, top_k=top_k
            )
            # mem0 returns {"results": [{"memory": "...", ...}, ...]} or similar
            memories = []
            if isinstance(results, dict):
                items = results.get("results", results.get("memories", []))
            elif isinstance(results, list):
                items = results
            else:
                items = []

            for item in items:
                if isinstance(item, dict):
                    text = item.get("memory", item.get("text", ""))
                else:
                    text = str(item)
                if text:
                    memories.append(text)

            logger.debug("Found %d memories for user %s", len(memories), user_id)
            return memories
        except Exception:
            logger.warning("Memory search failed for user %s", user_id, exc_info=True)
            return []

    async def add(self, user_id: str, user_msg: str, assistant_reply: str) -> None:
        """Extract and store memories from a conversation turn.

        Runs async (fire-and-forget from caller). Best-effort — never raises.
        """
        if not self._available:
            return

        try:
            messages = [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_reply},
            ]
            await asyncio.to_thread(
                self._mem0.add, messages, user_id=user_id
            )
            logger.debug("Stored memories for user %s", user_id)
        except Exception:
            logger.warning("Failed to store memory for user %s", user_id, exc_info=True)

    async def get_all(self, user_id: str) -> list[dict]:
        """Get all memories for a user. Returns list of {id, memory, ...}."""
        if not self._available:
            return []

        try:
            results = await asyncio.to_thread(
                self._mem0.get_all, filters={"user_id": user_id}
            )
            if isinstance(results, dict):
                return results.get("results", results.get("memories", []))
            elif isinstance(results, list):
                return results
            return []
        except Exception:
            logger.warning("Failed to get memories for user %s", user_id, exc_info=True)
            return []

    async def update(self, memory_id: str, new_text: str) -> bool:
        """Update a memory by ID. Returns True on success."""
        if not self._available:
            return False

        try:
            await asyncio.to_thread(
                self._mem0.update, memory_id, new_text
            )
            return True
        except Exception:
            logger.warning("Failed to update memory %s", memory_id, exc_info=True)
            return False

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID. Returns True on success."""
        if not self._available:
            return False

        try:
            await asyncio.to_thread(self._mem0.delete, memory_id)
            return True
        except Exception:
            logger.warning("Failed to delete memory %s", memory_id, exc_info=True)
            return False

    async def delete_all(self, user_id: str) -> bool:
        """Delete all memories for a user. Returns True on success."""
        if not self._available:
            return False

        try:
            await asyncio.to_thread(self._mem0.delete_all, user_id=user_id)
            return True
        except Exception:
            logger.warning("Failed to delete all memories for user %s", user_id, exc_info=True)
            return False
