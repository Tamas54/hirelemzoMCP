"""
ECHOLOT — unified async news scraper.

Merges Hirmagnet (HU + EU + intl press) with the Echolot multi-sphere
intelligence layer (CN/RU/IL/IR/UA/JP/KR/US partisan press + Telegram
channels). Single SQLite schema, FTS5 index across all languages (the
LLM consumer reads every language fluently — no translation needed).

Run modes:
    python scraper.py              # one-shot scrape
    python scraper.py --daemon     # forever loop
    python scraper.py --source telex  # single source by id substring
    python scraper.py --cleanup 21    # delete articles older than N days
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp
import feedparser
import yaml
from dateutil import parser as date_parser

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("echolot")

# ============================================================
# Config
# ============================================================

DB_PATH = Path(os.getenv("DB_PATH", "echolot.db"))
SOURCES_PATH = Path(os.getenv("SOURCES_PATH", "sources.yaml"))

FETCH_TIMEOUT_S = int(os.getenv("ECHOLOT_FETCH_TIMEOUT", "30"))
FETCH_CONCURRENCY = int(os.getenv("ECHOLOT_CONCURRENCY", "20"))
# Per-feed entry cap. Prolific sources (Sydney Morning Herald, Hindustan Times,
# Breitbart, etc.) hit the previous 50-cap every scrape cycle and were losing
# articles. 200 is well above any feed's actual entry count.
MAX_ENTRIES_PER_FEED = int(os.getenv("ECHOLOT_MAX_ENTRIES_PER_FEED", "200"))
USER_AGENT = os.getenv("ECHOLOT_UA", "Echolot/1.0 (+https://github.com/Tamas54/hirelemzoMCP)")
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "21"))


# ============================================================
# Data model
# ============================================================

@dataclass
class Source:
    id: str
    name: str
    url: str
    spheres: list[str]
    language: str
    trust_tier: int = 3
    lean: str = "unknown"
    category: str = "general"
    source_type: str = "rss"           # 'rss' | 'telegram'
    telegram_channel: str = ""
    notes: str = ""
    # Backwards-compat with original Hirmagnet metadata
    hirmagnet_source_type: str = ""
    hirmagnet_content_profile: str = ""
    hirmagnet_priority: int = 2

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        return cls(
            id=d["id"],
            name=d["name"],
            url=d["url"],
            spheres=d.get("spheres", []),
            language=d.get("language", "en"),
            trust_tier=int(d.get("trust_tier", 3)),
            lean=d.get("lean", "unknown"),
            category=d.get("category", "general"),
            source_type=d.get("source_type", "rss"),
            telegram_channel=d.get("telegram_channel", ""),
            notes=d.get("notes", ""),
            hirmagnet_source_type=d.get("hirmagnet_source_type", ""),
            hirmagnet_content_profile=d.get("hirmagnet_content_profile", ""),
            hirmagnet_priority=int(d.get("hirmagnet_priority", 2)),
        )


@dataclass
class Article:
    article_id: str
    source_id: str
    title: str
    lead: str
    url: str
    published_at: Optional[datetime]
    language: str
    spheres: list[str]
    category: str
    source_name: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================
# Source registry
# ============================================================

def load_sources(path: Path = SOURCES_PATH) -> list[Source]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    log.info("loaded %d sources from %s", len(raw), path)

    # Optionally load extra source-pack(s) for P3 expansion (Reddit, Substack,
    # Mastodon, Bluesky, etc.). Files are merged onto the main list with
    # later entries overriding earlier ones if id collides.
    extra_paths = [
        Path(os.getenv("SOURCES_EXTRA_PATH", "sources_p3_international.yaml")),
    ]
    by_id: dict[str, dict] = {s["id"]: s for s in raw if "id" in s}
    for ep in extra_paths:
        if not ep.exists():
            continue
        extra = yaml.safe_load(ep.read_text(encoding="utf-8")) or []
        new_n = sum(1 for s in extra if "id" in s and s["id"] not in by_id)
        for s in extra:
            if "id" in s:
                by_id[s["id"]] = s
        log.info("loaded %d sources from %s (%d new)", len(extra), ep, new_n)

    merged = list(by_id.values())
    sources = [Source.from_dict(d) for d in merged]
    log.info("total sources after merge: %d", len(sources))
    return sources


# ============================================================
# Storage — SQLite
# ============================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    language        TEXT NOT NULL,
    trust_tier      INTEGER NOT NULL,
    lean            TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'general',
    source_type     TEXT NOT NULL DEFAULT 'rss',
    spheres_json    TEXT NOT NULL,
    notes           TEXT,
    hirmagnet_source_type     TEXT,
    hirmagnet_content_profile TEXT,
    hirmagnet_priority        INTEGER
);

CREATE TABLE IF NOT EXISTS articles (
    article_id              TEXT PRIMARY KEY,
    source_id               TEXT NOT NULL REFERENCES sources(id),
    source_name             TEXT NOT NULL,
    title                   TEXT NOT NULL,
    lead                    TEXT,
    url                     TEXT NOT NULL UNIQUE,
    published_at            TEXT,
    language                TEXT NOT NULL,
    category                TEXT NOT NULL DEFAULT 'general',
    spheres_json            TEXT NOT NULL,
    fetched_at              TEXT NOT NULL,
    content_hash            TEXT,
    full_text               TEXT,
    full_text_status        TEXT,
    full_text_fetched_at    TEXT,
    full_text_block_reason  TEXT
);

CREATE INDEX IF NOT EXISTS ix_articles_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS ix_articles_source    ON articles(source_id);
CREATE INDEX IF NOT EXISTS ix_articles_category  ON articles(category);
CREATE INDEX IF NOT EXISTS ix_articles_language  ON articles(language);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title,
    lead,
    full_text,
    article_id UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    items_seen   INTEGER DEFAULT 0,
    items_new    INTEGER DEFAULT 0,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS ix_fetch_log_source ON fetch_log(source_id, started_at DESC);

CREATE TABLE IF NOT EXISTS scrape_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    sources_total   INTEGER DEFAULT 0,
    sources_ok      INTEGER DEFAULT 0,
    sources_failed  INTEGER DEFAULT 0,
    articles_found  INTEGER DEFAULT 0,
    articles_new    INTEGER DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running'
);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Idempotent ALTER TABLE ADD COLUMN — SQLite has no IF NOT EXISTS for columns."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        log.info("added column %s.%s", table, column)


def _ensure_fts_has_full_text(conn: sqlite3.Connection) -> None:
    """FTS5 has no ALTER — if articles_fts is the old 2-column shape, drop and
    rebuild with the 3-column shape (title, lead, full_text), then re-index
    from the articles table. Idempotent: if full_text column already present,
    no-op.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(articles_fts)").fetchall()}
    if "full_text" in cols:
        return
    log.info("migrating articles_fts: adding full_text column (drop + rebuild)")
    conn.execute("DROP TABLE articles_fts")
    conn.execute("""
        CREATE VIRTUAL TABLE articles_fts USING fts5(
            title, lead, full_text, article_id UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    conn.execute("""
        INSERT INTO articles_fts (article_id, title, lead, full_text)
        SELECT article_id, title, lead, COALESCE(full_text, '') FROM articles
    """)
    log.info("articles_fts rebuilt with %d rows",
             conn.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0])


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)
        # Backfill columns on existing databases (idempotent).
        # Full-text fetched by the Brave-MCP background worker (echolot_brave_fetcher).
        _ensure_column(conn, "articles", "full_text", "TEXT")
        _ensure_column(conn, "articles", "full_text_status", "TEXT")
        _ensure_column(conn, "articles", "full_text_fetched_at", "TEXT")
        _ensure_column(conn, "articles", "full_text_block_reason", "TEXT")
        _ensure_fts_has_full_text(conn)
    log.info("DB initialised at %s", DB_PATH)


def upsert_source(conn: sqlite3.Connection, src: Source) -> None:
    conn.execute(
        """
        INSERT INTO sources (id, name, url, language, trust_tier, lean, category,
                             source_type, spheres_json, notes,
                             hirmagnet_source_type, hirmagnet_content_profile,
                             hirmagnet_priority)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, url=excluded.url, language=excluded.language,
            trust_tier=excluded.trust_tier, lean=excluded.lean,
            category=excluded.category, source_type=excluded.source_type,
            spheres_json=excluded.spheres_json, notes=excluded.notes,
            hirmagnet_source_type=excluded.hirmagnet_source_type,
            hirmagnet_content_profile=excluded.hirmagnet_content_profile,
            hirmagnet_priority=excluded.hirmagnet_priority
        """,
        (src.id, src.name, src.url, src.language, src.trust_tier, src.lean,
         src.category, src.source_type, json.dumps(src.spheres), src.notes,
         src.hirmagnet_source_type, src.hirmagnet_content_profile, src.hirmagnet_priority),
    )


def _content_hash(title: str, url: str) -> str:
    return hashlib.sha256(f"{title.strip().lower()}|{url.strip()}".encode("utf-8")).hexdigest()


def upsert_article(conn: sqlite3.Connection, art: Article) -> bool:
    """Insert if URL not already seen — return True if newly inserted."""
    cur = conn.execute("SELECT 1 FROM articles WHERE url = ?", (art.url,))
    if cur.fetchone() is not None:
        return False

    chash = _content_hash(art.title, art.url)
    try:
        conn.execute(
            """
            INSERT INTO articles (
                article_id, source_id, source_name, title, lead,
                url, published_at, language, category, spheres_json, fetched_at,
                content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                art.article_id, art.source_id, art.source_name,
                art.title, art.lead, art.url,
                art.published_at.isoformat() if art.published_at else None,
                art.language, art.category, json.dumps(art.spheres),
                art.fetched_at.isoformat(), chash,
            ),
        )
    except sqlite3.IntegrityError:
        return False  # race
    conn.execute(
        "INSERT INTO articles_fts (article_id, title, lead, full_text) VALUES (?, ?, ?, '')",
        (art.article_id, art.title, art.lead),
    )
    return True


