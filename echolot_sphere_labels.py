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


def sphere_label(sphere: str | None, lang: str = "hu") -> str:
    """Emberi név egy szféra-kulcshoz. HU/EN; más nyelv → EN fallback."""
    if not sphere:
        return "?"
    key = sphere.strip().lower().replace("-", "_")
    pair = _LABELS.get(key)
    if pair is None:
        return _prettify(key)
    return pair[0] if lang == "hu" else pair[1]
