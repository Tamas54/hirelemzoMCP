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
    # ── Landing hero ───────────────────────────────────────────────
    "landing.hero_title": {
        "hu": "Globális narratíva-térkép",
        "en": "Global narrative map",
        "de": "Globale Narrativ-Karte",
        "es": "Mapa narrativo global",
        "zh": "全球叙事地图",
        "fr": "Carte narrative mondiale",
    },
    "landing.hero_description": {
        "hu": "315 forrás 63 információs szférából — magyar sajtó, globális anchor lapok, kínai állami média, izraeli bal/jobb, iráni rezsim/ellenzék, ukrán front-OSINT, orosz milblog/ellenzék, japán/koreai/indiai/török/arab/dél-amerikai sajtó, US partisan szubsztakok, AI / climate / health / OSINT topikális csomagok, Telegram-csatornák.",
        "en": "315 sources across 63 information spheres — Hungarian press, global anchor outlets, Chinese state media, Israeli left/right, Iranian regime/opposition, Ukrainian front-OSINT, Russian milblog/opposition, Japanese/Korean/Indian/Turkish/Arab/South-American press, US partisan substacks, AI / climate / health / OSINT topical bundles, Telegram channels.",
        "de": "315 Quellen aus 63 Informationssphären — ungarische Presse, globale Anchor-Medien, chinesische Staatsmedien, israelische Linke/Rechte, iranisches Regime/Opposition, ukrainisches Front-OSINT, russische Milblogs/Opposition, japanische/koreanische/indische/türkische/arabische/südamerikanische Presse, US-Partisanen-Substacks, KI / Klima / Gesundheit / OSINT-Themenbündel, Telegram-Kanäle.",
        "es": "315 fuentes en 63 esferas informativas — prensa húngara, medios globales de referencia, medios estatales chinos, izquierda/derecha israelí, régimen/oposición iraní, OSINT del frente ucraniano, milblogs/oposición rusa, prensa japonesa/coreana/india/turca/árabe/sudamericana, substacks partidistas de EE.UU., paquetes temáticos de IA / clima / salud / OSINT, canales de Telegram.",
        "zh": "63 个信息圈中的 315 个来源 — 匈牙利媒体、全球主流媒体、中国官方媒体、以色列左右派、伊朗政权/反对派、乌克兰前线 OSINT、俄罗斯军事博客/反对派,日本/韩国/印度/土耳其/阿拉伯/南美媒体、美国党派 Substack、AI/气候/健康/OSINT 主题包、Telegram 频道。",
        "fr": "315 sources dans 63 sphères d'information — presse hongroise, médias d'ancrage mondiaux, médias d'État chinois, gauche/droite israélienne, régime/opposition iranienne, OSINT du front ukrainien, milblogs/opposition russes, presse japonaise/coréenne/indienne/turque/arabe/sud-américaine, substacks partisans US, paquets thématiques IA / climat / santé / OSINT, chaînes Telegram.",
    },
    "landing.hero_native_note": {
        "hu": "Eredeti nyelven — az olvasó AI minden nyelvet ért.",
        "en": "In original language — the reader AI understands every language.",
        "de": "In Originalsprache — die lesende KI versteht jede Sprache.",
        "es": "En idioma original — la IA lectora entiende todos los idiomas.",
        "zh": "原文呈现 — 阅读端 AI 通晓所有语言。",
        "fr": "En langue originale — l'IA lectrice comprend toutes les langues.",
    },
    "landing.stat.fresh_articles": {
        "hu": "friss cikk",
        "en": "fresh articles",
        "de": "neue Artikel",
        "es": "artículos recientes",
        "zh": "最新文章",
        "fr": "articles récents",
    },
    "landing.stat.spheres": {
        "hu": "szféra",
        "en": "spheres",
        "de": "Sphären",
        "es": "esferas",
        "zh": "视角圈",
        "fr": "sphères",
    },
    "landing.stat.sources": {
        "hu": "forrás",
        "en": "sources",
        "de": "Quellen",
        "es": "fuentes",
        "zh": "来源",
        "fr": "sources",
    },
    "landing.bar.theme": {
        "hu": "téma",
        "en": "theme",
        "de": "Thema",
        "es": "tema",
        "zh": "主题",
        "fr": "thème",
    },
    "landing.bar.all": {
        "hu": "Mind",
        "en": "All",
        "de": "Alle",
        "es": "Todo",
        "zh": "全部",
        "fr": "Tout",
    },
    "landing.bar.toggle_detailed": {
        "hu": "▼ részletes szféra-lista (63)",
        "en": "▼ detailed sphere list (63)",
        "de": "▼ detaillierte Sphärenliste (63)",
        "es": "▼ lista detallada de esferas (63)",
        "zh": "▼ 详细视角圈列表 (63)",
        "fr": "▼ liste détaillée des sphères (63)",
    },
    "landing.news.title": {
        "hu": "Élő hírfolyam",
        "en": "Live news feed",
        "de": "Live-Nachrichten-Feed",
        "es": "Flujo de noticias en vivo",
        "zh": "实时新闻流",
        "fr": "Flux d'actualités en direct",
    },
    "landing.news.loading": {
        "hu": "Hírek betöltése…",
        "en": "Loading news…",
        "de": "Nachrichten werden geladen…",
        "es": "Cargando noticias…",
        "zh": "正在加载新闻…",
        "fr": "Chargement des actualités…",
    },
    "landing.config.copy_button": {
        "hu": "Konfiguráció másolása",
        "en": "Copy configuration",
        "de": "Konfiguration kopieren",
        "es": "Copiar configuración",
        "zh": "复制配置",
        "fr": "Copier la configuration",
    },
    "landing.config.copy_url_button": {
        "hu": "URL másolása",
        "en": "Copy URL",
        "de": "URL kopieren",
        "es": "Copiar URL",
        "zh": "复制 URL",
        "fr": "Copier l'URL",
    },
    "landing.config.copied_ack": {
        "hu": "Másolva!",
        "en": "Copied!",
        "de": "Kopiert!",
        "es": "¡Copiado!",
        "zh": "已复制!",
        "fr": "Copié !",
    },
    "landing.tools.title": {
        "hu": "MCP eszközök",
        "en": "MCP tools",
        "de": "MCP-Werkzeuge",
        "es": "Herramientas MCP",
        "zh": "MCP 工具",
        "fr": "Outils MCP",
    },
    "landing.tools.intro": {
        "hu": "Klasszikus napi/heti hírlekérés, FTS-keresés és trending — plus a payoff: a <code>narrative_divergence</code>, ami megmondja, ugyanarról a témáról mit ír a kínai állami sajtó, az iráni ellenzék, az ukrán front, az amerikai MAGA-szubsztak — egymás mellett.",
        "en": "Classic daily/weekly news retrieval, FTS search and trending — plus the payoff: <code>narrative_divergence</code>, which tells you what Chinese state media, the Iranian opposition, the Ukrainian front, and US MAGA substacks each say about the same topic — side by side.",
        "de": "Klassischer täglicher/wöchentlicher Nachrichtenabruf, FTS-Suche und Trending — plus der Mehrwert: <code>narrative_divergence</code>, das zeigt, was chinesische Staatsmedien, die iranische Opposition, die ukrainische Front und US-MAGA-Substacks zum gleichen Thema sagen — nebeneinander.",
        "es": "Recuperación clásica diaria/semanal de noticias, búsqueda FTS y tendencias — más el valor añadido: <code>narrative_divergence</code>, que muestra qué dicen los medios estatales chinos, la oposición iraní, el frente ucraniano y los substacks MAGA de EE. UU. sobre el mismo tema — uno al lado del otro.",
        "zh": "经典的每日/每周新闻检索、FTS 搜索和热门话题 — 加上核心价值:<code>narrative_divergence</code>,它能告诉你中国官方媒体、伊朗反对派、乌克兰前线和美国 MAGA Substack 对同一话题的不同表述 — 并列对比。",
        "fr": "Récupération quotidienne/hebdomadaire classique des actualités, recherche FTS et tendances — plus la valeur ajoutée : <code>narrative_divergence</code>, qui montre ce que disent côte à côte les médias d'État chinois, l'opposition iranienne, le front ukrainien et les substacks MAGA américains sur un même sujet.",
    },
    "landing.tools.col_tool": {
        "hu": "Eszköz",
        "en": "Tool",
        "de": "Werkzeug",
        "es": "Herramienta",
        "zh": "工具",
        "fr": "Outil",
    },
    "landing.tools.col_desc": {
        "hu": "Leírás",
        "en": "Description",
        "de": "Beschreibung",
        "es": "Descripción",
        "zh": "说明",
        "fr": "Description",
    },
    "landing.footer.tagline": {
        "hu": "globális hírelemző MCP",
        "en": "global news-intelligence MCP",
        "de": "globaler Nachrichten-Analytik-MCP",
        "es": "MCP de inteligencia de noticias global",
        "zh": "全球新闻情报 MCP",
        "fr": "MCP d'intelligence d'actualités mondiale",
    },
    # ── SEO meta descriptions (max ~160 chars) ─────────────────────
    "seo.site.description": {
        "hu": "Echolot — globális narratíva-térkép. 315 hírforrás 63 információs szférából, 8 nyelven. Magyar sajtó, kínai állam, iráni ellenzék, ukrán front — egymás mellett.",
        "en": "Echolot — global narrative map. 315 news sources across 63 information spheres, 8 languages. Hungarian press, Chinese state, Iranian opposition, Ukrainian front — side by side.",
        "de": "Echolot — globale Narrativ-Karte. 315 Nachrichtenquellen aus 63 Informationssphären, 8 Sprachen. Ungarische Presse, chinesischer Staat, iranische Opposition, ukrainische Front — nebeneinander.",
        "es": "Echolot — mapa narrativo global. 315 fuentes de noticias en 63 esferas informativas, 8 idiomas. Prensa húngara, Estado chino, oposición iraní, frente ucraniano — lado a lado.",
        "zh": "Echolot — 全球叙事地图。63 个信息圈中的 315 个新闻来源,8 种语言。匈牙利媒体、中国官方、伊朗反对派、乌克兰前线 — 并列对比。",
        "fr": "Echolot — carte narrative mondiale. 315 sources d'actualité dans 63 sphères d'information, 8 langues. Presse hongroise, État chinois, opposition iranienne, front ukrainien — côte à côte.",
    },
    "seo.page.trending.description": {
        "hu": "Felkapott témák minden szférában — sphere-velocity, Wikipédia top-pageviews, Google News, YouTube trending. Globális trendek élesben.",
        "en": "Trending topics across every sphere — sphere velocity, Wikipedia top pageviews, Google News, YouTube trending. Global trends in real time.",
        "de": "Trending-Themen in jeder Sphäre — Sphären-Velocity, Wikipedia-Top-Pageviews, Google News, YouTube-Trends. Globale Trends in Echtzeit.",
        "es": "Tendencias en todas las esferas — velocidad de esferas, top de Wikipedia, Google News, tendencias de YouTube. Tendencias globales en tiempo real.",
        "zh": "所有视角圈中的热门话题 — 视角圈热度、维基百科最热条目、Google News、YouTube 热门。实时全球趋势。",
        "fr": "Sujets tendance dans toutes les sphères — vélocité des sphères, top Wikipédia, Google News, tendances YouTube. Tendances mondiales en temps réel.",
    },
    "seo.page.spheres.description": {
        "hu": "Az Echolot 63 információs szférája — szerkesztői perspektíva, regionális hovatartozás, rezsim-igazodás szerint csoportosítva. Lássd melyik él, melyik csendes.",
        "en": "Echolot's 63 information spheres — grouped by editorial perspective, regional alignment, regime affiliation. See which is alive and which is quiet.",
        "de": "Die 63 Informationssphären von Echolot — gruppiert nach redaktioneller Perspektive, regionaler Ausrichtung, Regime-Zugehörigkeit. Sehen Sie, welche aktiv ist.",
        "es": "Las 63 esferas informativas de Echolot — agrupadas por perspectiva editorial, alineación regional, afiliación al régimen. Vea cuáles están activas.",
        "zh": "Echolot 的 63 个信息圈 — 按编辑视角、地区归属、政权立场分组。查看哪些活跃,哪些沉寂。",
        "fr": "Les 63 sphères d'information d'Echolot — regroupées par perspective éditoriale, alignement régional, affiliation au régime. Voyez lesquelles sont actives.",
    },
    "seo.page.health.description": {
        "hu": "Echolot rendszer-egészség — sphere-szintű élet/halott jelzések, X-source aktivitás, ingest-cikkszám, friss-cikk-kor, scraper-pipeline állapot.",
        "en": "Echolot system health — per-sphere alive/dead signals, X-source activity, ingest article counts, freshness, scraper pipeline status.",
        "de": "Echolot-Systemzustand — Sphären-bezogene Lebend/Tot-Signale, X-Quellenaktivität, Ingest-Artikelzahlen, Aktualität, Scraper-Pipeline-Status.",
        "es": "Estado del sistema Echolot — señales de vida/muerte por esfera, actividad de fuentes X, cantidad de artículos, frescura, estado del pipeline scraper.",
        "zh": "Echolot 系统健康状况 — 各视角圈活跃/沉寂指标、X 源活跃度、入库文章数、新鲜度、爬虫管道状态。",
        "fr": "État du système Echolot — signaux vivant/mort par sphère, activité des sources X, nombres d'articles ingérés, fraîcheur, état du pipeline scraper.",
    },
    "seo.page.sphere_detail.description_tpl": {
        "hu": "{sphere} szféra cikkei — Echolot globális hírelemző MCP. Eredeti nyelven, friss tartalom.",
        "en": "Articles from the {sphere} sphere — Echolot global news intelligence MCP. Original language, fresh content.",
        "de": "Artikel aus der Sphäre {sphere} — Echolot globaler Nachrichten-Intelligenz-MCP. Originalsprache, frische Inhalte.",
        "es": "Artículos de la esfera {sphere} — Echolot MCP de inteligencia de noticias global. Idioma original, contenido reciente.",
        "zh": "来自 {sphere} 视角圈的文章 — Echolot 全球新闻情报 MCP。原文呈现,最新内容。",
        "fr": "Articles de la sphère {sphere} — Echolot MCP d'intelligence d'actualités mondiale. Langue originale, contenu récent.",
    },
    # ── Tab-groups: HU domestic ────────────────────────────────────
    "group.hu.domestic":      {"hu": "Magyar",          "en": "Hungarian",          "de": "Ungarisch",            "es": "Húngaro",              "zh": "匈牙利",       "fr": "Hongrois"},
    "group.hu.local":         {"hu": "Belföldi",        "en": "Hungarian domestic", "de": "Ungarisches Inland",   "es": "Doméstico húngaro",    "zh": "匈牙利国内",   "fr": "Intérieur hongrois"},
    "group.hu.economy":       {"hu": "Magyar gazdaság", "en": "Hungarian economy",  "de": "Ungarische Wirtschaft","es": "Economía húngara",     "zh": "匈牙利经济",   "fr": "Économie hongroise"},
    "group.hu.tech":          {"hu": "Magyar tech",     "en": "Hungarian tech",     "de": "Ungarische Tech",      "es": "Tecnología húngara",   "zh": "匈牙利科技",   "fr": "Tech hongroise"},
    "group.hu.sport":         {"hu": "Sport",           "en": "Sport (HU)",         "de": "Sport (HU)",           "es": "Deportes (HU)",        "zh": "体育(匈)",     "fr": "Sport (HU)"},
    "group.hu.lifestyle":     {"hu": "Életmód",         "en": "Lifestyle (HU)",     "de": "Lebensstil (HU)",      "es": "Estilo de vida (HU)",  "zh": "生活方式(匈)", "fr": "Mode de vie (HU)"},
    "group.hu.entertainment": {"hu": "Szórakoztató",    "en": "Entertainment (HU)", "de": "Unterhaltung (HU)",    "es": "Entretenimiento (HU)", "zh": "娱乐(匈)",     "fr": "Divertissement (HU)"},
    # ── Tab-groups: EN domestic ────────────────────────────────────
    "group.en.uk_domestic":   {"hu": "UK belföld",         "en": "UK domestic",         "de": "UK Inland",                 "es": "Reino Unido doméstico", "zh": "英国国内",       "fr": "Royaume-Uni intérieur"},
    "group.en.us_politics":   {"hu": "US politika",        "en": "US politics",         "de": "US-Politik",                "es": "Política de EE. UU.",   "zh": "美国政治",       "fr": "Politique américaine"},
    "group.en.anglo_business":{"hu": "Angolszász üzleti",  "en": "Anglosphere business","de": "Angelsächsische Wirtschaft","es": "Negocios anglosajones", "zh": "英语世界商业",   "fr": "Affaires anglosaxonnes"},
    # ── Tab-groups: DE domestic ────────────────────────────────────
    "group.de.domestic":      {"hu": "Németország (belföld)", "en": "Germany (domestic)", "de": "Deutschland", "es": "Alemania (doméstico)", "zh": "德国国内", "fr": "Allemagne (intérieur)"},
    # ── Tab-groups: ES domestic ────────────────────────────────────
    "group.es.spain":         {"hu": "Spanyolország (belföld)", "en": "Spain (domestic)", "de": "Spanien (Inland)", "es": "España", "zh": "西班牙国内", "fr": "Espagne (intérieur)"},
    "group.es.latam":         {"hu": "Latin-Amerika",          "en": "Latin America",     "de": "Lateinamerika",     "es": "Latinoamérica", "zh": "拉丁美洲", "fr": "Amérique latine"},
    # ── Tab-groups: ZH domestic ────────────────────────────────────
    "group.zh.cn_mainland":   {"hu": "Kína (kontinentális)", "en": "China (mainland)", "de": "China (Festland)", "es": "China (continental)", "zh": "中国大陆", "fr": "Chine (continentale)"},
    "group.zh.hk":            {"hu": "Hongkong",             "en": "Hong Kong",        "de": "Hongkong",         "es": "Hong Kong",           "zh": "香港",     "fr": "Hong Kong"},
    "group.zh.tw":            {"hu": "Tajvan",               "en": "Taiwan",           "de": "Taiwan",           "es": "Taiwán",              "zh": "台湾",     "fr": "Taïwan"},
    "group.zh.diaspora":      {"hu": "Kínai diaszpóra",      "en": "Chinese diaspora", "de": "Chinesische Diaspora","es": "Diáspora china",   "zh": "海外华人", "fr": "Diaspora chinoise"},
    "group.zh.weibo_pulse":   {"hu": "Weibo-puls",           "en": "Weibo pulse",      "de": "Weibo-Puls",       "es": "Pulso Weibo",         "zh": "微博热点", "fr": "Pouls Weibo"},
    # ── Tab-groups: FR domestic ────────────────────────────────────
    "group.fr.france":        {"hu": "Franciaország (belföld)", "en": "France (domestic)", "de": "Frankreich (Inland)", "es": "Francia (doméstico)", "zh": "法国国内", "fr": "France"},
    # ── Tab-groups: Universal topical ──────────────────────────────
    "group.world":            {"hu": "Világ",       "en": "World",          "de": "Welt",        "es": "Mundo",         "zh": "世界", "fr": "Monde"},
    "group.economy":          {"hu": "Gazdaság",    "en": "Economy",        "de": "Wirtschaft",  "es": "Economía",      "zh": "经济", "fr": "Économie"},
    "group.tech":             {"hu": "Tech",        "en": "Tech",           "de": "Tech",        "es": "Tecnología",    "zh": "科技", "fr": "Tech"},
    "group.ai":               {"hu": "AI",          "en": "AI",             "de": "KI",          "es": "IA",            "zh": "人工智能", "fr": "IA"},
    "group.science":          {"hu": "Tudomány",    "en": "Science",        "de": "Wissenschaft","es": "Ciencia",       "zh": "科学", "fr": "Science"},
    "group.climate":          {"hu": "Klíma",       "en": "Climate",        "de": "Klima",       "es": "Clima",         "zh": "气候", "fr": "Climat"},
    "group.health":           {"hu": "Egészségügy", "en": "Health",         "de": "Gesundheit",  "es": "Salud",         "zh": "健康", "fr": "Santé"},
    "group.analysis":         {"hu": "Elemzés",     "en": "Analysis",       "de": "Analyse",     "es": "Análisis",      "zh": "分析", "fr": "Analyse"},
    "group.conflict":         {"hu": "Konfliktus",  "en": "Conflict",       "de": "Konflikt",    "es": "Conflicto",     "zh": "冲突", "fr": "Conflit"},
    "group.osint":            {"hu": "OSINT",       "en": "OSINT",          "de": "OSINT",       "es": "OSINT",         "zh": "公开情报", "fr": "OSINT"},
    "group.entertainment":    {"hu": "Szórakoztató","en": "Entertainment",  "de": "Unterhaltung","es": "Entretenimiento","zh": "娱乐", "fr": "Divertissement"},
    "group.sport":            {"hu": "Sport",       "en": "Sport",          "de": "Sport",       "es": "Deportes",      "zh": "体育", "fr": "Sport"},
    "group.football":         {"hu": "Foci",        "en": "Football",       "de": "Fußball",     "es": "Fútbol",        "zh": "足球", "fr": "Football"},
    "group.tabloid":          {"hu": "Bulvár",      "en": "Tabloid",        "de": "Boulevard",   "es": "Prensa rosa",   "zh": "八卦", "fr": "Tabloïd"},
    "group.telegram":         {"hu": "Telegram",    "en": "Telegram",       "de": "Telegram",    "es": "Telegram",      "zh": "Telegram", "fr": "Telegram"},
    # ── Tab-groups: Universal geo perspectives ─────────────────────
    "group.geo.china":         {"hu": "Kína",          "en": "China",         "de": "China",        "es": "China",         "zh": "中国",     "fr": "Chine"},
    "group.geo.italy":         {"hu": "Olaszország",   "en": "Italy",         "de": "Italien",      "es": "Italia",        "zh": "意大利",   "fr": "Italie"},
    "group.geo.belarus":       {"hu": "Fehéroroszország","en": "Belarus",       "de": "Belarus",      "es": "Bielorrusia",   "zh": "白俄罗斯", "fr": "Biélorussie"},
    "group.geo.poland":        {"hu": "Lengyelország", "en": "Poland",        "de": "Polen",        "es": "Polonia",       "zh": "波兰",     "fr": "Pologne"},
    "group.geo.czechia":       {"hu": "Csehország",    "en": "Czechia",       "de": "Tschechien",   "es": "Chequia",       "zh": "捷克",     "fr": "Tchéquie"},
    "group.geo.russia":        {"hu": "Oroszország",   "en": "Russia",        "de": "Russland",     "es": "Rusia",         "zh": "俄罗斯",   "fr": "Russie"},
    "group.geo.us":            {"hu": "USA",           "en": "USA",           "de": "USA",          "es": "EE. UU.",       "zh": "美国",     "fr": "États-Unis"},
    "group.geo.uk":            {"hu": "UK",            "en": "UK",            "de": "UK",           "es": "Reino Unido",   "zh": "英国",     "fr": "Royaume-Uni"},
    "group.geo.germany":       {"hu": "Németország",   "en": "Germany",       "de": "Deutschland",  "es": "Alemania",      "zh": "德国",     "fr": "Allemagne"},
    "group.geo.france":        {"hu": "Franciaország", "en": "France",        "de": "Frankreich",   "es": "Francia",       "zh": "法国",     "fr": "France"},
    "group.geo.spain":         {"hu": "Spanyolország", "en": "Spain",         "de": "Spanien",      "es": "España",        "zh": "西班牙",   "fr": "Espagne"},
    "group.geo.south_america": {"hu": "Dél-Amerika",   "en": "South America", "de": "Südamerika",   "es": "Sudamérica",    "zh": "南美",     "fr": "Amérique du Sud"},
    "group.geo.japan":         {"hu": "Japán",         "en": "Japan",         "de": "Japan",        "es": "Japón",         "zh": "日本",     "fr": "Japon"},
    "group.geo.korea":         {"hu": "Korea",         "en": "Korea",         "de": "Korea",        "es": "Corea",         "zh": "韩国",     "fr": "Corée"},
    "group.geo.india":         {"hu": "India",         "en": "India",         "de": "Indien",       "es": "India",         "zh": "印度",     "fr": "Inde"},
    "group.geo.australia":     {"hu": "Ausztrália",    "en": "Australia",     "de": "Australien",   "es": "Australia",     "zh": "澳大利亚", "fr": "Australie"},
    "group.geo.v4":            {"hu": "V4 / Közép-Európa", "en": "V4 / Central Europe", "de": "V4 / Mitteleuropa", "es": "V4 / Europa Central", "zh": "V4 / 中欧", "fr": "V4 / Europe centrale"},
    "group.geo.israel":        {"hu": "Izrael",        "en": "Israel",        "de": "Israel",       "es": "Israel",        "zh": "以色列",   "fr": "Israël"},
    "group.geo.iran":          {"hu": "Irán",          "en": "Iran",          "de": "Iran",         "es": "Irán",          "zh": "伊朗",     "fr": "Iran"},
    "group.geo.ukraine":       {"hu": "Ukrajna",       "en": "Ukraine",       "de": "Ukraine",      "es": "Ucrania",       "zh": "乌克兰",   "fr": "Ukraine"},
    "group.geo.turkey":        {"hu": "Törökország",   "en": "Turkey",        "de": "Türkei",       "es": "Turquía",       "zh": "土耳其",   "fr": "Turquie"},
    "group.geo.arab_world":    {"hu": "Arab világ",    "en": "Arab world",    "de": "Arabische Welt","es": "Mundo árabe",  "zh": "阿拉伯世界","fr": "Monde arabe"},
    "group.geo.africa":        {"hu": "Afrika",        "en": "Africa",        "de": "Afrika",       "es": "África",        "zh": "非洲",     "fr": "Afrique"},
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
