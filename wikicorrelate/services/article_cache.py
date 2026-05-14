"""
Article Cache Service - Top Wikipedia articles cache for fast correlation search.

Layer 1 of Category Expansion:
- Fetches top 10,000 most-read Wikipedia articles
- Caches their pageview data for instant correlation search
- Replaces the fixed 353 articles with dynamic top articles
"""
import aiosqlite
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import json

from wikicorrelate.config import (
    DATABASE_PATH,
    WIKIPEDIA_USER_AGENT,
    WIKIPEDIA_RATE_LIMIT_DELAY
)


class ArticleCache:
    """
    Top Wikipedia articles cache for fast correlation search.

    Features:
    - Fetches top 10,000 most-read Wikipedia articles
    - Caches pageview time series data
    - Provides instant search against cached data
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DATABASE_PATH)
        self.user_agent = WIKIPEDIA_USER_AGENT
        self._initialized = False

    async def init_db(self):
        """Initialize cache tables if not exists"""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            # Top articles list table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS top_articles (
                    rank INTEGER PRIMARY KEY,
                    article TEXT NOT NULL,
                    avg_daily_views INTEGER,
                    last_updated TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_top_articles_article ON top_articles(article)"
            )

            # Pageview cache table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS article_cache (
                    article TEXT PRIMARY KEY,
                    pageviews TEXT,
                    fetched_at TIMESTAMP,
                    total_views INTEGER
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_article_cache_fetched ON article_cache(fetched_at)"
            )

            await db.commit()

        self._initialized = True

    async def fetch_top_articles(self, limit: int = 10000) -> List[Tuple[str, int]]:
        """
        Fetch top Wikipedia articles from the Pageviews API.

        Gets the most-read articles from the past 12 months and aggregates views.

        Args:
            limit: Maximum number of articles to return

        Returns:
            List of (article_name, total_views) tuples, sorted by views
        """
        articles = {}

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Fetch top articles from last 12 months
            for months_ago in range(1, 13):
                date = datetime.now() - timedelta(days=30 * months_ago)
                year = date.strftime("%Y")
                month = date.strftime("%m")

                url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{year}/{month}/all-days"

                try:
                    response = await client.get(
                        url,
                        headers={'User-Agent': self.user_agent}
                    )

                    if response.status_code == 200:
                        data = response.json()
                        for item in data.get("items", []):
                            for article_data in item.get("articles", []):
                                name = article_data["article"]
                                views = article_data["views"]

                                # Skip special pages
                                if name.startswith(("Special:", "Wikipedia:", "File:", "Template:", "Help:", "Category:", "Portal:", "Draft:", "Module:", "MediaWiki:")):
                                    continue
                                if name in ["Main_Page", "-", "Search"]:
                                    continue
                                # Skip disambiguation pages (often end with _)
                                if name.endswith("_(disambiguation)"):
                                    continue

                                if name not in articles:
                                    articles[name] = 0
                                articles[name] += views
                    else:
                        print(f"Failed to fetch {year}/{month}: {response.status_code}")

                except Exception as e:
                    print(f"Error fetching {year}/{month}: {e}")

                await asyncio.sleep(0.1)  # Rate limit respect

        # Sort by views and return top N
        sorted_articles = sorted(articles.items(), key=lambda x: x[1], reverse=True)
        return sorted_articles[:limit]

    async def update_top_articles_list(self, limit: int = 10000) -> int:
        """
        Update the top articles list in database.

        Should be run daily via cron job.

        Args:
            limit: Number of top articles to store

        Returns:
            Number of articles updated
        """
        await self.init_db()

        print(f"[ArticleCache] Fetching top {limit} Wikipedia articles...")
        top_articles = await self.fetch_top_articles(limit=limit)

        async with aiosqlite.connect(self.db_path) as db:
            # Clear old data
            await db.execute("DELETE FROM top_articles")

            # Insert new data
            for rank, (article, views) in enumerate(top_articles, 1):
                await db.execute(
                    "INSERT INTO top_articles (rank, article, avg_daily_views, last_updated) VALUES (?, ?, ?, ?)",
                    (rank, article, views // 365, datetime.now())
                )

            await db.commit()

        print(f"[ArticleCache] Saved {len(top_articles)} articles to top_articles table")
        return len(top_articles)

    async def get_top_articles(self, limit: int = 10000) -> List[str]:
        """
        Get the cached top articles list.

        Args:
            limit: Maximum number of articles to return

        Returns:
            List of article names
        """
        await self.init_db()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT article FROM top_articles ORDER BY rank LIMIT ?",
                (limit,)
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_top_articles_with_views(self, limit: int = 10000) -> List[Dict]:
        """
        Get top articles with their view counts.

        Args:
            limit: Maximum number of articles to return

        Returns:
            List of dicts with 'article', 'rank', 'avg_daily_views'
        """
        await self.init_db()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT rank, article, avg_daily_views FROM top_articles ORDER BY rank LIMIT ?",
                (limit,)
            )
            rows = await cursor.fetchall()
            return [
                {"rank": row[0], "article": row[1], "avg_daily_views": row[2]}
                for row in rows
            ]

    async def is_cached(self, article: str, max_age_hours: int = 24) -> bool:
        """
        Check if an article's pageviews are cached and fresh.

        Args:
            article: Article name
            max_age_hours: Maximum age of cache in hours

        Returns:
            True if cached and fresh, False otherwise
        """
        await self.init_db()

        cutoff = datetime.now() - timedelta(hours=max_age_hours)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM article_cache WHERE article = ? AND fetched_at > ?",
                (article, cutoff)
            )
            result = await cursor.fetchone()
            return result is not None

    async def get_cached_pageviews(self, article: str) -> Optional[List[Dict]]:
        """
        Get cached pageview data for an article.

        Args:
            article: Article name

        Returns:
            List of pageview dicts or None if not cached
        """
        await self.init_db()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT pageviews FROM article_cache WHERE article = ?",
                (article,)
            )
            row = await cursor.fetchone()

            if row:
                try:
                    return json.loads(row[0])
                except json.JSONDecodeError:
                    return None
            return None

    async def save_to_cache(self, article: str, pageviews: List[Dict]):
        """
        Save pageview data to cache.

        Args:
            article: Article name
            pageviews: List of pageview dicts with 'date' and 'views' keys
        """
        await self.init_db()

        total = sum(pv.get("views", 0) for pv in pageviews)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO article_cache (article, pageviews, fetched_at, total_views)
                VALUES (?, ?, ?, ?)
            """, (article, json.dumps(pageviews), datetime.now(), total))
            await db.commit()

    async def get_cache_stats(self) -> Dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats
        """
        await self.init_db()

        async with aiosqlite.connect(self.db_path) as db:
            # Top articles count
            cursor = await db.execute("SELECT COUNT(*) FROM top_articles")
            top_count = (await cursor.fetchone())[0]

            # Cached pageviews count
            cursor = await db.execute("SELECT COUNT(*) FROM article_cache")
            cached_count = (await cursor.fetchone())[0]

            # Fresh cache (last 24h)
            cutoff = datetime.now() - timedelta(hours=24)
            cursor = await db.execute(
                "SELECT COUNT(*) FROM article_cache WHERE fetched_at > ?",
                (cutoff,)
            )
            fresh_count = (await cursor.fetchone())[0]

            # Last update time
            cursor = await db.execute(
                "SELECT MAX(last_updated) FROM top_articles"
            )
            last_update = (await cursor.fetchone())[0]

            return {
                "top_articles_count": top_count,
                "cached_pageviews_count": cached_count,
                "fresh_cache_count": fresh_count,
                "last_top_articles_update": last_update,
                "target_top_articles": 10000
            }

    async def clear_old_cache(self, max_age_days: int = 7):
        """
        Clear cache entries older than max_age_days.

        Args:
            max_age_days: Maximum age of cache entries to keep
        """
        await self.init_db()

        cutoff = datetime.now() - timedelta(days=max_age_days)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM article_cache WHERE fetched_at < ?",
                (cutoff,)
            )
            await db.commit()
            print(f"[ArticleCache] Cleared {cursor.rowcount} old cache entries")

    async def is_in_top_articles(self, article: str) -> bool:
        """
        Check if an article is in the top articles list.

        Args:
            article: Article name

        Returns:
            True if in top articles, False otherwise
        """
        await self.init_db()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM top_articles WHERE article = ?",
                (article,)
            )
            result = await cursor.fetchone()
            return result is not None

    async def search_top_articles(self, query: str, limit: int = 20) -> List[str]:
        """
        Search top articles by name (fuzzy match).

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching article names
        """
        await self.init_db()

        # Use LIKE for simple fuzzy matching
        search_pattern = f"%{query}%"

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT article FROM top_articles WHERE article LIKE ? ORDER BY rank LIMIT ?",
                (search_pattern, limit)
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


# Singleton instance
article_cache = ArticleCache()
