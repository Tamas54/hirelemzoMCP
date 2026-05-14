"""
ECHOLOT — unified launcher.
Starts MCP server (streamable-http) + background scraper in one process.
Single Railway service.
"""

import logging
import os
import threading
import time
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("echolot-launcher")


def scraper_thread():
    """Background scrape loop. Survives any per-cycle crash."""
    time.sleep(5)  # let MCP server bind first

    try:
        from scraper import init_db
        init_db()
    except Exception as e:
        log.error("scraper init_db failed: %s", e, exc_info=True)

    interval_min = int(os.environ.get("SCRAPE_INTERVAL_MINUTES", "30"))
    retention_days = int(os.environ.get("RETENTION_DAYS", "21"))

    log.info("scraper daemon: interval=%dmin, retention=%dd",
             interval_min, retention_days)

    cycle = 0
    while True:
        try:
            from scraper import run_scrape
            stats = run_scrape()
            log.info("cycle %d done: new=%d found=%d ok=%d failed=%d",
                     cycle, stats.get("new_articles", 0), stats.get("found", 0),
                     stats.get("fetched", 0), stats.get("failed", 0))
        except Exception as e:
            log.error("scrape cycle %d crashed: %s\n%s", cycle, e, traceback.format_exc())

        cycle += 1
        if cycle % 24 == 0:
            try:
                from scraper import cleanup_old
                cleanup_old(retention_days)
            except Exception as e:
                log.error("cleanup failed: %s", e)

        log.info("sleeping %d min before next cycle", interval_min)
        time.sleep(interval_min * 60)


def wikicorrelate_warmer_thread():
    """Nightly cache-warmer for the wikicorrelate engine.

    Pre-fetches top Wikipedia articles' pageview series so correlation
    searches don't pay the per-call API latency. Runs once on startup
    (after a delay) and then every 24h.

    Disabled by default; set WIKICORRELATE_WARM=true to enable.
    """
    if os.environ.get("WIKICORRELATE_WARM", "").lower() not in {"1", "true", "yes"}:
        log.info("wikicorrelate cache-warmer disabled (set WIKICORRELATE_WARM=true to enable)")
        return

    # Wait 5 minutes after startup so the main app is healthy first
    time.sleep(300)
    interval_s = int(os.environ.get("WIKICORRELATE_WARM_INTERVAL_S", str(24 * 3600)))
    max_articles = int(os.environ.get("WIKICORRELATE_WARM_MAX", "2000"))
    batch_size = int(os.environ.get("WIKICORRELATE_WARM_BATCH", "100"))
    days = int(os.environ.get("WIKICORRELATE_WARM_DAYS", "365"))

    log.info("wikicorrelate cache-warmer: every %ds, max %d articles, batch %d, %d days",
             interval_s, max_articles, batch_size, days)

    cycle = 0
    while True:
        try:
            import asyncio
            from wikicorrelate.jobs.warm_cache import warm_cache
            log.info("wikicorrelate warm cycle %d starting", cycle)
            asyncio.run(warm_cache(batch_size=batch_size, max_articles=max_articles, days=days))
            log.info("wikicorrelate warm cycle %d done", cycle)
        except Exception as e:
            log.error("wikicorrelate warm cycle %d crashed: %s\n%s",
                      cycle, e, traceback.format_exc())
        cycle += 1
        time.sleep(interval_s)


def brave_fetcher_thread():
    """Background full-text fetcher via our brave-mcp-server. Survives crashes."""
    time.sleep(20)  # let scraper get articles in first

    interval_s = int(os.environ.get("BRAVE_FETCH_INTERVAL_S", "60"))
    log.info("brave-fetcher daemon: interval=%ds", interval_s)

    cycle = 0
    while True:
        try:
            from echolot_brave_fetcher import run_cycle
            stats = run_cycle()
            if stats.get("claimed", 0):
                log.info("brave cycle %d: %s", cycle, stats)
        except Exception as e:
            log.error("brave cycle %d crashed: %s\n%s",
                      cycle, e, traceback.format_exc())
        cycle += 1
        time.sleep(interval_s)


def main():
    t = threading.Thread(target=scraper_thread, daemon=True, name="scraper")
    t.start()
    log.info("scraper thread launched")

    # Brave fetcher activates when BRAVE_MCP_URL env var is set.
    # No URL = no fetcher (safe default for local/dev runs).
    brave_url = os.environ.get("BRAVE_MCP_URL", "").strip()
    if brave_url:
        t2 = threading.Thread(target=brave_fetcher_thread, daemon=True, name="brave-fetcher")
        t2.start()
        log.info("brave-fetcher thread launched (BRAVE_MCP_URL=%s)", brave_url)
    else:
        log.info("brave-fetcher disabled (set BRAVE_MCP_URL to enable)")

    # Wikicorrelate cache-warmer (off by default — set WIKICORRELATE_WARM=true)
    t3 = threading.Thread(target=wikicorrelate_warmer_thread, daemon=True, name="wiki-warmer")
    t3.start()

    log.info("starting Echolot MCP server")
    import uvicorn
    from echolot_app import build_app
    uvicorn.run(
        build_app(),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
