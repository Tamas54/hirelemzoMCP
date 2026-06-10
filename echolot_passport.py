"""Echolot narrative_passport — verify and trace any news claim or article URL.

This is the "killer tool" assembler. Given a short factual claim (any language)
OR a single article URL, it returns a structured "passport":

  - where the story first appeared (origin)
  - how it spread across the monitored media spheres (propagation chain)
  - which spheres cover it vs. which live spheres stay silent (corroboration matrix)
  - how the headline mutated between sources (mutation / headline diffs)
  - whether the spread pattern looks organic or coordinated (velocity)

COVERS/SILENT MODE (this build, no LLM):
  The assembler ONLY aggregates data already in the corpus — it never makes a
  synchronous per-article LLM call. Stance classification (confirms vs.
  contradicts) and frame genealogy require the F1/F3 batch classifier and are
  marked as deferred here. The spec explicitly green-lights shipping the
  covers/silent matrix without stance ("NE blokkold az F2-t az F3-ra várva").

IRON RULES (from spec §1.2):
  - verdict.one_line is ALWAYS filled (the weakest agent quotes it).
  - Empty result => corroboration_level "not_found" + coverage_stats, never an
    empty object or a bare error string.
  - All timestamps are UTC ISO-8601.
  - citations: max 10, always with URL.
  - "silent" is computed ONLY against spheres_monitored_live — a dead/configured
    sphere is not silence.

Public API:
  build_passport(claim_or_url, *, time_window_days=14, language="auto",
                 detail="summary", db_path=...) -> dict
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from echolot_sphere_taxonomy import dedup_spheres, CHILD_TO_PARENT

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_WINDOW_DAYS = 14
MAX_WINDOW_DAYS = 90
MAX_ARTICLES = 1000
MAX_PROPAGATION = 40
MAX_CITATIONS = 10
CACHE_TTL_SECONDS = 3600  # 1h, per spec
CACHE_MAXSIZE = 500  # hard cap on cached passports (bounded memory)
LIVE_SPHERE_MAX_AGE_HOURS = 24  # green+yellow definition shared with get_spheres

# Minimal stopword set for similarity tokenization (multilingual-light).
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "as", "at", "by", "it", "its", "with", "from", "that",
    "this", "has", "have", "had", "but", "not", "no", "new", "says", "said",
    "az", "egy", "es", "is", "hogy", "nem", "meg", "ki", "be", "el", "fel",
    "der", "die", "das", "und", "von", "den", "im", "le", "la", "les", "des",
    "et", "que", "el", "los", "las", "y", "de", "por", "con",
}


# ---------------------------------------------------------------------------
# Text + time utilities
# ---------------------------------------------------------------------------
def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_tokens(text: str) -> list[str]:
    """Lowercase, accent-strip, split to alnum tokens, drop short/stopwords."""
    if not text:
        return []
    low = _strip_accents(text.lower())
    return [t for t in _WORD_RE.findall(low) if len(t) > 2 and t not in _STOP]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return round(inter / union, 3) if union else 0.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(ts: str | None) -> datetime | None:
    """Parse a mixed-offset published_at into a tz-aware UTC datetime."""
    if not ts:
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Last resort: take the leading date.
        try:
            dt = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _build_fts_match(query: str) -> tuple[str | None, list[str]]:
    """Local FTS5 AND-builder (mirrors server._build_fts_query, no import cycle).

    "russia ceasefire" -> '"russia" AND "ceasefire"'. Phrase-aware via shlex.
    """
    try:
        tokens = shlex.split(query)
    except ValueError:
        tokens = query.split()
    terms = [t for t in tokens if len(t) > 2]
    if not terms:
        return None, []
    parts = [f'"{t}"' for t in terms]
    return " AND ".join(parts), terms


def _looks_like_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.IGNORECASE))


# ---------------------------------------------------------------------------
# Sphere helpers
# ---------------------------------------------------------------------------
def _family(sphere: str) -> str:
    """Map a sphere to its taxonomy family (parent) or itself if standalone."""
    return CHILD_TO_PARENT.get(sphere, sphere)


def _article_spheres(spheres_json: str | None) -> list[str]:
    try:
        raw = json.loads(spheres_json or "[]")
    except (ValueError, TypeError):
        return []
    return dedup_spheres(raw)


def _live_spheres(conn: sqlite3.Connection) -> set[str]:
    """Spheres with at least one article in the last LIVE_SPHERE_MAX_AGE_HOURS.

    This is the ONLY valid basis for a 'silent' diagnosis (spec iron rule).
    """
    rows = conn.execute(
        f"""
        SELECT DISTINCT je.value AS sphere
        FROM articles a, json_each(a.spheres_json) je
        WHERE a.published_at IS NOT NULL
          AND (julianday('now') - julianday(a.published_at)) * 24
              <= {LIVE_SPHERE_MAX_AGE_HOURS}
          AND (julianday('now') - julianday(a.published_at)) * 24 >= 0
        """
    ).fetchall()
    live = {r[0] for r in rows if r[0]}
    return set(dedup_spheres(sorted(live)))


# ---------------------------------------------------------------------------
# URL branch (no LLM): claim = og:title / extracted title
# ---------------------------------------------------------------------------
def _extract_from_url(url: str) -> dict:
    """Best-effort claim extraction from an article URL, LLM-free.

    Strategy: OG fast-path (og:title/og:description) → on failure return a
    minimal stub. We deliberately avoid any model call; the title IS the claim
    surface for covers/silent matching.
    """
    from echolot_og_fastpath import fetch_og  # local import keeps module light

    headline = ""
    lead = ""
    try:
        og = fetch_og(url, timeout=10)
    except Exception:
        og = None
    if og:
        headline = (og.get("title") or "").strip()
        lead = (og.get("text") or "").strip()
    claim = headline or lead
    return {
        "claim": claim,
        "headline": headline,
        "lead": lead,
        "url": url,
        "ok": bool(claim),
    }


# ---------------------------------------------------------------------------
# Article retrieval
# ---------------------------------------------------------------------------
def _find_articles(conn: sqlite3.Connection, query: str, days: int) -> tuple[list[dict], str | None]:
    fts, terms = _build_fts_match(query)
    if fts is None:
        return [], None
    since = (_now_utc() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    sql = """
        SELECT a.article_id, a.title, a.lead, a.url, a.source_name,
               a.published_at, a.language, a.spheres_json,
               s.lean, s.trust_tier
        FROM articles a
        JOIN articles_fts fts ON fts.article_id = a.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE articles_fts MATCH ?
          AND a.published_at >= ?
        ORDER BY a.published_at ASC
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, (fts, since, MAX_ARTICLES)).fetchall()
    except sqlite3.OperationalError:
        # Malformed FTS expression (e.g. stray quote in a weak-agent claim) or a
        # missing articles_fts/articles table on a fresh DB. Treat as no coverage
        # rather than crashing — the passport degrades to "not_found".
        return [], None
    out = []
    for r in rows:
        pub = _parse_utc(r["published_at"])
        if pub is None:
            continue
        title = r["title"] or ""
        lead = r["lead"] or ""
        out.append({
            "article_id": r["article_id"],
            "title": title,
            "lead": lead[:400],
            "url": r["url"],
            "source": r["source_name"],
            "language": r["language"],
            "lean": r["lean"],
            "trust_tier": r["trust_tier"],
            "published_utc": _iso_utc(pub),
            "_pub_dt": pub,
            "_spheres": _article_spheres(r["spheres_json"]),
            "_tokens": set(_norm_tokens(f"{title} {lead}")),
        })
    out.sort(key=lambda a: a["_pub_dt"])
    return out, fts


