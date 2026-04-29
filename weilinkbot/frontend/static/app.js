// WeiLinkBot Dashboard — Alpine.js Application

const PRESETS = {
    openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
    deepseek: { base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
};

function dashboard() {
    return {
        // ── State ────────────────────────────────────────────────
        activeTab: "status",
        tabs: [
            { id: "status", label: "Status" },
            { id: "conversations", label: "Conversations" },
            { id: "prompts", label: "Prompts" },
            { id: "models", label: "Models" },
            { id: "users", label: "Users" },
            { id: "characters", label: "Characters" },
        ],

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
        modelForm: { id: null, name: "", provider: "openai", api_key: "", base_url: "", model: "", max_tokens: 2048, temperature: 0.7, is_active: false },

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

        // Toast
        toast: { show: false, message: "", type: "info" },

        // Polling
        _pollTimer: null,

        // ── Init ─────────────────────────────────────────────────
        async init() {
            await this.refreshAll();
            this._pollTimer = setInterval(() => this.refreshBotStatus(), 3000);
            // Refresh token stats every 15 seconds
            setInterval(() => this.refreshTokenStats(), 15000);
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
            this.showToast("Bot starting...", "info");
            await this.refreshBotStatus();
        },

        async stopBot() {
            await this.api("/api/bot/stop", { method: "POST" });
            this.showToast("Bot stopped", "info");
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
            if (!confirm(`Clear all messages for ${userId}?`)) return;
            await this.api(`/api/conversations/${userId}`, { method: "DELETE" });
            this.selectedMessages = [];
            await this.refreshConversations();
            await this.refreshTokenStats();
            this.showToast("Conversation cleared", "success");
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
                this.showToast("Name and content are required", "error");
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
            this.showToast("Prompt saved", "success");
        },

        async setDefaultPrompt(id) {
            await this.api(`/api/prompts/${id}/default`, { method: "POST" });
            await this.refreshPrompts();
            this.showToast("Default prompt updated", "success");
        },

        async deletePrompt(id) {
            if (!confirm("Delete this prompt?")) return;
            await this.api(`/api/prompts/${id}`, { method: "DELETE" });
            await this.refreshPrompts();
            this.showToast("Prompt deleted", "success");
        },

        // ── Models ───────────────────────────────────────────────
        async refreshModels() {
            try {
                this.models = await this.api("/api/models");
            } catch { this.models = []; }
        },

        resetModelForm() {
            this.modelForm = { id: null, name: "", provider: "openai", api_key: "", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", max_tokens: 2048, temperature: 0.7, is_active: false };
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
            };
            this.showModelForm = true;
        },

        async saveModel() {
            const form = this.modelForm;
            if (!form.name || !form.model || !form.base_url) {
                this.showToast("Name, model, and base URL are required", "error");
                return;
            }
            // For new models, API key is required
            if (!form.id && !form.api_key) {
                this.showToast("API key is required for new models", "error");
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
            this.showToast("Model saved", "success");
        },

        async activateModel(id) {
            await this.api(`/api/models/${id}/activate`, { method: "POST" });
            await this.refreshModels();
            await this.refreshBotStatus();
            this.showToast("Model activated", "success");
        },

        async deleteModel(id, name) {
            if (!confirm(`Delete model '${name}'?`)) return;
            await this.api(`/api/models/${id}`, { method: "DELETE" });
            await this.refreshModels();
            this.showToast("Model deleted", "success");
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
                user.is_blocked ? "User unblocked" : "User blocked",
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
                this.showToast("Name is required", "error");
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
            this.showToast("Character saved", "success");
        },

        async activateCharacter(id) {
            await this.api(`/api/characters/${id}/activate`, { method: "POST" });
            await this.refreshCharacters();
            this.charForm.is_active = true;
            this.showToast("Character activated", "success");
        },

        async deactivateCharacter() {
            await this.api("/api/characters/deactivate", { method: "POST" });
            await this.refreshCharacters();
            this.charForm.is_active = false;
            this.showToast("Character deactivated", "success");
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
                this.showToast("Character exported", "success");
            } catch (e) {
                this.showToast(e.message, "error");
            }
        },

        async deleteCharacter(id) {
            if (!confirm("Delete this character card?")) return;
            await this.api(`/api/characters/${id}`, { method: "DELETE" });
            this.showCharForm = false;
            await this.refreshCharacters();
            this.showToast("Character deleted", "success");
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
                this.showToast("Character imported", "success");
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
                this.showToast("Avatar uploaded", "success");
            } catch (e) {
                this.showToast(e.message, "error");
            }
        },
    };
}
