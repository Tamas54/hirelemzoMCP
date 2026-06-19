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
import os
import sqlite3
import threading
import time
import urllib.error
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

# Utolsó 25 log-sor a /health?brief=1 diagnosztikához (classifier-minta) —
# Railway-log nélkül is látható, MIÉRT bukik egy generálás.
from collections import deque as _deque
_recent_logs: "_deque[str]" = _deque(maxlen=25)


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _recent_logs.append(
                f"{time.strftime('%H:%M:%S', time.gmtime(record.created))}Z "
                f"{record.levelname} {record.getMessage()}")
        except Exception:
            pass


log.addHandler(_RingHandler())
log.setLevel(logging.INFO)

REQUEST_TIMEOUT = 120
REFRESH_HOURS = int(os.environ.get("BRIEF_REFRESH_HOURS", "12"))  # a MAI brief ennyi óránként frissül (Kommandant 2026-06-19: 4→12)
WORKER_INTERVAL_S = 600    # worker ciklus
# A worker mind a 10 UI-nyelvre magától generál (Kommandant 2026-06-12:
# "a németen nincs, és a többi nyelven se látom"). HU+EN elöl, hogy a két
# fő nyelv frissüljön először; ~10 hívás/ciklus, 10s szünetekkel.
AUTO_LANGS = ("hu", "en", "de", "it", "pl", "fr", "es", "ru", "uk", "zh")
MAX_TOPICS = 8
MAX_LOCAL_TOPICS = 6
# Tartalmi séma-verzió: emelése a MAI briefeket újragenerálja (múlt napok
# véglegesek maradnak). v2: globális + nyelvterületi blokk (Kommandant-kérés
# 2026-06-12 — "kell egy magyar/olasz/lengyel is, az adott nyelvterület
# fontos hírei az adott nyelven"). v3: anyanyelvi stílusszabály a promptban
# ("trillionári" → idiomatikus körülírás, billió≠trillió).
SCHEMA_VER = 3

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
    # 60s busy-timeout: a scraper/classifier/translator írói mellett a 15s
    # kevés volt → "database is locked" (2026-06-12, /health?brief=1 fogta).
    conn = sqlite3.connect(str(db_path), timeout=60)
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
    if int(brief.get("v") or 1) < SCHEMA_VER:
        return True  # régi sémájú MAI brief → újragenerálás az új szerkezettel
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
        local_top = cluster_top_stories(db_path, hours=24, min_sources=2, limit=8, lang=lang)
    except Exception as exc:
        log.warning("brief: local top failed: %s", exc)
        local_top = []
    try:
        entities = top_entities_24h(db_path, hours=24, limit=10, lang=None)
    except Exception:
        entities = []
    if not global_top and not local_top:
        return None
    # Egyetlen kombinált lista a ref-feloldáshoz: globálisak elöl, utánuk a
    # CSAK-lokális klaszterek. n_global jelöli a határt — a prompt két
    # szekcióként sorolja fel (globális + nyelvterületi).
    seen, clusters = set(), []
    for s in (global_top or [])[:14]:
        cid = s.get("cluster_id")
        if cid in seen:
            continue
        seen.add(cid)
        clusters.append(s)
    n_global = len(clusters)
    for s in (local_top or []):
        cid = s.get("cluster_id")
        if cid in seen:
            continue
        seen.add(cid)
        clusters.append(s)
    return {"clusters": clusters[:22], "n_global": n_global, "entities": entities}


def _wants_local(inputs: dict, lang: str) -> bool:
    """Kell-e nyelvterületi blokk: en-nél nem (a globális eleve angol
    súlyú), és csak ha van lokális klaszter-pool."""
    return lang != "en" and inputs.get("n_global", 0) < len(inputs.get("clusters") or [])