# ---------------------------------------------------------------------------
# Origin + propagation chain
# ---------------------------------------------------------------------------
def _word_diff_note(origin_title: str, later_title: str) -> str | None:
    """Cheap headline-diff note: surface added/removed salient words."""
    a = set(_norm_tokens(origin_title))
    b = set(_norm_tokens(later_title))
    removed = sorted(a - b)[:4]
    added = sorted(b - a)[:4]
    if not removed and not added:
        return None
    bits = []
    if removed:
        bits.append("dropped: " + ", ".join(removed))
    if added:
        bits.append("added: " + ", ".join(added))
    return "; ".join(bits)


def _build_origin_propagation(articles: list[dict]) -> tuple[dict | None, list[dict]]:
    if not articles:
        return None, []
    origin_a = articles[0]
    origin_dt = origin_a["_pub_dt"]
    origin = {
        "first_seen_utc": origin_a["published_utc"],
        "source": origin_a["source"],
        "sphere": (origin_a["_spheres"][0] if origin_a["_spheres"] else None),
        "spheres": origin_a["_spheres"],
        "article_url": origin_a["url"],
        "headline_original": origin_a["title"],
        "headline_translated": None,  # deferred (translation layer / F1)
    }
    origin_tokens = origin_a["_tokens"]
    propagation = []
    for i, a in enumerate(articles[1:], start=2):
        delay_min = round((a["_pub_dt"] - origin_dt).total_seconds() / 60.0)
        propagation.append({
            "order": i,
            "delay_minutes": delay_min,
            "source": a["source"],
            "sphere": (a["_spheres"][0] if a["_spheres"] else None),
            "spheres": a["_spheres"],
            "url": a["url"],
            "language": a["language"],
            "similarity_to_origin": _jaccard(origin_tokens, a["_tokens"]),
            "frame": None,                  # deferred (F1 frame classifier)
            "frame_shift_from_origin": None,  # deferred (F3)
            "headline_diff_note": _word_diff_note(origin_a["title"], a["title"]),
        })
        if len(propagation) >= MAX_PROPAGATION:
            break
    return origin, propagation


