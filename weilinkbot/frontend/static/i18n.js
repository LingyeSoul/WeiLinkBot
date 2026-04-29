// WeiLinkBot i18n — frontend internationalization

function detectLang() {
    const nav = navigator.language || navigator.userLanguage || "en";
    return nav.startsWith("zh") ? "zh-CN" : "en";
}

window.i18n = {
    lang: localStorage.getItem("lang") || detectLang(),
    translations: {},

    // Load translations synchronously so Alpine.js x-text bindings work immediately
    init() {
        const xhr = new XMLHttpRequest();
        xhr.open("GET", `/locales/${this.lang}.json`, false); // synchronous
        try {
            xhr.send();
            if (xhr.status === 200) {
                this.translations = JSON.parse(xhr.responseText);
            }
        } catch {}

        // Fallback to English if load failed
        if (!Object.keys(this.translations).length) {
            try {
                const fb = new XMLHttpRequest();
                fb.open("GET", "/locales/en.json", false);
                fb.send();
                if (fb.status === 200) {
                    this.translations = JSON.parse(fb.responseText);
                }
            } catch {}
        }

        // Sync frontend language choice to backend (async, fire-and-forget)
        this._syncToBackend(this.lang);
    },

    t(key) {
        return this.translations[key] || key;
    },

    async switchLang(lang) {
        this.lang = lang;
        localStorage.setItem("lang", lang);
        // Update backend global language
        await this._syncToBackend(lang);
        // Re-fetch translations
        try {
            const resp = await fetch(`/locales/${lang}.json`);
            if (resp.ok) {
                this.translations = await resp.json();
            }
        } catch {}
        window.dispatchEvent(new Event("lang-changed"));
    },

    // Sync language to backend so magic commands use the same language
    async _syncToBackend(lang) {
        try {
            await fetch("/api/lang", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ lang }),
            });
        } catch {}
    }
};

// Load translations immediately (synchronous) before Alpine.js starts
window.i18n.init();

// Global shorthand
window.t = (key) => window.i18n.t(key);
