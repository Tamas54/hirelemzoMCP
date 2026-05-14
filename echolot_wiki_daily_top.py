"""Echolot Wikipedia daily top-pageviews — what Wikipedia readers spike on TODAY.

Hits the Wikimedia Pageviews API `/top/{wiki}/all-access/YYYY/MM/DD` endpoint
for yesterday's UTC date (today is incomplete) and returns the top-N most-read
articles.

Multilingual: pass geo_wiki='hu' for hu.wikipedia, 'de' for de.wikipedia, etc.

No auth, no rate-limit issue at this volume (1 request per call). Cached for
1 hour in-memory.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx

log = logging.getLogger("echolot.wiki_daily_top")

USER_AGENT = "Echolot/1.0 (https://github.com/Tamas54/hirelemzoMCP)"
CACHE_TTL = 60 * 60  # 1 hour
_cache: dict[tuple, tuple[float, list]] = {}

SKIP_PREFIXES = (
    "Special:", "Wikipedia:", "File:", "Template:", "Help:",
    "Category:", "Portal:", "Draft:", "Module:", "MediaWiki:",
)
SKIP_EXACT = {"Main_Page", "Kezdőlap", "Hauptseite", "-", "Search"}

SUPPORTED_WIKIS = {
    "en", "hu", "de", "fr", "es", "it", "pl", "ru", "uk",
    "ja", "zh", "ar", "tr", "pt", "nl", "sv", "cs", "ro",
}


async def top_pageviews(
    geo_wiki: str = "en",
    limit: int = 20,
    days_back: int = 1,
) -> list[dict]:
    """Top N Wikipedia articles by daily pageviews.

    Args:
        geo_wiki: language-code prefix for Wikipedia (en, hu, de, fr, es, ...).
            Default 'en'.
        limit: how many articles to return, 1-100 (default 20).
        days_back: 1 = yesterday (today is incomplete in the API).
            Bump if yesterday is also not yet published (~6h after UTC midnight).

    Returns:
        List of {article, views, rank, wiki, date}, sorted by views desc.
        Empty list on transport / API error.
    """
    geo_wiki = (geo_wiki or "en").lower()
    if geo_wiki not in SUPPORTED_WIKIS:
        return []
    limit = max(1, min(100, limit))
    target = datetime.utcnow() - timedelta(days=max(1, days_back))
    date_path = target.strftime("%Y/%m/%d")
    cache_key = (geo_wiki, date_path)
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1][:limit]

    url = (
        f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
        f"{geo_wiki}.wikipedia/all-access/{date_path}"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        log.warning("wiki_daily_top: HTTP %d for %s/%s", exc.response.status_code, geo_wiki, date_path)
        return []
    except Exception as exc:
        log.warning("wiki_daily_top: %s for %s: %s", type(exc).__name__, geo_wiki, exc)
        return []

    items = data.get("items", [])
    if not items:
        return []
    raw_articles = items[0].get("articles", [])

    filtered: list[dict] = []
    for a in raw_articles:
        name = a.get("article", "")
        if not name or name.startswith(SKIP_PREFIXES) or name in SKIP_EXACT:
            continue
        if name.endswith("_(disambiguation)"):
            continue
        filtered.append({
            "article": name,
            "title": name.replace("_", " "),
            "views": a.get("views", 0),
            "rank": a.get("rank"),
            "wiki": f"{geo_wiki}.wikipedia",
            "date": target.strftime("%Y-%m-%d"),
        })
        if len(filtered) >= limit:
            break

    _cache[cache_key] = (now, filtered)
    return filtered