# ---------------------------------------------------------------------------
# Corroboration matrix (covers/silent mode — no stance)
# ---------------------------------------------------------------------------
def _build_corroboration(articles: list[dict], live: set[str]) -> dict:
    covering: set[str] = set()
    for a in articles:
        covering.update(a["_spheres"])
    covering = set(dedup_spheres(sorted(covering)))
    # Silent = live spheres that did NOT cover the story. Iron rule: only live.
    silent = sorted(live - covering)
    confirms = sorted(covering)

    # Heuristic silence note — flag conspicuous absences by family.
    covering_families = {_family(s) for s in covering}
    silent_families = {_family(s) for s in silent}
    note_bits = []
    if not confirms:
        note_bits.append("No live sphere covers this — story is absent from the monitored corpus.")
    else:
        western = {"regional_us", "us_liberal_press", "de_press", "fr_press",
                   "regional_western", "global_anchor"}
        if western & silent_families and not (western & covering_families):
            note_bits.append("Western mainstream spheres show zero coverage.")
        if len(covering_families) == 1:
            fam = next(iter(covering_families))
            note_bits.append(f"Coverage confined to a single sphere family ({fam}).")
    silence_note = " ".join(note_bits) if note_bits else (
        f"{len(silent)} live spheres carry no coverage of this story."
    )

    return {
        "mode": "covers_silent",
        "confirms": confirms,          # = "covers" in this mode
        "contradicts": [],             # deferred: needs stance classifier (F3)
        "silent": silent,
        "silence_note": silence_note,
        "stance_note": "confirms = spheres that cover the story. contradicts/refutes "
                       "is deferred to the F3 stance classifier; this matrix runs in "
                       "covers/silent mode.",
    }


# ---------------------------------------------------------------------------
# Mutation (headline diffs only — frame genealogy deferred)
# ---------------------------------------------------------------------------
def _build_mutation(articles: list[dict]) -> dict:
    if not articles:
        return {
            "frame_genealogy": [],
            "sentiment_drift": None,
            "key_fact_mutations": [],
        }
    origin = articles[0]
    mutations = []
    for a in articles[1:]:
        note = _word_diff_note(origin["title"], a["title"])
        if not note:
            continue
        sim = _jaccard(origin["_tokens"], a["_tokens"])
        mutations.append({
            "step": f"{origin['source']} -> {a['source']}",
            "from_headline": origin["title"],
            "to_headline": a["title"],
            "change": note,
            "similarity": sim,
            # severity heuristic: low similarity + a diff => more drift
            "severity": "high" if sim < 0.34 else ("medium" if sim < 0.6 else "low"),
        })
        if len(mutations) >= MAX_PROPAGATION:
            break
    return {
        "frame_genealogy": [],          # deferred (F1 frame classifier)
        "sentiment_drift": None,        # deferred (F1 sentiment)
        "key_fact_mutations": mutations,
    }