def cleanup_old(days: int = RETENTION_DAYS) -> int:
    """Delete articles older than N days. Returns number removed."""
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM articles WHERE published_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        n = result.rowcount
        # Also prune FTS rows that lost their parent
        conn.execute(
            "DELETE FROM articles_fts WHERE article_id NOT IN (SELECT article_id FROM articles)"
        )
    log.info("cleanup: removed %d articles older than %d days", n, days)
    return n


# ============================================================
# Helpers
# ============================================================

def _hash_id(source_id: str, url: str) -> str:
    return hashlib.sha256(f"{source_id}|{url}".encode("utf-8")).hexdigest()[:24]


def _parse_published(entry: Any) -> Optional[datetime]:
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                dt = date_parser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                continue
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ============================================================
# RSS fetcher
# ============================================================

async def fetch_rss(session: aiohttp.ClientSession, src: Source) -> tuple[Source, list[Article], Optional[str]]:
    try:
        async with session.get(
            src.url,
            timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT_S),
            headers={"User-Agent": USER_AGENT,
                     "Accept": "application/rss+xml, application/xml, application/atom+xml, */*"},
        ) as resp:
            if resp.status != 200:
                return src, [], f"HTTP {resp.status}"
            body = await resp.read()
    except asyncio.TimeoutError:
        return src, [], "timeout"
    except Exception as e:
        return src, [], f"fetch error: {type(e).__name__}: {e}"

    try:
        feed = feedparser.parse(body)
    except Exception as e:
        return src, [], f"parse error: {e}"

    articles: list[Article] = []
    for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
        url = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if not url or not title:
            continue
        lead = _strip_html(entry.get("summary") or entry.get("description") or "")[:1500]
        articles.append(Article(
            article_id=_hash_id(src.id, url),
            source_id=src.id,
            source_name=src.name,
            title=title,
            lead=lead,
            url=url,
            published_at=_parse_published(entry),
            language=src.language,
            spheres=src.spheres,
            category=src.category,
        ))
    return src, articles, None


