"""Human-readable sphere labels — UX feedback 2026-06-11.

A teszter visszajelzése: a nyers szféra-kulcsok (global_preprint,
global_tabloid, hu_foreign_commentary…) a landing "Most pörgő témák"
blokkban és a trending-oldalakon laikus olvasónak értelmezhetetlenek.

Ez a modul az EGYETLEN kanonikus kulcs→emberi név térkép. HU és EN
címkék minden (93) szférához; más UI-nyelvek az angolra esnek vissza.
Ismeretlen kulcsra olvasható prettify a fallback ("global_foo" → "foo").

Usage:
    from echolot_sphere_labels import sphere_label
    sphere_label("global_tabloid", "hu")  # → "Bulvár (globális)"
"""
from __future__ import annotations

# (hu, en) párok — a sources*.yaml-ban élő mind a 93 szférára.
_LABELS: dict[str, tuple[str, str]] = {
    "bsky_journalism":        ("Bluesky-újságírók", "Bluesky journalism"),
    "cn_diaspora_analysis":   ("Kínai diaszpóra-elemzés", "Chinese diaspora analysis"),
    "cn_hk":                  ("Hongkongi sajtó", "Hong Kong press"),
    "cn_state":               ("Kínai állami média", "Chinese state media"),
    "cn_state_aligned":       ("Kínai államközeli média", "China state-aligned media"),
    "cn_tw":                  ("Tajvani sajtó", "Taiwanese press"),
    "cn_weibo_pulse":         ("Weibo-pulzus", "Weibo pulse"),
    "global_ai":              ("AI-hírek (globális)", "AI news (global)"),
    "global_americansports":  ("Amerikai sportok", "US sports"),
    "global_analysis":        ("Elemző sajtó (globális)", "Analysis press (global)"),
    "global_anchor":          ("Vezető világlapok", "Global anchor outlets"),
    "global_basketball":      ("Kosárlabda", "Basketball"),
    "global_celebrity":       ("Celebhírek", "Celebrity news"),
    "global_climate":         ("Klíma", "Climate"),
    "global_conflict":        ("Háborús hírek", "Conflict news"),
    "global_critical_tech":   ("Tech-kritika", "Tech criticism"),
    "global_economy":         ("Gazdasági világsajtó", "Global economy press"),
    "global_entertainment":   ("Szórakoztatóipar", "Entertainment"),
    "global_football":        ("Futball", "Football"),
    "global_health":          ("Egészségügy", "Health"),
    "global_investigative":   ("Oknyomozó újságírás", "Investigative journalism"),
    "global_motorsport":      ("Motorsport / F1", "Motorsport / F1"),
    "global_osint":           ("OSINT-elemzők", "OSINT analysts"),
    "global_preprint":        ("Tudományos preprintek", "Scientific preprints"),
    "global_press":           ("Nemzetközi sajtó", "International press"),
    "global_science":         ("Tudomány", "Science"),
    "global_sport":           ("Sport (globális)", "Sport (global)"),
    "global_tabloid":         ("Bulvár (globális)", "Tabloid (global)"),
    "global_tech":            ("Tech (globális)", "Tech (global)"),
    "global_tennis_sport":    ("Tenisz", "Tennis"),
    "hu_cars":                ("Magyar autós lapok", "Hungarian car press"),
    "hu_economy":             ("Magyar gazdasági sajtó", "Hungarian economy press"),
    "hu_entertainment":       ("Magyar szórakoztató", "Hungarian entertainment"),
    "hu_foreign_commentary":  ("Magyar külpol. kommentár", "Hungarian foreign-affairs commentary"),
    "hu_lifestyle":           ("Magyar életmód", "Hungarian lifestyle"),
    "hu_premium":             ("Magyar minőségi sajtó", "Hungarian premium press"),
    "hu_press":               ("Magyar sajtó", "Hungarian press"),
    "hu_sport":               ("Magyar sport", "Hungarian sport"),
    "hu_tech":                ("Magyar tech", "Hungarian tech"),
    "iran_opposition":        ("Iráni ellenzék", "Iranian opposition"),
    "iran_regime":            ("Iráni rezsimmédia", "Iranian regime media"),
    "israel_press_center":    ("Izraeli középsajtó", "Israeli centrist press"),
    "israel_press_left":      ("Izraeli baloldali sajtó", "Israeli left-wing press"),
    "israel_press_right":     ("Izraeli jobboldali sajtó", "Israeli right-wing press"),
    "jp_press_english":       ("Japán sajtó (angol)", "Japanese press (English)"),
    "jp_press_native":        ("Japán sajtó", "Japanese press"),
    "kr_press_english":       ("Koreai sajtó (angol)", "Korean press (English)"),
    "mastodon_tech":          ("Mastodon-tech", "Mastodon tech"),
    "reddit_finance":         ("Reddit: pénzügy", "Reddit finance"),
    "reddit_geopol":          ("Reddit: geopolitika", "Reddit geopolitics"),
    "reddit_tech":            ("Reddit: tech", "Reddit tech"),
    "reddit_ua_war":          ("Reddit: ukrán háború", "Reddit Ukraine war"),
    "regional_african":       ("Afrikai sajtó", "African press"),
    "regional_arabic":        ("Arab sajtó", "Arabic press"),
    "regional_australian":    ("Ausztrál sajtó", "Australian press"),
    "regional_belarusian":    ("Belarusz sajtó", "Belarusian press"),
    "regional_chinese":       ("Kínai sajtó (összes)", "Chinese press (all)"),
    "regional_czech":         ("Cseh sajtó", "Czech press"),
    "regional_french":        ("Francia sajtó", "French press"),
    "regional_german":        ("Német sajtó", "German press"),
    "regional_indian":        ("Indiai sajtó", "Indian press"),
    "regional_iranian":       ("Iráni sajtó (összes)", "Iranian press (all)"),
    "regional_israeli":       ("Izraeli sajtó (összes)", "Israeli press (all)"),
    "regional_italian":       ("Olasz sajtó", "Italian press"),
    "regional_japanese":      ("Japán sajtó (összes)", "Japanese press (all)"),
    "regional_korean":        ("Koreai sajtó (összes)", "Korean press (all)"),
    "regional_polish":        ("Lengyel sajtó", "Polish press"),
    "regional_russian":       ("Orosz sajtó (összes)", "Russian press (all)"),
    "regional_south_american": ("Dél-amerikai sajtó", "South American press"),
    "regional_spanish":       ("Spanyol sajtó", "Spanish press"),
    "regional_turkish":       ("Török sajtó", "Turkish press"),
    "regional_uk":            ("Brit sajtó", "UK press"),
    "regional_ukrainian":     ("Ukrán sajtó", "Ukrainian press"),
    "regional_us":            ("Amerikai sajtó", "US press"),
    "regional_v4":            ("Közép-európai (V4) sajtó", "Central European (V4) press"),
    "ru_milblog_pro":         ("Orosz háborúpárti milblogok", "Russian pro-war milblogs"),
    "ru_opposition":          ("Orosz ellenzék / emigráció", "Russian opposition / exile"),
    "ru_state_media":         ("Orosz állami média", "Russian state media"),
    "ua_front_osint":         ("Ukrán front-OSINT", "Ukraine front OSINT"),
    "us_liberal_press":       ("US liberális sajtó", "US liberal press"),
    "us_liberal_substack":    ("US liberális Substackek", "US liberal substacks"),
    "us_maga_blog":           ("US MAGA-blogok", "US MAGA blogs"),
    "us_maga_substack":       ("US MAGA-Substackek", "US MAGA substacks"),
    "x_central_banks":        ("X: jegybankok", "X: central banks"),
    "x_finance_traders":      ("X: pénzügyi traderek", "X: finance traders"),
    "x_geopol_analysts":      ("X: geopol. elemzők", "X: geopolitics analysts"),
    "x_milblog_ru":           ("X: orosz milblogok", "X: Russian milblogs"),
    "x_milblog_ua":           ("X: ukrán milblogok", "X: Ukrainian milblogs"),
    "x_milblog_west":         ("X: nyugati milblogok", "X: Western milblogs"),
    "x_us_politics":          ("X: US politika", "X: US politics"),
    "yt_finance":             ("YouTube: pénzügy", "YouTube finance"),
    "yt_geopol_analysts":     ("YouTube: geopolitika", "YouTube geopolitics"),
    "yt_tech_ai":             ("YouTube: tech / AI", "YouTube tech / AI"),
}


