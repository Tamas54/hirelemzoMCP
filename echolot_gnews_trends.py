"""Echolot Google-News-based trending (Plan B for Google Trends).

pytrends is deprecated and SerpAPI's google_trends engine costs money.
Tamas54/Trendinghub solved the problem by reading Google News RSS feeds
per country — the "Top Stories" feed effectively reflects what's
trending in that locale, free and via feedparser. We use the same
pattern here.

Cache: 30-minute in-memory LRU keyed by (geo, limit). Google News updates
its feed roughly every 15-30 minutes anyway.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import feedparser

log = logging.getLogger("echolot.gnews_trends")

# (geo_code, hl, ceid_locale) — the standard Google News RSS URL format
# https://news.google.com/rss?hl=<hl>&gl=<geo>&ceid=<geo>:<hl_short>
GEO_FEEDS = {
    "HU": ("hu",     "HU", "HU:hu"),
    "US": ("en-US",  "US", "US:en"),
    "GB": ("en-GB",  "GB", "GB:en"),
    "DE": ("de",     "DE", "DE:de"),
    "FR": ("fr",     "FR", "FR:fr"),
    "ES": ("es",     "ES", "ES:es"),
    "IT": ("it",     "IT", "IT:it"),
    "PL": ("pl",     "PL", "PL:pl"),
    "RU": ("ru",     "RU", "RU:ru"),
    "UA": ("uk",     "UA", "UA:uk"),
    "JP": ("ja",     "JP", "JP:ja"),
    "CN": ("zh-CN",  "CN", "CN:zh-Hans"),
    "BR": ("pt-BR",  "BR", "BR:pt-419"),
    "MX": ("es-419", "MX", "MX:es-419"),
    # Bővítés 2026-05-15: a 4 új regional sphere és a meglévő ország-csomagok
    # lefedéséhez. CZ + BY az új sphere-ekhez; KR/IN/AU/NL/TR/CA a meglévő
    # regional_korean/indian/australian/dutch/turkish/canadian-bővítéshez.
    "CZ": ("cs",     "CZ", "CZ:cs"),
    "BY": ("be",     "BY", "BY:be"),
    "KR": ("ko",     "KR", "KR:ko"),
    "IN": ("en-IN",  "IN", "IN:en"),
    "AU": ("en-AU",  "AU", "AU:en"),
    "NL": ("nl",     "NL", "NL:nl"),
    "TR": ("tr",     "TR", "TR:tr"),
    "CA": ("en-CA",  "CA", "CA:en"),
    "SE": ("sv",     "SE", "SE:sv"),
    "AR": ("es-419", "AR", "AR:es-419"),
}

CACHE_TTL = 30 * 60  # 30 minutes
_cache: dict[tuple, tuple[float, list]] = {}


def _feed_url(geo: str) -> Optional[str]:
    info = GEO_FEEDS.get(geo.upper())
    if not info:
        return None
    hl, gl, ceid = info
    return f"https://news.google.com/rss?hl={hl}&gl={gl}&ceid={ceid}"


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").strip()


def fetch_country_trending(geo: str = "HU", limit: int = 15) -> list[dict]:
    """Return current Google-News trending stories for a country.

    Each item: {title, link, published, source, geo}.
    Cached for CACHE_TTL seconds.
    """
    geo = geo.upper()
    cache_key = (geo, limit)
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]

    url = _feed_url(geo)
    if not url:
        log.warning("gnews_trends: unknown geo %r", geo)
        return []

    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        log.warning("gnews_trends: feedparser failed for %s: %s", geo, exc)
        return []

    results: list[dict] = []
    for entry in feed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        # Google News titles are usually "Article title - Source name"
        source = ""
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            if len(parts) == 2 and len(parts[1]) < 60:
                title, source = parts[0], parts[1]
        if not source:
            source = (entry.get("source", {}) or {}).get("title", "") if hasattr(entry, "source") else ""
        results.append({
            "title": title,
            "source": source,
            "link": link,
            "published": entry.get("published") or entry.get("updated") or "",
            "geo": geo,
        })

    _cache[cache_key] = (now, results)
    return results


def cross_source_supertrends(
    geos: list[str] | None = None,
    min_overlap: int = 2,
    limit: int = 20,
) -> list[dict]:
    """Identify topics trending across multiple countries simultaneously.

    Adapted from Tamas54/Trendinghub super_trends.py — keyword-overlap
    detection on Google News feeds from `geos`.

    Returns list of {topic_phrase, geos, count, sample_titles[]}, sorted
    by cross-country overlap descending.
    """
    if not geos:
        geos = ["HU", "US", "GB", "DE", "FR"]
    geos = [g.upper() for g in geos if g.upper() in GEO_FEEDS]
    if len(geos) < 2:
        return []

    # Keyword extraction
    STOPWORDS = {
        # English
        "the", "and", "for", "with", "from", "that", "this", "are", "was",
        "have", "has", "will", "would", "could", "should", "about", "after",
        "before", "into", "than", "more", "most", "such", "only", "very",
        "what", "when", "where", "which", "while", "their", "they", "them",
        # Hungarian
        "egy", "ez", "az", "és", "vagy", "de", "hogy", "van", "volt",
        "lesz", "lehet", "nem", "igen", "ezt", "azt", "ami", "aki",
        "most", "csak", "még", "már", "után", "előtt", "alatt", "felett",
        # German
        "der", "die", "das", "und", "ist", "war", "von", "den", "dem",
        "ein", "eine", "einen", "einem", "wird", "werden", "noch",
        # French
        "les", "des", "que", "qui", "pour", "avec", "dans", "sur", "par",
        "une", "ses", "son", "leur", "cette", "votre",
        # Spanish
        "los", "las", "que", "por", "para", "con", "una", "este", "esta",
    }

    def keywords(text: str) -> set[str]:
        words = re.findall(r"\w{4,}", _strip_html(text).lower(), re.UNICODE)
        return {w for w in words if w not in STOPWORDS}

    # Gather per-geo keyword sets and original titles
    per_geo: dict[str, list[tuple[set, str]]] = {}
    for geo in geos:
        items = fetch_country_trending(geo, limit=25)
        per_geo[geo] = [(keywords(it["title"]), it["title"]) for it in items]

    # Weak/generic tokens common in product copy or clickbait — drop any
    # n-gram that contains one of these. Prevents fragments like
    # "fits neatly", "pocket your budget", "your pocket" from inflating
    # the supertrend list.
    WEAK_TOKENS = {
        "your", "their", "his", "her", "its", "this", "that",
        "these", "those", "fits", "neatly", "pocket", "budget",
        "really", "very", "much", "more", "less", "just",
        "they", "them", "with", "from", "have", "been", "what",
        "when", "where", "which", "while", "about", "after", "before",
    }

    # Find phrases that appear in >= min_overlap geos
    # Use 2-3 word phrases for richer signal. Reject any n-gram that
    # contains a stopword OR a weak token (per-token check, not whole
    # phrase) — fixes the "fits neatly" / "pocket your budget" leak.
    def phrases(text: str) -> set[str]:
        clean = _strip_html(text).lower()
        clean = re.sub(r"[^\w\s]", " ", clean, flags=re.UNICODE)
        toks = [w for w in clean.split() if len(w) >= 4 and w not in STOPWORDS]
        out = set()
        for i in range(len(toks) - 1):
            bigram = toks[i:i + 2]
            if not any(t in WEAK_TOKENS or t in STOPWORDS for t in bigram):
                out.add(" ".join(bigram))
            if i + 2 < len(toks):
                trigram = toks[i:i + 3]
                if not any(t in WEAK_TOKENS or t in STOPWORDS for t in trigram):
                    out.add(" ".join(trigram))
        return out

    phrase_to_geos: dict[str, set[str]] = {}
    phrase_to_titles: dict[str, list[str]] = {}
    phrase_to_urls: dict[str, set[str]] = {}
    for geo in geos:
        items = fetch_country_trending(geo, limit=25)
        for it in items:
            for p in phrases(it["title"]):
                phrase_to_geos.setdefault(p, set()).add(geo)
                phrase_to_titles.setdefault(p, []).append(f"[{geo}] {it['title']}")
                url = (it.get("link") or "").strip()
                if url:
                    phrase_to_urls.setdefault(p, set()).add(url)

    supertrends = []
    for phrase, geo_set in phrase_to_geos.items():
        if len(geo_set) < min_overlap:
            continue
        # Require >= min_overlap DIFFERENT URLs — guards against the
        # same article being syndicated under different geos but
        # representing only ONE underlying story.
        url_set = phrase_to_urls.get(phrase, set())
        if len(url_set) < min_overlap:
            continue
        supertrends.append({
            "topic_phrase": phrase,
            "geos": sorted(geo_set),
            "count": len(geo_set),
            "sample_titles": phrase_to_titles[phrase][:5],
            "_url_count": len(url_set),
        })

    # Article-cluster dedup: phrases that appear in the SAME set of
    # titles describe the same underlying story. Collapse each cluster
    # to its single best representative (most countries → longest →
    # fewest weak tokens).
    def _normalize_titles(titles: list[str]) -> frozenset[str]:
        # Strip "[GEO] " prefix and lowercase for comparison.
        out: set[str] = set()
        for t in titles:
            if "] " in t:
                t = t.split("] ", 1)[-1]
            out.add(t.lower().strip())
        return frozenset(out)

    def _phrase_quality(st: dict) -> tuple:
        toks = st["topic_phrase"].split()
        weak = sum(1 for t in toks if t in WEAK_TOKENS)
        # Lower sort key wins: more countries, then longer phrase,
        # then fewer weak tokens, then more distinct URLs.
        return (-st["count"], -len(toks), weak, -st.get("_url_count", 0))

    clusters: dict[frozenset, list[dict]] = {}
    for st in supertrends:
        key = _normalize_titles(st["sample_titles"])
        clusters.setdefault(key, []).append(st)

    deduped: list[dict] = []
    for group in clusters.values():
        group.sort(key=_phrase_quality)
        best = group[0]
        # Drop the internal sort-only field before returning.
        best.pop("_url_count", None)
        deduped.append(best)

    deduped.sort(key=lambda x: (-x["count"], x["topic_phrase"]))
    return deduped[:limit]
