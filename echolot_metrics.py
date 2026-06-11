"""Olvasó-analytics + feedback — szerver-oldali, tracker-mentes (plan 7a).

GDPR-barát mérés KÜLSŐ szolgáltatás és süti nélkül:
- minden HTTP-kérés egy memóriapufferbe kerül (record() — SOHA nem ír DB-t
  a kérés útvonalán!), egy háttér-szál 20 másodpercenként flushöli
- visitor-azonosító: sha1(IP + User-Agent + NAPI só) — naponta forgó hash,
  vissza nem fejthető, csak napi unique-számolásra jó
- bot-szűrés User-Agent alapján (a bot-forgalom külön számolódik)
- path-osztályok: landing/story/entities/dashboard/passport/api/mcp/other
  (a konkrét URL-eket NEM tároljuk, csak az osztályt + a story/entity
  azonosítót a top-listákhoz)

Public API:
  record(path, lang, ip, user_agent)   — kérés-naplózás (gyors, lock-olt)
  flush(db_path)                       — puffer → SQLite (háttér-szál hívja)
  summary(db_path, days)               — admin-oldal aggregátumai
  save_feedback(db_path, page, message, ua)
  list_feedback(db_path, limit)
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timezone

_BUF: deque = deque(maxlen=5000)
_LOCK = threading.Lock()

_BOT_RE = re.compile(
    r"bot|crawler|spider|slurp|curl|wget|python-requests|httpx|scrapy|"
    r"facebookexternalhit|preview|monitor|uptime|headless", re.I)

_PATH_CLASS = [
    (re.compile(r"^/$"), "landing"),
    (re.compile(r"^/story/"), "story"),
    (re.compile(r"^/entities/"), "entity"),
    (re.compile(r"^/entities"), "entities"),
    (re.compile(r"^/source/"), "source"),
    (re.compile(r"^/passport"), "passport"),
    (re.compile(r"^/analysis"), "analysis"),
    (re.compile(r"^/dashboard"), "dashboard"),
    (re.compile(r"^/weather"), "weather"),
    (re.compile(r"^/mcp"), "mcp"),
    (re.compile(r"^/api/"), "api"),
    (re.compile(r"^/feedback"), "feedback"),
    (re.compile(r"^/(static|robots|sitemap|llms|favicon|\.well-known)"), "asset"),
]


def _classify(path: str) -> tuple[str, str]:
    """(path_class, detail) — detail csak story/entity azonosítóhoz."""
    for rx, cls in _PATH_CLASS:
        if rx.search(path):
            detail = ""
            if cls in ("story", "entity"):
                parts = path.rstrip("/").split("/")
                detail = parts[-1][:60] if parts else ""
            return cls, detail
    return "other", ""


def _day_salt(day: str) -> str:
    # Determinisztikus napi só — nem titok, csak a hash napi forgásához kell
    # (cross-day követés ellen). Vissza nem fejthető IP-vé.
    return hashlib.sha1(f"echolot-salt:{day}".encode()).hexdigest()[:12]


def record(path: str, lang: str, ip: str, user_agent: str) -> None:
    """Kérés-naplózás a pufferbe — a kérés útvonalán NINCS DB-írás."""
    try:
        cls, detail = _classify(path or "/")
        if cls == "asset":
            return
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        visitor = hashlib.sha1(
            f"{ip}|{(user_agent or '')[:80]}|{_day_salt(day)}".encode()
        ).hexdigest()[:16]
        is_bot = 1 if _BOT_RE.search(user_agent or "") else 0
        with _LOCK:
            _BUF.append((day, now.hour, cls, detail, (lang or "")[:5],
                         visitor, is_bot))
    except Exception:
        pass  # a mérés SOHA nem törheti a kiszolgálást


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pageviews (
            day        TEXT NOT NULL,
            hour       INTEGER,
            path_class TEXT,
            detail     TEXT,
            lang       TEXT,
            visitor    TEXT,
            is_bot     INTEGER DEFAULT 0
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_pv_day ON pageviews(day)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            page       TEXT,
            message    TEXT NOT NULL,
            user_agent TEXT
        )""")


def flush(db_path: str) -> int:
    """Puffer → SQLite. A háttér-szál hívja ~20s-onként. Visszaadja a sorszámot."""
    with _LOCK:
        rows = list(_BUF)
        _BUF.clear()
    if not rows:
        return 0
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _ensure(conn)
            conn.executemany(
                "INSERT INTO pageviews VALUES (?,?,?,?,?,?,?)", rows)
            # 90 napos retenció
            conn.execute(
                "DELETE FROM pageviews WHERE day < date('now','-90 days')")
            conn.commit()
        finally:
            conn.close()
        return len(rows)
    except sqlite3.OperationalError:
        # lock-bukásnál visszatesszük a sorokat (legfeljebb duplán mérünk)
        with _LOCK:
            _BUF.extendleft(reversed(rows))
        return 0


def flusher_thread(db_path: str, interval: int = 20) -> None:
    """start.py indítja daemon-szálként."""
    while True:
        time.sleep(interval)
        try:
            flush(db_path)
        except Exception:
            pass


def summary(db_path: str, days: int = 14) -> dict:
    """Admin-aggregátumok: napi uniques/views, osztályok, nyelvek, top tartalmak."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        _ensure(conn)
        win = (f"-{int(days)} days",)
        daily = conn.execute("""
            SELECT day,
                   COUNT(*) AS views,
                   COUNT(DISTINCT visitor) AS uniques,
                   SUM(is_bot) AS bot_views
            FROM pageviews WHERE day >= date('now', ?)
            GROUP BY day ORDER BY day""", win).fetchall()
        classes = conn.execute("""
            SELECT path_class, COUNT(*) n, COUNT(DISTINCT visitor) u
            FROM pageviews WHERE day >= date('now', ?) AND is_bot=0
            GROUP BY path_class ORDER BY n DESC""", win).fetchall()
        langs = conn.execute("""
            SELECT COALESCE(NULLIF(lang,''),'?') lang, COUNT(*) n
            FROM pageviews WHERE day >= date('now', ?) AND is_bot=0
            GROUP BY 1 ORDER BY n DESC LIMIT 12""", win).fetchall()
        top_stories = conn.execute("""
            SELECT detail, COUNT(*) n FROM pageviews
            WHERE day >= date('now', ?) AND path_class='story' AND is_bot=0
            GROUP BY detail ORDER BY n DESC LIMIT 10""", win).fetchall()
        top_entities = conn.execute("""
            SELECT detail, COUNT(*) n FROM pageviews
            WHERE day >= date('now', ?) AND path_class='entity' AND is_bot=0
            GROUP BY detail ORDER BY n DESC LIMIT 10""", win).fetchall()
        return {
            "daily": [dict(r) for r in daily],
            "classes": [dict(r) for r in classes],
            "langs": [dict(r) for r in langs],
            "top_stories": [dict(r) for r in top_stories],
            "top_entities": [dict(r) for r in top_entities],
        }
    finally:
        conn.close()


def save_feedback(db_path: str, page: str, message: str, ua: str) -> bool:
    msg = " ".join((message or "").split())[:2000]
    if len(msg) < 3:
        return False
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _ensure(conn)
        conn.execute(
            "INSERT INTO feedback (created_at, page, message, user_agent) "
            "VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),
             (page or "")[:200], msg, (ua or "")[:160]))
        conn.commit()
        return True
    finally:
        conn.close()


def list_feedback(db_path: str, limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        _ensure(conn)
        rows = conn.execute(
            "SELECT created_at, page, message FROM feedback "
            "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
