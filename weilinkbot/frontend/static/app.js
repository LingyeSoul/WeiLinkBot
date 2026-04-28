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
            { id: "settings", label: "Settings" },
            { id: "users", label: "Users" },
        ],

        // Bot
        botStatus: { status: "stopped", login_url: null, error: null, user_id: null, account_id: null },

        // Conversations
        conversations: [],
        selectedUser: null,
        selectedMessages: [],

        // Prompts
        prompts: [],
        showPromptForm: false,
        promptForm: { id: null, name: "", content: "", is_default: false },

        // LLM Config
        llmForm: { provider: "openai", api_key: "", base_url: "", model: "", max_tokens: 2048, temperature: 0.7 },
        llmSaved: false,

        // Users
        users: [],

        // Toast
        toast: { show: false, message: "", type: "info" },

        // Polling
        _pollTimer: null,

        // ── Init ─────────────────────────────────────────────────
        async init() {
            await this.refreshAll();
            // Poll bot status every 3 seconds
            this._pollTimer = setInterval(() => this.refreshBotStatus(), 3000);
        },

        async refreshAll() {
            await Promise.all([
                this.refreshBotStatus(),
                this.refreshConversations(),
                this.refreshPrompts(),
                this.refreshLLMConfig(),
                this.refreshUsers(),
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

        // ── Bot Control ──────────────────────────────────────────
        async refreshBotStatus() {
            try {
                this.botStatus = await this.api("/api/bot/status");
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
                // Scroll to bottom
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

        // ── LLM Config ───────────────────────────────────────────
        async refreshLLMConfig() {
            try {
                const data = await this.api("/api/config");
                this.llmForm = {
                    provider: data.provider,
                    base_url: data.base_url,
                    model: data.model,
                    max_tokens: data.max_tokens,
                    temperature: data.temperature,
                    api_key: "",  // Never pre-fill
                };
            } catch { /* use defaults */ }
        },

        onProviderChange() {
            const preset = PRESETS[this.llmForm.provider];
            if (preset) {
                this.llmForm.base_url = preset.base_url;
                this.llmForm.model = preset.model;
            }
        },

        async saveLLMConfig() {
            const body = {};
            if (this.llmForm.provider) body.provider = this.llmForm.provider;
            if (this.llmForm.api_key) body.api_key = this.llmForm.api_key;
            if (this.llmForm.base_url) body.base_url = this.llmForm.base_url;
            if (this.llmForm.model) body.model = this.llmForm.model;
            if (this.llmForm.max_tokens) body.max_tokens = this.llmForm.max_tokens;
            if (this.llmForm.temperature !== undefined) body.temperature = this.llmForm.temperature;

            await this.api("/api/config", { method: "PUT", body: JSON.stringify(body) });
            this.llmSaved = true;
            this.llmForm.api_key = "";  // Clear after save
            setTimeout(() => { this.llmSaved = false; }, 2000);
            this.showToast("LLM config updated", "success");
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
    };
}
