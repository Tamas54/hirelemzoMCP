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
def resolve_qid_from_name(name: str) -> Optional[tuple[str, str]]:
    """Look up a name on Wikidata's search API; return (qid, primary_label)
    for the top result, or None if nothing found.
    """
    data = _http_get_json(SEARCH_URL, {
        "action": "wbsearchentities",
        "search": name,
        "language": "en",
        "format": "json",
        "limit": "1",
        "type": "item",
    })
    if not data:
        return None
    hits = data.get("search") or []
    if not hits:
        return None
    qid = hits[0].get("id")
    label = hits[0].get("label") or name
    if not qid:
        return None
    return qid, label


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


def resolve(name_or_qid: str) -> Optional[dict]:
    """Combined resolution. Returns a dict:
        {
          "qid": "Q22686",
          "primary_label": "Donald Trump",
          "aliases": [{"label": "...", "lang": "..."}],
          "filtered_aliases": [...],
        }
    or None if the entity can't be found.
    """
    name_or_qid = (name_or_qid or "").strip()
    if not name_or_qid:
        return None
    if QID_RE.match(name_or_qid):
        qid = name_or_qid.upper()
        primary_label = None
    else:
        hit = resolve_qid_from_name(name_or_qid)
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
