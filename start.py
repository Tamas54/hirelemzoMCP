"""
HírMagnet MCP — Unified launcher.
Starts MCP server (streamable-http) + background scraper in one process.
Perfect for Railway single-service deployment.
"""

import os
import threading
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hirmagnet")

RETENTION_DAYS = 21  # 3-week rolling window


def run_scraper_daemon():
    """Background scraper loop."""
    time.sleep(5)  # Wait for server to start

    from scraper import run_scrape, cleanup_old
    interval = int(os.environ.get("SCRAPE_INTERVAL_MINUTES", 30))

    logger.info("Running initial scrape...")
    try:
        run_scrape()
    except Exception as e:
        logger.error(f"Initial scrape error: {e}")

    try:
        cleanup_old(RETENTION_DAYS)
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

    cycle = 0
    while True:
        time.sleep(interval * 60)
        cycle += 1
        try:
            run_scrape()
        except Exception as e:
            logger.error(f"Scrape cycle error: {e}")

        # Periodic cleanup every 24 cycles (~12h at 30min interval)
        if cycle % 24 == 0:
            try:
                cleanup_old(RETENTION_DAYS)
            except Exception as e:
                logger.error(f"Cleanup error: {e}")


def main():
    scraper_thread = threading.Thread(target=run_scraper_daemon, daemon=True)
    scraper_thread.start()
    logger.info("Scraper daemon started in background thread")

    logger.info("Starting HírMagnet MCP server")
    from server import mcp
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
