"""Blindspot detector — sphere-aszimmetria sztorikat keres.

Két dimenzió:
  - politikai: L/R bias-aszimmetria (csak baloldal vagy csak jobboldal hozza)
  - geo: csak egy regionális sphere hozza (csak regional_chinese,
    csak regional_us, etc.) miközben a globális anchor-szférák nem hozzák.

Tipikus használat:
    from echolot_blindspot import find_political_blindspots, find_geo_blindspots
    pol = find_political_blindspots("echolot.db", hours=24, limit=8)
    geo = find_geo_blindspots("echolot.db", hours=24, limit=8)

A modul saját egyszerűsített clusteringet használ (Jaccard-overlap a
normalizált címek tokenjein). Ha a testvér-modul `echolot_top_stories`
elérhető és exportál egy `cluster_top_stories` fn-t, azt használjuk
helyette.

CLI:
    python3 echolot_blindspot.py [echolot.db] [hours]
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("echolot.blindspot")

CACHE_TTL = 900  # 15 minutes
_cache: dict[tuple, tuple[float, Any]] = {}


# --------------------------------------------------------------------------
# Optional reuse of sibling top_stories clustering
# --------------------------------------------------------------------------
try:  # pragma: no cover — optional sibling
    from echolot_top_stories import cluster_top_stories as _sibling_cluster  # type: ignore
except Exception:  # noqa: BLE001
    _sibling_cluster = None


# --------------------------------------------------------------------------
# Sphere / lean → bias mapping (kept in sync with echolot_top_stories)
# --------------------------------------------------------------------------
ANCHOR_SPHERES: frozenset[str] = frozenset({
    "regional_us",
    "regional_uk",
    "regional_german",
    "regional_french",
    "global_anchor",
})

# Spheres that, combined with lean=gov, push the source to the R bucket
# (state propaganda from authoritarian regimes — treated as right/regime side
# in line with Ground News' "Lean" axis on similar outlets).
_GOV_R_SPHERES: frozenset[str] = frozenset({
    "cn_state",
    "ru_state_media",
    "iran_regime",
})

# Public-service broadcasters whose lean=gov should map to Center.
_PUBLIC_SERVICE_NAMES: frozenset[str] = frozenset({
    "BBC", "BBC News",
    "ARD", "ARD Tagesschau",
    "NHK", "NHK World",
    "RAI", "RAI News",
    "France Inter", "France Info", "Radio France",
    "RTVE", "RTVE Noticias",
    "RTÉ", "RTE", "RTÉ News",
})

# Specific regional spheres that count as "non-anchor regional" for geo
# blindspot detection. We derive this dynamically from PARENT_TO_CHILDREN
# but maintain a fallback for when the taxonomy module is missing.
_FALLBACK_REGIONAL_SPHERES: frozenset[str] = frozenset({
    "regional_chinese", "regional_indian", "regional_african",
    "regional_iranian", "regional_arabic", "regional_turkish",
    "regional_japanese", "regional_korean", "regional_russian",
    "regional_ukrainian", "regional_israeli", "regional_australian",
    "regional_south_american", "regional_spanish", "regional_v4",
})

try:
    from echolot_sphere_taxonomy import PARENT_TO_CHILDREN as _PARENT_TO_CHILDREN
    REGIONAL_SPHERES: frozenset[str] = frozenset(
        sph for sph in _PARENT_TO_CHILDREN.keys() if sph not in ANCHOR_SPHERES
    ) | _FALLBACK_REGIONAL_SPHERES
except Exception:  # noqa: BLE001
    REGIONAL_SPHERES = _FALLBACK_REGIONAL_SPHERES


def lean_to_bias(lean: str | None, source_name: str | None,
                 spheres: Iterable[str] | None) -> str:
    """Map (lean, source_name, spheres) → 'L' | 'C' | 'R'.

    Rules (must mirror echolot_top_stories):
      - left, opposition          → L
      - right, right_independent  → R
      - gov + cn_state/ru_state_media/iran_regime → R
      - gov + public-service broadcaster name     → C
      - gov (other)               → C   (default-safe; many regional gov outlets
                                          are de-facto centrist on global stories)
      - center, analytical, independent, unknown, None → C
    """
    if not lean:
        return "C"
    lean = lean.lower().strip()
    if lean in ("left", "opposition"):
        return "L"
    if lean in ("right", "right_independent"):
        return "R"
    if lean == "gov":
        sph_set = set(spheres or [])
        if sph_set & _GOV_R_SPHERES:
            return "R"
        if source_name and source_name in _PUBLIC_SERVICE_NAMES:
            return "C"
        return "C"
    return "C"  # center, analytical, independent, unknown


# --------------------------------------------------------------------------
# Stop-words & title normalisation (kept simple & multi-lingual safe)
# --------------------------------------------------------------------------
_STOP_WORDS: frozenset[str] = frozenset({
    # English
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "by", "at", "from", "as", "is", "are", "was", "were", "be",
    "been", "has", "have", "had", "will", "would", "could", "should",
    "this", "that", "these", "those", "it", "its", "his", "her", "their",
    "they", "them", "we", "us", "our", "you", "your", "he", "she",
    "after", "before", "over", "under", "into", "out", "up", "down",
    "new", "says", "say", "said", "report", "reports", "reported",
    "vs", "via", "amid", "amidst", "during", "while", "than", "then",
    # Hungarian (small set)
    "a", "az", "egy", "és", "vagy", "de", "hogy", "ki", "be", "fel",
    "le", "el", "meg", "is", "csak", "már", "még", "után", "előtt",
    "miatt", "szerint", "lett", "van", "volt", "lesz",
    # German
    "der", "die", "das", "und", "oder", "aber", "von", "zu", "mit", "im",
    "auf", "für", "ist", "sind", "war", "waren", "wird", "werden",
    # French
    "le", "la", "les", "un", "une", "et", "ou", "mais", "de", "du", "des",
    "à", "au", "aux", "sur", "pour", "par", "avec", "sans", "dans",
})

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿĀ-žА-я]+", re.UNICODE)


def _tokenize(title: str) -> set[str]:
    """Lower-case word tokens, length≥3, stop-words removed."""
    if not title:
        return set()
    toks = _WORD_RE.findall(title.lower())
    return {t for t in toks if len(t) >= 3 and t not in _STOP_WORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------
def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v]
    except Exception:  # noqa: BLE001
        pass
    return []


def _fetch_articles(
    conn: sqlite3.Connection, hours: int, lang: str | None = None
) -> list[dict[str, Any]]:
    """Articles within `hours` joined with source lean/spheres.

    Ha `lang` megadva, csak az adott nyelvű cikkeket adja vissza.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    if lang:
        cur = conn.execute(
            """
            SELECT a.article_id, a.title, a.lead, a.url,
                   a.source_id, a.source_name, a.language,
                   a.published_at, a.spheres_json AS article_spheres,
                   s.lean        AS source_lean,
                   s.spheres_json AS source_spheres
              FROM articles a
              LEFT JOIN sources s ON s.id = a.source_id
             WHERE a.published_at >= ? AND a.language = ?
            """,
            (cutoff, lang),
        )
    else:
        cur = conn.execute(
            """
            SELECT a.article_id, a.title, a.lead, a.url,
                   a.source_id, a.source_name, a.language,
                   a.published_at, a.spheres_json AS article_spheres,
                   s.lean        AS source_lean,
                   s.spheres_json AS source_spheres
              FROM articles a
              LEFT JOIN sources s ON s.id = a.source_id
             WHERE a.published_at >= ?
            """,
            (cutoff,),
        )
    out: list[dict[str, Any]] = []
    for r in cur.fetchall():
        spheres = _safe_json_list(r["source_spheres"]) or _safe_json_list(r["article_spheres"])
        out.append({
            "article_id": r["article_id"],
            "title": r["title"] or "",
            "lead": r["lead"] or "",
            "url": r["url"] or "",
            "source_id": r["source_id"] or "",
            "source_name": r["source_name"] or "",
            "language": r["language"] or "",
            "published_at": r["published_at"] or "",
            "spheres": spheres,
            "lean": (r["source_lean"] or "unknown"),
            "bias": lean_to_bias(r["source_lean"], r["source_name"], spheres),
            "_tokens": _tokenize(r["title"] or ""),
        })
    return out


