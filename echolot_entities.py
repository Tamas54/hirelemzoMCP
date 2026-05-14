"""Echolot cross-language entity resolution (Wikidata-backed).

Given a name ("Trump") or a Wikidata QID ("Q22686"), resolve to all known
multilingual aliases — so the corpus can be searched in any of the 8 languages
we cover (HU, EN, DE, RU, ZH, JA, FR, UK), not just whichever spelling the
caller happened to pick.

NOT an AI step — pure lookup: Wikidata SPARQL endpoint + an LRU cache.
Search is then a plain FTS5 OR of all aliases, run by the caller (server.py).

Two-step resolution:
  1. resolve_qid_from_name(name) → QID (Wikidata search API)
  2. fetch_aliases(qid)          → list of (label, lang) tuples (SPARQL)

Combined:
  resolve(name_or_qid) → {"qid": ..., "primary_label": ..., "aliases": [...]}

Both steps are LRU-cached per process. Restart drops the cache; that's fine,
Wikidata is fast and we rarely repeat queries during a single session.

CLI test:
  python3 echolot_entities.py "Trump"
  python3 echolot_entities.py Q22686
"""
from __future__ import annotations

import json
import logging
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Optional

log = logging.getLogger("echolot.entities")

LANGS = ("en", "hu", "de", "ru", "zh", "ja", "fr", "uk")
USER_AGENT = "echolot-entity-resolver/0.1 (https://github.com/Tamas54/hirelemzoMCP)"
SPARQL_URL = "https://query.wikidata.org/sparql"
SEARCH_URL = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
TIMEOUT_S = 15
QID_RE = re.compile(r"^Q\d+$", re.IGNORECASE)

# Alias filter: drop very short or noisy aliases ("DJT", "@realDonaldTrump").
# 4+ chars, and not starting with "@" (handles), and not all-caps acronyms.
MIN_ALIAS_LEN = 4


