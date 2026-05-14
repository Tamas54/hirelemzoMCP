"""Echolot dashboard i18n — translations for 6 languages.

Kept minimal and key-based. Add new keys as the dashboard grows; the
fallback for any missing translation is the English ('en') value.

Languages:
    hu — Hungarian (default for Magyar audience)
    en — English (international)
    de — German
    es — Spanish
    zh — Chinese (Simplified)
    fr — French

Usage:
    from echolot_i18n import t, lang_options, resolve_lang
    label = t("search.button", "hu")
    options = lang_options()  # for the language selector UI
"""
from __future__ import annotations

SUPPORTED_LANGS = ("hu", "en", "de", "es", "zh", "fr")
DEFAULT_LANG = "hu"

# Each translation key holds a dict of lang -> string. English is the
# fallback whenever a language is missing.
TRANSLATIONS: dict[str, dict[str, str]] = {
    # ── Site ────────────────────────────────────────────────────────
    "site.title": {
        "hu": "Echolot — Multi-szféra híranalitika",
        "en": "Echolot — Multi-sphere news intelligence",
        "de": "Echolot — Multi-Sphären-Nachrichtenanalyse",
        "es": "Echolot — Inteligencia de noticias multi-esfera",
        "zh": "Echolot — 多视角新闻情报",
        "fr": "Echolot — Renseignement d'actualité multi-sphère",
    },
    "site.subtitle": {
        "hu": "Több perspektíva, 380+ forrás, 8 nyelv — narratíva-eltérés egyetlen kérdéssel",
        "en": "Multiple perspectives, 380+ sources, 8 languages — narrative divergence in one query",
        "de": "Mehrere Perspektiven, 380+ Quellen, 8 Sprachen — Narrativ-Divergenz mit einer Anfrage",
        "es": "Múltiples perspectivas, 380+ fuentes, 8 idiomas — divergencia narrativa en una consulta",
        "zh": "多视角,380+来源,8种语言 — 一次查询即可获得叙事差异",
        "fr": "Multiples perspectives, 380+ sources, 8 langues — divergence narrative en une requête",
    },
    # ── Search ──────────────────────────────────────────────────────
    "search.placeholder": {
        "hu": "Keresési kifejezés (pl. Trump vámok, MNB kamatdöntés)",
        "en": "Search terms (e.g. Trump tariffs, ECB rate decision)",
        "de": "Suchbegriffe (z. B. Trump Zölle, EZB-Zinsentscheidung)",
        "es": "Términos de búsqueda (p. ej. aranceles de Trump)",
        "zh": "搜索关键词 (例如:Trump 关税)",
        "fr": "Termes de recherche (ex. droits de douane Trump)",
    },
    "search.button": {
        "hu": "Keresés",
        "en": "Search",
        "de": "Suchen",
        "es": "Buscar",
        "zh": "搜索",
        "fr": "Rechercher",
    },
    "search.days_label": {
        "hu": "Visszatekintés (nap)",
        "en": "Lookback (days)",
        "de": "Rückblick (Tage)",
        "es": "Rango (días)",
        "zh": "回溯 (天)",
        "fr": "Période (jours)",
    },
    # ── Tabs ────────────────────────────────────────────────────────
    "tab.divergence": {
        "hu": "Narratíva-eltérés",
        "en": "Narrative divergence",
        "de": "Narrativ-Divergenz",
        "es": "Divergencia narrativa",
        "zh": "叙事差异",
        "fr": "Divergence narrative",
    },
    "tab.search": {
        "hu": "Keresés",
        "en": "Search",
        "de": "Suche",
        "es": "Buscar",
        "zh": "搜索",
        "fr": "Recherche",
    },
    "tab.trending": {
        "hu": "Felkapott témák",
        "en": "Trending",
        "de": "Im Trend",
        "es": "Tendencias",
        "zh": "热门话题",
        "fr": "Tendances",
    },
    "tab.spheres": {
        "hu": "Szférák",
        "en": "Spheres",
        "de": "Sphären",
        "es": "Esferas",
        "zh": "视角圈",
        "fr": "Sphères",
    },
    "tab.health": {
        "hu": "Állapot",
        "en": "Health",
        "de": "Status",
        "es": "Estado",
        "zh": "状态",
        "fr": "État",
    },
    # ── Article fields ──────────────────────────────────────────────
    "article.source": {
        "hu": "Forrás",
        "en": "Source",
        "de": "Quelle",
        "es": "Fuente",
        "zh": "来源",
        "fr": "Source",
    },
    "article.published_at": {
        "hu": "Megjelenés",
        "en": "Published",
        "de": "Veröffentlicht",
        "es": "Publicado",
        "zh": "发布时间",
        "fr": "Publié",
    },
    "article.trust": {
        "hu": "Megbízhatóság",
        "en": "Trust",
        "de": "Vertrauen",
        "es": "Confianza",
        "zh": "可信度",
        "fr": "Fiabilité",
    },
    "article.lean": {
        "hu": "Beállítottság",
        "en": "Lean",
        "de": "Tendenz",
        "es": "Tendencia",
        "zh": "倾向",
        "fr": "Tendance",
    },
    # ── Status / messages ───────────────────────────────────────────
    "msg.loading": {
        "hu": "Betöltés…",
        "en": "Loading…",
        "de": "Lädt…",
        "es": "Cargando…",
        "zh": "加载中…",
        "fr": "Chargement…",
    },
    "msg.no_results": {
        "hu": "Nincs találat",
        "en": "No results",
        "de": "Keine Treffer",
        "es": "Sin resultados",
        "zh": "无结果",
        "fr": "Aucun résultat",
    },
    "msg.empty_query": {
        "hu": "Adj meg egy keresési kifejezést",
        "en": "Enter a search term",
        "de": "Suchbegriff eingeben",
        "es": "Introduce un término",
        "zh": "请输入搜索关键词",
        "fr": "Saisissez un terme",
    },
    "msg.error": {
        "hu": "Hiba",
        "en": "Error",
        "de": "Fehler",
        "es": "Error",
        "zh": "错误",
        "fr": "Erreur",
    },
    # ── About / footer ──────────────────────────────────────────────
    "footer.about": {
        "hu": "Az Echolot egy nyílt MCP-szerver, ami 380+ hírforrást és közösségi-média csatornát összegez 63 szférába rendezve. Magyar, angol, német, orosz, kínai, japán, francia, ukrán nyelven.",
        "en": "Echolot is an open MCP server aggregating 380+ news and social-media sources into 63 perspective spheres. Hungarian, English, German, Russian, Chinese, Japanese, French, Ukrainian.",
        "de": "Echolot ist ein offener MCP-Server, der 380+ Nachrichten- und Social-Media-Quellen in 63 Perspektiv-Sphären zusammenführt. Ungarisch, Englisch, Deutsch, Russisch, Chinesisch, Japanisch, Französisch, Ukrainisch.",
        "es": "Echolot es un servidor MCP abierto que agrega 380+ fuentes de noticias y redes sociales en 63 esferas de perspectiva. Húngaro, inglés, alemán, ruso, chino, japonés, francés, ucraniano.",
        "zh": "Echolot 是一个开源的 MCP 服务器,将 380+ 新闻和社交媒体来源汇总到 63 个视角圈中。支持匈牙利语、英语、德语、俄语、中文、日语、法语、乌克兰语。",
        "fr": "Echolot est un serveur MCP ouvert qui agrège 380+ sources de presse et de médias sociaux dans 63 sphères de perspective. Hongrois, anglais, allemand, russe, chinois, japonais, français, ukrainien.",
    },
    # ── Language selector ──────────────────────────────────────────
    "lang.label": {
        "hu": "Nyelv",
        "en": "Language",
        "de": "Sprache",
        "es": "Idioma",
        "zh": "语言",
        "fr": "Langue",
    },
}

LANG_NATIVE_NAMES = {
    "hu": "Magyar",
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "zh": "中文",
    "fr": "Français",
}


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Translate `key` to `lang`. Falls back to English, then to the key."""
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key  # unknown key → return as-is (helps spotting missing translations)
    return entry.get(lang) or entry.get("en") or key


def lang_options() -> list[tuple[str, str]]:
    """List of (code, native_name) tuples for the language selector."""
    return [(code, LANG_NATIVE_NAMES[code]) for code in SUPPORTED_LANGS]


def resolve_lang(
    query_lang: str | None = None,
    cookie_lang: str | None = None,
    accept_language: str | None = None,
) -> str:
    """Pick the best language. Precedence: query > cookie > Accept-Language > default."""
    for candidate in (query_lang, cookie_lang):
        if candidate and candidate.lower() in SUPPORTED_LANGS:
            return candidate.lower()
    if accept_language:
        # Parse e.g. "hu,en;q=0.9,de;q=0.8" — first supported wins
        for chunk in accept_language.split(","):
            code = chunk.strip().split(";")[0].strip().lower().split("-")[0]
            if code in SUPPORTED_LANGS:
                return code
    return DEFAULT_LANG
