"""Memory service — wraps mem0 for long-term user memory."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[misc]

from ..config import AppConfig
from .local_embedding_service import LOCAL_EMBEDDING_PROVIDER, LocalOnnxEmbeddingService

logger = logging.getLogger(__name__)


class MemoryService:
    """Async wrapper around mem0 for user memory management.

    Degrades to no-op when memory is not configured.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._mem0 = None
        self._local_embedder: LocalOnnxEmbeddingService | None = None
        self._local_collection = None
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

        if mem_cfg.embedding.provider == LOCAL_EMBEDDING_PROVIDER:
            self._init_local_modelscope()
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

            embedder_config: dict[str, str] = {
                "model": emb_model,
                "api_key": emb_key,
            }

            # Build mem0 config
            mem0_config: dict[str, object] = {
                "version": "v1.1",
                "embedder": {
                    "provider": mem_cfg.embedding.provider,
                    "config": embedder_config,
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
                embedder_config["openai_base_url"] = emb_url

            # Configure LLM for memory extraction (fall back to main LLM)
            llm_url = mem_cfg.llm.base_url or self._config.llm.base_url

            if llm_key and llm_model:
                llm_provider_config: dict[str, str] = {
                    "model": llm_model,
                    "api_key": llm_key,
                }
                llm_config: dict[str, object] = {
                    "provider": mem_cfg.llm.provider or "openai",
                    "config": llm_provider_config,
                }
                if llm_url:
                    llm_provider_config["openai_base_url"] = llm_url
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

    def update_config(self, **kwargs: object) -> dict[str, object]:
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
            mem_cfg.enabled = bool(kwargs["memory_enabled"])
        _set_if_nonempty("embedding_provider", mem_cfg.embedding, "provider")
        _set_if_nonempty("embedding_api_key", mem_cfg.embedding, "api_key")
        _set_if_provided("embedding_base_url", mem_cfg.embedding, "base_url")
        _set_if_nonempty("embedding_model", mem_cfg.embedding, "model")
        _set_if_provided("embedding_local_path", mem_cfg.embedding, "local_path")
        _set_if_nonempty("embedding_quantization", mem_cfg.embedding, "quantization")
        _set_if_nonempty("embedding_onnx_model_file", mem_cfg.embedding, "onnx_model_file")
        _set_if_nonempty("embedding_modelscope_model_id", mem_cfg.embedding, "modelscope_model_id")
        _set_if_nonempty("llm_provider", mem_cfg.llm, "provider")
        _set_if_nonempty("llm_api_key", mem_cfg.llm, "api_key")
        _set_if_provided("llm_base_url", mem_cfg.llm, "base_url")
        _set_if_nonempty("llm_model", mem_cfg.llm, "model")
        if "top_k" in kwargs:
            mem_cfg.top_k = int(str(kwargs["top_k"]))
        if "db_path" in kwargs:
            mem_cfg.db_path = str(kwargs["db_path"])

        # Auto-enable when the configured memory backend has the required inputs.
        if mem_cfg.embedding.provider == LOCAL_EMBEDDING_PROVIDER:
            emb_ready = bool(mem_cfg.embedding.model and mem_cfg.embedding.onnx_model_file)
            llm_ready = True
        else:
            emb_ready = bool(mem_cfg.embedding.model and (
                mem_cfg.embedding.api_key or self._config.llm.api_key
            ))
            llm_ready = bool((mem_cfg.llm.model or self._config.llm.model) and (
                mem_cfg.llm.api_key or self._config.llm.api_key
            ))
        if emb_ready and llm_ready:
            mem_cfg.enabled = True

        # Tear down and reinitialize
        self._mem0 = None
        self._local_embedder = None
        self._local_collection = None
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
        local_path: str | None = None,
        quantization: str | None = None,
        onnx_model_file: str | None = None,
        modelscope_model_id: str | None = None,
    ) -> dict[str, object]:
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

        if emb_provider == LOCAL_EMBEDDING_PROVIDER:
            try:
                start = time.monotonic()
                embedder = LocalOnnxEmbeddingService(
                    model_dir=local_path or mem_cfg.embedding.local_path,
                    onnx_model_file=onnx_model_file or mem_cfg.embedding.onnx_model_file,
                    modelscope_model_id=modelscope_model_id or mem_cfg.embedding.modelscope_model_id,
                )
                _, dimension = embedder.test()
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                selected_quantization = quantization or mem_cfg.embedding.quantization
                return {
                    "success": True,
                    "message": (
                        f"Local ONNX embedding successful "
                        f"(quantization: {selected_quantization}, dim: {dimension}, latency: {latency_ms}ms)"
                    ),
                    "latency_ms": latency_ms,
                }
            except Exception as exc:
                return {
                    "success": False,
                    "message": f"Local ONNX embedding test failed: {exc}",
                    "latency_ms": None,
                }

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

        if self._local_collection is not None and self._local_embedder is not None:
            return await self._local_search(user_id, query)

        if self._mem0 is None:
            return []
        mem0 = self._mem0

        try:
            top_k = self._config.memory.top_k
            results = await asyncio.to_thread(
                mem0.search, query, filters={"user_id": user_id}, top_k=top_k
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

        if self._local_collection is not None and self._local_embedder is not None:
            await self._local_add(user_id, user_msg, assistant_reply)
            return

        if self._mem0 is None:
            return
        mem0 = self._mem0

        try:
            messages = [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_reply},
            ]
            await asyncio.to_thread(
                mem0.add, messages, user_id=user_id
            )
            logger.debug("Stored memories for user %s", user_id)
        except Exception:
            logger.warning("Failed to store memory for user %s", user_id, exc_info=True)

    async def get_all(self, user_id: str) -> list[dict[str, object]]:
        """Get all memories for a user. Returns list of {id, memory, ...}."""
        if not self._available:
            return []

        if self._local_collection is not None:
            return await self._local_get_all(user_id)

        if self._mem0 is None:
            return []
        mem0 = self._mem0

        try:
            results = await asyncio.to_thread(
                mem0.get_all, filters={"user_id": user_id}
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

        if self._local_collection is not None:
            return await self._local_update(memory_id, new_text)

        if self._mem0 is None:
            return False
        mem0 = self._mem0

        try:
            await asyncio.to_thread(
                mem0.update, memory_id, new_text
            )
            return True
        except Exception:
            logger.warning("Failed to update memory %s", memory_id, exc_info=True)
            return False

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID. Returns True on success."""
        if not self._available:
            return False

        if self._local_collection is not None:
            return await self._local_delete(memory_id)

        if self._mem0 is None:
            return False
        mem0 = self._mem0

        try:
            await asyncio.to_thread(mem0.delete, memory_id)
            return True
        except Exception:
            logger.warning("Failed to delete memory %s", memory_id, exc_info=True)
            return False

    async def delete_all(self, user_id: str) -> bool:
        """Delete all memories for a user. Returns True on success."""
        if not self._available:
            return False

        if self._local_collection is not None:
            return await self._local_delete_all(user_id)

        if self._mem0 is None:
            return False
        mem0 = self._mem0

        try:
            await asyncio.to_thread(mem0.delete_all, user_id=user_id)
            return True
        except Exception:
            logger.warning("Failed to delete all memories for user %s", user_id, exc_info=True)
            return False

    def _init_local_modelscope(self) -> None:
        """Initialize local ModelScope ONNX embedder and Chroma collection."""
        mem_cfg = self._config.memory
        try:
            import chromadb

            self._local_embedder = LocalOnnxEmbeddingService(
                model_dir=mem_cfg.embedding.local_path,
                onnx_model_file=mem_cfg.embedding.onnx_model_file,
                modelscope_model_id=mem_cfg.embedding.modelscope_model_id,
            )
            self._local_embedder.ensure_available()
            client = chromadb.PersistentClient(path=mem_cfg.db_path)
            self._local_collection = client.get_or_create_collection(
                name="weilinkbot_memory_local",
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
            self._init_error = None
            logger.info(
                "Local memory module initialized (model=%s, onnx=%s, db=%s)",
                mem_cfg.embedding.model,
                mem_cfg.embedding.onnx_model_file,
                mem_cfg.db_path,
            )
        except Exception as exc:
            logger.exception("Failed to initialize local ModelScope memory module")
            self._local_embedder = None
            self._local_collection = None
            self._available = False
            self._init_error = str(exc)

    async def _local_search(self, user_id: str, query: str) -> list[str]:
        try:
            if self._local_embedder is None or self._local_collection is None:
                return []
            embedder = self._local_embedder
            collection = self._local_collection
            vector = (await asyncio.to_thread(embedder.embed, [query]))[0]
            result = await asyncio.to_thread(
                collection.query,
                query_embeddings=[vector],
                n_results=self._config.memory.top_k,
                where={"user_id": user_id},
                include=["documents", "metadatas"],
            )
            docs = result.get("documents") or [[]]
            return [doc for doc in docs[0] if doc]
        except Exception:
            logger.warning("Local memory search failed for user %s", user_id, exc_info=True)
            return []

    async def _local_add(self, user_id: str, user_msg: str, assistant_reply: str) -> None:
        text = f"用户：{user_msg}\n助手：{assistant_reply}".strip()
        if not text:
            return
        try:
            if self._local_embedder is None or self._local_collection is None:
                return
            embedder = self._local_embedder
            collection = self._local_collection
            memory_id = hashlib.sha256(f"{user_id}:{text}".encode("utf-8")).hexdigest()
            vector = (await asyncio.to_thread(embedder.embed, [text]))[0]
            await asyncio.to_thread(
                collection.upsert,
                ids=[memory_id],
                embeddings=[vector],
                documents=[text],
                metadatas=[{"user_id": user_id, "memory": text}],
            )
        except Exception:
            logger.warning("Failed to store local memory for user %s", user_id, exc_info=True)

    async def _local_get_all(self, user_id: str) -> list[dict[str, object]]:
        try:
            if self._local_collection is None:
                return []
            collection = self._local_collection
            result = await asyncio.to_thread(
                collection.get,
                where={"user_id": user_id},
                include=["documents", "metadatas"],
            )
            ids = result.get("ids") or []
            docs = result.get("documents") or []
            metadatas = result.get("metadatas") or []
            items: list[dict[str, object]] = []
            for idx, memory_id in enumerate(ids):
                raw_metadata = metadatas[idx] if idx < len(metadatas) and metadatas[idx] else {}
                metadata = dict(raw_metadata)
                text = metadata.get("memory") or (docs[idx] if idx < len(docs) else "")
                items.append({"id": memory_id, "memory": text, **metadata})
            return items
        except Exception:
            logger.warning("Failed to get local memories for user %s", user_id, exc_info=True)
            return []

    async def _local_update(self, memory_id: str, new_text: str) -> bool:
        try:
            if self._local_embedder is None or self._local_collection is None:
                return False
            embedder = self._local_embedder
            collection = self._local_collection
            existing = await asyncio.to_thread(
                collection.get,
                ids=[memory_id],
                include=["metadatas"],
            )
            metadatas = existing.get("metadatas") or []
            metadata = dict(metadatas[0]) if metadatas and metadatas[0] else {}
            metadata["memory"] = new_text
            vector = (await asyncio.to_thread(embedder.embed, [new_text]))[0]
            await asyncio.to_thread(
                collection.update,
                ids=[memory_id],
                embeddings=[vector],
                documents=[new_text],
                metadatas=[metadata],
            )
            return True
        except Exception:
            logger.warning("Failed to update local memory %s", memory_id, exc_info=True)
            return False

    async def _local_delete(self, memory_id: str) -> bool:
        try:
            if self._local_collection is None:
                return False
            collection = self._local_collection
            await asyncio.to_thread(collection.delete, ids=[memory_id])
            return True
        except Exception:
            logger.warning("Failed to delete local memory %s", memory_id, exc_info=True)
            return False

    async def _local_delete_all(self, user_id: str) -> bool:
        try:
            if self._local_collection is None:
                return False
            collection = self._local_collection
            await asyncio.to_thread(collection.delete, where={"user_id": user_id})
            return True
        except Exception:
            logger.warning("Failed to delete all local memories for user %s", user_id, exc_info=True)
            return False
