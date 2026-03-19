"""
HírMagnet RSS Scraper — fetches news from configured sources into SQLite.

Run modes:
    python scraper.py              # One-shot: scrape all sources once
    python scraper.py --daemon     # Daemon: scrape every 30 minutes
    python scraper.py --source HVG # Scrape single source (for testing)
"""

import os
import sys
import time
import hashlib
import sqlite3
import logging
import argparse
from datetime import datetime, timezone
from contextlib import contextmanager

import feedparser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hirmagnet-scraper")

DB_PATH = os.environ.get("DB_PATH", "hirmagnet_news.db")
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL_MINUTES", 30))

# --- Sources ---
# Import from sources.py — this is the master list
from sources import NEWS_SOURCES


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def content_hash(title: str, url: str) -> str:
    """Generate hash for dedup."""
    return hashlib.md5(f"{title.strip().lower()}|{url.strip()}".encode()).hexdigest()


def parse_date(entry) -> str | None:
    """Extract publication date from RSS entry."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, field, None)
        if parsed:
            try:
                dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    # Fallback to string parsing
    for field in ("published", "updated"):
        val = getattr(entry, field, None)
        if val:
            return val
    return datetime.now(timezone.utc).isoformat()


def extract_lead(entry) -> str | None:
    """Extract lead/summary from RSS entry."""
    # Try summary first, then description
    for field in ("summary", "description"):
        val = getattr(entry, field, None)
        if val:
            # Strip HTML tags (simple)
            import re
            text = re.sub(r"<[^>]+>", "", val).strip()
            if len(text) > 20:
                return text[:1000]  # Cap at 1000 chars
    return None


def scrape_source(source: dict, conn: sqlite3.Connection) -> tuple[int, int]:
    """Scrape a single RSS source. Returns (found, new)."""
    name = source["name"]
    url = source["url"]
    category = source.get("category", "egyéb")
    language = source.get("language", "hu")

    try:
        feed = feedparser.parse(url, agent="HirMagnet-MCP/1.0")

        if feed.bozo and not feed.entries:
            logger.warning(f"  [{name}] Feed parse error: {feed.bozo_exception}")
            return 0, 0

        found = len(feed.entries)
        new = 0

        for entry in feed.entries:
            title = getattr(entry, "title", None)
            link = getattr(entry, "link", None)
            if not title or not link:
                continue

            chash = content_hash(title, link)
            lead = extract_lead(entry)
            pub_date = parse_date(entry)

            try:
                conn.execute("""
                    INSERT OR IGNORE INTO articles 
                    (title, lead, url, source_name, source_category, language, published_at, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (title.strip(), lead, link.strip(), name, category, language, pub_date, chash))
                if conn.total_changes:
                    new += 1
            except sqlite3.IntegrityError:
                pass  # Duplicate URL

        conn.commit()
        logger.info(f"  [{name}] {found} found, {new} new")
        return found, new

    except Exception as e:
        logger.error(f"  [{name}] Error: {e}")
        return 0, 0


def run_scrape(source_filter: str = None):
    """Run a full scrape cycle."""
    sources = NEWS_SOURCES
    if source_filter:
        sources = [s for s in sources if source_filter.lower() in s["name"].lower()]
        if not sources:
            logger.error(f"No source matching '{source_filter}'")
            return

    logger.info(f"Starting scrape of {len(sources)} sources...")

    with get_db() as conn:
        # Log scrape start
        cursor = conn.execute(
            "INSERT INTO scrape_log (status) VALUES ('running')"
        )
        log_id = cursor.lastrowid
        conn.commit()

        total_found = 0
        total_new = 0
        errors = 0

        for source in sources:
            try:
                found, new = scrape_source(source, conn)
                total_found += found
                total_new += new
            except Exception as e:
                logger.error(f"  [{source['name']}] Fatal: {e}")
                errors += 1

        # Log scrape finish
        conn.execute("""
            UPDATE scrape_log SET 
                finished_at = CURRENT_TIMESTAMP, 
                articles_found = ?, articles_new = ?, errors = ?, status = 'done'
            WHERE id = ?
        """, (total_found, total_new, errors, log_id))
        conn.commit()

    logger.info(f"Scrape done: {total_found} found, {total_new} new, {errors} errors")


def daemon_mode():
    """Run scraper in a loop."""
    logger.info(f"Daemon mode: scraping every {SCRAPE_INTERVAL} minutes")
    while True:
        try:
            run_scrape()
        except Exception as e:
            logger.error(f"Scrape cycle error: {e}")
        logger.info(f"Next scrape in {SCRAPE_INTERVAL} minutes...")
        time.sleep(SCRAPE_INTERVAL * 60)


# --- Cleanup ---
def cleanup_old(days: int = 30):
    """Remove articles older than N days."""
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM articles WHERE published_at < datetime('now', ?)",
            [f"-{days} days"]
        )
        conn.commit()
        logger.info(f"Cleaned up {result.rowcount} articles older than {days} days")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HírMagnet RSS Scraper")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    parser.add_argument("--source", type=str, help="Scrape specific source only")
    parser.add_argument("--cleanup", type=int, help="Remove articles older than N days")
    args = parser.parse_args()

    if args.cleanup:
        cleanup_old(args.cleanup)
    elif args.daemon:
        daemon_mode()
    else:
        run_scrape(args.source)
