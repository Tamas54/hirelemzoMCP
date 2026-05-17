"""
Daily ranking refresh — designed to be triggered by cron or APScheduler.

Run manually:
    python scripts/update_rankings.py

Cron example (3am daily):
    0 3 * * * cd /app && python scripts/update_rankings.py >> /var/log/rankings.log 2>&1
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Allow running as a standalone script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain_intel import DomainAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ranking_updater")


async def main():
    analyzer = DomainAnalyzer.from_env()
    logger.info("Starting daily ranking refresh...")
    results = await analyzer.refresh_rankings()
    logger.info(f"Refresh complete: {results}")

    # Sanity check: do a few well-known domains have ranks?
    test_domains = ["google.com", "facebook.com"]
    for d in test_domains:
        sources = await analyzer.ranking_db.lookup(d)
        ranks = {s.source: s.rank for s in sources}
        logger.info(f"Sanity check {d}: {ranks}")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
