"""Napi vezetői brief — az oldal "önmagát szerkesztő" címlapja.

UX-teszter kérés (2026-06-11): "minden napra - minden nyelvről egy vezetői
briefet ír — mi uralja a narratívát ma, mire keresnek az emberek, mi uralta
tegnap — és így követhetővé válik, melyik téma laposodik, melyik tör előre."

Működés:
  - Naponta (Europe/Budapest dátum-kulcs) és UI-nyelvenként EGY brief,
    a `daily_briefs` táblában cache-elve. A nap folyamán REFRESH_HOURS
    óránként frissül (a "ma" képe változik); a múlt napok véglegesek.
  - Input: az elmúlt 24h globális top-clusterei + a kért nyelv top-sztorijai
    + top-entitások ("mire keresnek") + a TEGNAPI brief témái (trend-
    összevetéshez). Egyetlen LLM-hívás (SiliconFlow, classifier-kulcs).
  - Output JSON: headline + lead + témák (cím, 1-2 mondat, trend-jelölő:
    new/rising/steady/fading, cluster-hivatkozás → /story link) + kitekintő.
  - KEY-GATED: kulcs nélkül no-op (a landing-blokk és a /brief oldal
    "nem elérhető" hintet mutat).

Worker: 10 percenként ellenőrzi, hogy a mai HU+EN brief létezik/friss-e.
Más nyelvek az első /brief látogatáskor készülnek (on-demand kick).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Budapest")
except Exception:  # pragma: no cover
    _TZ = timezone(timedelta(hours=2))

from echolot_classifier import _config as _shared_config, _parse_json_lenient

log = logging.getLogger("echolot.daily_brief")

REQUEST_TIMEOUT = 120
REFRESH_HOURS = 4          # a MAI brief ennyi óránként frissül
WORKER_INTERVAL_S = 600    # worker ciklus
AUTO_LANGS = ("hu", "en")  # ezekre a worker magától generál
MAX_TOPICS = 8

# nyelvkód → a brief célnyelvének neve a promptban
_LANG_NAME = {
    "hu": "Hungarian", "en": "English", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pl": "Polish", "ru": "Russian",
    "uk": "Ukrainian", "zh": "Simplified Chinese",
}

_SYSTEM = """You are the editor-in-chief of Echolot, a global news-intelligence platform
aggregating 750+ sources across 93 information spheres in 9 languages.
Every day you write a concise executive brief: what dominates the global
narrative TODAY, drawing on clustered top stories and trending entities.
You compare against yesterday's topics to mark what is rising and fading.
Write tight, factual, analytical prose — no fluff, no moralizing.
Respond ONLY with a JSON object, no markdown fences."""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_briefs (
            brief_date  TEXT NOT NULL,
            lang        TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'ok',
            content_json TEXT,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (brief_date, lang)
        )
    """)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    _ensure_schema(conn)
    return conn


def today_str(offset_days: int = 0) -> str:
    d = datetime.now(_TZ).date() - timedelta(days=offset_days)
    return d.isoformat()


def get_brief(db_path: str | Path, brief_date: str, lang: str) -> dict | None:
    """A tárolt brief dict-je ({status, created_at, ...content}) vagy None."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, content_json, created_at FROM daily_briefs "
            "WHERE brief_date=? AND lang=?", (brief_date, lang)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    out = {"status": row["status"], "created_at": row["created_at"],
           "brief_date": brief_date, "lang": lang}
    if row["content_json"]:
        try:
            out.update(json.loads(row["content_json"]))
        except Exception:
            pass
    return out


def list_dates(db_path: str | Path, limit: int = 14) -> list[str]:
    """Napok, amelyekre létezik kész brief (bármely nyelven), csökkenő sorrend."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT brief_date FROM daily_briefs WHERE status='ok' "
            "ORDER BY brief_date DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [r["brief_date"] for r in rows]


def is_stale(brief: dict | None, brief_date: str) -> bool:
    """Kell-e (újra)generálás: nincs, hibás, vagy a MAI brief túl régi."""
    if brief is None:
        return True
    if brief.get("status") == "failed":
        # bukás után 10 perc visszavárás — ne kickeljen minden oldalletöltés
        try:
            made = datetime.fromisoformat(brief["created_at"])
            return (datetime.now(timezone.utc) - made).total_seconds() > 600
        except Exception:
            return True
    if brief.get("status") == "pending":
        # beragadt pending (>15 perc) → újrapróbálható
        try:
            made = datetime.fromisoformat(brief["created_at"])
            return (datetime.now(timezone.utc) - made).total_seconds() > 900
        except Exception:
            return True
    if brief_date != today_str():
        return False  # múlt nap: végleges
    try:
        made = datetime.fromisoformat(brief["created_at"])
        return (datetime.now(timezone.utc) - made).total_seconds() > REFRESH_HOURS * 3600
    except Exception:
        return True