def _build_prompt(inputs: dict, lang: str, brief_date: str,
                  yesterday_topics: list[dict]) -> str:
    lang_name = _LANG_NAME.get(lang, "English")
    n_global = inputs.get("n_global", len(inputs["clusters"]))
    lines = [f"DATE: {brief_date}",
             f"OUTPUT LANGUAGE: {lang_name}",
             "", "GLOBAL TOP STORY CLUSTERS (last 24h, ranked, with source counts):"]
    for i, c in enumerate(inputs["clusters"]):
        if i == n_global:
            lines += ["", f"{lang_name.upper()}-LANGUAGE-AREA TOP CLUSTERS "
                          f"(the {lang_name}-language press, last 24h):"]
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

    local_schema = ""
    local_rules = ""
    if _wants_local(inputs, lang):
        local_schema = f""",
 "local": {{
   "lead": "1-2 sentences: what dominates the {lang_name}-language press today",
   "topics": [ same shape as above, 3 to 5 topics from the
               {lang_name}-language-area clusters (refs from that section;
               a global index is allowed when that story dominates the
               local press too) ]
 }}"""
        local_rules = (f"\nThe \"local\" block covers the {lang_name}-language "
                       "area: domestic politics, economy, society — the stories "
                       "a local reader must know today. Do NOT repeat a global "
                       "topic in the local block unless its local angle differs.")
    lines += ["", f"""TASK: Write the daily brief for {brief_date} in {lang_name}.
Return JSON:
{{
 "headline": "one strong sentence: what dominates the global narrative today",
 "lead": "2-3 sentences that ADD context beyond the headline (drivers, why now, what changed) — never restate the headline's list",
 "topics": [
   {{"title": "topic name", "summary": "1-2 tight sentences, MAX 30 words",
     "trend": "new|rising|steady|fading", "ref": <cluster index or null>}},
   ... 4 to 6 topics, ordered by importance ...
 ],
 "outlook": "1-2 sentences: what to watch next / which topics are flattening vs surging vs yesterday"{local_schema}
}}
HARD LIMIT: the whole JSON must stay under ~700 words — the response is cut
off beyond that, so prefer fewer, sharper topics over long ones.
STYLE: Write natural, idiomatic {lang_name} exactly as a native news editor
would — NEVER calque English words or grammar. Use the target language's own
terminology and number-naming conventions: the English "trillion" is 10^12,
which in Hungarian is "billió" (NOT "trillió"), so "trillionaire" must be
rendered descriptively (e.g. Hungarian: "ezermilliárd dolláros vagyonú").
If a term has no natural equivalent, paraphrase it — an awkward loanword
("trillionári") is worse than a longer native phrase.
Trend rules: compare with yesterday's topics — "new" if absent yesterday,
"rising"/"fading" by coverage momentum, "steady" otherwise. If no yesterday
data, use "new" sparingly and prefer "steady".{local_rules}"""]
    return "\n".join(lines)


