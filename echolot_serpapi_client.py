"""Echolot ↔ SerpAPI Google Trends client.

Thin sync HTTP client for SerpAPI's google_trends_trending_now engine.
Carries an API key via SERPAPI_KEY env var (Kommandant's account, billed
per request — leave unset to disable the google_trends tool gracefully).

Endpoint: https://serpapi.com/search.json
Engine:   google_trends_trending_now
Response: realtime_searches[] with title, search_volume, articles[]
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

log = logging.getLogger("echolot.serpapi")

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
SERPAPI_URL = "https://serpapi.com/search.json"
SERPAPI_TIMEOUT_S = int(os.getenv("SERPAPI_TIMEOUT_S", "20"))


def is_enabled() -> bool:
    """True iff SERPAPI_KEY is set."""
    return bool(SERPAPI_KEY)


def trending_now(geo: str = "HU", frequency: str = "realtime",
                 timeout: Optional[int] = None) -> Optional[dict]:
    """SerpAPI google_trends_trending_now — currently spiking searches.

    Args:
        geo: 2-letter country code (HU, US, DE, FR, ES, JP, CN, GB, ...)
        frequency: 'realtime' (real-time spikes) or 'daily' (top of day)
        timeout: per-request seconds

    Returns the SerpAPI JSON response or None on error / unconfigured.
    """
    if not SERPAPI_KEY:
        return None
    params = {
        "engine": "google_trends_trending_now",
        "frequency": frequency,
        "geo": geo.upper(),
        "api_key": SERPAPI_KEY,
    }
    qs = urllib.parse.urlencode(params)
    url = f"{SERPAPI_URL}?{qs}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "echolot-serpapi-client/0.1",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout or SERPAPI_TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        log.warning("serpapi: HTTP %d %s", exc.code, exc.reason)
        return None
    except urllib.error.URLError as exc:
        log.warning("serpapi: transport error: %s", exc)
        return None
    except Exception as exc:
        log.warning("serpapi: %s: %s", type(exc).__name__, exc)
        return None


def trends_for(query: str, geo: str = "HU", date_range: str = "now 7-d",
               timeout: Optional[int] = None) -> Optional[dict]:
    """SerpAPI google_trends — interest-over-time for a specific query.

    Args:
        query: search term
        geo: country code, '' for global
        date_range: 'now 1-d', 'now 7-d', 'today 1-m', 'today 12-m', etc.
    """
    if not SERPAPI_KEY:
        return None
    params = {
        "engine": "google_trends",
        "q": query,
        "geo": geo.upper() if geo else "",
        "date": date_range,
        "data_type": "TIMESERIES",
        "api_key": SERPAPI_KEY,
    }
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v != ""})
    url = f"{SERPAPI_URL}?{qs}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "echolot-serpapi-client/0.1",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout or SERPAPI_TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        log.warning("serpapi: HTTP %d %s for query %r", exc.code, exc.reason, query)
        return None
    except Exception as exc:
        log.warning("serpapi: %s on query %r: %s", type(exc).__name__, query, exc)
        return None