def _prettify(key: str) -> str:
    """Fallback ismeretlen kulcsra: 'global_foo_bar' → 'foo bar'."""
    k = key.strip().lower()
    for prefix in ("global_", "regional_"):
        if k.startswith(prefix):
            k = k[len(prefix):]
            break
    return k.replace("_", " ")


_EXTRA_LANGS = frozenset({"de", "es", "zh", "fr", "pl", "ru", "uk", "it"})


def sphere_label(sphere: str | None, lang: str = "hu") -> str:
    """Emberi név egy szféra-kulcshoz mind a 9 UI-nyelven (hu/en + a 8 extra).
    Ismeretlen nyelv vagy hiányzó fordítás → EN, ismeretlen kulcs → prettify."""
    if not sphere:
        return "?"
    key = sphere.strip().lower().replace("-", "_")
    pair = _LABELS.get(key)
    if pair is None:
        return _prettify(key)
    if lang == "hu":
        return pair[0]
    if lang in _EXTRA_LANGS:
        lbl = _LABELS_EXTRA.get(key, {}).get(lang)
        if lbl:
            return lbl
    return pair[1]  # en (és minden más nyelv) fallback


# ─── 8 további UI-nyelv (de/es/zh/fr/pl/ru/uk/it) — gpt-4o-mini, 2026-06-19 ───
_LABELS_EXTRA: dict[str, dict[str, str]] = {
    "bsky_journalism": {"de": "Bluesky-Journalismus", "es": "Periodismo de Bluesky", "zh": "Bluesky 新闻", "fr": "Journalisme Bluesky", "pl": "Dziennikarstwo Bluesky", "ru": "Журналистика Bluesky", "uk": "Журналістика Bluesky", "it": "Giornalismo Bluesky"},
    "cn_diaspora_analysis": {"de": "Analyse der chinesischen Diaspora", "es": "Análisis de la diáspora china", "zh": "华人侨民分析", "fr": "Analyse de la diaspora chinoise", "pl": "Analiza chińskiej diaspory", "ru": "Анализ китайской диаспоры", "uk": "Аналіз китайської діаспори", "it": "Analisi della diaspora cinese"},
    "cn_hk": {"de": "Hongkonger Presse", "es": "Prensa de Hong Kong", "zh": "香港媒体", "fr": "Presse de Hong Kong", "pl": "Prasa z Hongkongu", "ru": "Пресса Гонконга", "uk": "Преса Гонконгу", "it": "Stampa di Hong Kong"},
    "cn_state": {"de": "Chinesische Staatsmedien", "es": "Medios estatales chinos", "zh": "中国国家媒体", "fr": "Médias d'État chinois", "pl": "Chińskie media państwowe", "ru": "Китайские государственные СМИ", "uk": "Китайські державні ЗМІ", "it": "Media statali cinesi"},
    "cn_state_aligned": {"de": "China-staatlich ausgerichtete Medien", "es": "Medios alineados con el estado chino", "zh": "中国国家对齐媒体", "fr": "Médias alignés sur l'État chinois", "pl": "Media zbieżne z państwem chińskim", "ru": "СМИ, согласованные с государством Китая", "uk": "Медіа, що узгоджуються з державою Китаю", "it": "Media allineati allo stato cinese"},
    "cn_tw": {"de": "Taiwanesische Presse", "es": "Prensa taiwanesa", "zh": "台湾媒体", "fr": "Presse taïwanaise", "pl": "Prasa tajwańska", "ru": "Тайваньская пресса", "uk": "Тайваньська преса", "it": "Stampa taiwanese"},
    "cn_weibo_pulse": {"de": "Weibo-Puls", "es": "Pulso de Weibo", "zh": "微博脉搏", "fr": "Pouls Weibo", "pl": "Puls Weibo", "ru": "Пульс Weibo", "uk": "Пульс Weibo", "it": "Polso di Weibo"},
    "global_ai": {"de": "KI-Nachrichten (global)", "es": "Noticias de IA (global)", "zh": "人工智能新闻（全球）", "fr": "Actualités IA (mondial)", "pl": "Wiadomości AI (globalne)", "ru": "Новости ИИ (глобальные)", "uk": "Новини ШІ (глобальні)", "it": "Notizie AI (globale)"},
    "global_americansports": {"de": "US-Sport", "es": "Deportes de EE. UU.", "zh": "美国体育", "fr": "Sports américains", "pl": "Sport w USA", "ru": "Спорт в США", "uk": "Спорт США", "it": "Sport americani"},
    "global_analysis": {"de": "Analyse-Presse (global)", "es": "Prensa de análisis (global)", "zh": "分析媒体（全球）", "fr": "Presse d'analyse (mondial)", "pl": "Prasa analityczna (globalna)", "ru": "Аналитическая пресса (глобальная)", "uk": "Аналіз преса (глобальна)", "it": "Stampa di analisi (globale)"},
    "global_anchor": {"de": "Globale Anker-Medien", "es": "Medios ancla globales", "zh": "全球锚定媒体", "fr": "Médias d'ancrage mondiaux", "pl": "Globalne media kotwiczne", "ru": "Глобальные якорные СМИ", "uk": "Глобальні якорні ЗМІ", "it": "Media ancorati globali"},
    "global_basketball": {"de": "Basketball", "es": "Baloncesto", "zh": "篮球", "fr": "Basket-ball", "pl": "Koszykówka", "ru": "Баскетбол", "uk": "Баскетбол", "it": "Pallacanestro"},
    "global_celebrity": {"de": "Promi-Nachrichten", "es": "Noticias de celebridades", "zh": "名人新闻", "fr": "Actualités des célébrités", "pl": "Wiadomości o celebrytach", "ru": "Новости знаменитостей", "uk": "Новини знаменитостей", "it": "Notizie sulle celebrità"},
    "global_climate": {"de": "Klima", "es": "Clima", "zh": "气候", "fr": "Climat", "pl": "Klimat", "ru": "Климат", "uk": "Клімат", "it": "Clima"},
    "global_conflict": {"de": "Konfliktnachrichten", "es": "Noticias de conflicto", "zh": "冲突新闻", "fr": "Actualités sur les conflits", "pl": "Wiadomości o konfliktach", "ru": "Новости конфликтов", "uk": "Новини конфліктів", "it": "Notizie sui conflitti"},
    "global_critical_tech": {"de": "Technikkritik", "es": "Crítica tecnológica", "zh": "技术批评", "fr": "Critique technologique", "pl": "Krytyka technologii", "ru": "Критика технологий", "uk": "Критика технологій", "it": "Critica tecnologica"},
    "global_economy": {"de": "Globale Wirtschaftspresse", "es": "Prensa de economía global", "zh": "全球经济新闻", "fr": "Presse économique mondiale", "pl": "Prasa gospodarcza (globalna)", "ru": "Глобальная экономическая пресса", "uk": "Глобальна економічна преса", "it": "Stampa economica globale"},
    "global_entertainment": {"de": "Unterhaltung", "es": "Entretenimiento", "zh": "娱乐", "fr": "Divertissement", "pl": "Rozrywka", "ru": "Развлечения", "uk": "Розваги", "it": "Intrattenimento"},
    "global_football": {"de": "Fußball", "es": "Fútbol", "zh": "足球", "fr": "Football", "pl": "Piłka nożna", "ru": "Футбол", "uk": "Футбол", "it": "Calcio"},
    "global_health": {"de": "Gesundheit", "es": "Salud", "zh": "健康", "fr": "Santé", "pl": "Zdrowie", "ru": "Здоровье", "uk": "Здоров'я", "it": "Salute"},
    "global_investigative": {"de": "Investigativer Journalismus", "es": "Periodismo de investigación", "zh": "调查性新闻", "fr": "Journalisme d'investigation", "pl": "Dziennikarstwo śledcze", "ru": "Расследовательская журналистика", "uk": "Розслідувальна журналістика", "it": "Giornalismo investigativo"},
    "global_motorsport": {"de": "Motorsport / F1", "es": "Deportes de motor / F1", "zh": "赛车 / F1", "fr": "Sport automobile / F1", "pl": "Motorsport / F1", "ru": "Моторный спорт / F1", "uk": "Мотоспорт / F1", "it": "Motorsport / F1"},
    "global_osint": {"de": "OSINT-Analysten", "es": "Analistas de OSINT", "zh": "OSINT 分析师", "fr": "Analystes OSINT", "pl": "Analitycy OSINT", "ru": "Аналитики OSINT", "uk": "Аналітики OSINT", "it": "Analisti OSINT"},
    "global_preprint": {"de": "Wissenschaftliche Preprints", "es": "Preprints científicos", "zh": "科学预印本", "fr": "Prépublications scientifiques", "pl": "Preprinty naukowe", "ru": "Научные препринты", "uk": "Наукові препринти", "it": "Preprint scientifici"},
    "global_press": {"de": "Internationale Presse", "es": "Prensa internacional", "zh": "国际新闻", "fr": "Presse internationale", "pl": "Prasa międzynarodowa", "ru": "Международная пресса", "uk": "Міжнародна преса", "it": "Stampa internazionale"},
    "global_science": {"de": "Wissenschaft", "es": "Ciencia", "zh": "科学", "fr": "Science", "pl": "Nauka", "ru": "Наука", "uk": "Наука", "it": "Scienza"},
    "global_sport": {"de": "Sport (global)", "es": "Deportes (global)", "zh": "体育 (全球)", "fr": "Sport (global)", "pl": "Sport (globalny)", "ru": "Спорт (глобальный)", "uk": "Спорт (глобальний)", "it": "Sport (globale)"},
    "global_tabloid": {"de": "Boulevardpresse (global)", "es": "Prensa sensacionalista (global)", "zh": "小报 (全球)", "fr": "Tabloïd (global)", "pl": "Tabloidy (globalne)", "ru": "Таблоид (глобальный)", "uk": "Таблоїд (глобальний)", "it": "Tabloid (globale)"},
    "global_tech": {"de": "Technologie (global)", "es": "Tecnología (global)", "zh": "科技 (全球)", "fr": "Technologie (globale)", "pl": "Technologia (globalna)", "ru": "Технологии (глобальные)", "uk": "Технології (глобальні)", "it": "Tecnologia (globale)"},
    "global_tennis_sport": {"de": "Tennis", "es": "Tenis", "zh": "网球", "fr": "Tennis", "pl": "Tenis", "ru": "Теннис", "uk": "Теніс", "it": "Tennis"},
    "hu_cars": {"de": "Ungarische Auto-Presse", "es": "Prensa de coches húngara", "zh": "匈牙利汽车新闻", "fr": "Presse automobile hongroise", "pl": "Węgierska prasa motoryzacyjna", "ru": "Венгерская автомобильная пресса", "uk": "Угорська автомобільна преса", "it": "Stampa automobilistica ungherese"},
    "hu_economy": {"de": "Ungarische Wirtschaftspresse", "es": "Prensa de economía húngara", "zh": "匈牙利经济新闻", "fr": "Presse économique hongroise", "pl": "Węgierska prasa gospodarcza", "ru": "Венгерская экономическая пресса", "uk": "Угорська економічна преса", "it": "Stampa economica ungherese"},
    "hu_entertainment": {"de": "Ungarische Unterhaltung", "es": "Entretenimiento húngaro", "zh": "匈牙利娱乐", "fr": "Divertissement hongrois", "pl": "Węgierska rozrywka", "ru": "Венгерские развлечения", "uk": "Угорське розваги", "it": "Intrattenimento ungherese"},
    "hu_foreign_commentary": {"de": "Ungarische Außenpolitik-Kommentare", "es": "Comentario sobre asuntos exteriores húngaro", "zh": "匈牙利外交评论", "fr": "Commentaire sur les affaires étrangères hongrois", "pl": "Węgierski komentarz zagraniczny", "ru": "Венгерские комментарии по внешним делам", "uk": "Угорський коментар з питань зовнішньої політики", "it": "Commento sulla politica estera ungherese"},
    "hu_lifestyle": {"de": "Ungarischer Lebensstil", "es": "Estilo de vida húngaro", "zh": "匈牙利生活方式", "fr": "Style de vie hongrois", "pl": "Węgierski styl życia", "ru": "Венгерский образ жизни", "uk": "Угорський стиль життя", "it": "Stile di vita ungherese"},
    "hu_premium": {"de": "Ungarische Premium-Presse", "es": "Prensa premium húngara", "zh": "匈牙利优质媒体", "fr": "Presse premium hongroise", "pl": "Węgierska prasa premium", "ru": "Венгерская премиум пресса", "uk": "Угорська преміум преса", "it": "Stampa premium ungherese"},
    "hu_press": {"de": "Ungarische Presse", "es": "Prensa húngara", "zh": "匈牙利媒体", "fr": "Presse hongroise", "pl": "Węgierska prasa", "ru": "Венгерская пресса", "uk": "Угорська преса", "it": "Stampa ungherese"},
    "hu_sport": {"de": "Ungarischer Sport", "es": "Deporte húngaro", "zh": "匈牙利体育", "fr": "Sport hongrois", "pl": "Węgierski sport", "ru": "Венгерский спорт", "uk": "Угорський спорт", "it": "Sport ungherese"},
    "hu_tech": {"de": "Ungarische Technik", "es": "Tecnología húngara", "zh": "匈牙利科技", "fr": "Technologie hongroise", "pl": "Węgierska technologia", "ru": "Венгерская техника", "uk": "Угорська техніка", "it": "Tecnologia ungherese"},
    "iran_opposition": {"de": "Iranische Opposition", "es": "Oposición iraní", "zh": "伊朗反对派", "fr": "Opposition iranienne", "pl": "Irańska opozycja", "ru": "Иранская оппозиция", "uk": "Іранська опозиція", "it": "Opposizione iraniana"},
    "iran_regime": {"de": "Iranische Regime-Medien", "es": "Medios del régimen iraní", "zh": "伊朗政权媒体", "fr": "Médias du régime iranien", "pl": "Media reżimu irańskiego", "ru": "СМИ иранского режима", "uk": "Медіа іранського режиму", "it": "Media del regime iraniano"},
    "israel_press_center": {"de": "Israels zentristische Presse", "es": "Prensa centrista israelí", "zh": "以色列中间派媒体", "fr": "Presse centriste israélienne", "pl": "Izraelska prasa centrowa", "ru": "Израильская центристская пресса", "uk": "Ізраїльська центристська преса", "it": "Stampa centrista israeliana"},
    "israel_press_left": {"de": "Israels linke Presse", "es": "Prensa de izquierda israelí", "zh": "以色列左翼媒体", "fr": "Presse de gauche israélienne", "pl": "Izraelska prasa lewicowa", "ru": "Израильская левая пресса", "uk": "Ізраїльська ліва преса", "it": "Stampa di sinistra israeliana"},
    "israel_press_right": {"de": "Israels rechte Presse", "es": "Prensa de derecha israelí", "zh": "以色列右翼媒体", "fr": "Presse de droite israélienne", "pl": "Izraelska prasa prawicowa", "ru": "Израильская правая пресса", "uk": "Ізраїльська права преса", "it": "Stampa di destra israeliana"},
    "jp_press_english": {"de": "Japanische Presse (Englisch)", "es": "Prensa japonesa (inglés)", "zh": "日本媒体（英语）", "fr": "Presse japonaise (anglais)", "pl": "Japońska prasa (angielski)", "ru": "Японская пресса (английский)", "uk": "Японська преса (англійською)", "it": "Stampa giapponese (inglese)"},
    "jp_press_native": {"de": "Japanische Presse", "es": "Prensa japonesa", "zh": "日本媒体", "fr": "Presse japonaise", "pl": "Japońska prasa", "ru": "Японская пресса", "uk": "Японська преса", "it": "Stampa giapponese"},
    "kr_press_english": {"de": "Koreanische Presse (Englisch)", "es": "Prensa coreana (inglés)", "zh": "韩国媒体（英语）", "fr": "Presse coréenne (anglais)", "pl": "Koreańska prasa (angielski)", "ru": "Корейская пресса (английский)", "uk": "Корейська преса (англійською)", "it": "Stampa coreana (inglese)"},
    "mastodon_tech": {"de": "Mastodon-Technologie", "es": "Tecnología de Mastodon", "zh": "Mastodon科技", "fr": "Technologie Mastodon", "pl": "Technologia Mastodon", "ru": "Технология Mastodon", "uk": "Технології Mastodon", "it": "Tecnologia di Mastodon"},
    "reddit_finance": {"de": "Reddit Finanzen", "es": "Reddit finanzas", "zh": "Reddit 财经", "fr": "Reddit finance", "pl": "Reddit finanse", "ru": "Reddit финансы", "uk": "Reddit фінанси", "it": "Reddit finanza"},
    "reddit_geopol": {"de": "Reddit Geopolitik", "es": "Reddit geopolítica", "zh": "Reddit 地缘政治", "fr": "Reddit géopolitique", "pl": "Reddit geopolityka", "ru": "Reddit геополитика", "uk": "Reddit геополітика", "it": "Reddit geopolitica"},
    "reddit_tech": {"de": "Reddit Technik", "es": "Reddit tecnología", "zh": "Reddit 科技", "fr": "Reddit technologie", "pl": "Reddit technologia", "ru": "Reddit технологии", "uk": "Reddit технології", "it": "Reddit tecnologia"},
    "reddit_ua_war": {"de": "Reddit Ukrainekrieg", "es": "Reddit guerra de Ucrania", "zh": "Reddit 乌克兰战争", "fr": "Reddit guerre d'Ukraine", "pl": "Reddit wojna na Ukrainie", "ru": "Reddit война в Украине", "uk": "Reddit війна в Україні", "it": "Reddit guerra in Ucraina"},
    "regional_african": {"de": "Afrikanische Presse", "es": "Prensa africana", "zh": "非洲媒体", "fr": "Presse africaine", "pl": "Prasa afrykańska", "ru": "Африканская пресса", "uk": "Африканська преса", "it": "Stampa africana"},
    "regional_arabic": {"de": "Arabische Presse", "es": "Prensa árabe", "zh": "阿拉伯媒体", "fr": "Presse arabe", "pl": "Prasa arabska", "ru": "Арабская пресса", "uk": "Арабська преса", "it": "Stampa araba"},
    "regional_australian": {"de": "Australische Presse", "es": "Prensa australiana", "zh": "澳大利亚媒体", "fr": "Presse australienne", "pl": "Prasa australijska", "ru": "Австралийская пресса", "uk": "Австралійська преса", "it": "Stampa australiana"},
    "regional_belarusian": {"de": "Belarussische Presse", "es": "Prensa bielorrusa", "zh": "白俄罗斯媒体", "fr": "Presse biélorusse", "pl": "Prasa białoruska", "ru": "Белорусская пресса", "uk": "Білоруська преса", "it": "Stampa bielorussa"},
    "regional_chinese": {"de": "Chinesische Presse (alle)", "es": "Prensa china (todas)", "zh": "中国媒体（全部）", "fr": "Presse chinoise (toutes)", "pl": "Prasa chińska (wszystkie)", "ru": "Китайская пресса (все)", "uk": "Китайська преса (всі)", "it": "Stampa cinese (tutte)"},
    "regional_czech": {"de": "Tschechische Presse", "es": "Prensa checa", "zh": "捷克媒体", "fr": "Presse tchèque", "pl": "Prasa czeska", "ru": "Чешская пресса", "uk": "Чеська преса", "it": "Stampa ceca"},
    "regional_french": {"de": "Französische Presse", "es": "Prensa francesa", "zh": "法国媒体", "fr": "Presse française", "pl": "Prasa francuska", "ru": "Французская пресса", "uk": "Французька преса", "it": "Stampa francese"},
    "regional_german": {"de": "Deutsche Presse", "es": "Prensa alemana", "zh": "德国媒体", "fr": "Presse allemande", "pl": "Prasa niemiecka", "ru": "Немецкая пресса", "uk": "Німецька преса", "it": "Stampa tedesca"},
    "regional_indian": {"de": "Indische Presse", "es": "Prensa india", "zh": "印度媒体", "fr": "Presse indienne", "pl": "Prasa indyjska", "ru": "Индийская пресса", "uk": "Індійська преса", "it": "Stampa indiana"},
    "regional_iranian": {"de": "Iranische Presse (alle)", "es": "Prensa iraní (todas)", "zh": "伊朗媒体（全部）", "fr": "Presse iranienne (toutes)", "pl": "Prasa irańska (wszystkie)", "ru": "Иранская пресса (все)", "uk": "Іранська преса (всі)", "it": "Stampa iraniana (tutte)"},
    "regional_israeli": {"de": "Israelische Presse (alle)", "es": "Prensa israelí (todas)", "zh": "以色列媒体（全部）", "fr": "Presse israélienne (toutes)", "pl": "Prasa izraelska (wszystkie)", "ru": "Израильская пресса (все)", "uk": "Ізраїльська преса (всі)", "it": "Stampa israeliana (tutte)"},
    "regional_italian": {"de": "Italienische Presse", "es": "Prensa italiana", "zh": "意大利媒体", "fr": "Presse italienne", "pl": "Prasa włoska", "ru": "Итальянская пресса", "uk": "Італійська преса", "it": "Stampa italiana"},
    "regional_japanese": {"de": "Japanische Presse (alle)", "es": "Prensa japonesa (todas)", "zh": "日本媒体（全部）", "fr": "Presse japonaise (toute)", "pl": "Japońska prasa (wszystkie)", "ru": "Японская пресса (все)", "uk": "Японська преса (всі)", "it": "Stampa giapponese (tutte)"},
    "regional_korean": {"de": "Koreanische Presse (alle)", "es": "Prensa coreana (todas)", "zh": "韩国媒体（全部）", "fr": "Presse coréenne (toute)", "pl": "Koreańska prasa (wszystkie)", "ru": "Корейская пресса (все)", "uk": "Корейська преса (всі)", "it": "Stampa coreana (tutte)"},
    "regional_polish": {"de": "Polnische Presse", "es": "Prensa polaca", "zh": "波兰媒体", "fr": "Presse polonaise", "pl": "Polska prasa", "ru": "Польская пресса", "uk": "Польська преса", "it": "Stampa polacca"},
    "regional_russian": {"de": "Russische Presse (alle)", "es": "Prensa rusa (todas)", "zh": "俄罗斯媒体（全部）", "fr": "Presse russe (toute)", "pl": "Rosyjska prasa (wszystkie)", "ru": "Российская пресса (все)", "uk": "Російська преса (всі)", "it": "Stampa russa (tutte)"},
    "regional_south_american": {"de": "Südamerikanische Presse", "es": "Prensa sudamericana", "zh": "南美媒体", "fr": "Presse sud-américaine", "pl": "Południowoamerykańska prasa", "ru": "Южноамериканская пресса", "uk": "Південноамериканська преса", "it": "Stampa sudamericana"},
    "regional_spanish": {"de": "Spanische Presse", "es": "Prensa española", "zh": "西班牙媒体", "fr": "Presse espagnole", "pl": "Hiszpańska prasa", "ru": "Испанская пресса", "uk": "Іспанська преса", "it": "Stampa spagnola"},
    "regional_turkish": {"de": "Türkische Presse", "es": "Prensa turca", "zh": "土耳其媒体", "fr": "Presse turque", "pl": "Turecka prasa", "ru": "Турецкая пресса", "uk": "Турецька преса", "it": "Stampa turca"},
    "regional_uk": {"de": "UK-Presse", "es": "Prensa del Reino Unido", "zh": "英国媒体", "fr": "Presse britannique", "pl": "Prasa brytyjska", "ru": "Британская пресса", "uk": "Британська преса", "it": "Stampa del Regno Unito"},
    "regional_ukrainian": {"de": "Ukrainische Presse", "es": "Prensa ucraniana", "zh": "乌克兰媒体", "fr": "Presse ukrainienne", "pl": "Ukraińska prasa", "ru": "Украинская пресса", "uk": "Українська преса", "it": "Stampa ucraina"},
    "regional_us": {"de": "US-Presse", "es": "Prensa de EE. UU.", "zh": "美国媒体", "fr": "Presse américaine", "pl": "Prasa amerykańska", "ru": "Американская пресса", "uk": "Американська преса", "it": "Stampa americana"},
    "regional_v4": {"de": "Zentraleuropäische (V4) Presse", "es": "Prensa de Europa Central (V4)", "zh": "中欧（V4）媒体", "fr": "Presse d'Europe centrale (V4)", "pl": "Prasa Europy Środkowej (V4)", "ru": "Центральноевропейская пресса (V4)", "uk": "Центральноєвропейська преса (V4)", "it": "Stampa dell'Europa centrale (V4)"},
    "ru_milblog_pro": {"de": "Russische pro-Kriegs-Milblogs", "es": "Milblogs pro-guerra rusos", "zh": "俄罗斯亲战军事博客", "fr": "Milblogs pro-guerre russes", "pl": "Rosyjskie prowojenne milblogi", "ru": "Российские про-военные милблоги", "uk": "Російські про-військові мілблоги", "it": "Milblog pro-guerra russi"},
    "ru_opposition": {"de": "Russische Opposition / Exil", "es": "Oposición rusa / exilio", "zh": "俄罗斯反对派 / 流亡", "fr": "Opposition russe / exil", "pl": "Rosyjska opozycja / eksil", "ru": "Российская оппозиция / изгнание", "uk": "Російська опозиція / вигнання", "it": "Opposizione russa / esilio"},
    "ru_state_media": {"de": "Russische Staatsmedien", "es": "Medios estatales rusos", "zh": "俄罗斯国家媒体", "fr": "Médias d'État russes", "pl": "Rosyjskie media państwowe", "ru": "Российские государственные СМИ", "uk": "Російські державні ЗМІ", "it": "Media statali russi"},
    "ua_front_osint": {"de": "Ukrainische Front-OSINT", "es": "OSINT del frente ucraniano", "zh": "乌克兰前线OSINT", "fr": "OSINT du front ukrainien", "pl": "OSINT frontu ukraińskiego", "ru": "Украинский фронт OSINT", "uk": "Український фронт OSINT", "it": "OSINT del fronte ucraino"},
    "us_liberal_press": {"de": "US-liberale Presse", "es": "Prensa liberal de EE. UU.", "zh": "美国自由派媒体", "fr": "Presse libérale américaine", "pl": "Amerykańska prasa liberalna", "ru": "Американская либеральная пресса", "uk": "Американська ліберальна преса", "it": "Stampa liberale americana"},
    "us_liberal_substack": {"de": "US liberale Substack", "es": "Substacks liberales de EE. UU.", "zh": "美国自由派Substack", "fr": "Substacks libéraux des États-Unis", "pl": "Amerykańskie liberalne substacks", "ru": "Либеральные Substack в США", "uk": "Ліберальні Substack США", "it": "Substack liberali degli Stati Uniti"},
    "us_maga_blog": {"de": "US MAGA-Blogs", "es": "Blogs MAGA de EE. UU.", "zh": "美国MAGA博客", "fr": "Blogs MAGA des États-Unis", "pl": "Amerykańskie blogi MAGA", "ru": "Блоги MAGA в США", "uk": "Блоги MAGA США", "it": "Blog MAGA degli Stati Uniti"},
    "us_maga_substack": {"de": "US MAGA Substack", "es": "Substack MAGA de EE. UU.", "zh": "美国MAGA Substack", "fr": "Substack MAGA des États-Unis", "pl": "Amerykański MAGA Substack", "ru": "MAGA Substack в США", "uk": "MAGA Substack США", "it": "Substack MAGA degli Stati Uniti"},
    "x_central_banks": {"de": "X: Zentralbanken", "es": "X: bancos centrales", "zh": "X: 中央银行", "fr": "X : banques centrales", "pl": "X: banki centralne", "ru": "X: центральные банки", "uk": "X: центральні банки", "it": "X: banche centrali"},
    "x_finance_traders": {"de": "X: Finanzhändler", "es": "X: traders financieros", "zh": "X: 金融交易员", "fr": "X : traders financiers", "pl": "X: traderzy finansowi", "ru": "X: финансовые трейдеры", "uk": "X: фінансові трейдери", "it": "X: trader finanziari"},
    "x_geopol_analysts": {"de": "X: Geopolitik-Analysten", "es": "X: analistas de geopolítica", "zh": "X: 地缘政治分析师", "fr": "X : analystes en géopolitique", "pl": "X: analitycy geopolityczni", "ru": "X: аналитики геополитики", "uk": "X: аналітики геополітики", "it": "X: analisti geopolitici"},
    "x_milblog_ru": {"de": "X: Russische Milblogs", "es": "X: milblogs rusos", "zh": "X: 俄罗斯军事博客", "fr": "X : milblogs russes", "pl": "X: rosyjskie milblogi", "ru": "X: российские милблоги", "uk": "X: російські мілблоги", "it": "X: milblog russi"},
    "x_milblog_ua": {"de": "X: Ukrainische Milblogs", "es": "X: milblogs ucranianos", "zh": "X: 乌克兰军事博客", "fr": "X : milblogs ukrainiens", "pl": "X: ukraińskie milblogi", "ru": "X: украинские милблоги", "uk": "X: українські мілблоги", "it": "X: milblog ucraini"},
    "x_milblog_west": {"de": "X: Westliche Milblogs", "es": "X: milblogs occidentales", "zh": "X: 西方军事博客", "fr": "X : milblogs occidentaux", "pl": "X: zachodnie milblogi", "ru": "X: западные милблоги", "uk": "X: західні мілблоги", "it": "X: milblog occidentali"},
    "x_us_politics": {"de": "X: US-Politik", "es": "X: política de EE. UU.", "zh": "X: 美国政治", "fr": "X : politique américaine", "pl": "X: polityka USA", "ru": "X: политика США", "uk": "X: політика США", "it": "X: politica degli Stati Uniti"},
    "yt_finance": {"de": "YouTube Finanzen", "es": "YouTube finanzas", "zh": "YouTube 财务", "fr": "YouTube finances", "pl": "YouTube finanse", "ru": "YouTube финансы", "uk": "YouTube фінанси", "it": "YouTube finanza"},
    "yt_geopol_analysts": {"de": "YouTube Geopolitik-Analysten", "es": "YouTube analistas de geopolítica", "zh": "YouTube 地缘政治分析师", "fr": "YouTube analystes en géopolitique", "pl": "YouTube analitycy geopolityczni", "ru": "YouTube аналитики геополитики", "uk": "YouTube аналітики геополітики", "it": "YouTube analisti geopolitici"},
    "yt_tech_ai": {"de": "YouTube Technik / KI", "es": "YouTube tecnología / IA", "zh": "YouTube 技术 / AI", "fr": "YouTube technologie / IA", "pl": "YouTube technologia / AI", "ru": "YouTube технологии / ИИ", "uk": "YouTube технології / ШІ", "it": "YouTube tecnologia / AI"},
}