def _call_llm(cfg: dict, prompt: str,
              retries: int = 3) -> tuple[dict | None, str | None]:
    """(parsed, None) sikernél; (None, utolsó-hiba-szöveg) bukásnál."""
    body = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        # 2200 a magyar (és más nem-angol) kimenetet levágta → csonka JSON →
        # parse-bukás. A v2 séma hosszabb, de 4096 a modell-plafon: maradjunk
        # ALATTA (a 4800 minden hívást 400-zal dobatott volna el).
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},  # V4-Flash: Non-Think (lásd classifier)
    }).encode()
    def _do_call() -> dict:
        req = urllib.request.Request(
            f"{cfg['base']}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {cfg['key']}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())

    last_err: str | None = None
    for attempt in range(retries):
        try:
            # KEMÉNY teljes-hívás határidő: az urlopen timeoutja csak a
            # socket-műveletek közti csendet méri — egy csöpögő válasz órákig
            # bent ragadhat (2026-06-12: az 'it' generálás 10+ percre beállt,
            # és a _gen_lock mögött minden nyelv várt rá). shutdown(wait=False):
            # a lógó szálat NEM várjuk meg, hagyjuk elhalni a háttérben.
            import concurrent.futures as _cf
            _ex = _cf.ThreadPoolExecutor(max_workers=1)
            try:
                data = _ex.submit(_do_call).result(timeout=REQUEST_TIMEOUT + 30)
            finally:
                _ex.shutdown(wait=False, cancel_futures=True)
            choice = (data.get("choices") or [{}])[0]
            content = choice.get("message", {}).get("content", "")
            parsed = _parse_json_lenient(content)
            if isinstance(parsed, dict) and parsed.get("headline"):
                return parsed, None
            last_err = (f"unparseable (finish={choice.get('finish_reason')}, "
                        f"len={len(content)}, tail={content[-120:]!r})")
            log.warning("brief: %s (attempt %d/%d)", last_err, attempt + 1, retries)
        except urllib.error.HTTPError as exc:
            # az API hibatörzse a lényeg (pl. max_tokens-plafon, kvóta)
            try:
                detail = exc.read().decode()[:300]
            except Exception:
                detail = ""
            last_err = f"HTTP {exc.code}: {detail or exc.reason}"
            log.warning("brief LLM call failed (attempt %d/%d): %s",
                        attempt + 1, retries, last_err)
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            log.warning("brief LLM call failed (attempt %d/%d): %s",
                        attempt + 1, retries, last_err)
        time.sleep(2.0 * (attempt + 1))
    return None, last_err


def _clean_topics(raw, clusters: list[dict], cap: int) -> list[dict]:
    """Topic-lista tisztítás + a ref indexek /story linkké oldása."""
    topics = []
    for t_ in (raw or [])[:cap]:
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
    return topics


def _sanitize(parsed: dict, clusters: list[dict]) -> dict:
    out = {
        "v": SCHEMA_VER,
        "headline": str(parsed.get("headline") or "")[:300],
        "lead": str(parsed.get("lead") or "")[:1200],
        "topics": _clean_topics(parsed.get("topics"), clusters, MAX_TOPICS),
        "outlook": str(parsed.get("outlook") or "")[:600],
    }
    loc = parsed.get("local")
    if isinstance(loc, dict):
        loc_topics = _clean_topics(loc.get("topics"), clusters, MAX_LOCAL_TOPICS)
        if loc_topics:
            out["local_lead"] = str(loc.get("lead") or "")[:600]
            out["local_topics"] = loc_topics
    return out


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


# Egyszerre csak EGY generálás fusson (worker + on-demand kickek együtt):
# a párhuzamos nyelvek egymást lockolták ki az SQLite-ból ("database is
# locked"), és a klaszterezés CPU-ját is egyszerre tapossák.
_gen_lock = threading.Lock()


def generate_brief(db_path: str | Path, brief_date: str | None = None,
                   lang: str = "hu") -> dict | None:
    """Szinkron generálás + tárolás. None ha kulcs/adat hiányzik vagy bukott."""
    cfg = _shared_config()
    if not cfg:
        log.info("brief disabled (no CLASSIFIER_API_KEY)")
        return None
    with _gen_lock:
        return _generate_brief_locked(cfg, db_path, brief_date, lang)


def _generate_brief_locked(cfg: dict, db_path: str | Path,
                           brief_date: str | None, lang: str) -> dict | None:
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
    parsed, err = _call_llm(cfg, _build_prompt(inputs, lang, brief_date, y_topics))
    if parsed is None:
        # a hibaszöveg a content_json-ba kerül → /health?brief=1 mutatja
        _store(db_path, brief_date, lang, "failed", {"error": (err or "?")[:400]})
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


def diagnostics(db_path: str | Path) -> dict:
    """/health?brief=1 — kulcs-gating, tárolt sorok (hibaszöveggel), friss logok."""
    out: dict = {"enabled": _shared_config() is not None,
                 "auto_langs": list(AUTO_LANGS), "schema_ver": SCHEMA_VER}
    try:
        conn = _connect(db_path)
        try:
            rows = conn.execute(
                "SELECT brief_date, lang, status, created_at, content_json "
                "FROM daily_briefs ORDER BY brief_date DESC, lang LIMIT 14").fetchall()
        finally:
            conn.close()
        briefs = []
        for r in rows:
            item = {"date": r["brief_date"], "lang": r["lang"],
                    "status": r["status"], "created_at": r["created_at"]}
            if r["content_json"]:
                try:
                    c = json.loads(r["content_json"])
                    item["v"] = c.get("v", 1)
                    item["error"] = c.get("error")
                    item["local"] = bool(c.get("local_topics"))
                    item["chars"] = len(r["content_json"])
                except Exception:
                    pass
            briefs.append(item)
        out["briefs"] = briefs
    except Exception as exc:
        out["db_error"] = str(exc)
    out["recent_logs"] = list(_recent_logs)
    return out


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
