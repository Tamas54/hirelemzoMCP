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

    if os.environ.get("BRAVE_FETCH_ENABLED", "false").lower() in {"1", "true", "yes"}:
        t2 = threading.Thread(target=brave_fetcher_thread, daemon=True, name="brave-fetcher")
        t2.start()
        log.info("brave-fetcher thread launched")
    else:
        log.info("brave-fetcher disabled (set BRAVE_FETCH_ENABLED=true to enable)")

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
