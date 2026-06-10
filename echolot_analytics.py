"""Echolot F1 analytical MCP tools — read-side aggregation over the classifier
columns (frame/emotion/sentiment) and the entity-role table.

These back the §2.6 tools frame_divergence / source_profile / entity_portrait.
They ONLY aggregate what the classifier/translator workers have written; they
never call an LLM. Until the classifier runs they degrade gracefully — every
response carries a `classification_coverage` block and a clear note instead of
pretending data exists (weakest-agent rule).

Pure functions taking db_path; the server wraps them as @mcp.tool().
"""
from __future__ import annotations

import json
import re
import shlex
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone

from echolot_sphere_taxonomy import dedup_spheres, CHILD_TO_PARENT

FRAMES = ["conflict", "human_interest", "economic", "morality", "vulnerability",
          "responsibility", "security_threat", "progress", "other"]
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
         "az", "egy", "es", "hogy", "nem", "der", "die", "das", "und", "von"}


def _conn(db_path):
    c = sqlite3.connect(str(db_path), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _strip(s):
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def _terms(query):
    try:
        toks = shlex.split(query)
    except ValueError:
        toks = query.split()
    out, seen = [], set()
    for t in toks:
        n = "".join(ch for ch in _strip(t.lower()) if ch.isalnum())
        if len(n) > 2 and n not in _STOP and n not in seen:
            seen.add(n); out.append(n)
    return out


def _fts_and(query):
    ts = _terms(query)
    return (" AND ".join(f"{t}*" for t in ts), ts) if ts else (None, [])


def _since(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def _family(sphere):
    return CHILD_TO_PARENT.get(sphere, sphere)


def _coverage(rows_total, rows_classified):
    pct = round(100 * rows_classified / rows_total) if rows_total else 0
    note = None
    if rows_total == 0:
        note = "No matching articles in the window."
    elif rows_classified == 0:
        note = ("F1 classifier has not run yet — frame/emotion/sentiment are pending. "
                "Coverage/structure is shown; enrich once classification is on.")
    elif pct < 100:
        note = f"{pct}% of matched articles classified so far; rest pending."
    return {"articles_total": rows_total, "articles_classified": rows_classified,
            "percent": pct, "note": note}


# ---------------------------------------------------------------------------
# frame_divergence — frame distribution per sphere for a topic (§2.6)
# ---------------------------------------------------------------------------
def frame_divergence(query, days=7, db_path="echolot.db"):
    days = max(1, min(90, int(days)))
    fts, terms = _fts_and(query)
    if fts is None:
        return {"error": "Query too short", "query": query}
    sql = """
        SELECT a.spheres_json, a.frame, a.classification_status
        FROM articles a JOIN articles_fts f ON f.article_id = a.article_id
        WHERE articles_fts MATCH ? AND a.published_at >= ?
        LIMIT 2000
    """
    conn = _conn(db_path)
    try:
        try:
            rows = conn.execute(sql, (fts, _since(days))).fetchall()
        except sqlite3.OperationalError as e:
            return {"error": f"FTS error: {e}", "query": query}
    finally:
        conn.close()

    by_sphere = {}
    n_class = 0
    for r in rows:
        classified = r["classification_status"] == "ok" and r["frame"]
        if classified:
            n_class += 1
        for sph in dedup_spheres(json.loads(r["spheres_json"] or "[]")):
            d = by_sphere.setdefault(sph, {"articles": 0, "frames": {}})
            d["articles"] += 1
            if classified:
                d["frames"][r["frame"]] = d["frames"].get(r["frame"], 0) + 1
    out = {}
    for sph, d in sorted(by_sphere.items(), key=lambda kv: -kv[1]["articles"]):
        dom = max(d["frames"].items(), key=lambda kv: kv[1])[0] if d["frames"] else None
        out[sph] = {"articles": d["articles"], "dominant_frame": dom,
                    "frame_distribution": d["frames"]}
    return {
        "query": query, "fts_query": fts, "days": days,
        "spheres_found": len(out),
        "by_sphere": out,
        "frame_taxonomy": FRAMES,
        "classification_coverage": _coverage(len(rows), n_class),
    }


# ---------------------------------------------------------------------------
# source_profile — per-source frame/emotion/sentiment intelligence (§2.4/§2.6)
# ---------------------------------------------------------------------------
def source_profile(source="", days=30, limit=40, db_path="echolot.db"):
    days = max(1, min(90, int(days)))
    limit = max(1, min(200, int(limit)))
    where = "a.published_at >= ?"
    params = [_since(days)]
    if source:
        where += " AND LOWER(a.source_name) LIKE LOWER(?)"
        params.append(f"%{source}%")
    sql = f"""
        SELECT a.source_name, s.lean, s.trust_tier, s.spheres_json,
               a.frame, a.emotion, a.sentiment, a.classification_status
        FROM articles a JOIN sources s ON s.id = a.source_id
        WHERE {where}
    """
    conn = _conn(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    prof = {}
    n_class = 0
    for r in rows:
        p = prof.setdefault(r["source_name"], {
            "articles": 0, "lean": r["lean"], "trust_tier": r["trust_tier"],
            "spheres": dedup_spheres(json.loads(r["spheres_json"] or "[]")),
            "frames": {}, "emotions": {}, "_sent_sum": 0.0, "_sent_n": 0})
        p["articles"] += 1
        if r["classification_status"] == "ok":
            n_class += 1
            if r["frame"]:
                p["frames"][r["frame"]] = p["frames"].get(r["frame"], 0) + 1
            if r["emotion"]:
                p["emotions"][r["emotion"]] = p["emotions"].get(r["emotion"], 0) + 1
            if r["sentiment"] is not None:
                p["_sent_sum"] += r["sentiment"]; p["_sent_n"] += 1
    out = {}
    for name, p in sorted(prof.items(), key=lambda kv: -kv[1]["articles"])[:limit]:
        avg = round(p["_sent_sum"] / p["_sent_n"], 3) if p["_sent_n"] else None
        dom = max(p["frames"].items(), key=lambda kv: kv[1])[0] if p["frames"] else None
        out[name] = {"articles": p["articles"], "lean": p["lean"],
                     "trust_tier": p["trust_tier"], "spheres": p["spheres"],
                     "dominant_frame": dom, "frame_distribution": p["frames"],
                     "emotion_distribution": p["emotions"], "avg_sentiment": avg}
    return {
        "source_filter": source or "all", "days": days, "sources": len(out),
        "profiles": out,
        "classification_coverage": _coverage(len(rows), n_class),
    }


# ---------------------------------------------------------------------------
# entity_portrait — entity coverage + sentiment + role per sphere (§2.3/§2.6)
# ---------------------------------------------------------------------------
def entity_portrait(name_or_qid, days=30, db_path="echolot.db"):
    days = max(1, min(90, int(days)))
    # Resolve entity to its multilingual aliases (works today; no LLM).
    try:
        from echolot_entities import resolve as resolve_entity, fetch_aliases
    except Exception:
        resolve_entity = None
    qid = primary = None
    aliases = []
    if resolve_entity:
        res = resolve_entity(name_or_qid)
        if res:
            qid = res.get("qid"); primary = res.get("primary_label")
            aliases = [a.get("label") for a in (res.get("aliases") or res.get("filtered_aliases") or []) if a.get("label")]
    if not aliases:
        aliases = [name_or_qid]
    quoted = " OR ".join(f'"{a}"' for a in aliases[:25] if a)
    sql = """
        SELECT a.spheres_json, a.source_name, a.frame, a.emotion, a.sentiment,
               a.classification_status, a.published_at
        FROM articles a JOIN articles_fts f ON f.article_id = a.article_id
        WHERE articles_fts MATCH ? AND a.published_at >= ?
        LIMIT 2000
    """
    conn = _conn(db_path)
    roles = []
    try:
        try:
            rows = conn.execute(sql, (quoted, _since(days))).fetchall() if quoted else []
        except sqlite3.OperationalError:
            rows = []
        # entity-role rows (populated by the classifier's entity pass — may be empty)
        if qid:
            try:
                roles = conn.execute(
                    """SELECT role, COUNT(*) n, AVG(sentiment) s FROM article_entities
                       WHERE qid=? GROUP BY role""", (qid,)).fetchall()
            except sqlite3.OperationalError:
                roles = []
    finally:
        conn.close()

    by_sphere, by_source = {}, {}
    n_class = 0
    sent_sum = sent_n = 0
    for r in rows:
        if r["classification_status"] == "ok":
            n_class += 1
            if r["sentiment"] is not None:
                sent_sum += r["sentiment"]; sent_n += 1
        for sph in dedup_spheres(json.loads(r["spheres_json"] or "[]")):
            by_sphere[sph] = by_sphere.get(sph, 0) + 1
        by_source[r["source_name"]] = by_source.get(r["source_name"], 0) + 1
    role_dist = {r["role"]: {"mentions": r["n"], "avg_sentiment": round(r["s"], 3) if r["s"] is not None else None}
                 for r in roles if r["role"]}
    return {
        "input": name_or_qid, "qid": qid, "primary_label": primary,
        "alias_count": len(aliases), "days": days,
        "articles": len(rows),
        "avg_sentiment": round(sent_sum / sent_n, 3) if sent_n else None,
        "by_sphere": dict(sorted(by_sphere.items(), key=lambda kv: -kv[1])),
        "top_sources": dict(sorted(by_source.items(), key=lambda kv: -kv[1])[:15]),
        "role_distribution": role_dist,  # empty until the entity-role pass runs
        "classification_coverage": _coverage(len(rows), n_class),
    }