# --------------------------------------------------------------------------
# Clustering (own simplified) — Jaccard ≥ threshold over title tokens.
# --------------------------------------------------------------------------
def _own_cluster(
    articles: list[dict[str, Any]],
    *,
    sim_threshold: float = 0.5,
    min_tokens: int = 3,
) -> list[list[dict[str, Any]]]:
    """Greedy single-pass clustering.

    Each article either joins the first existing cluster whose representative
    token-set Jaccard-overlaps it >= sim_threshold, or starts a new cluster.
    O(n^2) on cluster count; fine for the typical few-hundred-articles/24h.

    Articles whose tokenized title has fewer than `min_tokens` tokens are
    skipped (too short to cluster reliably — would create false neighbours).
    """
    clusters: list[dict[str, Any]] = []  # {"rep": set[str], "items": list[...]}
    for art in articles:
        toks = art["_tokens"]
        if len(toks) < min_tokens:
            continue
        best_idx = -1
        best_sim = sim_threshold
        for i, c in enumerate(clusters):
            sim = _jaccard(toks, c["rep"])
            if sim >= best_sim:
                best_sim = sim
                best_idx = i
        if best_idx >= 0:
            clusters[best_idx]["items"].append(art)
            # Update representative as token intersection of first 3 items
            # to stabilise drift; simpler: keep first.
        else:
            clusters.append({"rep": set(toks), "items": [art]})
    return [c["items"] for c in clusters]


