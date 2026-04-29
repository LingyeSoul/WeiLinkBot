// WeiLinkBot i18n — frontend internationalization

window.i18n = {
    lang: localStorage.getItem("lang") || detectLang(),
    translations: {},
    _listeners: [],

    async init() {
        try {
            const resp = await fetch(`/locales/${this.lang}.json`);
            if (resp.ok) {
                this.translations = await resp.json();
            } else {
                // Fallback to English
                const fallback = await fetch("/locales/en.json");
                this.translations = await fallback.json();
            }
        } catch {
            this.translations = {};
        }
    },

    t(key) {
        return this.translations[key] || key;
    },

    async switchLang(lang) {
        this.lang = lang;
        localStorage.setItem("lang", lang);
        await this.init();
        window.dispatchEvent(new Event("lang-changed"));
    },

    onChange(fn) {
        this._listeners.push(fn);
    }
};

function detectLang() {
    const nav = navigator.language || navigator.userLanguage || "en";
    return nav.startsWith("zh") ? "zh-CN" : "en";
}

// Global shorthand
window.t = (key) => window.i18n.t(key);
