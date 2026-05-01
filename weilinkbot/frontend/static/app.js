// WeiLinkBot Dashboard — Alpine.js Application

const PRESETS = {
    openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
    deepseek: { base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
};

function dashboard() {
    return {
        // ── State ────────────────────────────────────────────────
        activeTab: "status",
        langLabel: "EN",

        // Bot
        botStatus: { status: "stopped", login_url: null, error: null, user_id: null, account_id: null, active_model: null, uptime_seconds: null },

        // Conversations
        conversations: [],
        selectedUser: null,
        selectedMessages: [],

        // Prompts
        prompts: [],
        showPromptForm: false,
        promptForm: { id: null, name: "", content: "", is_default: false },

        // Models
        models: [],
        showModelForm: false,
        modelForm: { id: null, name: "", provider: "openai", api_key: "", base_url: "", model: "", max_tokens: 2048, temperature: 0.7, is_active: false, capability_text: true, capability_audio: false, capability_image: false, preprocess_voice_model_id: null, preprocess_image_model_id: null, preprocess_voice: false, preprocess_image: false, voice_method: "llm", asr_language: null },

        // Users
        users: [],

        // Characters
        characters: [],
        showCharForm: false,
        charForm: { id: null, name: "", description: "", personality: "", scenario: "", first_mes: "", mes_example: "", is_active: false },

        // Token Stats
        tokenStats: { models: [], total_tokens: 0, total_requests: 0 },       // all-time (from API)
        sessionTokenStats: { models: [], total_tokens: 0, total_requests: 0 }, // current session (from bot status)
        tokenView: "session",  // "session" or "history"

        // About
        botVersion: "0.1.0",

        // Toast
        toast: { show: false, message: "", type: "info" },

        // Polling
        _pollTimer: null,

        // ── Tabs getter (re-evaluates on language change) ────────
        get tabs() {
            return [
                { id: "status", label: t("tab.status") },
                { id: "conversations", label: t("tab.conversations") },
                { id: "prompts", label: t("tab.prompts") },
                { id: "models", label: t("tab.models") },
                { id: "users", label: t("tab.users") },
                { id: "characters", label: t("tab.characters") },
                { id: "memories", label: t("memory.title") },
                { id: "about", label: t("tab.about") },
            ];
        },

        // ── Init ─────────────────────────────────────────────────
        async init() {
            this.langLabel = t("lang.toggle");
            window.addEventListener("lang-changed", () => {
                this.langLabel = t("lang.toggle");
            });
            await this.refreshAll();
            this._pollTimer = setInterval(() => this.refreshBotStatus(), 3000);
            setInterval(() => this.refreshTokenStats(), 15000);
        },

        // ── Language switch ──────────────────────────────────────
        async switchLang() {
            const newLang = window.i18n.lang === "zh-CN" ? "en" : "zh-CN";
            await window.i18n.switchLang(newLang);
            location.reload();
        },

        async refreshAll() {
            await Promise.all([
                this.refreshBotStatus(),
                this.refreshConversations(),
                this.refreshPrompts(),
                this.refreshModels(),
                this.refreshUsers(),
                this.refreshCharacters(),
                this.refreshTokenStats(),
                this.refreshVersion(),
            ]);
        },

        // ── API Helpers ──────────────────────────────────────────
        async api(path, opts = {}) {
            try {
                const resp = await fetch(path, {
                    headers: { "Content-Type": "application/json" },
                    ...opts,
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                    throw new Error(err.detail || `HTTP ${resp.status}`);
                }
                return await resp.json();
            } catch (e) {
                this.showToast(e.message, "error");
                throw e;
            }
        },

        showToast(message, type = "info") {
            this.toast = { show: true, message, type };
            setTimeout(() => { this.toast.show = false; }, 3000);
        },

        formatUptime(seconds) {
            if (!seconds && seconds !== 0) return "—";
            if (seconds < 60) return Math.floor(seconds) + "s";
            if (seconds < 3600) return Math.floor(seconds / 60) + "m " + Math.floor(seconds % 60) + "s";
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            return h + "h " + m + "m";
        },

        formatNumber(n) {
            if (!n && n !== 0) return "—";
            return n.toLocaleString();
        },

        get charPromptPreview() {
            const f = this.charForm;
            const parts = [`[character("${f.name || '?'}")]`];
            if (f.description) parts.push(`[description("${f.description}")]`);
            if (f.personality) parts.push(`[personality("${f.personality}")]`);
            if (f.scenario) parts.push(`[scenario("${f.scenario}")]`);
            parts.push("<START>");
            if (f.first_mes) parts.push(`{{char}}: ${f.first_mes}`);
            if (f.mes_example) parts.push(f.mes_example);
            return parts.join("\n");
        },

        // Returns the active token stats based on toggle (session or history)
        get activeTokenStats() {
            if (this.tokenView === "session") return this.sessionTokenStats;
            return this.tokenStats;
        },

        async refreshTokenStats() {
            try {
                this.tokenStats = await this.api("/api/stats/tokens");
            } catch { this.tokenStats = { models: [], total_tokens: 0, total_requests: 0 }; }
        },

        async refreshVersion() {
            try {
                const data = await this.api("/api/version");
                this.botVersion = data.version;
            } catch { /* keep default */ }
        },

        // ── Bot Control ──────────────────────────────────────────
        async refreshBotStatus() {
            try {
                const data = await this.api("/api/bot/status");
                this.botStatus = data;
                // Extract session token stats from bot status
                if (data.session_token_stats) {
                    this.sessionTokenStats = data.session_token_stats;
                }
            } catch { /* ignore polling errors */ }
        },

        async startBot() {
            await this.api("/api/bot/start", { method: "POST" });
            this.showToast(t("toast.bot_starting"), "info");
            await this.refreshBotStatus();
        },

        async stopBot() {
            await this.api("/api/bot/stop", { method: "POST" });
            this.showToast(t("toast.bot_stopped"), "info");
            await this.refreshBotStatus();
        },

        // ── Conversations ────────────────────────────────────────
        async refreshConversations() {
            try {
                this.conversations = await this.api("/api/conversations");
            } catch { this.conversations = []; }
        },

        async selectConversation(userId) {
            this.selectedUser = userId;
            try {
                const data = await this.api(`/api/conversations/${userId}`);
                this.selectedMessages = data.messages || [];
                this.$nextTick(() => {
                    const el = document.getElementById("msg-container");
                    if (el) el.scrollTop = el.scrollHeight;
                });
            } catch { this.selectedMessages = []; }
        },

        async clearConversation(userId) {
            if (!confirm(t("confirm.clear_history").replace("{userId}", userId))) return;
            await this.api(`/api/conversations/${userId}`, { method: "DELETE" });
            this.selectedMessages = [];
            await this.refreshConversations();
            await this.refreshTokenStats();
            this.showToast(t("toast.conv_cleared"), "success");
        },

        // ── Prompts ──────────────────────────────────────────────
        async refreshPrompts() {
            try {
                this.prompts = await this.api("/api/prompts");
            } catch { this.prompts = []; }
        },

        editPrompt(prompt) {
            this.promptForm = { ...prompt };
            this.showPromptForm = true;
        },

        resetPromptForm() {
            this.promptForm = { id: null, name: "", content: "", is_default: false };
            this.showPromptForm = false;
        },

        async savePrompt() {
            const form = this.promptForm;
            if (!form.name || !form.content) {
                this.showToast(t("validate.name_content_required"), "error");
                return;
            }
            if (form.id) {
                await this.api(`/api/prompts/${form.id}`, {
                    method: "PUT",
                    body: JSON.stringify({ name: form.name, content: form.content, is_default: form.is_default }),
                });
            } else {
                await this.api("/api/prompts", {
                    method: "POST",
                    body: JSON.stringify({ name: form.name, content: form.content, is_default: form.is_default }),
                });
            }
            this.resetPromptForm();
            await this.refreshPrompts();
            this.showToast(t("toast.prompt_saved"), "success");
        },

        async setDefaultPrompt(id) {
            await this.api(`/api/prompts/${id}/default`, { method: "POST" });
            await this.refreshPrompts();
            this.showToast(t("toast.default_updated"), "success");
        },

        async deletePrompt(id) {
            if (!confirm(t("confirm.delete_prompt"))) return;
            await this.api(`/api/prompts/${id}`, { method: "DELETE" });
            await this.refreshPrompts();
            this.showToast(t("toast.prompt_deleted"), "success");
        },

        // ── Models ───────────────────────────────────────────────
        async refreshModels() {
            try {
                this.models = await this.api("/api/models");
            } catch { this.models = []; }
        },

        resetModelForm() {
            this.modelForm = { id: null, name: "", provider: "openai", api_key: "", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", max_tokens: 2048, temperature: 0.7, is_active: false, capability_text: true, capability_audio: false, capability_image: false, preprocess_voice_model_id: null, preprocess_image_model_id: null, preprocess_voice: false, preprocess_image: false, voice_method: "llm", asr_language: null };
        },

        onModelProviderChange() {
            const preset = PRESETS[this.modelForm.provider];
            if (preset) {
                this.modelForm.base_url = preset.base_url;
                this.modelForm.model = preset.model;
            }
        },

        editModel(m) {
            this.modelForm = {
                id: m.id,
                name: m.name,
                provider: m.provider,
                api_key: "",  // Never pre-fill
                base_url: m.base_url,
                model: m.model,
                max_tokens: m.max_tokens,
                temperature: m.temperature,
                is_active: m.is_active,
                capability_text: m.capability_text,
                capability_audio: m.capability_audio,
                capability_image: m.capability_image,
                preprocess_voice_model_id: m.preprocess_voice_model_id,
                preprocess_image_model_id: m.preprocess_image_model_id,
                preprocess_voice: m.preprocess_voice,
                preprocess_image: m.preprocess_image,
                voice_method: m.voice_method || "llm",
                asr_language: m.asr_language,
            };
            this.showModelForm = true;
        },

        async saveModel() {
            const form = this.modelForm;
            if (!form.name || !form.model || !form.base_url) {
                this.showToast(t("validate.name_model_url_required"), "error");
                return;
            }
            // For new models, API key is required
            if (!form.id && !form.api_key) {
                this.showToast(t("validate.api_key_required"), "error");
                return;
            }

            const body = {
                name: form.name,
                provider: form.provider,
                base_url: form.base_url,
                model: form.model,
                max_tokens: form.max_tokens,
                temperature: form.temperature,
                is_active: form.is_active,
                capability_text: form.capability_text,
                capability_audio: form.capability_audio,
                capability_image: form.capability_image,
                preprocess_voice_model_id: form.preprocess_voice_model_id || null,
                preprocess_image_model_id: form.preprocess_image_model_id || null,
                preprocess_voice: form.preprocess_voice,
                preprocess_image: form.preprocess_image,
                voice_method: form.voice_method || "llm",
                asr_language: form.asr_language || null,
            };
            if (form.api_key) body.api_key = form.api_key;

            if (form.id) {
                await this.api(`/api/models/${form.id}`, { method: "PUT", body: JSON.stringify(body) });
            } else {
                await this.api("/api/models", { method: "POST", body: JSON.stringify(body) });
            }
            this.showModelForm = false;
            this.resetModelForm();
            await this.refreshModels();
            await this.refreshBotStatus();
            this.showToast(t("toast.model_saved"), "success");
        },

        async activateModel(id) {
            await this.api(`/api/models/${id}/activate`, { method: "POST" });
            await this.refreshModels();
            await this.refreshBotStatus();
            this.showToast(t("toast.model_activated"), "success");
        },

        async deleteModel(id, name) {
            if (!confirm(t("confirm.delete_model").replace("{name}", name))) return;
            await this.api(`/api/models/${id}`, { method: "DELETE" });
            await this.refreshModels();
            this.showToast(t("toast.model_deleted"), "success");
        },

        // ── Users ────────────────────────────────────────────────
        async refreshUsers() {
            try {
                this.users = await this.api("/api/users");
            } catch { this.users = []; }
        },

        async toggleBlock(user) {
            await this.api(`/api/users/${user.user_id}`, {
                method: "PUT",
                body: JSON.stringify({ is_blocked: !user.is_blocked }),
            });
            await this.refreshUsers();
            this.showToast(
                user.is_blocked ? t("toast.user_unblocked") : t("toast.user_blocked"),
                "success"
            );
        },

        // ── Characters ─────────────────────────────────────────────
        async refreshCharacters() {
            try { this.characters = await this.api("/api/characters"); }
            catch { this.characters = []; }
        },

        openCharacterForm() {
            this.charForm = { id: null, name: "", description: "", personality: "", scenario: "", first_mes: "", mes_example: "", is_active: false };
            this.showCharForm = true;
        },

        openCharacterEdit(card) {
            this.charForm = {
                id: card.id,
                name: card.name,
                description: card.description || "",
                personality: card.personality || "",
                scenario: card.scenario || "",
                first_mes: card.first_mes || "",
                mes_example: card.mes_example || "",
                is_active: card.is_active || false,
            };
            this.showCharForm = true;
        },

        async saveCharacter() {
            const form = this.charForm;
            if (!form.name) {
                this.showToast(t("validate.name_required"), "error");
                return;
            }
            const body = {
                name: form.name,
                description: form.description,
                personality: form.personality,
                scenario: form.scenario,
                first_mes: form.first_mes || null,
                mes_example: form.mes_example || null,
            };
            if (form.id) {
                await this.api(`/api/characters/${form.id}`, { method: "PUT", body: JSON.stringify(body) });
            } else {
                await this.api("/api/characters", { method: "POST", body: JSON.stringify(body) });
            }
            this.showCharForm = false;
            await this.refreshCharacters();
            this.showToast(t("toast.char_saved"), "success");
        },

        async activateCharacter(id) {
            await this.api(`/api/characters/${id}/activate`, { method: "POST" });
            await this.refreshCharacters();
            this.charForm.is_active = true;
            this.showToast(t("toast.char_activated"), "success");
        },

        async deactivateCharacter() {
            await this.api("/api/characters/deactivate", { method: "POST" });
            await this.refreshCharacters();
            this.charForm.is_active = false;
            this.showToast(t("toast.char_deactivated"), "success");
        },

        async exportCharacter(format) {
            if (!this.charForm.id) return;
            try {
                const resp = await fetch(`/api/characters/${this.charForm.id}/export/${format}`);
                if (!resp.ok) throw new Error("Export failed");
                const blob = await resp.blob();
                const ext = format === "png" ? ".png" : ".json";
                const filename = (this.charForm.name || "character") + ext;
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = filename;
                a.click();
                URL.revokeObjectURL(url);
                this.showToast(t("toast.char_exported"), "success");
            } catch (e) {
                this.showToast(e.message, "error");
            }
        },

        async deleteCharacter(id) {
            if (!confirm(t("confirm.delete_char"))) return;
            await this.api(`/api/characters/${id}`, { method: "DELETE" });
            this.showCharForm = false;
            await this.refreshCharacters();
            this.showToast(t("toast.char_deleted"), "success");
        },

        async importCharacter(event) {
            const file = event.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append("file", file);
            try {
                const resp = await fetch("/api/characters/import", { method: "POST", body: formData });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                    throw new Error(err.detail || `HTTP ${resp.status}`);
                }
                await this.refreshCharacters();
                this.showToast(t("toast.char_imported"), "success");
            } catch (e) {
                this.showToast(e.message, "error");
            }
            event.target.value = "";
        },

        async uploadAvatar(event) {
            const file = event.target.files[0];
            if (!file || !this.charForm.id) return;
            const formData = new FormData();
            formData.append("file", file);
            try {
                const resp = await fetch(`/api/characters/${this.charForm.id}/avatar`, { method: "POST", body: formData });
                if (!resp.ok) throw new Error("Upload failed");
                await this.refreshCharacters();
                this.showToast(t("toast.avatar_uploaded"), "success");
            } catch (e) {
                this.showToast(e.message, "error");
            }
        },
    };
}

function memoriesPanel() {
    return {
        status: { available: false },
        statusLoaded: false,
        showConfig: false,
        configForm: {
            embedding_provider: 'openai',
            embedding_model: '',
            embedding_base_url: '',
            embedding_api_key: '',
            embedding_api_key_set: false,
            embedding_local_path: './data/models/bge-small-zh-v1.5',
            embedding_quantization: 'fp32',
            embedding_onnx_model_file: 'onnx/model.onnx',
            embedding_modelscope_model_id: 'Xenova/bge-small-zh-v1.5',
            llm_provider: 'openai',
            llm_model: '',
            llm_base_url: '',
            llm_api_key: '',
            llm_api_key_set: false,
            top_k: 5,
            min_score: 0,
            max_context_chars: 2000,
            preload_onnx: false,
            hnsw_space: 'cosine',
            hnsw_m: 16,
            hnsw_construction_ef: 200,
            hnsw_search_ef: 100,
        },
        users: [],
        selectedUser: null,
        userMemories: [],
        displayedMemories: [],
        searchQuery: '',
        editingId: null,
        editText: '',
        totalMemories: 0,
        saving: false,
        testing: false,

        async init() {
            this.initShowToast();
            await this.loadConfig();
            await this.loadStatus();
            if (this.status.available) {
                await this.loadUsers();
            }
        },

        async loadConfig() {
            try {
                const res = await fetch('/api/memories/config');
                if (res.ok) {
                    const data = await res.json();
                    this.configForm.embedding_provider = data.embedding?.provider || 'openai';
                    this.configForm.embedding_model = data.embedding?.model || '';
                    this.configForm.embedding_base_url = data.embedding?.base_url || '';
                    this.configForm.embedding_api_key = '';
                    this.configForm.embedding_api_key_set = data.embedding?.api_key_set || false;
                    this.configForm.embedding_local_path = data.embedding?.local_path || './data/models/bge-small-zh-v1.5';
                    this.configForm.embedding_quantization = data.embedding?.quantization || 'fp32';
                    this.configForm.embedding_onnx_model_file = data.embedding?.onnx_model_file || 'onnx/model.onnx';
                    this.configForm.embedding_modelscope_model_id = data.embedding?.modelscope_model_id || 'Xenova/bge-small-zh-v1.5';
                    this.configForm.llm_provider = data.llm?.provider || 'openai';
                    this.configForm.llm_model = data.llm?.model || '';
                    this.configForm.llm_base_url = data.llm?.base_url || '';
                    this.configForm.llm_api_key = '';
                    this.configForm.llm_api_key_set = data.llm?.api_key_set || false;
                    this.configForm.top_k = data.top_k || 5;
                    this.configForm.min_score = data.min_score ?? 0;
                    this.configForm.max_context_chars = data.max_context_chars || 2000;
                    this.configForm.preload_onnx = data.preload_onnx || false;
                    this.configForm.hnsw_space = data.hnsw?.space || 'cosine';
                    this.configForm.hnsw_m = data.hnsw?.m || 16;
                    this.configForm.hnsw_construction_ef = data.hnsw?.construction_ef || 200;
                    this.configForm.hnsw_search_ef = data.hnsw?.search_ef || 100;
                    // Auto-show config when not configured
                    if (!this.configForm.embedding_model) {
                        this.showConfig = true;
                    }
                }
            } catch (e) {
                console.error('Failed to load memory config', e);
            }
        },

        onEmbeddingProviderChange() {
            const presets = {
                openai: { base_url: 'https://api.openai.com/v1', model: 'text-embedding-3-small' },
                'modelscope-local': { base_url: '', model: 'Xenova/bge-small-zh-v1.5' },
            };
            const p = presets[this.configForm.embedding_provider];
            if (p) {
                this.configForm.embedding_base_url = p.base_url;
                this.configForm.embedding_model = p.model;
            }
            if (this.configForm.embedding_provider === 'modelscope-local') {
                this.configForm.embedding_local_path ||= './data/models/bge-small-zh-v1.5';
                this.configForm.embedding_modelscope_model_id ||= 'Xenova/bge-small-zh-v1.5';
                this.configForm.embedding_onnx_model_file ||= 'onnx/model.onnx';
                this.configForm.embedding_quantization ||= 'fp32';
            }
        },

        onEmbeddingOnnxModelChange() {
            const fileName = (this.configForm.embedding_onnx_model_file || '').split('/').pop();
            const mapping = {
                'model_fp16.onnx': 'fp16',
                'model_quantized.onnx': 'quantized',
                'model_int8.onnx': 'int8',
                'model_uint8.onnx': 'uint8',
                'model_q4.onnx': 'q4',
                'model_q4f16.onnx': 'q4f16',
                'model_bnb4.onnx': 'bnb4',
                'model.onnx': 'fp32',
            };
            this.configForm.embedding_quantization = mapping[fileName] || 'custom';
        },

        get isLocalEmbeddingProvider() {
            return this.configForm.embedding_provider === 'modelscope-local';
        },

        get isLocalEmbeddingBusy() {
            return this.isLocalEmbeddingProvider && (this.saving || this.testing);
        },

        get localEmbeddingBusyText() {
            if (this.testing) {
                return '正在检查本地 ONNX 模型。首次使用会从 ModelScope 下载模型文件并加载 ONNX Runtime，可能需要几分钟，请不要关闭页面。';
            }
            if (this.saving) {
                return '正在保存并初始化本地 ONNX 模型。首次使用会从 ModelScope 下载模型文件并加载 ONNX Runtime，可能需要几分钟，请耐心等待。';
            }
            return '首次使用本地模型时会从 ModelScope 下载 ONNX 文件并加载模型，过程可能需要几分钟。';
        },

        async saveConfig() {
            if (!this.configForm.embedding_model.trim()) {
                this.showToast(t('memory.config.model_required'), 'error');
                return;
            }
            if (this.saving) return;
            this.saving = true;
            try {
                const body = {
                    embedding_provider: this.configForm.embedding_provider,
                    embedding_model: this.configForm.embedding_model.trim(),
                    embedding_base_url: this.configForm.embedding_base_url.trim(),
                    embedding_local_path: this.configForm.embedding_local_path.trim(),
                    embedding_quantization: this.configForm.embedding_quantization,
                    embedding_onnx_model_file: this.configForm.embedding_onnx_model_file,
                    embedding_modelscope_model_id: this.configForm.embedding_modelscope_model_id.trim(),
                    top_k: this.configForm.top_k,
                    min_score: this.configForm.min_score,
                    max_context_chars: this.configForm.max_context_chars,
                    preload_onnx: this.configForm.preload_onnx,
                    hnsw_space: this.configForm.hnsw_space,
                    hnsw_m: this.configForm.hnsw_m,
                    hnsw_construction_ef: this.configForm.hnsw_construction_ef,
                    hnsw_search_ef: this.configForm.hnsw_search_ef,
                    llm_provider: this.configForm.llm_provider,
                    llm_model: this.configForm.llm_model.trim(),
                    llm_base_url: this.configForm.llm_base_url.trim(),
                };
                if (this.configForm.embedding_api_key) {
                    body.embedding_api_key = this.configForm.embedding_api_key;
                }
                if (this.configForm.llm_api_key) {
                    body.llm_api_key = this.configForm.llm_api_key;
                }
                const res = await fetch('/api/memories/config', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (res.ok) {
                    const data = await res.json();
                    this.showConfig = false;
                    this.configForm.embedding_api_key = '';
                    this.configForm.llm_api_key = '';
                    await this.loadConfig();
                    await this.loadStatus();
                    if (this.status.available) {
                        await this.loadUsers();
                    }
                    if (data.init_error) {
                        this.showToast(t('memory.config.saved_with_error') + ': ' + data.init_error, 'error');
                    } else {
                        this.showToast(t('memory.config.saved'), 'success');
                    }
                } else {
                    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                    this.showToast(err.detail || t('memory.config.save_failed'), 'error');
                }
            } catch (e) {
                console.error('Failed to save memory config', e);
                this.showToast(t('memory.config.save_failed') + ': ' + e.message, 'error');
            } finally {
                this.saving = false;
            }
        },

        async testConnection() {
            if (this.testing) return;
            this.testing = true;
            try {
                const body = {
                    embedding_provider: this.configForm.embedding_provider,
                    embedding_model: this.configForm.embedding_model.trim(),
                    embedding_base_url: this.configForm.embedding_base_url.trim(),
                    embedding_local_path: this.configForm.embedding_local_path.trim(),
                    embedding_quantization: this.configForm.embedding_quantization,
                    embedding_onnx_model_file: this.configForm.embedding_onnx_model_file,
                    embedding_modelscope_model_id: this.configForm.embedding_modelscope_model_id.trim(),
                };
                if (this.configForm.embedding_api_key) {
                    body.embedding_api_key = this.configForm.embedding_api_key;
                }
                const res = await fetch('/api/memories/config/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await res.json();
                if (data.success) {
                    this.showToast(data.message, 'success');
                } else {
                    this.showToast(data.message, 'error');
                }
            } catch (e) {
                console.error('Connection test failed', e);
                this.showToast(t('memory.config.save_failed') + ': ' + e.message, 'error');
            } finally {
                this.testing = false;
            }
        },

        get selectedUserNickname() {
            const u = this.users.find(u => u.user_id === this.selectedUser);
            return u ? u.nickname : null;
        },

        async loadStatus() {
            try {
                const res = await fetch('/api/memories/status');
                if (res.ok) {
                    this.status = await res.json();
                }
            } catch (e) {
                console.error('Failed to load memory status', e);
            }
            this.statusLoaded = true;
        },

        async loadUsers() {
            try {
                const res = await fetch('/api/memories/users');
                if (res.ok) {
                    const data = await res.json();
                    this.users = data.users || [];
                    this.totalMemories = this.users.reduce((sum, u) => sum + u.count, 0);
                }
            } catch (e) {
                console.error('Failed to load memory users', e);
            }
        },

        showToast(message, type = "info") {
            const dashboard = Alpine.$data(document.querySelector('[x-data="dashboard()"]'));
            if (dashboard && dashboard.showToast) dashboard.showToast(message, type);
        },

        initShowToast() {
            window.showToast = (msg, type) => this.showToast(msg, type);
        },

        async selectUser(userId) {
            this.selectedUser = userId;
            this.searchQuery = '';
            this.editingId = null;
            await this.loadUserMemories();
        },

        async loadUserMemories() {
            try {
                const res = await fetch(`/api/memories/${this.selectedUser}`);
                if (res.ok) {
                    const data = await res.json();
                    this.userMemories = data.memories || [];
                    this.displayedMemories = [...this.userMemories];
                }
            } catch (e) {
                console.error('Failed to load user memories', e);
            }
        },

        async searchMemories() {
            if (!this.searchQuery.trim()) {
                this.displayedMemories = [...this.userMemories];
                return;
            }
            try {
                const res = await fetch(`/api/memories/${this.selectedUser}/search?query=${encodeURIComponent(this.searchQuery)}`);
                if (res.ok) {
                    const data = await res.json();
                    this.displayedMemories = (data.results || []).map((text, i) => ({
                        id: `search-${i}`,
                        memory: text,
                        _isSearchResult: true,
                    }));
                }
            } catch (e) {
                console.error('Failed to search memories', e);
            }
        },

        startEdit(mem) {
            this.editingId = mem.id;
            this.editText = mem.memory || mem.text;
        },

        cancelEdit() {
            this.editingId = null;
            this.editText = '';
        },

        async saveEdit(memoryId) {
            try {
                const res = await fetch(`/api/memories/${memoryId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: this.editText }),
                });
                if (res.ok) {
                    this.editingId = null;
                    if (window.showToast) showToast(t('memory.detail.updated'));
                    await this.loadUserMemories();
                }
            } catch (e) {
                console.error('Failed to update memory', e);
            }
        },

        async deleteMemory(memoryId) {
            try {
                const res = await fetch(`/api/memories/${memoryId}`, { method: 'DELETE' });
                if (res.ok) {
                    if (window.showToast) showToast(t('memory.detail.deleted'));
                    await this.loadUserMemories();
                    await this.loadUsers();
                }
            } catch (e) {
                console.error('Failed to delete memory', e);
            }
        },

        async clearAllMemories() {
            if (!confirm(t('memory.detail.confirm_clear'))) return;
            try {
                const res = await fetch(`/api/memories/user/${this.selectedUser}`, { method: 'DELETE' });
                if (res.ok) {
                    if (window.showToast) showToast(t('memory.detail.cleared'));
                    this.userMemories = [];
                    this.displayedMemories = [];
                    await this.loadUsers();
                }
            } catch (e) {
                console.error('Failed to clear memories', e);
            }
        },

        async exportMemories() {
            try {
                const res = await fetch('/api/memories/export');
                if (!res.ok) {
                    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                    throw new Error(err.detail || 'Export failed');
                }
                const data = await res.json();
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                const stamp = new Date().toISOString().replace(/[:.]/g, '-');
                a.href = url;
                a.download = `weilinkbot-memories-${stamp}.json`;
                a.click();
                URL.revokeObjectURL(url);
                this.showToast('记忆已导出', 'success');
            } catch (e) {
                console.error('Failed to export memories', e);
                this.showToast('记忆导出失败: ' + e.message, 'error');
            }
        },
    };
}
