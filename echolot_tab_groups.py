"""Language-aware tab-group definitions for the landing page chip-row.

Each language gets its own DOMESTIC block (what's "home news" depends on
the reader). The TOPICAL block (World/Tech/AI/Climate/…) and the
PERSPECTIVE block (Germany/France/China/Russia/…) are universal but
translated per language. Anti-duplication: the reader's own geo is
omitted from the perspective block (e.g. en user doesn't see USA+UK
in perspective because they already have UK_domestic + US_politics in
domestic).

The output is consumed by `echolot_dashboard.augment_landing()` which
serializes it into a JS `const TAB_GROUPS = [...]` array and replaces
the hard-coded one in LANDING_HTML.
"""
from __future__ import annotations

# Sphere CSV constant for "all China" used in zh-domestic decomposition
# and for excluding zh from the universal China-perspective.
_CN_ALL = "regional_chinese,cn_state,cn_state_aligned,cn_hk,cn_tw,cn_diaspora_analysis,cn_weibo_pulse"

# DOMESTIC block — language-specific. What's "home" for this reader.
# Each entry is (label_key_in_i18n, sphere_csv, optional extra_filter).
DOMESTIC_GROUPS_BY_LANG: dict[str, list[tuple[str, str, str]]] = {
    "hu": [
        ("group.hu.domestic",      "hu_press,hu_premium,hu_foreign_commentary", ""),
        ("group.hu.local",         "hu_press", ""),
        ("group.hu.economy",       "hu_economy", ""),
        ("group.hu.tech",          "hu_tech", ""),
        ("group.hu.sport",         "hu_sport", ""),
        ("group.hu.lifestyle",     "hu_lifestyle,hu_cars", ""),
        ("group.hu.entertainment", "hu_entertainment,global_entertainment,asia_entertainment", ""),
    ],
    "en": [
        ("group.en.uk_domestic",   "regional_uk", ""),
        ("group.en.us_politics",   "regional_us,us_liberal_press,us_maga_blog,us_liberal_substack,us_maga_substack", ""),
        ("group.en.anglo_business","global_economy,global_press", ""),
    ],
    "de": [
        ("group.de.domestic",      "regional_german", ""),
    ],
    "es": [
        ("group.es.spain",         "regional_spanish", ""),
        ("group.es.latam",         "regional_south_american", ""),
    ],
    "zh": [
        ("group.zh.cn_mainland",   "regional_chinese,cn_state,cn_state_aligned", ""),
        ("group.zh.hk",            "cn_hk", ""),
        ("group.zh.tw",            "cn_tw", ""),
        ("group.zh.diaspora",      "cn_diaspora_analysis", ""),
        ("group.zh.weibo_pulse",   "cn_weibo_pulse", ""),
    ],
    "fr": [
        ("group.fr.france",        "regional_french", ""),
    ],
}

# TOPICAL block — universal, only labels translate.
TOPICAL_GROUPS: list[tuple[str, str, str]] = [
    ("group.world",         "global_anchor,global_press", ""),
    ("group.economy",       "global_economy", ""),
    ("group.tech",          "global_tech", ""),
    ("group.ai",            "global_ai", ""),
    ("group.science",       "global_science", ""),
    ("group.climate",       "global_climate", ""),
    ("group.health",        "global_health", ""),
    ("group.analysis",      "global_analysis,global_investigative", ""),
    ("group.conflict",      "global_conflict,ua_front_osint", ""),
    ("group.osint",         "global_osint,global_investigative", ""),
    ("group.entertainment", "global_entertainment,asia_entertainment", ""),
    ("group.telegram",      "", "source_type=telegram"),
]

# GEO PERSPECTIVE block — universal, only labels translate. Each entry
# also lists `lang_owners` — readers in those languages will NOT see
# this geo in the perspective block (because it's already in their
# domestic block).
GEO_GROUPS: list[dict] = [
    {"label_key": "group.geo.china",         "spheres": _CN_ALL, "extra": "", "lang_owners": ("zh",)},
    {"label_key": "group.geo.italy",         "spheres": "regional_italian", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.russia",        "spheres": "regional_russian,ru_state_media,ru_opposition,ru_milblog_pro", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.belarus",       "spheres": "regional_belarusian", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.us",            "spheres": "regional_us,us_maga_blog,us_maga_substack,us_liberal_press,us_liberal_substack", "extra": "", "lang_owners": ("en",)},
    {"label_key": "group.geo.uk",            "spheres": "regional_uk", "extra": "", "lang_owners": ("en",)},
    {"label_key": "group.geo.germany",       "spheres": "regional_german", "extra": "", "lang_owners": ("de",)},
    {"label_key": "group.geo.france",        "spheres": "regional_french", "extra": "", "lang_owners": ("fr",)},
    {"label_key": "group.geo.spain",         "spheres": "regional_spanish", "extra": "", "lang_owners": ("es",)},
    {"label_key": "group.geo.south_america", "spheres": "regional_south_american", "extra": "", "lang_owners": ("es",)},
    {"label_key": "group.geo.japan",         "spheres": "regional_japanese,jp_press_english,jp_press_native", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.korea",         "spheres": "regional_korean,kr_press_english", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.india",         "spheres": "regional_indian", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.australia",     "spheres": "regional_australian", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.v4",            "spheres": "regional_v4", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.israel",        "spheres": "regional_israeli,israel_press_left,israel_press_center,israel_press_right", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.iran",          "spheres": "regional_iranian,iran_regime,iran_opposition", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.ukraine",       "spheres": "regional_ukrainian,ua_front_osint", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.turkey",        "spheres": "regional_turkish", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.arab_world",    "spheres": "regional_arabic", "extra": "", "lang_owners": ()},
    {"label_key": "group.geo.africa",        "spheres": "regional_african", "extra": "", "lang_owners": ()},
]


def build_tab_groups(lang: str) -> list[dict]:
    """Return the full chip-row list for a given UI language.

    Order: All → DOMESTIC (lang-specific) → TOPICAL (universal) →
    GEO PERSPECTIVE (universal minus reader's own geo).

    Each returned dict has: label_key (for i18n lookup), spheres (CSV),
    extra (optional ?source_type=… style filter).
    """
    lang = (lang or "hu").lower()
    out: list[dict] = [
        {"label_key": "landing.bar.all", "spheres": "", "extra": ""},
    ]
    for label_key, spheres, extra in DOMESTIC_GROUPS_BY_LANG.get(lang, DOMESTIC_GROUPS_BY_LANG["hu"]):
        out.append({"label_key": label_key, "spheres": spheres, "extra": extra})
    for label_key, spheres, extra in TOPICAL_GROUPS:
        out.append({"label_key": label_key, "spheres": spheres, "extra": extra})
    for geo in GEO_GROUPS:
        if lang in geo["lang_owners"]:
            continue  # anti-dup: reader's own geo already in domestic block
        out.append({
            "label_key": geo["label_key"],
            "spheres": geo["spheres"],
            "extra": geo["extra"],
        })
    return out
