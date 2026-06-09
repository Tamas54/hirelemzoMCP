"""Echolot full-text fetcher (Brave-MCP backed).

Background worker: picks articles with NULL full_text_status, fetches the
full page text via brave-mcp-server, updates the DB.

One cycle does at most `batch_size` articles. The launcher (start.py) is
expected to call run_cycle() on a timer (e.g. every 60s).

States stored in articles.full_text_status:
  pending  — currently being fetched (so concurrent workers skip)
  ok       — full_text populated, ready to use
  blocked  — Brave reported content_usable=False (paywall, CF, empty)
  failed   — transport/protocol error (we'll retry-on-next-cycle by leaving
             these as NULL — see _claim_batch).

Env:
  BRAVE_FETCH_BATCH            — max articles per cycle (default 50)
  BRAVE_FETCH_CONCURRENCY      — parallel Brave calls (default 15)
  BRAVE_FETCH_ROBUST           — "true" to always use brave_scrape_robust (default false)
  BRAVE_FETCH_HTTPX_FALLBACK   — "true" to fall back to direct httpx fetch when
                                 Brave returns None (default true)
  BRAVE_FETCH_HTTPX_TIMEOUT_S  — per-request timeout for httpx fallback (default 20)
  BRAVE_FETCH_HTTPX_MIN_CHARS  — minimum extracted-text length to count as
                                 successful httpx recovery (default 200)

Run as CLI for ad-hoc fetching:
    python3 echolot_brave_fetcher.py [batch_size]
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import httpx

from echolot_brave_client import fetch as brave_fetch
from echolot_content_extract import extract_main_text

log = logging.getLogger("echolot.brave_fetcher")

DB_PATH = Path(os.getenv("DB_PATH", "echolot.db"))
BATCH_SIZE = int(os.getenv("BRAVE_FETCH_BATCH", "50"))
CONCURRENCY = int(os.getenv("BRAVE_FETCH_CONCURRENCY", "15"))
ROBUST = os.getenv("BRAVE_FETCH_ROBUST", "false").lower() in {"1", "true", "yes"}
HTTPX_FALLBACK = os.getenv("BRAVE_FETCH_HTTPX_FALLBACK", "true").lower() in {"1", "true", "yes"}
HTTPX_TIMEOUT_S = int(os.getenv("BRAVE_FETCH_HTTPX_TIMEOUT_S", "20"))
HTTPX_MIN_CHARS = int(os.getenv("BRAVE_FETCH_HTTPX_MIN_CHARS", "200"))

_HTTPX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EcholotFetcher/0.1; +https://github.com/Tamas54/hirelemzoMCP)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hu;q=0.8",
    # Only advertise encodings httpx can always decode. Brotli ("br") needs the
    # optional brotli/brotlicffi package; without it httpx hands back the raw
    # compressed bytes, which extract_main_text turns into U+FFFD garbage that
    # then gets stored as full_text. gzip/deflate are always decoded natively.
    "Accept-Encoding": "gzip, deflate",
}


def _looks_like_text(s: str) -> bool:
    """True if `s` is plausibly real article text, not binary/garbage.

    Undecoded compressed payloads (e.g. brotli without the codec) are dense
    with U+FFFD replacement characters and control bytes; genuine article text
    has essentially none. Used to refuse storing/serving garbage full_text."""
    if not s:
        return False
    sample = s[:4000]
    bad = sum(1 for c in sample
              if c == "�" or (ord(c) < 32 and c not in "\t\n\r"))
    return (bad / len(sample)) < 0.05


async def _httpx_fetch_extract(client: httpx.AsyncClient, url: str) -> Optional[dict]:
    """Direct httpx fetch + content extraction.

    Returns None on transport error (network, timeout, HTTP >= 400).
    Returns a Brave-shaped dict on success or extract-too-short.
    """
    try:
        resp = await client.get(url, timeout=HTTPX_TIMEOUT_S, follow_redirects=True)
        if resp.status_code >= 400:
            log.info("httpx_fallback: HTTP %d for %s", resp.status_code, url)
            return None
        html = resp.text
    except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPError) as exc:
        log.info("httpx_fallback: %s for %s", type(exc).__name__, url)
        return None
    except Exception as exc:
        log.warning("httpx_fallback: %s: %s", type(exc).__name__, exc)
        return None

    try:
        extracted = extract_main_text(html, url=url) or {}
    except Exception as exc:
        log.warning("httpx_fallback: extract_main_text failed for %s: %s", url, exc)
        return None

    text = extracted.get("text") or ""
    title = extracted.get("title") or ""
    if len(text) < HTTPX_MIN_CHARS:
        return {
            "content_usable": False,
            "block_reason": "httpx_extract_too_short",
            "text": text,
            "markdown": "",
            "title": title,
            "_via": "httpx_fallback",
        }
    return {
        "content_usable": True,
        "block_reason": None,
        "text": text,
        "markdown": "",
        "title": title,
        "_via": "httpx_fallback",
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _claim_batch(db_path: Path, batch_size: int) -> list[tuple[str, str]]:
    """Atomically claim up to `batch_size` pending articles.

    Marks them as full_text_status='pending' so a concurrent cycle won't grab
    the same rows. Returns list of (article_id, url).
    """
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        rows = conn.execute("""
            SELECT article_id, url
            FROM articles
            WHERE full_text_status IS NULL
              AND url IS NOT NULL AND url <> ''
            ORDER BY published_at DESC
            LIMIT ?
        """, (batch_size,)).fetchall()
        if not rows:
            return []
        conn.executemany(
            "UPDATE articles SET full_text_status='pending' WHERE article_id=?",
            [(r[0],) for r in rows],
        )
        conn.commit()
    return rows


def _persist(db_path: Path, article_id: str, result: Optional[dict]) -> str:
    """Write the fetch outcome back to the DB. Returns the status code stored."""
    now = _utc_now_iso()
    if result is None:
        # Transport error — reset to NULL so it gets retried next cycle.
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            conn.execute(
                "UPDATE articles SET full_text_status=NULL WHERE article_id=?",
                (article_id,),
            )
            conn.commit()
        return "failed"

    if result.get("content_usable"):
        text = result.get("text") or result.get("markdown") or ""
        if not _looks_like_text(text):
            # Undecoded/binary payload masquerading as text — refuse to store it.
            with sqlite3.connect(db_path, timeout=30.0) as conn:
                conn.execute("""
                    UPDATE articles
                    SET full_text_status='blocked',
                        full_text_fetched_at=?, full_text_block_reason='garbage_or_binary'
                    WHERE article_id=?
                """, (now, article_id))
                conn.commit()
            return "blocked"
        # Tag httpx-recovered rows so observability is clear without inventing a
        # new column. NULL stays NULL for the normal Brave path.
        block_marker = (
            "recovered_via_httpx_fallback"
            if result.get("_via") == "httpx_fallback"
            else None
        )
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            conn.execute("""
                UPDATE articles
                SET full_text=?, full_text_status='ok',
                    full_text_fetched_at=?, full_text_block_reason=?
                WHERE article_id=?
            """, (text, now, block_marker, article_id))
            # Keep FTS index in sync so search_news can hit the full text.
            # If articles_fts is still the old 2-column shape (pre-migration),
            # this update is a no-op which is fine — next init_db migrates.
            try:
                conn.execute(
                    "UPDATE articles_fts SET full_text=? WHERE article_id=?",
                    (text, article_id),
                )
            except sqlite3.OperationalError:
                pass
            conn.commit()
        return "ok"

    block = result.get("block_reason") or "unknown"
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.execute("""
            UPDATE articles
            SET full_text_status='blocked',
                full_text_fetched_at=?, full_text_block_reason=?
            WHERE article_id=?
        """, (now, block, article_id))
        conn.commit()
    return "blocked"


async def run_cycle_async(
    db_path: Path = DB_PATH,
    batch_size: int = BATCH_SIZE,
    concurrency: int = CONCURRENCY,
    robust: bool = ROBUST,
) -> dict:
    """One async cycle: claim → fetch in parallel → persist. Returns stats."""
    rows = _claim_batch(db_path, batch_size)
    if not rows:
        return {"claimed": 0, "ok": 0, "blocked": 0, "failed": 0, "recovered": 0}

    sem = asyncio.Semaphore(concurrency)
    stats = {"claimed": len(rows), "ok": 0, "blocked": 0, "failed": 0, "recovered": 0}

    async with aiohttp.ClientSession() as session, \
            httpx.AsyncClient(headers=_HTTPX_HEADERS, max_redirects=3) as httpx_client:

        async def worker(article_id: str, url: str) -> None:
            async with sem:
                result = await brave_fetch(session, url, robust=robust)
                if result is None and HTTPX_FALLBACK:
                    result = await _httpx_fetch_extract(httpx_client, url)
                outcome = _persist(db_path, article_id, result)
                if (
                    result
                    and result.get("_via") == "httpx_fallback"
                    and result.get("content_usable")
                ):
                    stats["recovered"] = stats.get("recovered", 0) + 1
                stats[outcome] = stats.get(outcome, 0) + 1

        await asyncio.gather(*[worker(aid, url) for aid, url in rows])

    return stats


def run_cycle(
    db_path: Path = DB_PATH,
    batch_size: int = BATCH_SIZE,
    concurrency: int = CONCURRENCY,
    robust: bool = ROBUST,
) -> dict:
    """Sync wrapper around run_cycle_async — handy for threaded daemons."""
    return asyncio.run(run_cycle_async(db_path, batch_size, concurrency, robust))


def reset_garbage_full_text(db_path: Path = DB_PATH) -> int:
    """One-shot cleanup: find rows whose stored full_text is binary garbage
    (undecoded brotli etc.) and reset them to NULL so the worker refetches them
    cleanly with the fixed Accept-Encoding. Returns how many were reset.

    Cheap enough to run at startup: it samples the first 4 KB of each 'ok' row."""
    try:
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            rows = conn.execute("""
                SELECT article_id, full_text FROM articles
                WHERE full_text_status='ok'
                  AND full_text IS NOT NULL AND length(full_text) > 0
            """).fetchall()
            bad = [aid for aid, ft in rows if not _looks_like_text(ft or "")]
            if bad:
                conn.executemany(
                    "UPDATE articles SET full_text=NULL, full_text_status=NULL, "
                    "full_text_block_reason=NULL WHERE article_id=?",
                    [(a,) for a in bad],
                )
                for a in bad:
                    try:
                        conn.execute(
                            "UPDATE articles_fts SET full_text='' WHERE article_id=?", (a,))
                    except sqlite3.OperationalError:
                        pass
                conn.commit()
            return len(bad)
    except Exception as exc:
        log.warning("reset_garbage_full_text failed: %s", exc)
        return 0


async def fetch_on_demand(
    items: list[tuple[str, str]],
    db_path: Path = DB_PATH,
    *,
    concurrency: int = 6,
    per_timeout: float = 5.0,
    overall_timeout: float = 7.0,
    robust: bool = False,
) -> dict[str, str]:
    """Fetch full text for specific (article_id, url) pairs RIGHT NOW.

    Used by the story-detail page so a freshly-clustered story has readable
    body text before the background worker reaches it. Persists every outcome
    to the DB (so the next visitor is instant) and returns {article_id: text}
    for the articles whose full text became usable. Bounded by overall_timeout
    so a slow source can never hang the page — whatever isn't ready in time is
    simply omitted and falls back to the lead.

    The caller is expected to pass only articles that don't already have text
    (status NULL/empty), so this won't refetch 'ok' or re-attempt 'blocked'.
    """
    if not items:
        return {}
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, str] = {}

    async def _go() -> None:
        async with aiohttp.ClientSession() as session, \
                httpx.AsyncClient(headers=_HTTPX_HEADERS, max_redirects=3) as httpx_client:

            async def worker(article_id: str, url: str) -> None:
                async with sem:
                    result = None
                    try:
                        result = await asyncio.wait_for(
                            brave_fetch(session, url, robust=robust), per_timeout)
                    except (asyncio.TimeoutError, Exception):
                        result = None
                    if result is None and HTTPX_FALLBACK:
                        try:
                            result = await asyncio.wait_for(
                                _httpx_fetch_extract(httpx_client, url), per_timeout)
                        except (asyncio.TimeoutError, Exception):
                            result = None
                    try:
                        _persist(db_path, article_id, result)
                    except Exception as exc:
                        log.warning("on-demand persist failed for %s: %s", article_id, exc)
                    if result and result.get("content_usable"):
                        out[article_id] = result.get("text") or result.get("markdown") or ""

            await asyncio.gather(*[worker(aid, url) for aid, url in items])

    try:
        await asyncio.wait_for(_go(), overall_timeout)
    except asyncio.TimeoutError:
        log.info("on-demand fetch hit overall_timeout (%ss); returning %d ready",
                 overall_timeout, len(out))
    return out


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    batch = int(argv[1]) if len(argv) > 1 else BATCH_SIZE
    stats = run_cycle(batch_size=batch)
    log.info("cycle done: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