# ============================================================
# Telegram fetcher (public web preview, no auth)
# ============================================================

def _parse_telegram_html(html: str, src: Source) -> list[Article]:
    block_starts = list(re.finditer(
        r'<div class="tgme_widget_message[^"]*"[^>]*data-post="([^"]+)"',
        html, re.IGNORECASE,
    ))
    if not block_starts:
        return []

    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(block_starts):
        post_id = m.group(1)
        start = m.start()
        end = block_starts[i + 1].start() if i + 1 < len(block_starts) else len(html)
        blocks.append((post_id, html[start:end]))

    articles: list[Article] = []
    for post_id, block_html in blocks:
        text_match = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            block_html, re.DOTALL | re.IGNORECASE,
        )
        text = _strip_html(text_match.group(1)) if text_match else ""
        if not text:
            continue
        dt_match = re.search(r'<time[^>]+datetime="([^"]+)"', block_html)
        published = None
        if dt_match:
            try:
                published = date_parser.parse(dt_match.group(1))
            except Exception:
                pass
        url = f"https://t.me/{post_id}"
        title = text[:200].strip()
        if len(text) > 200:
            title = title.rsplit(" ", 1)[0] + "…"
        articles.append(Article(
            article_id=_hash_id(src.id, url),
            source_id=src.id,
            source_name=src.name,
            title=title,
            lead=text[:1500],
            url=url,
            published_at=published,
            language=src.language,
            spheres=src.spheres,
            category=src.category,
        ))
    return articles


