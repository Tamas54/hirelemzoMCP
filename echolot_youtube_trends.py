"""Echolot YouTube trending — most-popular videos per region.

Ported from Tamas54/Trendinghub collector.py, simplified to a direct
httpx call against the YouTube Data API v3 (no googleapiclient dep).

Needs YOUTUBE_API_KEY env var — graceful no-op otherwise.

API: https://developers.google.com/youtube/v3/docs/videos/list
Quota: each call costs ~1 unit; the free tier gives 10000 units/day.
With a 1-hour cache that's effectively unlimited at our usage.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx

log = logging.getLogger("echolot.youtube_trends")

API_URL = "https://www.googleapis.com/youtube/v3/videos"
CACHE_TTL = 60 * 60  # 1 hour
_cache: dict[tuple, tuple[float, list]] = {}

# YouTube category IDs that matter for news/discussion
# Full list: https://developers.google.com/youtube/v3/docs/videoCategories/list
CATEGORY_IDS = {
    "all":      "",
    "news":     "25",
    "tech":     "28",
    "gaming":   "20",
    "music":    "10",
    "sports":   "17",
    "edu":      "27",
    "comedy":   "23",
    "movies":   "1",
}

# Supported regions (ISO 3166-1 alpha-2)
SUPPORTED_REGIONS = {
    "HU", "US", "GB", "DE", "FR", "ES", "IT", "PL", "RU", "UA",
    "JP", "KR", "CN", "BR", "MX", "IN", "TR", "NL", "SE", "CZ",
}


def is_enabled() -> bool:
    return bool(os.getenv("YOUTUBE_API_KEY", "").strip())


async def trending_videos(
    region: str = "HU",
    count: int = 20,
    category: str = "all",
    timeout: float = 15.0,
) -> Optional[list[dict]]:
    """Top trending videos in `region`.

    Args:
        region: ISO 3166-1 alpha-2 country code (HU, US, GB, …).
        count: max videos, 1-50.
        category: 'all' | 'news' | 'tech' | 'gaming' | 'music' | 'sports'
            | 'edu' | 'comedy' | 'movies'.
        timeout: request timeout in seconds.

    Returns:
        List of {rank, title, channel, video_id, url, views, likes,
        comments, published_at, description, thumbnail, engagement_score}
        sorted by trending rank, or None if disabled / API error.
    """
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return None
    region = region.upper()
    if region not in SUPPORTED_REGIONS:
        log.warning("youtube_trends: unsupported region %r", region)
        return None
    count = max(1, min(50, count))
    cat_id = CATEGORY_IDS.get(category, "")

    cache_key = (region, count, cat_id)
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]

    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": count,
        "key": api_key,
    }
    if cat_id:
        params["videoCategoryId"] = cat_id

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        # 403 = quota exhausted or key disabled; 400 = bad region/category
        log.warning("youtube_trends: HTTP %d for %s/%s: %s",
                    exc.response.status_code, region, cat_id,
                    exc.response.text[:200])
        return None
    except Exception as exc:
        log.warning("youtube_trends: %s for %s: %s",
                    type(exc).__name__, region, exc)
        return None

    results: list[dict] = []
    for rank, item in enumerate(data.get("items", []), 1):
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        vid = item.get("id", "")
        views = int(stats.get("viewCount", 0) or 0)
        likes = int(stats.get("likeCount", 0) or 0)
        comments = int(stats.get("commentCount", 0) or 0)
        engagement = round((likes + comments) / max(views, 1) * 10000, 2)
        thumbs = snippet.get("thumbnails", {})
        thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        results.append({
            "rank": rank,
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
            "views": views,
            "likes": likes,
            "comments": comments,
            "engagement_score": engagement,
            "published_at": snippet.get("publishedAt", ""),
            "description": (snippet.get("description") or "")[:200],
            "thumbnail": thumb,
            "category_id": snippet.get("categoryId", ""),
            "region": region,
        })

    _cache[cache_key] = (now, results)
    return results
