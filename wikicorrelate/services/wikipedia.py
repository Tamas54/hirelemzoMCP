"""
Wikipedia Pageviews Service
Ported from /home/tamas1/wikicorrelate/correlateA.py with async support

Updated with cache-first strategy for Category Expansion.
Uses central http_client for connection pooling.
"""
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd

from wikicorrelate.config import (
    WIKIPEDIA_BASE_URL,
    WIKIPEDIA_USER_AGENT,
    WIKIPEDIA_RATE_LIMIT_DELAY,
    DEFAULT_DAYS_LOOKBACK
)
from wikicorrelate.services.http_client import http_client, fetch_all_parallel, fetch_with_keys


class WikipediaService:
    """Wikipedia pageview data fetching service with cache support"""

    def __init__(self):
        self.base_url = WIKIPEDIA_BASE_URL
        self.user_agent = WIKIPEDIA_USER_AGENT
        self.rate_limit_delay = WIKIPEDIA_RATE_LIMIT_DELAY
        self._semaphore = asyncio.Semaphore(50)  # Max 50 concurrent requests
        self._cache = None  # Lazy loaded

    def _get_cache(self):
        """Lazy load the article cache to avoid circular imports"""
        if self._cache is None:
            from wikicorrelate.services.article_cache import article_cache
            self._cache = article_cache
        return self._cache

    async def _get_client(self) -> httpx.AsyncClient:
        """Get the shared HTTP client from central http_client module"""
        return await http_client.get_client()

    async def close(self):
        """Close the shared HTTP client"""
        await http_client.close()

    def _fill_missing_dates(
        self,
        views: List[Dict],
        start_date: str,
        end_date: str
    ) -> List[Dict]:
        """
        Fill in missing dates with 0 views to ensure continuous timeseries.

        Wikipedia API only returns days with pageviews, but we need all days
        for proper correlation calculation.
        """
        if not views:
            return views

        from datetime import timedelta

        start_dt = datetime.strptime(start_date, '%Y%m%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d')

        # Create a dict of existing data
        views_dict = {v['date']: v['views'] for v in views}

        # Generate all dates in range
        filled = []
        current = start_dt
        while current <= end_dt:
            date_str = current.strftime('%Y-%m-%d')
            filled.append({
                'date': date_str,
                'views': views_dict.get(date_str, 0)
            })
            current += timedelta(days=1)

        return filled

    async def get_pageviews(
        self,
        article: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True
    ) -> List[Dict]:
        """
        Fetch pageviews for a Wikipedia article with cache-first strategy.

        Args:
            article: Article title (e.g., "Bitcoin" or "Bitcoin_(cryptocurrency)")
            start_date: YYYYMMDD format
            end_date: YYYYMMDD format
            use_cache: Whether to try cache first (default True)

        Returns:
            List of dicts with 'date' and 'views' keys
        """
        article = article.replace(" ", "_")

        # Try cache first
        if use_cache:
            cache = self._get_cache()
            if await cache.is_cached(article):
                cached_data = await cache.get_cached_pageviews(article)
                if cached_data:
                    # Filter to requested date range
                    start_dt = datetime.strptime(start_date, '%Y%m%d')
                    end_dt = datetime.strptime(end_date, '%Y%m%d')
                    filtered = [
                        pv for pv in cached_data
                        if start_dt <= datetime.strptime(pv['date'], '%Y-%m-%d') <= end_dt
                    ]
                    if filtered:
                        # Fill missing dates
                        return self._fill_missing_dates(filtered, start_date, end_date)

        # Fetch from API
        views = await self._fetch_from_api(article, start_date, end_date)

        # Fill missing dates for continuous timeseries
        if views:
            views = self._fill_missing_dates(views, start_date, end_date)

        # Save to cache for future use
        if views and use_cache:
            cache = self._get_cache()
            await cache.save_to_cache(article, views)

        return views

    async def _fetch_from_api(
        self,
        article: str,
        start_date: str,
        end_date: str
    ) -> List[Dict]:
        """
        Fetch pageviews directly from Wikipedia API.

        Args:
            article: Article title
            start_date: YYYYMMDD format
            end_date: YYYYMMDD format

        Returns:
            List of dicts with 'date' and 'views' keys
        """
        url = f"{self.base_url}/{article}/daily/{start_date}/{end_date}"

        async with self._semaphore:
            try:
                client = await self._get_client()
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                # Parse response
                views = []
                for item in data.get('items', []):
                    views.append({
                        'date': datetime.strptime(
                            item['timestamp'], '%Y%m%d%H'
                        ).strftime('%Y-%m-%d'),
                        'views': item['views']
                    })

                return views

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    pass  # Common, don't spam logs
                else:
                    print(f"HTTP error for {article}: {e}")
                return []
            except Exception as e:
                print(f"Error fetching {article}: {e}")
                return []

    async def get_pageviews_df(
        self,
        article: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """Get pageviews as pandas DataFrame"""
        views = await self.get_pageviews(article, start_date, end_date)
        if not views:
            return pd.DataFrame()

        df = pd.DataFrame(views)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        return df

    async def get_pageviews_batch(
        self,
        articles: List[str],
        start_date: str,
        end_date: str,
        batch_size: int = 50
    ) -> Dict[str, List[Dict]]:
        """
        Fetch pageviews for multiple articles using parallel HTTP requests.

        Uses the central http_client for optimized connection pooling and
        parallel fetching with HTTP/2 multiplexing.

        Args:
            articles: List of article titles
            start_date: YYYYMMDD format
            end_date: YYYYMMDD format
            batch_size: Number of articles to process per batch

        Returns:
            Dict mapping article titles to their pageview lists
        """
        all_results = {}
        articles_to_fetch = []
        cache = self._get_cache()

        # 1. Check cache first for all articles
        for article in articles:
            article_normalized = article.replace(" ", "_")
            if await cache.is_cached(article_normalized):
                cached_data = await cache.get_cached_pageviews(article_normalized)
                if cached_data:
                    start_dt = datetime.strptime(start_date, '%Y%m%d')
                    end_dt = datetime.strptime(end_date, '%Y%m%d')
                    filtered = [
                        pv for pv in cached_data
                        if start_dt <= datetime.strptime(pv['date'], '%Y-%m-%d') <= end_dt
                    ]
                    if filtered:
                        all_results[article] = self._fill_missing_dates(filtered, start_date, end_date)
                        continue
            articles_to_fetch.append(article_normalized)

        # 2. Build URLs for uncached articles
        if articles_to_fetch:
            url_to_article = {}
            for article in articles_to_fetch:
                url = f"{self.base_url}/{article}/daily/{start_date}/{end_date}"
                url_to_article[url] = article

            # 3. Fetch ALL uncached articles in PARALLEL using central http_client
            fetched = await fetch_with_keys(url_to_article, max_concurrent=batch_size)

            # 4. Process results
            for article, data in fetched.items():
                if data and 'items' in data:
                    views = []
                    for item in data.get('items', []):
                        views.append({
                            'date': datetime.strptime(
                                item['timestamp'], '%Y%m%d%H'
                            ).strftime('%Y-%m-%d'),
                            'views': item['views']
                        })

                    if views:
                        views = self._fill_missing_dates(views, start_date, end_date)
                        all_results[article] = views
                        # Save to cache
                        await cache.save_to_cache(article, views)

        return all_results

    async def search_articles(self, query: str, limit: int = 10) -> List[str]:
        """
        Search for Wikipedia articles matching a query
        Uses Wikipedia OpenSearch API

        Args:
            query: Search query
            limit: Max results to return

        Returns:
            List of article titles
        """
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            'action': 'opensearch',
            'search': query,
            'limit': limit,
            'namespace': 0,
            'format': 'json'
        }

        try:
            client = await self._get_client()
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            # OpenSearch returns [query, [titles], [descriptions], [urls]]
            if len(data) >= 2:
                return data[1]
            return []

        except Exception as e:
            print(f"Search error: {e}")
            return []

    async def get_related_articles(self, article: str, limit: int = 30) -> List[str]:
        """
        Get related articles using Wikipedia links and categories

        Args:
            article: Base article title
            limit: Max results

        Returns:
            List of related article titles
        """
        url = "https://en.wikipedia.org/w/api.php"
        related = []

        # Strategy 1: Get outgoing links
        try:
            client = await self._get_client()
            params = {
                'action': 'query',
                'titles': article,
                'prop': 'links',
                'pllimit': 50,
                'plnamespace': 0,
                'format': 'json'
            }
            response = await client.get(url, params=params)
            data = response.json()

            pages = data.get('query', {}).get('pages', {})
            for page in pages.values():
                links = page.get('links', [])
                for link in links:
                    title = link.get('title', '')
                    if title and not title.startswith(('Wikipedia:', 'Help:', 'Template:')):
                        related.append(title)
        except Exception as e:
            print(f"Error getting links: {e}")

        # Strategy 2: Search variations
        search_queries = [
            article,
            f"{article} related",
            f"{article} similar"
        ]

        for query in search_queries:
            results = await self.search_articles(query, limit=10)
            related.extend(results)

        # Remove duplicates while preserving order, exclude the original article
        seen = set()
        unique_related = []
        for title in related:
            title_lower = title.lower()
            if title_lower not in seen and title.lower() != article.lower():
                seen.add(title_lower)
                unique_related.append(title)

        return unique_related[:limit]

    def get_date_range(self, days: int = DEFAULT_DAYS_LOOKBACK) -> tuple:
        """
        Get start and end dates for pageview queries

        Args:
            days: Number of days to look back

        Returns:
            Tuple of (start_date, end_date) in YYYYMMDD format
        """
        end_date = datetime.now() - timedelta(days=1)  # Yesterday
        start_date = end_date - timedelta(days=days)

        return (
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d")
        )


# Singleton instance
wikipedia_service = WikipediaService()
