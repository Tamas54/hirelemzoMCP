#!/usr/bin/env python3
"""
Warm Cache Job

Pre-fetches pageview data for the top articles to enable instant correlation search.
Run daily at 4:00 AM via cron (after update_cache.py).

Usage:
    python -m backend.jobs.warm_cache [--batch-size 100] [--max-articles 5000]

Cron example:
    0 4 * * * cd /home/tamas1/wikicorrelate/correlate-app && source venv/bin/activate && python -m backend.jobs.warm_cache
"""
import asyncio
import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from wikicorrelate.services.article_cache import article_cache
from wikicorrelate.services.wikipedia import wikipedia_service


async def warm_cache(
    batch_size: int = 100,
    max_articles: int = 5000,
    days: int = 365
):
    """
    Pre-fetch pageview data for top articles.

    This enables instant correlation search by having all pageview
    data already cached in the database.

    Args:
        batch_size: Number of articles to fetch in parallel per batch
        max_articles: Maximum number of articles to warm
        days: Days of history to fetch per article

    Time estimate: ~5000 articles * 0.1s rate limit = ~8-10 minutes
    """
    print(f"[{datetime.now()}] Starting cache warming job...")
    print(f"Settings: batch_size={batch_size}, max_articles={max_articles}, days={days}")

    try:
        # Get top articles
        top_articles = await article_cache.get_top_articles(limit=max_articles)

        if not top_articles:
            print("No top articles found. Run update_cache.py first.")
            return 0

        print(f"Found {len(top_articles)} articles to warm")

        # Get date range
        start_date, end_date = wikipedia_service.get_date_range(days)

        warmed = 0
        failed = 0

        for i in range(0, len(top_articles), batch_size):
            batch = top_articles[i:i + batch_size]

            # Check which articles need warming
            to_fetch = []
            for article in batch:
                if not await article_cache.is_cached(article, max_age_hours=12):
                    to_fetch.append(article)

            if not to_fetch:
                warmed += len(batch)
                print(f"[{datetime.now()}] Batch {i//batch_size + 1}: All {len(batch)} already cached")
                continue

            # Fetch pageviews in parallel
            tasks = [
                wikipedia_service.get_pageviews(article, start_date, end_date, use_cache=True)
                for article in to_fetch
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Count successes
            batch_success = 0
            for article, result in zip(to_fetch, results):
                if isinstance(result, Exception):
                    failed += 1
                elif result:
                    batch_success += 1

            warmed += batch_success + (len(batch) - len(to_fetch))

            print(
                f"[{datetime.now()}] Batch {i//batch_size + 1}: "
                f"Fetched {batch_success}/{len(to_fetch)}, "
                f"Cached {len(batch) - len(to_fetch)}, "
                f"Total: {warmed}/{len(top_articles)}"
            )

            # Rate limit between batches
            await asyncio.sleep(1)

        print(f"\n[{datetime.now()}] Cache warming complete!")
        print(f"Successfully warmed: {warmed}")
        print(f"Failed: {failed}")

        # Get final stats
        stats = await article_cache.get_cache_stats()
        print(f"Cache stats: {stats}")

        return warmed

    except Exception as e:
        print(f"[{datetime.now()}] ERROR: {e}")
        raise


async def warm_cache_smart(max_articles: int = 5000):
    """
    Smart cache warming - prioritizes uncached articles.

    Only fetches articles that aren't already in the cache.
    More efficient for incremental updates.
    """
    print(f"[{datetime.now()}] Starting SMART cache warming...")

    top_articles = await article_cache.get_top_articles(limit=max_articles)

    # Find uncached articles
    uncached = []
    for article in top_articles:
        if not await article_cache.is_cached(article, max_age_hours=20):
            uncached.append(article)

    print(f"Found {len(uncached)} uncached articles out of {len(top_articles)}")

    if not uncached:
        print("All articles already cached!")
        return 0

    # Warm only uncached articles
    start_date, end_date = wikipedia_service.get_date_range(365)

    warmed = 0
    for i, article in enumerate(uncached):
        try:
            result = await wikipedia_service.get_pageviews(
                article, start_date, end_date, use_cache=True
            )
            if result:
                warmed += 1

            if (i + 1) % 100 == 0:
                print(f"Progress: {i+1}/{len(uncached)} ({warmed} successful)")

        except Exception as e:
            print(f"Error fetching {article}: {e}")

    print(f"\n[{datetime.now()}] Smart warming complete! Warmed {warmed} articles.")
    return warmed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Warm Wikipedia pageview cache")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Articles per batch (default: 100)"
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=5000,
        help="Maximum articles to warm (default: 5000)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Days of history to fetch (default: 365)"
    )
    parser.add_argument(
        "--smart",
        action="store_true",
        help="Use smart warming (only fetch uncached)"
    )
    args = parser.parse_args()

    if args.smart:
        asyncio.run(warm_cache_smart(max_articles=args.max_articles))
    else:
        asyncio.run(warm_cache(
            batch_size=args.batch_size,
            max_articles=args.max_articles,
            days=args.days
        ))
