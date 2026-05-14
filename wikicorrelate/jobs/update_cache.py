#!/usr/bin/env python3
"""
Update Cache Job

Fetches the top 10,000 most-read Wikipedia articles and stores them in the database.
Run daily at 3:00 AM via cron.

Usage:
    python -m backend.jobs.update_cache [--limit 10000]

Cron example:
    0 3 * * * cd /home/tamas1/wikicorrelate/correlate-app && source venv/bin/activate && python -m backend.jobs.update_cache
"""
import asyncio
import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from wikicorrelate.services.article_cache import article_cache


async def main(limit: int = 10000):
    """
    Update the top articles cache.

    Args:
        limit: Number of top articles to cache
    """
    print(f"[{datetime.now()}] Starting cache update job...")
    print(f"Target: {limit} articles")

    try:
        # Update top articles list
        count = await article_cache.update_top_articles_list(limit=limit)
        print(f"[{datetime.now()}] Successfully cached {count} articles")

        # Get stats
        stats = await article_cache.get_cache_stats()
        print(f"Cache stats: {stats}")

        return count

    except Exception as e:
        print(f"[{datetime.now()}] ERROR: {e}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update Wikipedia article cache")
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Number of top articles to cache (default: 10000)"
    )
    args = parser.parse_args()

    asyncio.run(main(limit=args.limit))
