"""
Hacker News Data Source
Fetches story submissions and scores from the HN Firebase API.
"""
import asyncio
import httpx
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

from wikicorrelate.config import HACKERNEWS_RATE_LIMIT_DELAY


class HackerNewsDataSource:
    """
    Hacker News API integration for tech trend analysis.

    Uses the official Firebase API:
    https://hacker-news.firebaseio.com/v0/

    Provides:
    - Story submission frequency over time
    - Score (upvotes) trends
    - Comment volume analysis
    """

    def __init__(self):
        self.base_url = "https://hacker-news.firebaseio.com/v0"
        self.algolia_url = "https://hn.algolia.com/api/v1"  # For search
        self.user_agent = "CorrelateApp/1.0"

    async def _get_item(self, item_id: int) -> Optional[Dict]:
        """Fetch a single item (story, comment, etc) by ID."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/item/{item_id}.json",
                    headers={"User-Agent": self.user_agent}
                )
                if response.status_code == 200:
                    return response.json()
            except Exception as e:
                print(f"HN API error for item {item_id}: {e}")
        return None

    async def search_stories_by_topic(
        self,
        topic: str,
        from_date: date,
        to_date: date,
        max_results: int = 100
    ) -> List[Dict]:
        """
        Search for stories matching a topic using Algolia API.

        Args:
            topic: Search query
            from_date: Start date
            to_date: End date
            max_results: Maximum stories to return

        Returns:
            List of story metadata dicts
        """
        stories = []

        # Convert dates to Unix timestamps
        from_ts = int(datetime.combine(from_date, datetime.min.time()).timestamp())
        to_ts = int(datetime.combine(to_date, datetime.max.time()).timestamp())

        async with httpx.AsyncClient(timeout=30.0) as client:
            page = 0
            while len(stories) < max_results:
                params = {
                    "query": topic,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{from_ts},created_at_i<{to_ts}",
                    "hitsPerPage": min(50, max_results - len(stories)),
                    "page": page
                }

                try:
                    response = await client.get(
                        f"{self.algolia_url}/search",
                        params=params,
                        headers={"User-Agent": self.user_agent}
                    )

                    if response.status_code != 200:
                        break

                    data = response.json()
                    hits = data.get("hits", [])

                    if not hits:
                        break

                    for hit in hits:
                        stories.append({
                            "story_id": hit.get("objectID"),
                            "title": hit.get("title", ""),
                            "url": hit.get("url", ""),
                            "author": hit.get("author", ""),
                            "points": hit.get("points", 0),
                            "num_comments": hit.get("num_comments", 0),
                            "created_at": datetime.fromtimestamp(
                                hit.get("created_at_i", 0)
                            ).isoformat()
                        })

                    page += 1

                    if page >= data.get("nbPages", 1):
                        break

                    await asyncio.sleep(HACKERNEWS_RATE_LIMIT_DELAY)

                except Exception as e:
                    print(f"HN Algolia error: {e}")
                    break

        return stories

    async def get_topic_mention_frequency(
        self,
        topic: str,
        days: int = 365,
        granularity: str = "daily"
    ) -> List[Dict]:
        """
        Get story submission frequency for a topic over time.

        Creates a timeseries of "how many HN stories per day" which
        can be correlated with other metrics.

        Args:
            topic: Topic to search for
            days: Number of days to look back
            granularity: "daily" or "weekly"

        Returns:
            List of {"date": "YYYY-MM-DD", "mentions": int, "total_points": int}
        """
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        # Fetch all stories in the period
        stories = await self.search_stories_by_topic(
            topic=topic,
            from_date=start_date,
            to_date=end_date,
            max_results=1000
        )

        # Count per day
        daily_counts = defaultdict(lambda: {"mentions": 0, "points": 0, "comments": 0})

        for story in stories:
            created = story["created_at"][:10]  # YYYY-MM-DD
            daily_counts[created]["mentions"] += 1
            daily_counts[created]["points"] += story.get("points", 0)
            daily_counts[created]["comments"] += story.get("num_comments", 0)

        # Build timeseries
        timeseries = []
        current = start_date

        while current <= end_date:
            date_str = current.isoformat()

            if granularity == "weekly" and current.weekday() != 0:
                current += timedelta(days=1)
                continue

            if granularity == "weekly":
                # Sum the week
                week_data = {"mentions": 0, "points": 0, "comments": 0}
                for d in range(7):
                    day = (current + timedelta(days=d)).isoformat()
                    if day in daily_counts:
                        week_data["mentions"] += daily_counts[day]["mentions"]
                        week_data["points"] += daily_counts[day]["points"]
                        week_data["comments"] += daily_counts[day]["comments"]

                timeseries.append({
                    "date": date_str,
                    "mentions": week_data["mentions"],
                    "total_points": week_data["points"],
                    "total_comments": week_data["comments"]
                })
            else:
                day_data = daily_counts.get(date_str, {"mentions": 0, "points": 0, "comments": 0})
                timeseries.append({
                    "date": date_str,
                    "mentions": day_data["mentions"],
                    "total_points": day_data["points"],
                    "total_comments": day_data["comments"]
                })

            current += timedelta(days=1 if granularity == "daily" else 7)

        return timeseries

    async def get_story_details(self, story_id: int) -> Optional[Dict]:
        """
        Get detailed information about a specific story.

        Args:
            story_id: HN story ID

        Returns:
            Story details or None
        """
        item = await self._get_item(story_id)
        if not item:
            return None

        return {
            "story_id": story_id,
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "author": item.get("by", ""),
            "score": item.get("score", 0),
            "num_comments": len(item.get("kids", [])),
            "created_at": datetime.fromtimestamp(item.get("time", 0)).isoformat(),
            "type": item.get("type", "story")
        }

    async def get_front_page_stories(self) -> List[Dict]:
        """
        Get current front page stories (top 30).

        Useful for discovering what's trending RIGHT NOW.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/topstories.json",
                    headers={"User-Agent": self.user_agent}
                )

                if response.status_code != 200:
                    return []

                story_ids = response.json()[:30]

            except Exception as e:
                print(f"HN top stories error: {e}")
                return []

        # Fetch each story
        stories = []
        for story_id in story_ids:
            story = await self.get_story_details(story_id)
            if story:
                stories.append(story)
            await asyncio.sleep(HACKERNEWS_RATE_LIMIT_DELAY)

        return stories

    async def get_best_stories(self, limit: int = 50) -> List[Dict]:
        """Get best (highest voted) stories."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/beststories.json",
                    headers={"User-Agent": self.user_agent}
                )

                if response.status_code != 200:
                    return []

                story_ids = response.json()[:limit]

            except Exception as e:
                print(f"HN best stories error: {e}")
                return []

        stories = []
        for story_id in story_ids[:20]:  # Limit API calls
            story = await self.get_story_details(story_id)
            if story:
                stories.append(story)
            await asyncio.sleep(HACKERNEWS_RATE_LIMIT_DELAY)

        return stories

    async def get_topic_sentiment(
        self,
        topic: str,
        days: int = 30
    ) -> Dict:
        """
        Get aggregate sentiment indicators for a topic.

        Uses points and comment ratios as proxy for sentiment.

        Args:
            topic: Topic to analyze
            days: Days to look back

        Returns:
            Dict with sentiment indicators
        """
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        stories = await self.search_stories_by_topic(
            topic=topic,
            from_date=start_date,
            to_date=end_date,
            max_results=200
        )

        if not stories:
            return {
                "topic": topic,
                "error": "No stories found",
                "story_count": 0
            }

        total_points = sum(s.get("points", 0) for s in stories)
        total_comments = sum(s.get("num_comments", 0) for s in stories)
        avg_points = total_points / len(stories)
        avg_comments = total_comments / len(stories)

        # Engagement ratio (comments per point)
        engagement_ratio = total_comments / total_points if total_points > 0 else 0

        return {
            "topic": topic,
            "period_days": days,
            "story_count": len(stories),
            "total_points": total_points,
            "total_comments": total_comments,
            "avg_points_per_story": round(avg_points, 1),
            "avg_comments_per_story": round(avg_comments, 1),
            "engagement_ratio": round(engagement_ratio, 3),
            "top_stories": sorted(stories, key=lambda x: x.get("points", 0), reverse=True)[:5]
        }


# Singleton instance
hackernews_source = HackerNewsDataSource()