def _cluster(articles: list[dict[str, Any]],
             *,
             sim_threshold: float = 0.5) -> list[list[dict[str, Any]]]:
    """Try sibling top_stories clustering first, fall back to own."""
    if _sibling_cluster is not None:
        try:
            res = _sibling_cluster(articles, sim_threshold=sim_threshold)  # type: ignore[misc]
            # Expect list[list[dict]]; if it returns dict-wrapped clusters, normalise.
            if res and isinstance(res, list):
                if isinstance(res[0], dict) and "items" in res[0]:
                    return [c["items"] for c in res]
                if isinstance(res[0], list):
                    return res
        except Exception as exc:  # noqa: BLE001
            logger.debug("Sibling cluster_top_stories failed: %s — using own", exc)
    return _own_cluster(articles, sim_threshold=sim_threshold)


# --------------------------------------------------------------------------
# Cluster summarisation helpers
# --------------------------------------------------------------------------
def _bias_distribution(items: list[dict[str, Any]]) -> dict[str, int]:
    """Bias-percentage dist (0-100, summing to ~100) over distinct sources."""
    by_source: dict[str, str] = {}
    for it in items:
        sid = it["source_id"] or it["source_name"]
        if sid not in by_source:
            by_source[sid] = it["bias"]
    total = len(by_source)
    if total == 0:
        return {"L": 0, "C": 0, "R": 0}
    counts = {"L": 0, "C": 0, "R": 0}
    for b in by_source.values():
        counts[b] = counts.get(b, 0) + 1
    return {k: round(100 * v / total) for k, v in counts.items()}


