"""Memory service — wraps mem0 for long-term user memory."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

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
        self._init()

    def _init(self) -> None:
        """Initialize mem0 client if configuration is valid."""
        mem_cfg = self._config.memory
        if not mem_cfg.enabled:
            logger.info("Memory module disabled (memory.enabled=false)")
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
            llm_key = mem_cfg.llm.api_key or self._config.llm.api_key
            llm_url = mem_cfg.llm.base_url or self._config.llm.base_url
            llm_model = mem_cfg.llm.model or self._config.llm.model

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
            logger.info(
                "Memory module initialized (embedding=%s, db=%s)",
                emb_model, mem_cfg.db_path,
            )
        except Exception:
            logger.exception("Failed to initialize mem0 — memory module disabled")
            self._mem0 = None
            self._available = False

    def update_config(self, **kwargs) -> None:
        """Update memory/embedding config and reinitialize mem0.

        Supported kwargs: memory_enabled, embedding_provider, embedding_api_key,
        embedding_base_url, embedding_model, llm_provider, llm_api_key,
        llm_base_url, llm_model, top_k, db_path.
        """
        mem_cfg = self._config.memory

        if "memory_enabled" in kwargs:
            mem_cfg.enabled = kwargs["memory_enabled"]
        if "embedding_provider" in kwargs:
            mem_cfg.embedding.provider = kwargs["embedding_provider"]
        if "embedding_api_key" in kwargs:
            mem_cfg.embedding.api_key = kwargs["embedding_api_key"]
        if "embedding_base_url" in kwargs:
            mem_cfg.embedding.base_url = kwargs["embedding_base_url"]
        if "embedding_model" in kwargs:
            mem_cfg.embedding.model = kwargs["embedding_model"]
        if "llm_provider" in kwargs:
            mem_cfg.llm.provider = kwargs["llm_provider"]
        if "llm_api_key" in kwargs:
            mem_cfg.llm.api_key = kwargs["llm_api_key"]
        if "llm_base_url" in kwargs:
            mem_cfg.llm.base_url = kwargs["llm_base_url"]
        if "llm_model" in kwargs:
            mem_cfg.llm.model = kwargs["llm_model"]
        if "top_k" in kwargs:
            mem_cfg.top_k = kwargs["top_k"]
        if "db_path" in kwargs:
            mem_cfg.db_path = kwargs["db_path"]

        # Auto-enable if embedding is now fully configured
        if mem_cfg.embedding.model and (
            mem_cfg.embedding.api_key or self._config.llm.api_key
        ):
            mem_cfg.enabled = True

        # Tear down and reinitialize
        self._mem0 = None
        self._available = False
        self._init()
        logger.info("Memory service reconfigured (available=%s)", self._available)

    @property
    def available(self) -> bool:
        return self._available

    async def search(self, user_id: str, query: str) -> list[str]:
        """Search memories for a user. Returns list of memory strings.

        Returns empty list on any error or when unavailable.
        """
        if not self._available:
            return []

        try:
            top_k = self._config.memory.top_k
            results = await asyncio.to_thread(
                self._mem0.search, query, user_id=user_id, limit=top_k
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
                self._mem0.get_all, user_id=user_id
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