# ── Generálás ─────────────────────────────────────────────────────────

def _gather_inputs(db_path: str | Path, lang: str) -> dict | None:
    """Top-clusterek (globális + nyelvi), top-entitások. None ha üres a DB."""
    from echolot_top_stories import cluster_top_stories
    from echolot_entity_trending import top_entities_24h

    try:
        global_top = cluster_top_stories(db_path, hours=24, min_sources=3, limit=14, lang=None)
        if len(global_top) < 5:
            global_top = cluster_top_stories(db_path, hours=24, min_sources=2, limit=14, lang=None)
    except Exception as exc:
        log.warning("brief: global top failed: %s", exc)
        global_top = []
    try:
        local_top = cluster_top_stories(db_path, hours=24, min_sources=2, limit=6, lang=lang)
    except Exception as exc:
        log.warning("brief: local top failed: %s", exc)
        local_top = []
    try:
        entities = top_entities_24h(db_path, hours=24, limit=10, lang=None)
    except Exception:
        entities = []
    if not global_top and not local_top:
        return None
    # dedup cluster_id-re, globális elöl
    seen, clusters = set(), []
    for s in (global_top or []) + (local_top or []):
        cid = s.get("cluster_id")
        if cid in seen:
            continue
        seen.add(cid)
        clusters.append(s)
    return {"clusters": clusters[:18], "entities": entities}


def _build_prompt(inputs: dict, lang: str, brief_date: str,
                  yesterday_topics: list[dict]) -> str:
    lines = [f"DATE: {brief_date}",
             f"OUTPUT LANGUAGE: {_LANG_NAME.get(lang, 'English')}",
             "", "TOP STORY CLUSTERS (last 24h, ranked, with source counts):"]
    for i, c in enumerate(inputs["clusters"]):
        title = (c.get("title") or "").strip()[:200]
        lead = (c.get("lead_summary") or c.get("lead") or "").strip()[:300]
        n = c.get("source_count") or len(c.get("source_ids") or []) or 1
        langs = ",".join((c.get("languages") or [])[:5])
        lines.append(f"[{i}] ({n} sources; langs: {langs}) {title}")
        if lead:
            lines.append(f"    {lead}")
    ents = [e.get("name") for e in (inputs.get("entities") or []) if e.get("name")]
    if ents:
        lines += ["", "MOST-MENTIONED ENTITIES (24h): " + ", ".join(ents[:10])]
    if yesterday_topics:
        lines += ["", "YESTERDAY'S BRIEF TOPICS (for trend comparison):"]
        for t_ in yesterday_topics[:10]:
            lines.append(f"- {t_.get('title', '')}")
    lines += ["", f"""TASK: Write the executive brief for {brief_date} in {_LANG_NAME.get(lang, 'English')}.
Return JSON:
{{
 "headline": "one strong sentence: what dominates the global narrative today",
 "lead": "2-3 sentence summary paragraph of the day's media landscape",
 "topics": [
   {{"title": "topic name", "summary": "1-2 analytical sentences",
     "trend": "new|rising|steady|fading", "ref": <cluster index or null>}},
   ... 4 to {MAX_TOPICS} topics, ordered by importance ...
 ],
 "outlook": "1-2 sentences: what to watch next / which topics are flattening vs surging vs yesterday"
}}
Trend rules: compare with yesterday's topics — "new" if absent yesterday,
"rising"/"fading" by coverage momentum, "steady" otherwise. If no yesterday
data, use "new" sparingly and prefer "steady"."""]
    return "\n".join(lines)