def _cluster_sphere_set(items: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for it in items:
        out.update(it["spheres"])
    return out


def _distinct_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One representative item per source (the earliest one)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    # Sort by published_at asc so the lead URL is the earliest.
    items_sorted = sorted(items, key=lambda x: x.get("published_at", ""))
    for it in items_sorted:
        sid = it["source_id"] or it["source_name"]
        if sid in seen:
            continue
        seen.add(sid)
        out.append(it)
    return out


def _lead(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the canonical lead article: earliest published with non-empty url."""
    items_sorted = sorted(items, key=lambda x: x.get("published_at", ""))
    for it in items_sorted:
        if it.get("url"):
            return it
    return items_sorted[0] if items_sorted else {}


# --------------------------------------------------------------------------
# Cache wrapper
# --------------------------------------------------------------------------
def _cached(key: tuple, producer):
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < CACHE_TTL:
        return hit[1]
    val = producer()
    _cache[key] = (now, val)
    return val


def clear_cache() -> None:
    _cache.clear()


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def find_political_blindspots(
    db_path: str,
    hours: int = 24,
    min_sources: int = 5,
    bias_threshold: float = 0.7,
    opposite_max: float = 0.10,
    limit: int = 8,
    lang: str | None = None,
) -> list[dict]:
    """Politikai-aszimmetria sztorik: csak L vagy csak R oldal hozza.

    Args:
        db_path: SQLite path.
        hours: window length, articles fresher than now-hours kept.
        min_sources: minimum distinct sources in the cluster.
        bias_threshold: dominant side's share (0-1) must be >= this.
        opposite_max: opposite side's share (0-1) must be <= this.
        limit: top N.
        lang: ha megadva, csak az adott nyelvű cikkek alapján clusterez.
    """
    cache_key = ("pol", db_path, hours, min_sources,
                 round(bias_threshold, 3), round(opposite_max, 3), limit, lang)
    return _cached(
        cache_key,
        lambda: _find_political_blindspots_uncached(
            db_path, hours, min_sources, bias_threshold, opposite_max, limit, lang
        ),
    )


def _find_political_blindspots_uncached(
    db_path: str,
    hours: int,
    min_sources: int,
    bias_threshold: float,
    opposite_max: float,
    limit: int,
    lang: str | None = None,
) -> list[dict]:
    t0 = time.time()
    conn = _connect(db_path)
    try:
        articles = _fetch_articles(conn, hours, lang=lang)
    finally:
        conn.close()
    clusters = _cluster(articles, sim_threshold=0.5)

    bt_pct = bias_threshold * 100.0
    op_pct = opposite_max * 100.0
    out: list[dict[str, Any]] = []
    for items in clusters:
        distinct = _distinct_sources(items)
        n_sources = len(distinct)
        if n_sources < min_sources:
            continue
        bias_dist = _bias_distribution(items)
        L, R = bias_dist["L"], bias_dist["R"]
        dominant: str | None = None
        if L >= bt_pct and R <= op_pct:
            dominant = "L"
        elif R >= bt_pct and L <= op_pct:
            dominant = "R"
        if dominant is None:
            continue
        sphere_set = sorted(_cluster_sphere_set(items))
        lead = _lead(items)
        sample = [d["source_name"] for d in distinct[:6] if d.get("source_name")]
        # asymmetry score = |L - R| (max 100)
        asymmetry = abs(L - R)
        out.append({
            "title": lead.get("title", ""),
            "lead_url": lead.get("url", ""),
            "lead_source": lead.get("source_name", ""),
            "lead_published_at": lead.get("published_at", ""),
            "source_count": n_sources,
            "bias_dist": bias_dist,
            "dominant_side": dominant,
            "asymmetry": asymmetry,
            "sphere_set": sphere_set,
            "sample_sources": sample,
        })
    out.sort(key=lambda x: (x["asymmetry"], x["source_count"]), reverse=True)
    result = out[:limit]
    logger.info(
        "political_blindspots: %d clusters→%d hits in %.2fs (hours=%d)",
        len(clusters), len(result), time.time() - t0, hours,
    )
    return result


def find_geo_blindspots(
    db_path: str,
    hours: int = 24,
    min_sources: int = 3,
    limit: int = 8,
    lang: str | None = None,
) -> list[dict]:
    """Földrajzi-aszimmetria: csak egy regionális sphere hozza.

    A cluster akkor minősül geo-blindspotnak, ha:
      - legalább `min_sources` különálló forrásból jön,
      - a benne szereplő sphere-ek között VAN legalább 1 specifikus
        regionális sphere (regional_chinese, regional_indian, …),
      - és a globális anchor-szférák (regional_us, regional_uk,
        regional_german, regional_french, global_anchor) közül
        legfeljebb 1-et fed le (vagyis hiányzik ≥4 anchor).

    Ha `lang` megadva, csak az adott nyelvű cikkek alapján clusterez.
    """
    cache_key = ("geo", db_path, hours, min_sources, limit, lang)
    return _cached(
        cache_key,
        lambda: _find_geo_blindspots_uncached(db_path, hours, min_sources, limit, lang),
    )


def _find_geo_blindspots_uncached(
    db_path: str,
    hours: int,
    min_sources: int,
    limit: int,
    lang: str | None = None,
) -> list[dict]:
    t0 = time.time()
    conn = _connect(db_path)
    try:
        articles = _fetch_articles(conn, hours, lang=lang)
    finally:
        conn.close()
    clusters = _cluster(articles, sim_threshold=0.5)

    out: list[dict[str, Any]] = []
    for items in clusters:
        distinct = _distinct_sources(items)
        n_sources = len(distinct)
        if n_sources < min_sources:
            continue
        sphere_set = _cluster_sphere_set(items)
        regional_present = sphere_set & REGIONAL_SPHERES
        if not regional_present:
            continue
        anchor_present = sphere_set & ANCHOR_SPHERES
        if len(anchor_present) > 1:
            # Covered by mainstream — not a geo blindspot.
            continue
        # Determine the dominant geo sphere by source-count.
        per_sphere: dict[str, int] = defaultdict(int)
        for d in distinct:
            for sph in d["spheres"]:
                if sph in REGIONAL_SPHERES:
                    per_sphere[sph] += 1
        if not per_sphere:
            continue
        dominant_geo = max(per_sphere, key=lambda s: per_sphere[s])
        regional_source_count = per_sphere[dominant_geo]
        missing_anchors = sorted(ANCHOR_SPHERES - anchor_present)
        bias_dist = _bias_distribution(items)
        lead = _lead(items)
        sample = [d["source_name"] for d in distinct[:6] if d.get("source_name")]
        out.append({
            "title": lead.get("title", ""),
            "lead_url": lead.get("url", ""),
            "lead_source": lead.get("source_name", ""),
            "lead_published_at": lead.get("published_at", ""),
            "source_count": n_sources,
            "dominant_geo": dominant_geo,
            "regional_source_count": regional_source_count,
            "anchor_coverage": sorted(anchor_present),
            "missing_anchors": missing_anchors,
            "bias_dist": bias_dist,
            "sphere_set": sorted(sphere_set),
            "sample_sources": sample,
        })
    # Sort: more regional sources first, then fewer anchor coverage.
    out.sort(
        key=lambda x: (x["regional_source_count"], -len(x["anchor_coverage"]),
                       x["source_count"]),
        reverse=True,
    )
    result = out[:limit]
    logger.info(
        "geo_blindspots: %d clusters→%d hits in %.2fs (hours=%d)",
        len(clusters), len(result), time.time() - t0, hours,
    )
    return result


# --------------------------------------------------------------------------
# CLI smoke-test
# --------------------------------------------------------------------------
def _print_results(label: str, rows: list[dict]) -> None:
    print(f"\n=== {label}: {len(rows)} ===")
    for i, r in enumerate(rows, 1):
        print(f"\n[{i}] {r.get('title','')[:120]}")
        print(f"    lead: {r.get('lead_url','')}")
        print(f"    sources: {r.get('source_count',0)}  "
              f"bias_dist={r.get('bias_dist')}")
        if "dominant_side" in r:
            print(f"    dominant_side={r['dominant_side']}  "
                  f"asymmetry={r.get('asymmetry')}")
        if "dominant_geo" in r:
            print(f"    dominant_geo={r['dominant_geo']}  "
                  f"missing_anchors={r.get('missing_anchors')}")
        print(f"    sample: {', '.join(r.get('sample_sources', []))}")


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    db_path = argv[1] if len(argv) > 1 else "echolot.db"
    hours = int(argv[2]) if len(argv) > 2 else 24
    pol = find_political_blindspots(db_path, hours=hours)
    _print_results("POLITICAL BLINDSPOTS", pol)
    geo = find_geo_blindspots(db_path, hours=hours)
    _print_results("GEO BLINDSPOTS", geo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
