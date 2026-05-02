"""Memory service — wraps mem0 for long-term user memory."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[misc]

from ..config import AppConfig
from .local_embedding_service import LOCAL_EMBEDDING_PROVIDER, LocalOnnxEmbeddingService

logger = logging.getLogger(__name__)

MEMORY_CATEGORIES = ("user_preferences", "personality", "emotional", "general")
DEFAULT_CATEGORY = "general"


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

            # Inject persona-aware custom instructions for fact extraction
            custom_instr_parts: list[str] = []
            if mem_cfg.custom_instructions:
                custom_instr_parts.append(mem_cfg.custom_instructions)
            if mem_cfg.role_term_blacklist:
                blacklist_str = ", ".join(mem_cfg.role_term_blacklist)
                custom_instr_parts.append(
                    f"NEVER extract memories containing these character-specific roleplay terms: "
                    f"{blacklist_str}. These are fictional persona behaviors, not user facts."
                )
            custom_instr_parts.append(
                "Categorize each extracted memory with a 'category' field: "
                "'user_preferences' (likes, dislikes, habits), "
                "'personality' (traits, communication style), "
                "'emotional' (mood, feelings, relationships), "
                "'general' (facts, events, plans)."
            )
            if custom_instr_parts:
                mem0_config["custom_instructions"] = "\n\n".join(custom_instr_parts)

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
        llm_base_url, llm_model, top_k, db_path, tuning fields.
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
        if "min_score" in kwargs:
            mem_cfg.min_score = float(str(kwargs["min_score"]))
        if "max_context_chars" in kwargs:
            mem_cfg.max_context_chars = int(str(kwargs["max_context_chars"]))
        if "preload_onnx" in kwargs:
            mem_cfg.preload_onnx = bool(kwargs["preload_onnx"])
        _set_if_nonempty("hnsw_space", mem_cfg, "hnsw_space")
        if "hnsw_m" in kwargs:
            mem_cfg.hnsw_m = int(str(kwargs["hnsw_m"]))
        if "hnsw_construction_ef" in kwargs:
            mem_cfg.hnsw_construction_ef = int(str(kwargs["hnsw_construction_ef"]))
        if "hnsw_search_ef" in kwargs:
            mem_cfg.hnsw_search_ef = int(str(kwargs["hnsw_search_ef"]))
        if "fact_extraction" in kwargs:
            mem_cfg.fact_extraction = bool(kwargs["fact_extraction"])
        _set_if_provided("custom_instructions", mem_cfg, "custom_instructions")
        if "role_term_blacklist" in kwargs and kwargs["role_term_blacklist"] is not None:
            mem_cfg.role_term_blacklist = list(kwargs["role_term_blacklist"])
        if "category_budgets" in kwargs and kwargs["category_budgets"] is not None:
            mem_cfg.category_budgets = dict(kwargs["category_budgets"])

        if mem_cfg.hnsw_search_ef < mem_cfg.top_k:
            mem_cfg.hnsw_search_ef = mem_cfg.top_k
            logger.warning("hnsw_search_ef clamped to top_k=%d", mem_cfg.top_k)

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

    async def search(self, user_id: str, query: str) -> list[dict[str, str]]:
        """Search memories for a user. Returns list of {"text": str, "category": str}.

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
            memories: list[dict[str, str]] = []
            if isinstance(results, dict):
                items = results.get("results", results.get("memories", []))
            elif isinstance(results, list):
                items = results
            else:
                items = []

            for item in items:
                if isinstance(item, dict):
                    text = item.get("memory", item.get("text", ""))
                    category = item.get(
                        "category",
                        item.get("metadata", {}).get("category", DEFAULT_CATEGORY),
                    )
                else:
                    text = str(item)
                    category = DEFAULT_CATEGORY
                if text:
                    memories.append({"text": text, "category": category})

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
            from chromadb.config import Settings

            self._local_embedder = LocalOnnxEmbeddingService(
                model_dir=mem_cfg.embedding.local_path,
                onnx_model_file=mem_cfg.embedding.onnx_model_file,
                modelscope_model_id=mem_cfg.embedding.modelscope_model_id,
                preload=mem_cfg.preload_onnx,
            )
            if not mem_cfg.preload_onnx:
                self._local_embedder.ensure_files_available()
            client = chromadb.PersistentClient(
                path=mem_cfg.db_path,
                settings=Settings(anonymized_telemetry=False),
            )
            self._local_collection = client.get_or_create_collection(
                name="weilinkbot_memory_local",
                metadata={
                    "hnsw:space": mem_cfg.hnsw_space,
                    "hnsw:M": int(mem_cfg.hnsw_m),
                    "hnsw:construction_ef": int(mem_cfg.hnsw_construction_ef),
                    "hnsw:search_ef": int(mem_cfg.hnsw_search_ef),
                },
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

    async def _local_search(self, user_id: str, query: str) -> list[dict[str, str]]:
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
                include=["documents", "distances", "metadatas"],
            )
            docs = result.get("documents") or [[]]
            distances = result.get("distances") or [[]]
            metadatas = result.get("metadatas") or [[]]
            min_score = self._config.memory.min_score
            memories: list[dict[str, str]] = []
            for doc, distance, meta in zip(docs[0], distances[0], metadatas[0]):
                if not doc:
                    continue
                similarity = 1.0 - float(distance)
                if similarity >= min_score:
                    category = (meta or {}).get("category", DEFAULT_CATEGORY)
                    memories.append({"text": doc, "category": category})
            return memories
        except Exception:
            logger.warning("Local memory search failed for user %s", user_id, exc_info=True)
            return []

    async def _local_add(self, user_id: str, user_msg: str, assistant_reply: str) -> None:
        if not user_msg.strip():
            return
        try:
            if self._local_embedder is None or self._local_collection is None:
                return

            mem_cfg = self._config.memory
            facts: list[dict[str, str]] = []

            if mem_cfg.fact_extraction:
                # Try LLM-based extraction first
                llm_facts = await self._llm_extract_facts(user_msg, assistant_reply)
                if llm_facts:
                    facts = llm_facts
                else:
                    facts = self._rule_based_extract(user_msg)
            else:
                facts = self._rule_based_extract(user_msg)

            if not facts:
                return

            await self._deduplicate_and_store(user_id, facts)
        except Exception:
            logger.warning("Failed to store local memory for user %s", user_id, exc_info=True)

    async def _llm_extract_facts(
        self, user_msg: str, assistant_reply: str
    ) -> list[dict[str, str]] | None:
        """Extract structured facts via LLM. Returns None on failure."""
        mem_cfg = self._config.memory
        api_key = mem_cfg.llm.api_key or self._config.llm.api_key
        model = mem_cfg.llm.model or self._config.llm.model
        base_url = mem_cfg.llm.base_url or self._config.llm.base_url
        if not api_key or not model:
            return None

        categories_desc = ", ".join(MEMORY_CATEGORIES)
        blacklist_note = ""
        if mem_cfg.role_term_blacklist:
            terms = ", ".join(mem_cfg.role_term_blacklist)
            blacklist_note = (
                f"\nNEVER extract memories containing these character-specific roleplay terms: "
                f"{terms}. These are fictional persona behaviors, not user facts."
            )

        extraction_prompt = (
            "You are a memory extraction system. Analyze the conversation and extract "
            "important facts about the USER only. Ignore the assistant's roleplay behavior "
            "(e.g., tail wagging, ear movements, cute expressions — these are persona, not facts).\n"
            f"Categorize each fact into one of: {categories_desc}\n"
            "- user_preferences: likes, dislikes, habits, settings\n"
            "- personality: traits, communication style, values\n"
            "- emotional: mood, feelings, emotional state, relationships\n"
            "- general: facts, events, plans, context\n"
            f"{blacklist_note}\n"
            "Return a JSON array of objects with 'text' and 'category' fields. "
            "If nothing worth remembering, return an empty array [].\n"
            "Example: [{\"text\": \"用户喜欢科幻小说\", \"category\": \"user_preferences\"}]"
        )

        messages = [
            {"role": "system", "content": extraction_prompt},
            {
                "role": "user",
                "content": f"User: {user_msg}\nAssistant: {assistant_reply}",
            },
        ]

        try:
            import json
            import re

            from openai import AsyncOpenAI

            async with AsyncOpenAI(api_key=api_key, base_url=base_url or None) as client:
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.1,
                        max_tokens=500,
                    ),
                    timeout=15.0,
                )
            text = (response.choices[0].message.content or "").strip()

            # Parse JSON from response (handle markdown code blocks)
            match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()

            parsed = json.loads(text)
            if not isinstance(parsed, list):
                return None

            result: list[dict[str, str]] = []
            for item in parsed:
                if isinstance(item, dict) and "text" in item:
                    cat = item.get("category", DEFAULT_CATEGORY)
                    if cat not in MEMORY_CATEGORIES:
                        cat = DEFAULT_CATEGORY
                    result.append({"text": str(item["text"]), "category": cat})
            return result if result else None
        except Exception:
            logger.debug("LLM fact extraction failed, falling back to rule-based", exc_info=True)
            return None

    def _rule_based_extract(self, user_msg: str) -> list[dict[str, str]]:
        """Lightweight fact extraction without LLM. Returns user message as a single fact."""
        text = user_msg.strip()
        if not text:
            return []

        # Apply blacklist filtering
        blacklist = self._config.memory.role_term_blacklist
        if blacklist:
            for term in blacklist:
                text = text.replace(term, "")
            text = " ".join(text.split()).strip()
        if not text:
            return []

        # Keyword-based category detection
        import re

        preference_pattern = re.compile(
            r"喜欢|讨厌|偏好|不喜欢|最爱|最烦|prefer|like|dislike|favorite|hate|love",
            re.IGNORECASE,
        )
        emotional_pattern = re.compile(
            r"心情|开心|难过|伤心|生气|焦虑|压力|高兴|委屈|feeling|happy|sad|angry|anxious|stressed|upset",
            re.IGNORECASE,
        )
        personality_pattern = re.compile(
            r"性格|我是|我一直|我从来|我总是|I am|I always|I never|I'm",
            re.IGNORECASE,
        )

        if preference_pattern.search(text):
            category = "user_preferences"
        elif emotional_pattern.search(text):
            category = "emotional"
        elif personality_pattern.search(text):
            category = "personality"
        else:
            category = DEFAULT_CATEGORY

        return [{"text": text, "category": category}]

    async def _deduplicate_and_store(
        self, user_id: str, facts: list[dict[str, str]]
    ) -> None:
        """Store facts with semantic deduplication."""
        if self._local_embedder is None or self._local_collection is None:
            return
        embedder = self._local_embedder
        collection = self._local_collection
        now = datetime.now().isoformat()

        for fact in facts:
            text = fact["text"]
            category = fact.get("category", DEFAULT_CATEGORY)

            # Embed the new fact
            vector = (await asyncio.to_thread(embedder.embed, [text]))[0]

            # Check for similar existing memories
            existing = await asyncio.to_thread(
                collection.query,
                query_embeddings=[vector],
                n_results=3,
                where={"user_id": user_id},
                include=["documents", "distances", "metadatas"],
            )
            existing_ids = (existing.get("ids") or [[]])[0]
            existing_dists = (existing.get("distances") or [[]])[0]

            skip = False
            updated_any = False
            for eid, dist in zip(existing_ids, existing_dists):
                similarity = 1.0 - float(dist)
                if similarity > 0.92:
                    # Near-duplicate — skip
                    skip = True
                    break
                if similarity > 0.80:
                    # Similar but different — update all similar memories
                    try:
                        await asyncio.to_thread(
                            collection.update,
                            ids=[eid],
                            documents=[text],
                            embeddings=[vector],
                            metadatas=[{
                                "user_id": user_id,
                                "memory": text,
                                "category": category,
                                "updated_at": now,
                                "source": "chat",
                                "schema_version": 2,
                            }],
                        )
                        updated_any = True
                    except Exception:
                        logger.debug("Failed to update similar memory %s", eid, exc_info=True)

            if skip or updated_any:
                continue

            # No similar memory found — insert new
            memory_id = hashlib.sha256(f"{user_id}:{text}".encode("utf-8")).hexdigest()
            await asyncio.to_thread(
                collection.upsert,
                ids=[memory_id],
                embeddings=[vector],
                documents=[text],
                metadatas=[{
                    "user_id": user_id,
                    "memory": text,
                    "category": category,
                    "created_at": now,
                    "updated_at": now,
                    "source": "chat",
                    "schema_version": 2,
                }],
            )

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
            metadata["updated_at"] = datetime.now().isoformat()
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

    async def export_memories(self, user_id: str | None = None) -> dict[str, object]:
        """Export local memories for backup."""
        if user_id:
            memories = await self.get_all(user_id)
            return {"user_id": user_id, "memories": memories, "count": len(memories)}

        if self._local_collection is None:
            return {"user_id": None, "memories": [], "count": 0}

        try:
            result = await asyncio.to_thread(
                self._local_collection.get,
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
            return {"user_id": None, "memories": items, "count": len(items)}
        except Exception:
            logger.warning("Failed to export local memories", exc_info=True)
            return {"user_id": None, "memories": [], "count": 0}

    async def import_memories(self, memories: list[dict[str, object]]) -> int:
        """Import memory backup items into the local store."""
        imported = 0
        for item in memories:
            user_id = str(item.get("user_id", "")).strip()
            memory = str(item.get("memory", "")).strip()
            if not user_id or not memory:
                continue
            await self._local_add(user_id, memory, "")
            imported += 1
        return imported
