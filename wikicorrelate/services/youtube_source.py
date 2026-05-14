"""
YouTube Data Source
Fetches video upload frequency and view trends for topics from YouTube Data API v3.
"""
import asyncio
import httpx
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

from wikicorrelate.config import YOUTUBE_API_KEY, YOUTUBE_RATE_LIMIT_DELAY


class YouTubeDataSource:
    """
    YouTube Data API v3 integration for topic trend analysis.

    Provides:
    - Video upload frequency over time (how many videos/day on a topic)
    - Aggregate view counts for topic videos
    - Channel activity patterns
    """

    def __init__(self):
        self.api_key = YOUTUBE_API_KEY
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.user_agent = "CorrelateApp/1.0"

    def _check_api_key(self):
        """Verify API key is configured."""
        if not self.api_key:
            raise ValueError("YouTube API key not configured. Set YOUTUBE_API_KEY in .env")

    async def search_videos_by_topic(
        self,
        topic: str,
        published_after: date,
        published_before: date,
        max_results: int = 50
    ) -> List[Dict]:
        """
        Search for videos matching a topic within a date range.

        Args:
            topic: Search query
            published_after: Start date
            published_before: End date
            max_results: Maximum videos to return (max 50 per request)

        Returns:
            List of video metadata dicts
        """
        self._check_api_key()

        videos = []
        next_page_token = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(videos) < max_results:
                params = {
                    "key": self.api_key,
                    "part": "snippet",
                    "q": topic,
                    "type": "video",
                    "order": "date",
                    "publishedAfter": f"{published_after.isoformat()}T00:00:00Z",
                    "publishedBefore": f"{published_before.isoformat()}T23:59:59Z",
                    "maxResults": min(50, max_results - len(videos))
                }

                if next_page_token:
                    params["pageToken"] = next_page_token

                response = await client.get(
                    f"{self.base_url}/search",
                    params=params,
                    headers={"User-Agent": self.user_agent}
                )

                if response.status_code != 200:
                    print(f"YouTube API error: {response.status_code} - {response.text}")
                    break

                data = response.json()

                for item in data.get("items", []):
                    videos.append({
                        "video_id": item["id"]["videoId"],
                        "title": item["snippet"]["title"],
                        "channel_id": item["snippet"]["channelId"],
                        "channel_title": item["snippet"]["channelTitle"],
                        "published_at": item["snippet"]["publishedAt"],
                        "description": item["snippet"].get("description", "")[:200]
                    })

                next_page_token = data.get("nextPageToken")
                if not next_page_token:
                    break

                await asyncio.sleep(YOUTUBE_RATE_LIMIT_DELAY)

        return videos

    async def get_video_stats(self, video_ids: List[str]) -> Dict[str, Dict]:
        """
        Get statistics for multiple videos.

        Args:
            video_ids: List of video IDs (max 50 per request)

        Returns:
            Dict mapping video_id to stats
        """
        self._check_api_key()

        stats = {}

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Process in batches of 50
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i:i+50]

                params = {
                    "key": self.api_key,
                    "part": "statistics",
                    "id": ",".join(batch)
                }

                response = await client.get(
                    f"{self.base_url}/videos",
                    params=params,
                    headers={"User-Agent": self.user_agent}
                )

                if response.status_code != 200:
                    continue

                data = response.json()

                for item in data.get("items", []):
                    video_id = item["id"]
                    s = item.get("statistics", {})
                    stats[video_id] = {
                        "view_count": int(s.get("viewCount", 0)),
                        "like_count": int(s.get("likeCount", 0)),
                        "comment_count": int(s.get("commentCount", 0))
                    }

                await asyncio.sleep(YOUTUBE_RATE_LIMIT_DELAY)

        return stats

    async def get_topic_upload_frequency(
        self,
        topic: str,
        days: int = 365,
        granularity: str = "daily"
    ) -> List[Dict]:
        """
        Get video upload frequency for a topic over time.

        This creates a timeseries of "how many videos were uploaded per day"
        which can be correlated with other metrics.

        Args:
            topic: Topic to search for
            days: Number of days to look back
            granularity: "daily" or "weekly"

        Returns:
            List of {"date": "YYYY-MM-DD", "uploads": int}
        """
        self._check_api_key()

        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        # Fetch videos in chunks (API limitation)
        all_videos = []
        chunk_size = 30  # days per chunk

        current_start = start_date
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=chunk_size), end_date)

            videos = await self.search_videos_by_topic(
                topic=topic,
                published_after=current_start,
                published_before=current_end,
                max_results=50
            )

            all_videos.extend(videos)
            current_start = current_end + timedelta(days=1)

            await asyncio.sleep(YOUTUBE_RATE_LIMIT_DELAY)

        # Count uploads per day
        daily_counts = defaultdict(int)

        for video in all_videos:
            pub_date = video["published_at"][:10]  # YYYY-MM-DD
            daily_counts[pub_date] += 1

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
                week_count = sum(
                    daily_counts[(current + timedelta(days=d)).isoformat()]
                    for d in range(7)
                    if (current + timedelta(days=d)) <= end_date
                )
                timeseries.append({
                    "date": date_str,
                    "uploads": week_count
                })
            else:
                timeseries.append({
                    "date": date_str,
                    "uploads": daily_counts.get(date_str, 0)
                })

            current += timedelta(days=1 if granularity == "daily" else 7)

        return timeseries

    async def get_topic_view_trend(
        self,
        topic: str,
        days: int = 90,
        sample_size: int = 20
    ) -> Dict:
        """
        Estimate view trend for a topic by sampling recent videos.

        Note: YouTube API doesn't provide historical view counts,
        so we sample current views of videos published in different time windows.

        Args:
            topic: Topic to analyze
            days: Days to look back
            sample_size: Videos to sample per time window

        Returns:
            Dict with trend info and sampled data
        """
        self._check_api_key()

        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        # Get videos
        videos = await self.search_videos_by_topic(
            topic=topic,
            published_after=start_date,
            published_before=end_date,
            max_results=sample_size
        )

        if not videos:
            return {"error": "No videos found", "videos_found": 0}

        # Get stats for these videos
        video_ids = [v["video_id"] for v in videos]
        stats = await self.get_video_stats(video_ids)

        # Merge stats with video data
        for video in videos:
            vid = video["video_id"]
            if vid in stats:
                video.update(stats[vid])
            else:
                video["view_count"] = 0
                video["like_count"] = 0
                video["comment_count"] = 0

        # Calculate aggregates
        total_views = sum(v.get("view_count", 0) for v in videos)
        total_likes = sum(v.get("like_count", 0) for v in videos)
        avg_views = total_views / len(videos) if videos else 0

        return {
            "topic": topic,
            "period_days": days,
            "videos_sampled": len(videos),
            "total_views": total_views,
            "total_likes": total_likes,
            "avg_views_per_video": round(avg_views, 0),
            "videos": videos[:10]  # Return top 10 as sample
        }

    async def get_trending_topics_in_category(
        self,
        category_id: str = "0",  # 0 = all categories
        region_code: str = "US",
        max_results: int = 25
    ) -> List[Dict]:
        """
        Get currently trending videos to discover hot topics.

        Args:
            category_id: YouTube category ID (0 = all)
            region_code: Country code
            max_results: Max videos to return

        Returns:
            List of trending video metadata
        """
        self._check_api_key()

        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "key": self.api_key,
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": region_code,
                "maxResults": max_results
            }

            if category_id != "0":
                params["videoCategoryId"] = category_id

            response = await client.get(
                f"{self.base_url}/videos",
                params=params,
                headers={"User-Agent": self.user_agent}
            )

            if response.status_code != 200:
                return []

            data = response.json()
            videos = []

            for item in data.get("items", []):
                stats = item.get("statistics", {})
                videos.append({
                    "video_id": item["id"],
                    "title": item["snippet"]["title"],
                    "channel_title": item["snippet"]["channelTitle"],
                    "published_at": item["snippet"]["publishedAt"],
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "tags": item["snippet"].get("tags", [])[:10]
                })

            return videos


# Singleton instance
youtube_source = YouTubeDataSource()
