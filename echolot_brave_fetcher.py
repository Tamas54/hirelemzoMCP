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
  BRAVE_FETCH_BATCH       — max articles per cycle (default 20)
  BRAVE_FETCH_CONCURRENCY — parallel Brave calls (default 5)
  BRAVE_FETCH_ROBUST      — "true" to always use brave_scrape_robust (default false)

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

from echolot_brave_client import fetch as brave_fetch

log = logging.getLogger("echolot.brave_fetcher")

DB_PATH = Path(os.getenv("DB_PATH", "echolot.db"))
BATCH_SIZE = int(os.getenv("BRAVE_FETCH_BATCH", "20"))
CONCURRENCY = int(os.getenv("BRAVE_FETCH_CONCURRENCY", "5"))
ROBUST = os.getenv("BRAVE_FETCH_ROBUST", "false").lower() in {"1", "true", "yes"}


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
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            conn.execute("""
                UPDATE articles
                SET full_text=?, full_text_status='ok',
                    full_text_fetched_at=?, full_text_block_reason=NULL
                WHERE article_id=?
            """, (text, now, article_id))
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
        return {"claimed": 0, "ok": 0, "blocked": 0, "failed": 0}

    sem = asyncio.Semaphore(concurrency)
    stats = {"claimed": len(rows), "ok": 0, "blocked": 0, "failed": 0}

    async with aiohttp.ClientSession() as session:
        async def worker(article_id: str, url: str) -> None:
            async with sem:
                result = await brave_fetch(session, url, robust=robust)
                outcome = _persist(db_path, article_id, result)
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
