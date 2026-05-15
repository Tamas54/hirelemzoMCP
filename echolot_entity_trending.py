"""Entity-trending chip-row a Ground News-szerű főoldalra.

24h-os ablakban legtöbbet-említett entity-k (politikusok, országok,
intézmények, események) listáját adja vissza, multi-language
egyesítéssel ha lehetséges.

Approach (B → A-ready):
  1. Pull last `hours` of `title + lead` from articles (optional `lang` filter).
  2. Regex-extract capitalized 1–3-token candidates from each text.
  3. Score by frequency (multi-token entities get a bonus over single-token).
  4. Filter against STOP_TAGS (news outlets, weekdays, months, generic nouns,
     common stop-words across the 8 languages we cover).
  5. Optionally (off by default — too slow for a chip-row endpoint) enrich
     each top candidate with Wikidata QID + multi-language aliases via
     `echolot_entities.resolve(name)`. Set `enrich_wikidata=True` to opt in.

Cache: 30 min TTL keyed by (db_path, hours, limit, lang, enrich_wikidata).

CLI smoke-test:
    python3 echolot_entity_trending.py
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("echolot.entity_trending")

CACHE_TTL = 1800  # 30 minutes
_cache: dict[tuple, tuple[float, list[dict]]] = {}

# Drop entities with fewer than this many mentions.
MIN_MENTIONS = 2

# Multi-token (>=2-word) candidates get this multiplicative bonus over single-token
# ones. "Donald Trump" beats two separate "Donald" + "Trump" hits.
MULTI_TOKEN_BONUS = 1.5

# Cap candidates per article to avoid one mega-article skewing the ranking.
MAX_HITS_PER_ARTICLE_PER_NAME = 3

# Capitalized-token regex. Permissive for Latin + Cyrillic; CJK is whole-script
# different (no caps) so this keyword-frequency approach has limited value for
# zh/ja, but the multi-language Wikidata enrichment fixes that path.
_CAP_WORD = (
    r"[A-ZÁÉÍÓÚÖŐÜŰÄÖÜßÀÂÆÇÈÉÊËÎÏÔŒÙÛŸČĎĚŇŘŠŤŮŽŁŚŹŻĘÓŃĆ]"
    r"[a-záéíóúöőüűäöüßàâæçèéêëîïôœùûÿčďěňřšťůžłśźżęóńć']{1,30}"
)
# Optional connector words allowed *between* capitalized tokens (e.g. "of", "the",
# "von", "van", "de", "der", "del", "da", "di") so "Bank of England" or
# "Maria von Trapp" stay intact.
_CONNECTORS = (
    r"(?:of|the|and|von|van|de|der|den|das|del|della|di|da|du|le|la|les|el|los|las|és|és)"
)
# 1-3 capitalized tokens, optionally with one lowercase connector.
ENTITY_RE = re.compile(
    rf"\b({_CAP_WORD}(?:\s+(?:{_CONNECTORS}\s+)?{_CAP_WORD}){{0,2}})\b"
)

# Country-name + adjective pairs we want to surface even when only adjective form
# appears. Maps adjective → canonical country name (best-effort, not exhaustive).
ADJECTIVE_TO_COUNTRY = {
    "American": "United States", "British": "United Kingdom", "French": "France",
    "German": "Germany", "Russian": "Russia", "Chinese": "China",
    "Japanese": "Japan", "Hungarian": "Hungary", "Italian": "Italy",
    "Spanish": "Spain", "Polish": "Poland", "Ukrainian": "Ukraine",
    "Israeli": "Israel", "Iranian": "Iran", "Turkish": "Türkiye",
    "Indian": "India", "Brazilian": "Brazil", "Mexican": "Mexico",
    "Canadian": "Canada", "Australian": "Australia",
}

# ----------------------------------------------------------------------
# Stop-tag filter — must be excluded from results.
# ----------------------------------------------------------------------
STOP_TAGS: set[str] = {
    # --- News outlets / agencies (these leak in via bylines and "via X" tails) ---
    "Bloomberg", "Reuters", "AP", "AFP", "BBC", "CNN", "Fox", "Fox News", "MSNBC",
    "NBC", "ABC", "CBS", "PBS", "NPR", "Sky News", "Sky", "ITV",
    "The New York Times", "New York Times", "NYT",
    "The Washington Post", "Washington Post",
    "The Guardian", "Guardian", "The Times", "Times",
    "Le Monde", "Le Figaro", "Libération", "Les Echos",
    "El País", "El Mundo", "ABC España",
    "La Repubblica", "Corriere", "Corriere della Sera", "La Stampa",
    "Süddeutsche", "Süddeutsche Zeitung", "FAZ", "Welt", "Die Welt", "Spiegel",
    "Der Spiegel", "Bild", "Zeit", "Die Zeit", "Tagesschau", "Tagesspiegel",
    "Daily Mail", "The Sun", "Mirror", "Daily Mirror", "Telegraph",
    "Daily Telegraph", "Independent", "Standard", "Evening Standard",
    "TASS", "RIA", "RIA Novosti", "Xinhua", "China Daily", "CGTN",
    "Politico", "Axios", "Vox", "BuzzFeed", "Forbes", "Fortune", "Time",
    "WSJ", "Wall Street Journal", "Financial Times", "FT",
    "USA Today", "HuffPost", "Huffington Post",
    "Yahoo", "MSN", "Google News", "Apple News",
    "TikTok", "Twitter", "Facebook", "Instagram", "YouTube", "X",
    "Telex", "Index", "HVG", "24.hu", "444", "Origo", "Mandiner",
    "Magyar Nemzet", "Magyar Hírlap", "Népszava", "Blikk",
    # --- Weekdays (en + a few others) ---
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Hétfő", "Kedd", "Szerda", "Csütörtök", "Péntek", "Szombat", "Vasárnap",
    "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag",
    "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche",
    # --- Months ---
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "Január", "Február", "Március", "Április", "Május", "Június",
    "Július", "Augusztus", "Szeptember", "Október", "November", "December",
    "Januar", "Februar", "März", "Mai", "Juni", "Juli", "Oktober", "Dezember",
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août",
    "Septembre", "Octobre", "Novembre", "Décembre",
    # --- Generic noise / titles / role nouns ---
    "President", "Prime Minister", "Minister", "Government", "Parliament",
    "Congress", "Senate", "Court", "Supreme Court", "Council", "Commission",
    "Country", "World", "News", "Today", "Yesterday", "Tomorrow", "Now",
    "Update", "Live", "Breaking", "Latest", "Report", "Analysis", "Opinion",
    "Editorial", "Feature", "Column", "Photo", "Video", "Interview",
    "Read", "Watch", "Listen", "Read More", "Subscribe", "Sign Up",
    "Continue", "Continue Reading", "Click", "Click Here", "Share", "Comment",
    "War", "Peace", "Crisis", "Conflict", "Attack", "Strike",
    "Mr", "Mrs", "Ms", "Dr", "Sir", "Lord", "Lady",
    # Common Hungarian role/title nouns (capitalized at sentence-start, leak in)
    "Elnök", "Miniszter", "Miniszterelnök", "Kormány", "Magyar", "Magyarok",
    "Miért", "Hogyan", "Mikor", "Hová", "Honnan",
    # German role nouns
    "Bundeskanzler", "Kanzler", "Bundespräsident", "Bundestag", "Regierung",
    # French
    "Président", "Premier", "Ministre", "Gouvernement",
    # Sentence-start lowercase-language particles that get capitalized
    "The", "A", "An", "Le", "La", "Les", "El", "La", "Los", "Las",
    "Der", "Die", "Das", "Den", "Dem",
    "Egy", "Az", "Ez", "Ezt", "Ezek", "Most", "Még", "Már", "Szerint", "Szerintem",
    "Nem", "Igen", "Tovább", "Így", "Úgy", "Csak", "Vagy", "Mert", "Hogy",
    "Bár", "Pedig", "Akkor", "Akár", "Ami", "Aki", "Amelyik", "Amely",
    "Több", "Újabb", "Teszt", "Mindenki", "Senki", "Néhány", "Semmi",
    "Sokan", "Talán", "Például", "Egyik", "Másik", "Egyébként", "Persze",
    "Magyarországon", "Magyarországot", "Magyarországi", "Magyarországra",
    "Magyarországról", "Európában", "Európai", "Európáról",
    "Forma", "Tegnap", "Hétvégén", "Reggel", "Este",
    "After", "Before", "During", "Following", "Amid", "Despite", "Without",
    "How", "Why", "What", "When", "Where", "Who", "Which",
    "First", "Second", "Third", "Last", "Next", "New", "Old",
    "Here", "There", "These", "Those", "This", "That",
    # Generic time-bucket words
    "Year", "Years", "Week", "Month", "Day", "Days", "Hour", "Hours",
    "Morning", "Evening", "Night", "Afternoon",
}

# Normalize stop-tags to a lowercase lookup set for fast membership tests.
_STOP_LOWER: set[str] = {s.lower() for s in STOP_TAGS}


def _is_stop(name: str) -> bool:
    return name.strip().lower() in _STOP_LOWER


def _classify_entity(name: str) -> str:
    """Heuristic type tag — purely cosmetic for the chip UI."""
    lower = name.lower()
    if name in ADJECTIVE_TO_COUNTRY.values():
        return "location"
    # Cup / Championship / Festival / Award → event
    event_kw = ("cup", "championship", "festival", "awards", "award",
                "olympics", "summit", "election", "elections", "open",
                "fesztivál", "díj", "wm", "em")
    if any(kw in lower for kw in event_kw):
        return "event"
    # FC / Bank / Inc / Corp / Group / Party / Union → org
    org_kw = (" fc", "fc ", "bank", " inc", " corp", " group", " party",
              " union", "league", "ministry", "department", "agency",
              "commission", "committee")
    if any(kw in lower for kw in org_kw):
        return "org"
    # Single-token Capitalized = likely person OR location, can't tell cheaply
    return "person" if len(name.split()) >= 2 else "other"


def _fetch_corpus(
    db_path: str, hours: int, lang: Optional[str]
) -> list[tuple[str, str, str]]:
    """Return [(article_id, language, title+lead)] for the time window.

    `published_at` is unreliable across sources; we use `fetched_at` so the
    24h window means "ingested in the last 24h", which is what the chip-row
    semantically wants.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    sql = (
        "SELECT article_id, language, "
        "       title || COALESCE(' ' || lead, '') AS text "
        "FROM articles "
        "WHERE fetched_at >= ?"
    )
    params: list = [cutoff]
    if lang:
        sql += " AND language = ?"
        params.append(lang)
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        con.close()