async def fetch_telegram(session: aiohttp.ClientSession, src: Source) -> tuple[Source, list[Article], Optional[str]]:
    channel = src.telegram_channel or src.url.rstrip("/").split("/")[-1]
    if not channel:
        return src, [], "no telegram_channel configured"
    preview_url = f"https://t.me/s/{channel}"
    try:
        async with session.get(
            preview_url,
            timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT_S),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html",
                     "Accept-Language": "en;q=0.9"},
        ) as resp:
            if resp.status != 200:
                return src, [], f"HTTP {resp.status}"
            html = await resp.text()
    except asyncio.TimeoutError:
        return src, [], "timeout"
    except Exception as e:
        return src, [], f"fetch error: {type(e).__name__}: {e}"

    if "tgme_channel_preview_disabled" in html or "tgme_widget_message" not in html:
        return src, [], "web preview disabled or empty"

    try:
        articles = _parse_telegram_html(html, src)
    except Exception as e:
        return src, [], f"parse error: {e}"
    return src, articles, None


async def fetch_one(session: aiohttp.ClientSession, src: Source):
    if src.source_type == "telegram":
        return await fetch_telegram(session, src)
    return await fetch_rss(session, src)


# ============================================================
# Orchestrator
# ============================================================

async def ingest_all(sources: list[Source]) -> dict:
    init_db()

    with get_db() as conn:
        for src in sources:
            upsert_source(conn, src)
        cur = conn.execute(
            "INSERT INTO scrape_log (started_at, sources_total, status) VALUES (?, ?, 'running')",
            (datetime.now(timezone.utc).isoformat(), len(sources)),
        )
        run_id = cur.lastrowid

    connector = aiohttp.TCPConnector(limit=FETCH_CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_S * 3)
    stats = {"fetched": 0, "failed": 0, "found": 0, "new_articles": 0, "errors": []}

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        rss_n = sum(1 for s in sources if s.source_type == "rss")
        tg_n = sum(1 for s in sources if s.source_type == "telegram")
        log.info("fetching %d sources (RSS=%d, TG=%d, conc=%d)",
                 len(sources), rss_n, tg_n, FETCH_CONCURRENCY)

        results = await asyncio.gather(
            *[fetch_one(session, s) for s in sources],
            return_exceptions=True,
        )

        all_new: list[Article] = []
        log_rows: list[tuple] = []
        for src, result in zip(sources, results):
            now_iso = datetime.now(timezone.utc).isoformat()
            if isinstance(result, Exception):
                stats["failed"] += 1
                stats["errors"].append({"source": src.id, "error": str(result)})
                log_rows.append((src.id, now_iso, now_iso, "failed", 0, 0, str(result)))
                continue
            _, articles, err = result
            if err:
                stats["failed"] += 1
                stats["errors"].append({"source": src.id, "error": err})
                log_rows.append((src.id, now_iso, now_iso, "failed", 0, 0, err))
                continue
            stats["fetched"] += 1
            stats["found"] += len(articles)
            with get_db() as conn:
                items_new = 0
                for art in articles:
                    cur = conn.execute("SELECT 1 FROM articles WHERE url = ?", (art.url,))
                    if cur.fetchone() is None:
                        all_new.append(art)
                        items_new += 1
                log_rows.append((src.id, now_iso, now_iso, "ok", len(articles), items_new, None))

        with get_db() as conn:
            conn.executemany(
                "INSERT INTO fetch_log (source_id, started_at, finished_at, status, items_seen, items_new, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
                log_rows,
            )

        log.info("persisting %d new articles", len(all_new))
        with get_db() as conn:
            for art in all_new:
                if upsert_article(conn, art):
                    stats["new_articles"] += 1
            conn.execute("""UPDATE scrape_log
                            SET finished_at=?, sources_ok=?, sources_failed=?,
                                articles_found=?, articles_new=?, status='done'
                            WHERE id=?""",
                         (datetime.now(timezone.utc).isoformat(),
                          stats["fetched"], stats["failed"],
                          stats["found"], stats["new_articles"], run_id))

    log.info("ingest done: %s", {k: v for k, v in stats.items() if k != "errors"})
    return stats