def _http_get_json(url: str, params: dict) -> Optional[dict]:
    """GET ?params, decode JSON. Mimics a real client's full header set
    because the bare urllib fingerprint trips Wikidata's WAF rate-limiter
    even when curl with the same UA passes (observed 2026-05-13).
    """
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    req = urllib.request.Request(
        full,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "close",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        log.warning("wikidata: HTTP %d %s for %s", exc.code, exc.reason, url)
        return None
    except urllib.error.URLError as exc:
        log.warning("wikidata: transport error: %s", exc)
        return None
    except Exception as exc:
        log.warning("wikidata: %s: %s", type(exc).__name__, exc)
        return None


@lru_cache(maxsize=200)
def _wikipedia_candidates(name: str, limit: int = 10) -> tuple[tuple[str, str], ...]:
    """Wikipedia opensearch + pageprops → fame-ranked QID candidates.

    Wikidata's wbsearchentities matches labels/aliases literally, so a bare query
    like "Trump" returns family-name and trumpet entities first; Donald Trump
    (Q22686) is not in the top 50 because his label is "Donald Trump", not "Trump".
    Wikipedia's opensearch ranks by article importance/pageviews, so "Trump" →
    ["Donald Trump", "Melania Trump", ...] — exactly what we want.

    Returns a tuple of (qid, title) tuples (tuple so lru_cache can hold it).
    Empty tuple on failure.
    """
    if not name.strip():
        return ()
    titles_data = _http_get_json(WIKIPEDIA_API_URL, {
        "action": "opensearch", "search": name, "limit": str(limit),
        "format": "json", "namespace": "0",
    })
    if not titles_data or len(titles_data) < 2:
        return ()
    titles = titles_data[1] or []
    if not titles:
        return ()
    pp = _http_get_json(WIKIPEDIA_API_URL, {
        "action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
        "titles": "|".join(titles[:limit]), "format": "json",
        "redirects": "1",
    })
    if not pp:
        return ()
    pages = (pp.get("query") or {}).get("pages") or {}
    # Preserve opensearch ranking by mapping title → qid then re-ordering by titles list.
    title_to_qid: dict[str, str] = {}
    for _, p in pages.items():
        t = p.get("title")
        qid = (p.get("pageprops") or {}).get("wikibase_item")
        if t and qid:
            title_to_qid[t] = qid
    out: list[tuple[str, str]] = []
    for t in titles[:limit]:
        # Wikipedia may have applied redirects; the page entry's title can differ.
        # First try direct lookup, then accept any qid found if the title moved.
        if t in title_to_qid:
            out.append((title_to_qid[t], t))
    # Append any qid pages that didn't appear in the original titles list (redirects)
    seen = {q for q, _ in out}
    for t, q in title_to_qid.items():
        if q not in seen:
            out.append((q, t))
            seen.add(q)
    return tuple(out)


def _score_candidates(qids: list[str]) -> dict[str, int]:
    """Batched SPARQL: pull P31/P39/P106 + sitelinks for each candidate QID
    in a single query and compute a "this-is-likely-a-prominent-person" score.

    Returns {qid: score}. On any failure returns {} so the caller can fall
    back to legacy top-hit behavior.

    Scoring:
      +100 if instance_of (P31) includes Q5 (human)
      + 50 if has any P39 (position held)
      + 30 if has any P106 (occupation)
      + 20 if sitelinks > 50
      +  1 per sitelink up to 100
    """
    if not qids:
        return {}
    values = " ".join(f"wd:{q}" for q in qids)
    query = f"""
SELECT ?item
       (GROUP_CONCAT(DISTINCT ?p31; SEPARATOR="|") AS ?p31s)
       (GROUP_CONCAT(DISTINCT ?p39; SEPARATOR="|") AS ?p39s)
       (GROUP_CONCAT(DISTINCT ?p106; SEPARATOR="|") AS ?p106s)
       (SAMPLE(?sitelinks) AS ?sl)
WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P31 ?p31 . }}
  OPTIONAL {{ ?item wdt:P39 ?p39 . }}
  OPTIONAL {{ ?item wdt:P106 ?p106 . }}
  OPTIONAL {{ ?item wikibase:sitelinks ?sitelinks . }}
}}
GROUP BY ?item
"""
    data = _http_get_json(SPARQL_URL, {"query": query, "format": "json"})
    if not data:
        log.warning("wikidata: scoring SPARQL failed; falling back to top-hit")
        return {}
    scores: dict[str, int] = {}
    for b in data.get("results", {}).get("bindings", []):
        item_uri = b.get("item", {}).get("value", "")
        # http://www.wikidata.org/entity/Q5972170 -> Q5972170
        qid = item_uri.rsplit("/", 1)[-1] if item_uri else ""
        if not qid:
            continue
        p31s = b.get("p31s", {}).get("value", "")
        p39s = b.get("p39s", {}).get("value", "")
        p106s = b.get("p106s", {}).get("value", "")
        sl_raw = b.get("sl", {}).get("value", "0")
        try:
            sitelinks = int(sl_raw)
        except (TypeError, ValueError):
            sitelinks = 0

        p31_qids = {u.rsplit("/", 1)[-1] for u in p31s.split("|") if u}
        score = 0
        if "Q5" in p31_qids:
            score += 100
        if any(u for u in p39s.split("|") if u):
            score += 50
        if any(u for u in p106s.split("|") if u):
            score += 30
        if sitelinks > 50:
            score += 20
        score += min(sitelinks, 100)
        scores[qid] = score
    return scores


@lru_cache(maxsize=200)
def resolve_qid_from_name(name: str, prefer: str = "person") -> Optional[tuple[str, str]]:
    """Look up a name on Wikidata + Wikipedia; return (qid, primary_label).

    prefer="person" (default): UNION of two candidate pools:
      - Wikidata wbsearchentities top 10 (label/alias literal match)
      - Wikipedia opensearch top 10 (fame-ranked article search)
    Then score each by humanness + political signals + cross-wiki popularity,
    return best. Wikipedia opensearch is essential because wbsearchentities
    matches labels literally — bare query "Trump" misses Donald Trump (whose
    label is "Donald Trump") in its top 50, while Wikipedia ranks him #1.

    prefer="any": legacy behavior — first wbsearchentities hit, no scoring.

    Returns None if both APIs failed or nothing found.
    """
    if prefer != "person":
        # Legacy fast path
        data = _http_get_json(SEARCH_URL, {
            "action": "wbsearchentities", "search": name, "language": "en",
            "format": "json", "limit": "1", "type": "item",
        })
        if not data:
            return None
        hits = data.get("search") or []
        if not hits:
            return None
        qid = hits[0].get("id")
        if not qid:
            return None
        return qid, (hits[0].get("label") or name)

    # prefer == "person": gather candidates from both sources.
    pool: list[tuple[str, str]] = []  # (qid, label) preserving rank
    seen: set[str] = set()

    wd = _http_get_json(SEARCH_URL, {
        "action": "wbsearchentities", "search": name, "language": "en",
        "format": "json", "limit": "10", "type": "item",
    })
    if wd:
        for h in wd.get("search") or []:
            qid = h.get("id")
            if not qid or qid in seen:
                continue
            pool.append((qid, h.get("label") or name))
            seen.add(qid)

    wiki = _wikipedia_candidates(name, limit=10)
    for qid, title in wiki:
        if qid in seen:
            continue
        pool.append((qid, title))
        seen.add(qid)

    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]

    qids = [q for q, _ in pool]
    scores = _score_candidates(qids)
    if scores:
        # Tie-break: prefer earlier in pool (wbsearchentities exact-label match
        # first, then Wikipedia fame-rank). max() is stable, so we negate index.
        best_qid = max(qids, key=lambda q: (scores.get(q, -1), -qids.index(q)))
        for qid, label in pool:
            if qid == best_qid:
                return qid, label
    # Scoring failed → return first pool entry (wbsearchentities top hit).
    return pool[0]