def _extract_candidates(text: str) -> list[str]:
    """Pull capitalized 1–3-token sequences from `text`."""
    if not text:
        return []
    out: list[str] = []
    for m in ENTITY_RE.finditer(text):
        cand = m.group(1).strip()
        # Strip trailing connectors/punctuation that snuck in.
        cand = re.sub(r"[\s,.;:!?'\"]+$", "", cand)
        if not cand:
            continue
        out.append(cand)
    return out


def _score_and_rank(
    corpus: list[tuple[str, str, str]],
    limit: int,
) -> list[tuple[str, float, int, list[str], set[str]]]:
    """Return [(name, score, raw_count, sample_titles, languages)] top-`limit`.

    `score` = raw mention count × multi-token bonus.
    """
    raw_counts: Counter = Counter()
    per_article: defaultdict[str, Counter] = defaultdict(Counter)
    samples: defaultdict[str, list[str]] = defaultdict(list)
    languages: defaultdict[str, set[str]] = defaultdict(set)

    for article_id, language, text in corpus:
        cands = _extract_candidates(text)
        local: Counter = Counter()
        for c in cands:
            # Country adjective normalization (American → United States, etc.)
            if c in ADJECTIVE_TO_COUNTRY:
                c = ADJECTIVE_TO_COUNTRY[c]
            if _is_stop(c):
                continue
            # Strip trailing 's (English possessive) — "Trump's" → "Trump"
            if c.endswith("'s") or c.endswith("’s"):
                c = c[:-2]
            if _is_stop(c) or len(c) < 3:
                continue
            local[c] += 1

        first_title = text.split(".", 1)[0][:140] if text else ""
        for name, cnt in local.items():
            cnt = min(cnt, MAX_HITS_PER_ARTICLE_PER_NAME)
            raw_counts[name] += cnt
            per_article[name][article_id] += cnt
            languages[name].add(language)
            if first_title and len(samples[name]) < 3:
                # Avoid duplicate sample titles.
                if first_title not in samples[name]:
                    samples[name].append(first_title)

    # Rank with multi-token bonus.
    ranked: list[tuple[str, float, int, list[str], set[str]]] = []
    for name, cnt in raw_counts.items():
        if cnt < MIN_MENTIONS:
            continue
        bonus = MULTI_TOKEN_BONUS if len(name.split()) >= 2 else 1.0
        score = cnt * bonus
        # Distinct-article count is more meaningful than raw mention count for
        # the chip-row, but we keep raw_count for transparency.
        distinct_articles = len(per_article[name])
        ranked.append((name, score, distinct_articles, samples[name], languages[name]))

    # Dedup: if a 2+-token name and one of its tokens both appear in the top list,
    # drop the single-token if its count is roughly subsumed by the multi-token.
    ranked.sort(key=lambda r: r[1], reverse=True)
    multi_names = [r[0] for r in ranked if len(r[0].split()) >= 2]
    multi_subtokens: set[str] = set()
    for mn in multi_names[: limit * 3]:
        for t in mn.split():
            multi_subtokens.add(t)
    deduped: list[tuple[str, float, int, list[str], set[str]]] = []
    seen_lower: set[str] = set()
    for r in ranked:
        name = r[0]
        # Skip single-token entries fully subsumed by a multi-token sibling we
        # already accepted, but only if the multi-token entry is at least 60%
        # as frequent (avoids dropping high-traffic singletons like "Putin"
        # because of a one-off "Vladimir Putin").
        if len(name.split()) == 1 and name in multi_subtokens:
            sub_score = r[1]
            kept = False
            for d in deduped:
                if name in d[0].split() and d[1] * 0.6 >= sub_score:
                    kept = True
                    break
            if kept:
                continue
        if name.lower() in seen_lower:
            continue
        seen_lower.add(name.lower())
        deduped.append(r)
        if len(deduped) >= limit:
            break
    return deduped