def run_scrape(source_filter: str = None) -> dict:
    sources = load_sources()
    if source_filter:
        f = source_filter.lower()
        sources = [s for s in sources if f in s.id.lower() or f in s.name.lower()]
        if not sources:
            log.error("no source matching '%s'", source_filter)
            return {"error": "no matching source"}
    return asyncio.run(ingest_all(sources))


def daemon_mode(interval_min: int = 30):
    log.info("daemon: scrape every %d min", interval_min)
    cycle = 0
    while True:
        try:
            run_scrape()
        except Exception as e:
            log.error("scrape cycle failed: %s", e, exc_info=True)
        cycle += 1
        if cycle % 24 == 0:
            try:
                cleanup_old(RETENTION_DAYS)
            except Exception as e:
                log.error("cleanup failed: %s", e)
        log.info("next scrape in %d min", interval_min)
        time.sleep(interval_min * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Echolot unified scraper")
    parser.add_argument("--daemon", action="store_true", help="run forever")
    parser.add_argument("--source", type=str, help="filter by source id/name substring")
    parser.add_argument("--cleanup", type=int, help="delete articles older than N days, then exit")
    parser.add_argument("--interval", type=int,
                        default=int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30")),
                        help="daemon interval (min)")
    args = parser.parse_args()

    if args.cleanup is not None:
        init_db()
        cleanup_old(args.cleanup)
        sys.exit(0)

    if args.daemon:
        daemon_mode(args.interval)
    else:
        result = run_scrape(source_filter=args.source)
        print(json.dumps({k: v for k, v in result.items() if k != "errors"}, indent=2))
        if result.get("errors"):
            print(f"\n{len(result['errors'])} errors (first 10):")
            for e in result["errors"][:10]:
                print(f"  {e['source']}: {e['error']}")