# ---------------------------------------------------------------------------
# Velocity / spread pattern
# ---------------------------------------------------------------------------
def _build_velocity(articles: list[dict]) -> dict:
    """Spread-shape heuristic from the matched set (no cross-sphere baseline).

    current_multiplier here = articles-in-first-4h / hourly-average over the
    whole observed span (a coarse burst index). Pattern is inferred from how
    self-similar the early articles are.
    """
    n = len(articles)
    if n < 2:
        return {
            "current_multiplier": None,
            "pattern": "insufficient_data",
            "pattern_evidence": f"Only {n} matching article(s); spread shape not computable.",
        }
    origin_dt = articles[0]["_pub_dt"]
    span_hours = max(
        (articles[-1]["_pub_dt"] - origin_dt).total_seconds() / 3600.0, 0.1
    )
    avg_per_hour = n / span_hours
    early = [a for a in articles
             if (a["_pub_dt"] - origin_dt).total_seconds() <= 4 * 3600]
    n_early = len(early)
    early_per_hour = n_early / 4.0
    multiplier = round(early_per_hour / avg_per_hour, 2) if avg_per_hour > 0 else None

    # Self-similarity of the early burst vs the origin.
    sims = [_jaccard(articles[0]["_tokens"], a["_tokens"]) for a in early[1:]]
    avg_sim = round(sum(sims) / len(sims), 3) if sims else 0.0

    if n_early >= 8 and avg_sim >= 0.4:
        pattern = "wire_syndication"
        evidence = (f"{n_early} articles within 4h with {int(avg_sim*100)}% mean "
                    f"headline-token identity — consistent with a common wire feed.")
    elif n_early >= 5 and avg_sim >= 0.55:
        pattern = "coordinated_suspect"
        evidence = (f"{n_early} near-identical articles within 4h "
                    f"({int(avg_sim*100)}% mean similarity) — unusually uniform.")
    else:
        pattern = "organic"
        evidence = (f"{n_early} articles in the first 4h, "
                    f"{int(avg_sim*100)}% mean similarity — varied phrasing.")
    return {
        "current_multiplier": multiplier,
        "articles_first_4h": n_early,
        "span_hours": round(span_hours, 1),
        "pattern": pattern,
        "pattern_evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
def _build_verdict(articles: list[dict], corroboration: dict, days: int,
                   live_count: int) -> dict:
    n = len(articles)
    sources = {a["source"] for a in articles}
    families = {_family(s) for a in articles for s in a["_spheres"]}
    nf = len(families)

    if n == 0:
        return {
            "corroboration_level": "not_found",
            "confidence": 0.0,
            "one_line": (f"No coverage found across {live_count} live spheres in the "
                         f"last {days} days. The claim is unverified by the corpus — "
                         f"absence here is not proof of falsehood."),
        }
    if len(sources) == 1:
        return {
            "corroboration_level": "single_source",
            "confidence": 0.25,
            "one_line": (f"Reported by a single source ({next(iter(sources))}); "
                         f"no independent corroboration in the corpus yet."),
        }
    if nf <= 1:
        return {
            "corroboration_level": "unverified",
            "confidence": 0.4,
            "one_line": (f"Covered by {len(sources)} sources but all within one sphere "
                         f"family — independent corroboration is weak."),
        }
    if nf == 2:
        return {
            "corroboration_level": "contested",
            "confidence": 0.6,
            "one_line": (f"Covered by {len(sources)} sources across 2 sphere families; "
                         f"stance divergence is possible (stance classification pending)."),
        }
    # nf >= 3
    silent_n = len(corroboration["silent"])
    conf = min(0.95, 0.6 + 0.08 * nf)
    return {
        "corroboration_level": "confirmed",
        "confidence": round(conf, 2),
        "one_line": (f"Covered by {len(sources)} sources across {nf} independent sphere "
                     f"families; {silent_n} live spheres stay silent. "
                     f"(Stance classification pending — covers/silent mode.)"),
    }


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------
def _passport_id(normalized_claim: str, now: datetime) -> str:
    h = hashlib.sha1(normalized_claim.encode("utf-8")).hexdigest()[:4]
    return f"np_{now.strftime('%Y-%m-%d')}_{h}"


# Simple in-process cache: key -> (expiry_epoch, passport_dict)
_CACHE: dict[tuple, tuple[float, dict]] = {}


def _cache_key(claim_or_url: str, days: int, language: str, detail: str) -> tuple:
    return (claim_or_url.strip().lower(), days, language, detail)


def build_passport(
    claim_or_url: str,
    *,
    time_window_days: int = DEFAULT_WINDOW_DAYS,
    language: str = "auto",
    detail: str = "summary",
    db_path: str | Path = "echolot.db",
) -> dict:
    """Build a narrative passport for a claim or article URL. See module docstring."""
    claim_or_url = (claim_or_url or "").strip()
    days = max(1, min(MAX_WINDOW_DAYS, int(time_window_days or DEFAULT_WINDOW_DAYS)))
    detail = detail if detail in ("summary", "full") else "summary"
    language = language or "auto"

    if not claim_or_url:
        # Even the degenerate input gets a well-formed passport (weakest-agent).
        now = _now_utc()
        return {
            "passport_id": _passport_id("", now),
            "input_type": "claim",
            "normalized_claim": "",
            "verdict": {
                "corroboration_level": "not_found",
                "confidence": 0.0,
                "one_line": "No claim or URL provided — nothing to verify.",
            },
            "coverage_stats": {"articles_analyzed": 0, "spheres_with_coverage": 0,
                               "spheres_monitored_live": 0, "languages": []},
            "data_freshness_utc": _iso_utc(now),
        }

    ck = _cache_key(claim_or_url, days, language, detail)
    hit = _CACHE.get(ck)
    if hit and hit[0] > time.time():
        cached = dict(hit[1])
        cached["cached"] = True
        return cached

    is_url = _looks_like_url(claim_or_url)
    if is_url:
        extracted = _extract_from_url(claim_or_url)
        normalized_claim = extracted["claim"] or claim_or_url
        input_type = "url"
        search_text = extracted["claim"] or ""
    else:
        normalized_claim = claim_or_url
        input_type = "claim"
        search_text = claim_or_url

    now = _now_utc()
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            live = _live_spheres(conn)
        except sqlite3.OperationalError:
            live = set()  # fresh/empty DB with no articles table yet
        articles, fts = _find_articles(conn, search_text, days) if search_text else ([], None)
    finally:
        conn.close()

    live_count = len(live)
    origin, propagation = _build_origin_propagation(articles)
    corroboration = _build_corroboration(articles, live)
    mutation = _build_mutation(articles)
    velocity = _build_velocity(articles)
    verdict = _build_verdict(articles, corroboration, days, live_count)

    langs = sorted({a["language"] for a in articles if a["language"]})
    citations = [
        {"source": a["source"], "url": a["url"],
         "published_utc": a["published_utc"],
         "sphere": (a["_spheres"][0] if a["_spheres"] else None)}
        for a in articles[:MAX_CITATIONS]
    ]
    coverage_stats = {
        "articles_analyzed": len(articles),
        "spheres_with_coverage": len({s for a in articles for s in a["_spheres"]}),
        "spheres_monitored_live": live_count,
        "languages": langs,
        "time_window_days": days,
        "fts_query": fts,
    }

    passport = {
        "passport_id": _passport_id(normalized_claim, now),
        "input_type": input_type,
        "normalized_claim": normalized_claim,
        "language": language,
        "verdict": verdict,
        "origin": origin,
        "corroboration_matrix": corroboration,
        "velocity": velocity,
        "coverage_stats": coverage_stats,
        "citations": citations,
        "data_freshness_utc": _iso_utc(now),
        "cached": False,
    }
    if detail == "full":
        passport["propagation"] = propagation
        passport["mutation"] = mutation
    else:
        # Summary still carries a compact mutation signal (count only).
        passport["mutation_summary"] = {
            "headline_mutations": len(mutation["key_fact_mutations"]),
            "frame_genealogy": [],  # deferred
        }
        passport["propagation_count"] = len(propagation)

    # Bounded cache: purge expired entries, then hard-cap size so a long-running
    # server with many distinct claims cannot leak memory (each entry holds up to
    # MAX_CITATIONS citations + verdict; full-detail passports are larger).
    if len(_CACHE) >= CACHE_MAXSIZE:
        now_ts = time.time()
        for k in [k for k, (exp, _) in _CACHE.items() if exp <= now_ts]:
            del _CACHE[k]
        if len(_CACHE) >= CACHE_MAXSIZE:
            for k in list(_CACHE.keys())[: CACHE_MAXSIZE // 2]:
                del _CACHE[k]
    _CACHE[ck] = (time.time() + CACHE_TTL_SECONDS, passport)
    return passport


def build_passport_json(*args, **kwargs) -> str:
    """Convenience: build_passport() serialized to a JSON string (MCP return)."""
    p = build_passport(*args, **kwargs)
    return json.dumps(p, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    db = "echolot.db"
    claim = sys.argv[1] if len(sys.argv) > 1 else "iran nuclear"
    det = sys.argv[2] if len(sys.argv) > 2 else "summary"
    print(json.dumps(build_passport(claim, detail=det, db_path=db),
                     ensure_ascii=False, indent=2, default=str))