def _maybe_enrich_wikidata(name: str) -> tuple[Optional[str], Optional[str]]:
    """Best-effort QID + canonical label lookup. Returns (qid, label) or (None, None)
    on any failure (network, import error, missing entry).
    """
    try:
        from echolot_entities import resolve  # local import: keep base path light
        r = resolve(name)
        if not r:
            return None, None
        return r.get("qid"), r.get("primary_label") or name
    except Exception as exc:
        log.debug("wikidata enrich failed for %r: %s", name, exc)
        return None, None


def top_entities_24h(
    db_path: str,
    hours: int = 24,
    limit: int = 15,
    lang: Optional[str] = None,
    enrich_wikidata: bool = False,
) -> list[dict]:
    """Top-N entities mentioned in the corpus over the last `hours` hours.

    Args:
        db_path: SQLite file (echolot.db).
        hours: lookback window. Default 24.
        lang: if given (e.g. "hu"), restrict to that language; else all.
        limit: max chips to return.
        enrich_wikidata: if True, attach Wikidata QID + canonical label by
            calling `echolot_entities.resolve()` for each top candidate.
            DEFAULT FALSE — adds ~1–2s per candidate (network), too slow
            for a hot chip-row endpoint. Enable for offline batch jobs.

    Returns: list of dicts (see module docstring).
    """
    cache_key = (db_path, hours, limit, lang, enrich_wikidata)
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and (now - cached[0]) < CACHE_TTL:
        return cached[1]

    corpus = _fetch_corpus(db_path, hours, lang)
    if not corpus:
        _cache[cache_key] = (now, [])
        return []

    ranked = _score_and_rank(corpus, limit)

    out: list[dict] = []
    for name, score, distinct_articles, sample_titles, langs in ranked:
        qid: Optional[str] = None
        canonical = name
        if enrich_wikidata:
            qid, label = _maybe_enrich_wikidata(name)
            if label:
                canonical = label
        out.append({
            "name": canonical,
            "qid": qid,
            "article_count": distinct_articles,
            "score": round(score, 2),
            "sample_titles": sample_titles,
            "languages": sorted(langs),
            "type": _classify_entity(canonical),
            "search_query": name,
        })

    _cache[cache_key] = (now, out)
    return out


def clear_cache() -> None:
    """Drop the in-memory cache (for tests / forced refresh)."""
    _cache.clear()


def main() -> int:  # pragma: no cover — smoke test
    import argparse
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="/home/tamas1/Hirmagnetmcp/echolot.db")
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--lang", default=None)
    p.add_argument("--enrich", action="store_true",
                   help="Wikidata enrich (slow)")
    args = p.parse_args()

    t0 = time.time()
    rows = top_entities_24h(
        db_path=args.db, hours=args.hours, limit=args.limit,
        lang=args.lang, enrich_wikidata=args.enrich,
    )
    dt = time.time() - t0
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\n# {len(rows)} entities in {dt:.2f}s "
          f"(hours={args.hours}, lang={args.lang or 'all'}, "
          f"enrich={args.enrich})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