@lru_cache(maxsize=200)
def fetch_aliases(qid: str) -> Optional[tuple[tuple[str, str], ...]]:
    """Wikidata SPARQL: all labels + altLabels for the entity in the 8 langs.

    Returns a tuple of (label, lang) tuples (tuple so lru_cache can hold it).
    None on error.
    """
    lang_filter = ",".join(f'"{l}"' for l in LANGS)
    query = f"""
SELECT DISTINCT ?label ?lang WHERE {{
  VALUES ?item {{ wd:{qid} }}
  {{ ?item rdfs:label ?label . }}
  UNION
  {{ ?item skos:altLabel ?label . }}
  BIND(LANG(?label) AS ?lang)
  FILTER(?lang IN ({lang_filter}))
}}
"""
    data = _http_get_json(SPARQL_URL, {"query": query, "format": "json"})
    if not data:
        return None
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for b in data.get("results", {}).get("bindings", []):
        label = b.get("label", {}).get("value")
        lang = b.get("lang", {}).get("value", "")
        if not label or (label, lang) in seen:
            continue
        seen.add((label, lang))
        out.append((label, lang))
    return tuple(out)


def _alias_passes_filter(alias: str) -> bool:
    if len(alias) < MIN_ALIAS_LEN:
        return False
    if alias.startswith("@"):
        return False
    return True


def resolve(name_or_qid: str, prefer: str = "person") -> Optional[dict]:
    """Combined resolution. Returns a dict:
        {
          "qid": "Q22686",
          "primary_label": "Donald Trump",
          "aliases": [{"label": "...", "lang": "..."}],
          "filtered_aliases": [...],
        }
    or None if the entity can't be found.

    prefer="person" (default) biases the search toward prominent humans
    (politicians, etc.), avoiding less notable namesakes for queries like
    "Zelensky". Pass prefer="any" for raw top-hit behavior.
    """
    name_or_qid = (name_or_qid or "").strip()
    if not name_or_qid:
        return None
    if QID_RE.match(name_or_qid):
        qid = name_or_qid.upper()
        primary_label = None
    else:
        hit = resolve_qid_from_name(name_or_qid, prefer)
        if not hit:
            return None
        qid, primary_label = hit
    aliases = fetch_aliases(qid)
    if aliases is None:
        return None
    if primary_label is None and aliases:
        en_labels = [a for a, l in aliases if l == "en"]
        primary_label = en_labels[0] if en_labels else aliases[0][0]
    alias_dicts = [{"label": a, "lang": l} for a, l in aliases]
    filtered = [{"label": a, "lang": l} for a, l in aliases if _alias_passes_filter(a)]
    return {
        "qid": qid,
        "primary_label": primary_label,
        "aliases": alias_dicts,
        "filtered_aliases": filtered,
    }


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    if len(argv) < 2:
        print("Usage: python3 echolot_entities.py <name_or_qid>", file=sys.stderr)
        return 2
    r = resolve(argv[1])
    if r is None:
        print("Not found.", file=sys.stderr)
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