def _call_llm(cfg: dict, prompt: str, retries: int = 3) -> dict | None:
    body = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 2200,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},  # V4-Flash: Non-Think (lásd classifier)
    }).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{cfg['base']}/chat/completions", data=body,
                headers={"Authorization": f"Bearer {cfg['key']}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            parsed = _parse_json_lenient(content)
            if isinstance(parsed, dict) and parsed.get("headline"):
                return parsed
            log.warning("brief: unparseable response (attempt %d/%d)", attempt + 1, retries)
        except Exception as exc:
            log.warning("brief LLM call failed (attempt %d/%d): %s", attempt + 1, retries, exc)
        time.sleep(2.0 * (attempt + 1))
    return None


def _sanitize(parsed: dict, clusters: list[dict]) -> dict:
    """Trim + a ref indexeket /story linkké oldjuk (story_id mező)."""
    topics = []
    for t_ in (parsed.get("topics") or [])[:MAX_TOPICS]:
        if not isinstance(t_, dict) or not t_.get("title"):
            continue
        trend = t_.get("trend")
        if trend not in ("new", "rising", "steady", "fading"):
            trend = "steady"
        story_id = None
        ref = t_.get("ref")
        if isinstance(ref, int) and 0 <= ref < len(clusters):
            story_id = clusters[ref].get("cluster_id")
        topics.append({
            "title": str(t_["title"])[:160],
            "summary": str(t_.get("summary") or "")[:500],
            "trend": trend,
            "story_id": story_id,
        })
    return {
        "headline": str(parsed.get("headline") or "")[:300],
        "lead": str(parsed.get("lead") or "")[:1200],
        "topics": topics,
        "outlook": str(parsed.get("outlook") or "")[:600],
    }


def _store(db_path: str | Path, brief_date: str, lang: str,
           status: str, content: dict | None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO daily_briefs(brief_date, lang, status, content_json, created_at) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(brief_date, lang) DO UPDATE SET "
            "status=excluded.status, content_json=excluded.content_json, "
            "created_at=excluded.created_at",
            (brief_date, lang, status,
             json.dumps(content, ensure_ascii=False) if content else None,
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def generate_brief(db_path: str | Path, brief_date: str | None = None,
                   lang: str = "hu") -> dict | None:
    """Szinkron generálás + tárolás. None ha kulcs/adat hiányzik vagy bukott."""
    cfg = _shared_config()
    if not cfg:
        log.info("brief disabled (no CLASSIFIER_API_KEY)")
        return None
    brief_date = brief_date or today_str()
    inputs = _gather_inputs(db_path, lang)
    if not inputs:
        log.info("brief: no input clusters for %s/%s", brief_date, lang)
        return None
    # tegnapi témák a trend-összevetéshez — kért nyelven, fallback bármely nyelvre
    y_date = (datetime.fromisoformat(brief_date).date() - timedelta(days=1)).isoformat()
    y_brief = get_brief(db_path, y_date, lang)
    if not y_brief or y_brief.get("status") != "ok":
        for alt in AUTO_LANGS:
            y_brief = get_brief(db_path, y_date, alt)
            if y_brief and y_brief.get("status") == "ok":
                break
    y_topics = (y_brief or {}).get("topics") or []

    _store(db_path, brief_date, lang, "pending", None)
    parsed = _call_llm(cfg, _build_prompt(inputs, lang, brief_date, y_topics))
    if parsed is None:
        _store(db_path, brief_date, lang, "failed", None)
        return None
    content = _sanitize(parsed, inputs["clusters"])
    _store(db_path, brief_date, lang, "ok", content)
    log.info("brief generated: %s/%s — %d topics", brief_date, lang,
             len(content["topics"]))
    content.update({"status": "ok", "brief_date": brief_date, "lang": lang,
                    "created_at": datetime.now(timezone.utc).isoformat()})
    return content


# ── On-demand kick (route-okból) + worker ─────────────────────────────

_kick_lock = threading.Lock()
_kick_running: set[tuple[str, str]] = set()


def kick_async(db_path: str | Path, brief_date: str, lang: str) -> bool:
    """Háttérszálon generál, (date,lang)-enként egyszerre csak egy.
    True ha most indult, False ha már fut / kulcs hiányzik."""
    if not _shared_config():
        return False
    key = (brief_date, lang)
    with _kick_lock:
        if key in _kick_running:
            return False
        _kick_running.add(key)

    def _run():
        try:
            generate_brief(db_path, brief_date, lang)
        except Exception as exc:
            log.warning("brief kick failed %s: %s", key, exc)
        finally:
            with _kick_lock:
                _kick_running.discard(key)

    threading.Thread(target=_run, daemon=True, name=f"brief-{lang}").start()
    return True


def worker_loop(db_path: str | Path) -> None:
    """10 percenként: a mai HU+EN brief létezzen és legyen friss."""
    if not _shared_config():
        log.info("brief worker disabled (no CLASSIFIER_API_KEY)")
        return
    log.info("daily-brief worker started (langs=%s, refresh=%dh)",
             ",".join(AUTO_LANGS), REFRESH_HOURS)
    time.sleep(120)  # boot-torlódás (scraper/classifier) elkerülése
    while True:
        try:
            d = today_str()
            for lg in AUTO_LANGS:
                cur = get_brief(db_path, d, lg)
                if is_stale(cur, d):
                    generate_brief(db_path, d, lg)
                    time.sleep(10)  # RPM-kímélés a classifier-worker mellett
        except Exception as exc:
            log.warning("brief worker cycle failed: %s", exc)
        time.sleep(WORKER_INTERVAL_S)
