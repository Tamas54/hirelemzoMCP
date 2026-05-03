"""
ECHOLOT — source consolidation script.

Merges three legacy lists into one unified sources.yaml:
  1. /home/tamas1/hirmagnet/config/sources.py     — 186 HU + intl RSS feeds
  2. /home/tamas1/Hirmagnetmcp/poc_extracted/sources.yaml — Echolot global RSS + Telegram

Output: /home/tamas1/Hirmagnetmcp/sources.yaml — Echolot-format YAML with
sphere/lean/trust_tier metadata, deduplicated by URL.

Run once when source list changes. Idempotent.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# ============================================================
# Paths
# ============================================================

HIRMAGNET_PY = Path("/home/tamas1/hirmagnet/config/sources.py")
ECHOLOT_YAML = Path("/home/tamas1/Hirmagnetmcp/poc_extracted/sources.yaml")
EXTRA_YAML = Path("/home/tamas1/Hirmagnetmcp/sources_extra.yaml")
OUTPUT_YAML = Path("/home/tamas1/Hirmagnetmcp/sources.yaml")


# ============================================================
# Sphere/lean mapping for Hirmagnet sources
# ============================================================
#
# Hirmagnet sources have (category, source_type, language) — we derive
# sphere/lean/trust_tier from these plus a small override table for the
# well-known Hungarian outlets (lean is local knowledge, not in metadata).
#
# Trust tier mapping:
#   priority 1 → tier 2 (national broadsheet quality)
#   priority 2 → tier 3 (specialty / regional)
#   priority 3 → tier 4 (partisan / niche)

HU_LEAN_OVERRIDES = {
    # Pro-government (Fidesz orbit)
    "Magyar Nemzet": "gov", "Hír TV": "gov", "Origo": "gov", "Mandiner": "gov",
    "Demokrata": "gov", "PestiSrácok": "gov", "888.hu": "gov", "Magyar Hírlap": "gov",
    "Bors": "gov", "Lokál": "gov", "Ripost": "gov", "Index": "gov",
    "Index Politika": "gov", "Index Külföld": "gov", "Index Kultúra": "gov",
    "Index Gazdaság": "gov",
    # Center / liberal opposition mainstream
    "Telex": "opposition", "HVG": "opposition", "444": "opposition",
    "24.hu": "opposition", "Magyar Hang": "opposition", "Magyar Narancs": "opposition",
    "168 Óra": "opposition", "Népszava": "opposition", "Szabad Európa": "opposition",
    "EUrologus": "opposition", "Mérce": "left",
    # Right-independent
    "Válasz Online": "right_independent",
    # Economic / analytical (politically neutral business press)
    "Portfolio": "analytical", "Napi.hu": "analytical", "G7": "analytical",
    "Bank360": "analytical", "Pénzcentrum": "analytical", "Világgazdaság": "analytical",
    "MNB sajtóközlemények": "analytical", "MNB": "analytical",
    # Tech (analytical)
    "HWSW": "analytical", "Prohardver": "analytical", "Rakéta": "analytical",
    "Qubit": "analytical",
}


# URL/name patterns → granular global spheres.
# A source can match multiple patterns and end up in multiple spheres
# (e.g. FT = global_anchor + global_economy + regional_uk).
GLOBAL_PATTERNS: list[tuple[list[str], list[str]]] = [
    # ====== TOPICAL spheres ======
    # global_economy — international finance/markets
    (["bloomberg", "ft.com", "economist.com", "cnbc.com", "marketwatch",
      "wsj.com", "reuters.com/business", "businessinsider", "investopedia",
      "morningstar", "fortune.com", "barrons.com", "investing.com",
      "handelsblatt"],
     ["global_economy"]),
    # global_tech — international tech press
    (["techcrunch", "theverge", "wired.com", "arstechnica", "engadget",
      "venturebeat", "thenextweb", "gizmodo", "tomshardware", "anandtech",
      "9to5mac", "9to5google", "technologyreview"],
     ["global_tech"]),
    # global_ai — AI-specific outlets
    (["technologyreview.com/topic/artificial-intelligence", "anthropic.com",
      "openai.com/blog", "deepmind.com/blog", "ai.googleblog", "huggingface.co/blog",
      "thegradient.pub", "marktechpost", "venturebeat.com/category/ai",
      "ai-news", "aitrends", "/category/ai"],
     ["global_ai"]),
    # global_science — peer-reviewed + popular science
    (["nature.com", "science.org", "scientificamerican", "newscientist",
      "phys.org", "sciencedaily", "quantamagazine", "qubit.hu",
      "ng.hu", "nationalgeographic", "tudomanyplaza"],
     ["global_science"]),
    # global_analysis — think tanks, foreign policy commentary
    (["foreignaffairs", "foreignpolicy", "project-syndicate", "brookings",
      "carnegieendowment", "cfr.org", "atlanticcouncil", "ecfr.eu",
      "rusi.org", "csis.org", "rand.org", "chathamhouse"],
     ["global_analysis"]),
    # global_conflict — defense / war journalism
    (["warontherocks", "defenseone", "breakingdefense", "janes.com",
      "thecipherbrief", "smallwarsjournal", "armyrecognition", "thedrive.com/the-war-zone",
      "kyivindependent", "ukrainska_pravda", "euromaidan"],
     ["global_conflict"]),
    # global_osint — open-source intelligence specialists
    (["bellingcat", "occrp.org", "isw.", "understandingwar", "intelnews",
      "intelligencefusion", "stratfor.com", "soufancenter", "theintercept"],
     ["global_osint"]),
    # global_entertainment
    (["variety.com", "hollywoodreporter", "rollingstone.com", "deadline.com",
      "indiewire", "thewrap", "vulture.com", "ew.com", "nme.com", "billboard"],
     ["global_entertainment"]),
    # asia_entertainment
    (["soompi", "asianwiki", "kpopstarz", "allkpop", "jdramaoptimum",
      "japan-forward.com/culture", "tokyohive"],
     ["asia_entertainment"]),
    # global_anchor — top wire / international newspapers of record
    (["bbc.co.uk", "bbc.com", "reuters.com", "apnews.com", "afp.com",
      "theguardian.com", "nytimes.com", "washingtonpost.com",
      "dw.com", "france24", "aljazeera", "euronews"],
     ["global_anchor"]),

    # ====== REGIONAL spheres (national press groupings) ======
    # regional_uk — British press
    (["bbc.co.uk", "bbc.com", "theguardian.com", "ft.com", "telegraph.co.uk",
      "independent.co.uk", "thetimes.co.uk", "skynews.com", "spectator.co.uk",
      "newstatesman.com", "economist.com", "dailymail.co.uk"],
     ["regional_uk"]),
    # regional_us — US national press (covers both partisan + mainstream)
    (["nytimes.com", "washingtonpost.com", "wsj.com", "usatoday.com",
      "npr.org", "axios.com", "politico.com", "thehill.com", "bloomberg",
      "cbsnews.com", "abcnews.go.com", "nbcnews.com", "cnn.com", "foxnews.com",
      "msnbc.com", "vox.com", "theatlantic.com", "newyorker.com", "tpm",
      "talkingpointsmemo", "newrepublic", "nationalreview", "weeklystandard",
      "dailywire", "breitbart", "thefederalist", "americanconservative",
      "freep.com", "latimes.com", "chicagotribune", "bostonglobe"],
     ["regional_us"]),
    # regional_german — German-language press (DE/AT/CH)
    (["spiegel.de", "faz.net", "zeit.de", "nzz.ch", "handelsblatt",
      "welt.de", "sueddeutsche.de", "tagesschau.de", "n-tv.de",
      "derstandard.at", "diepresse.com", "krone.at"],
     ["regional_german"]),
    # regional_french — French-language press
    (["lemonde.fr", "lefigaro.fr", "liberation.fr", "lesechos.fr",
      "france24.com/fr", "rfi.fr", "lexpress.fr", "lepoint.fr",
      "marianne.net", "mediapart.fr", "humanite.fr"],
     ["regional_french"]),
    # regional_spanish — Spanish-language press (Spain primarily)
    (["elpais.com", "elmundo.es", "abc.es", "lavanguardia.com",
      "elperiodico.com", "publico.es", "20minutos.es", "rtve.es",
      "expansion.com", "vozpopuli.com"],
     ["regional_spanish"]),
    # regional_south_american — Latin American press
    (["clarin.com", "lanacion.com.ar", "infobae.com", "pagina12",
      "folha.uol.com.br", "globo.com", "estadao.com.br", "uol.com.br",
      "eluniversal.com.mx", "milenio.com", "jornada.com.mx",
      "eltiempo.com", "elespectador.com", "semana.com",
      "elmercurio.com", "latercera.com", "emol.com",
      "elcomercio.pe", "lapublicadr"],
     ["regional_south_american"]),
    # regional_chinese — all China-related sources (state + HK + TW + diaspora)
    (["xinhuanet", "people.cn", "globaltimes", "chinadaily", "cgtn",
      "caixin", "guancha", "thepaper.cn", "scmp.com", "taipei", "focustaiwan",
      "sinocism", "sinification", "chinatalk", "pekingnology",
      "chinadigitaltimes", "whatsonweibo"],
     ["regional_chinese"]),
    # regional_japanese — Japanese press (English + native)
    (["nhk.or.jp", "japantimes", "asahi.com", "mainichi.jp", "nikkei",
      "sankei", "japannews.yomiuri", "kyodo.co.jp"],
     ["regional_japanese"]),
    # regional_korean
    (["koreaherald", "yna.co.kr", "kbs.co.kr", "hani.co.kr", "chosun",
      "joongang.co.kr", "donga.com"],
     ["regional_korean"]),
    # regional_russian (state + opposition + milblog umbrella)
    (["tass.com", "tass.ru", "rt.com", "ria.ru", "interfax",
      "meduza.io", "novayagazeta", "moscowtimes", "thebell", "republic.ru"],
     ["regional_russian"]),
    # regional_israeli
    (["haaretz.com", "timesofisrael", "jpost.com", "i24news",
      "ynetnews", "ynet.co.il", "globes.co.il"],
     ["regional_israeli"]),
    # regional_iranian
    (["tehrantimes", "presstv", "tasnim", "mehrnews",
      "iranintl", "iranwire", "rferl.org/persia"],
     ["regional_iranian"]),
    # regional_ukrainian
    (["kyivindependent", "kyivpost", "pravda.com.ua", "ukrinform",
      "rferl.org/ukrai"],
     ["regional_ukrainian"]),
    # regional_indian
    (["timesofindia", "hindustantimes", "thehindu.com", "ndtv.com",
      "indianexpress.com", "thewire.in", "scroll.in", "thequint",
      "livemint.com", "businesstoday.in"],
     ["regional_indian"]),
    # regional_australian / NZ
    (["abc.net.au", "smh.com.au", "theage.com.au", "theaustralian",
      "afr.com", "9news.com.au", "news.com.au",
      "stuff.co.nz", "nzherald.co.nz", "rnz.co.nz"],
     ["regional_australian"]),
    # regional_v4 — Visegrád (CZ/SK/PL/HU-neighbors) + RO
    (["dennikn.sk", "novinky.cz", "wyborcza.pl", "denik.cz", "idnes.cz",
      "rzeczpospolita.pl", "tvp.pl", "interia.pl", "onet.pl",
      "hotnews.ro", "digi24.ro", "g4media.ro", "adevarul.ro"],
     ["regional_v4"]),
    # regional_turkish
    (["hurriyetdailynews", "dailysabah", "trtworld", "ahval.me",
      "duvarenglish", "bianet.org/english"],
     ["regional_turkish"]),
    # regional_arabic
    (["alarabiya", "ahram.org.eg", "english.alaraby", "middleeasteye",
      "thenationalnews.com", "arabnews.com", "english.almayadeen",
      "alquds.co.uk"],
     ["regional_arabic"]),
    # regional_african
    (["dailymaverick.co.za", "iol.co.za", "news24.com",
      "thisdaylive.com", "premiumtimesng", "punchng.com",
      "africanews", "mg.co.za"],
     ["regional_african"]),
    # ====== Additional topical spheres ======
    # global_climate
    (["carbonbrief", "insideclimatenews", "heated.world", "yaleclimateconnections",
      "climatehome", "energymonitor", "grist.org", "drilledpodcast"],
     ["global_climate"]),
    # global_health
    (["statnews.com", "healthaffairs", "thelancet", "kff.org/news",
      "medpagetoday", "fiercebiotech", "fiercehealthcare"],
     ["global_health"]),
]


def detect_global_spheres(url: str, name: str) -> list[str]:
    """Match URL/name against the GLOBAL_PATTERNS table — return all matches."""
    needle = (url + " " + name).lower()
    out: list[str] = []
    for patterns, spheres in GLOBAL_PATTERNS:
        if any(p in needle for p in patterns):
            for s in spheres:
                if s not in out:
                    out.append(s)
    return out


def hu_sphere_for(src: dict) -> list[str]:
    """Map a Hirmagnet source dict → list of sphere tags."""
    cat = src.get("category", "general")
    stype = src.get("source_type", "domestic_standard")
    lang = src.get("language", "hu")
    url = src.get("url", "")
    name = src.get("name", "")

    # First try domain-pattern matches — gets fine-grained global spheres
    pattern_spheres = detect_global_spheres(url, name)

    # International sources from the HU list — combine pattern + tier defaults
    if stype.startswith("international_") or stype == "investigative_premium":
        out = list(pattern_spheres)
        if stype == "international_premium" and "global_anchor" not in out:
            out.append("global_anchor")
        elif stype == "international_standard" and not out:
            out.append("global_press")
        if stype == "investigative_premium" and "global_conflict" not in out:
            # OCCRP/Bellingcat already covered by pattern; ProPublica/Intercept land here
            out.append("global_investigative")
        return out or ["global_press"]

    # economy_premium / tech_premium can be HU or international
    if stype in ("economy_premium", "tech_premium") and lang != "hu":
        out = list(pattern_spheres)
        if stype == "economy_premium" and "global_economy" not in out:
            out.append("global_economy")
        if stype == "tech_premium" and "global_tech" not in out:
            out.append("global_tech")
        return out or ["global_press"]

    # Hungarian sources
    spheres = ["hu_press"]
    if stype in ("domestic_premium", "economy_premium", "tech_premium"):
        spheres.append("hu_premium")
    if cat == "economy":
        spheres.append("hu_economy")
    elif cat == "tech":
        spheres.append("hu_tech")
    elif cat == "sport":
        return ["hu_sport"]
    elif cat == "lifestyle":
        return ["hu_lifestyle"]
    elif cat == "cars":
        return ["hu_lifestyle", "hu_cars"]
    elif cat == "entertainment":
        return ["hu_entertainment"]
    elif cat == "foreign":
        spheres.append("hu_foreign_commentary")
    # If a HU source happens to match a global pattern (rare — e.g. a HU
    # source that mirrors international content), add the global tag too.
    for ps in pattern_spheres:
        if ps not in spheres:
            spheres.append(ps)
    return spheres


def trust_tier_for(src: dict) -> int:
    prio = src.get("priority", 2)
    return {1: 2, 2: 3, 3: 4}.get(prio, 3)


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[áàâä]", "a", s)
    s = re.sub(r"[éèêë]", "e", s)
    s = re.sub(r"[íìîï]", "i", s)
    s = re.sub(r"[óòôöő]", "o", s)
    s = re.sub(r"[úùûüű]", "u", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s or "src"


def detect_language(src: dict) -> str:
    """Best-effort language detection if not explicitly set.

    Hirmagnet entries don't always set language. Strategy:
      1. Trust explicit language field if set.
      2. URL TLD (.hu/.de/.fr/.cz/.sk/.pl/.ru/.cn) wins regardless of source_type.
      3. For international/premium types without a known TLD, default English.
      4. Otherwise default Hungarian.
    """
    lang = src.get("language")
    if lang:
        return lang
    url = src.get("url", "").lower()

    # TLD-based detection (most reliable)
    tld_map = [
        (".hu", "hu"), (".de", "de"), (".at", "de"), (".ch/", "de"),
        (".fr", "fr"), (".it", "it"), (".cz", "cs"), (".sk", "sk"),
        (".pl", "pl"), (".ro", "ro"), (".ru", "ru"), (".ua", "uk"),
        (".jp", "ja"), (".kr", "ko"), (".cn", "zh"), (".tw", "zh"),
        (".il", "he"), (".ir", "fa"),
    ]
    for tld, lang_code in tld_map:
        if tld in url:
            # Some .cn/.jp/etc are English-language editions — special-case
            if tld in (".cn", ".tw") and any(x in url for x in [
                "xinhuanet", "globaltimes", "chinadaily", "cgtn",
                "scmp.com", "taipei_times", "focustaiwan",
            ]):
                return "en"
            if tld == ".jp" and any(x in url for x in ["japantimes", "nhk.or.jp/nhkworld"]):
                return "en"
            if tld == ".kr" and any(x in url for x in ["koreaherald", "yna.co.kr/en"]):
                return "en"
            if tld == ".ru" and "meduza.io/en" in url:
                return "en"
            return lang_code

    # No TLD match — fall back to source_type heuristic
    stype = src.get("source_type", "")
    if stype.startswith("international_") or stype in ("economy_premium", "tech_premium", "investigative_premium"):
        return "en"
    return "hu"


# ============================================================
# Loaders
# ============================================================

def load_hirmagnet() -> list[dict]:
    """Import the original NEWS_SOURCES list."""
    sys.path.insert(0, str(HIRMAGNET_PY.parent))
    import sources as hirmag  # type: ignore
    return list(hirmag.NEWS_SOURCES)


def load_echolot() -> list[dict]:
    """Load Echolot YAML (already in target format)."""
    return yaml.safe_load(ECHOLOT_YAML.read_text(encoding="utf-8")) or []


def load_extra() -> list[dict]:
    """Load the extra source pack (V4 / India / etc.)."""
    if not EXTRA_YAML.exists():
        return []
    return yaml.safe_load(EXTRA_YAML.read_text(encoding="utf-8")) or []


# ============================================================
# Conversion
# ============================================================

def convert_hu(src: dict, used_ids: set[str]) -> dict | None:
    name = src.get("name")
    url = src.get("url")
    if not name or not url:
        return None
    if not src.get("active", True):
        return None

    base_id = "hu_" + slugify(name)
    sid = base_id
    n = 2
    while sid in used_ids:
        sid = f"{base_id}_{n}"
        n += 1
    used_ids.add(sid)

    return {
        "id": sid,
        "name": name,
        "url": url,
        "spheres": hu_sphere_for(src),
        "language": detect_language(src),
        "trust_tier": trust_tier_for(src),
        "lean": HU_LEAN_OVERRIDES.get(name, "unknown"),
        "category": src.get("category", "general"),
        "source_type": "rss",
        # Preserve Hirmagnet-specific metadata for backwards-compat tools
        "hirmagnet_source_type": src.get("source_type", ""),
        "hirmagnet_content_profile": src.get("content_profile", ""),
        "hirmagnet_priority": src.get("priority", 2),
    }


def normalize_echolot(src: dict, used_ids: set[str]) -> dict:
    """Echolot entries are already in target format — augment with regional + topical
    spheres derived from URL pattern matching, on top of the existing sphere tags."""
    sid = src["id"]
    if sid in used_ids:
        sid = f"echolot_{sid}"
    used_ids.add(sid)

    spheres = list(src.get("spheres", []))
    pattern_spheres = detect_global_spheres(src["url"], src["name"])
    for ps in pattern_spheres:
        if ps not in spheres:
            spheres.append(ps)

    out = {
        "id": sid,
        "name": src["name"],
        "url": src["url"],
        "spheres": spheres,
        "language": src.get("language", "en"),
        "trust_tier": int(src.get("trust_tier", 3)),
        "lean": src.get("lean", "unknown"),
        "category": "global",
        "source_type": src.get("source_type", "rss"),
    }
    if src.get("notes"):
        out["notes"] = src["notes"]
    if src.get("telegram_channel"):
        out["telegram_channel"] = src["telegram_channel"]
    return out


# ============================================================
# Merge + dedup
# ============================================================

def normalize_url(url: str) -> str:
    """For dedup — strip trailing slash, lowercase scheme+host."""
    u = url.strip().rstrip("/")
    # lowercase only the scheme://host part, leave path case intact
    m = re.match(r"^([a-zA-Z]+://)([^/]+)(.*)$", u)
    if m:
        return m.group(1).lower() + m.group(2).lower() + m.group(3)
    return u


def main():
    used_ids: set[str] = set()
    by_url: dict[str, dict] = {}

    print("Loading Hirmagnet 186-source list...")
    hu_raw = load_hirmagnet()
    print(f"  raw entries: {len(hu_raw)}")

    converted_hu = []
    skipped_inactive = 0
    for src in hu_raw:
        c = convert_hu(src, used_ids)
        if c is None:
            skipped_inactive += 1
            continue
        converted_hu.append(c)

    print(f"  converted (active): {len(converted_hu)} (skipped {skipped_inactive})")

    print("Loading Echolot sources.yaml...")
    echolot_raw = load_echolot()
    converted_echolot = [normalize_echolot(s, used_ids) for s in echolot_raw]
    print(f"  loaded: {len(converted_echolot)}")

    print("Loading sources_extra.yaml...")
    extra_raw = load_extra()
    converted_extra = [normalize_echolot(s, used_ids) for s in extra_raw]
    print(f"  loaded: {len(converted_extra)}")

    # Merge — Echolot/extra wins on URL conflict (richer sphere metadata)
    for s in converted_hu:
        u = normalize_url(s["url"])
        by_url[u] = s
    overrides = 0
    for s in converted_echolot + converted_extra:
        u = normalize_url(s["url"])
        if u in by_url:
            overrides += 1
            existing = by_url[u]
            merged = list({*existing.get("spheres", []), *s.get("spheres", [])})
            s["spheres"] = merged
        by_url[u] = s

    print(f"  URL overrides (echolot/extra wins): {overrides}")
    final = sorted(by_url.values(), key=lambda x: (x.get("source_type", "rss"), x["id"]))

    print(f"\nWriting {OUTPUT_YAML} — {len(final)} unique sources")
    OUTPUT_YAML.write_text(
        yaml.safe_dump(final, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    # Summary by sphere
    from collections import Counter
    sphere_count: Counter[str] = Counter()
    lang_count: Counter[str] = Counter()
    type_count: Counter[str] = Counter()
    for s in final:
        for sph in s.get("spheres", []):
            sphere_count[sph] += 1
        lang_count[s.get("language", "?")] += 1
        type_count[s.get("source_type", "rss")] += 1

    print("\n=== SPHERES ===")
    for sph, n in sphere_count.most_common():
        print(f"  {sph:<28} {n:>4}")
    print("\n=== LANGUAGES ===")
    for lng, n in lang_count.most_common():
        print(f"  {lng:<6} {n:>4}")
    print("\n=== SOURCE TYPES ===")
    for t, n in type_count.most_common():
        print(f"  {t:<12} {n:>4}")


if __name__ == "__main__":
    main()
