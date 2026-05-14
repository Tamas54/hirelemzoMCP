"""Echolot ↔ wikicorrelate client.

Thin sync HTTP client for our own wikicorrelate FastAPI service.
Deployed separately on Railway (Tamas54/wikicorrelate), the service
exposes Wikipedia-pageview-based correlation, top-movers and
predictive-lag endpoints.

Endpoint base set via WIKICORRELATE_URL env var (no default — if unset,
the wiki_trends tool returns a 'disabled' marker so callers can fall back
gracefully).

We use the same urllib-based fingerprint trick as the entities client
because some upstream WAFs/CDNs trip on raw Python-urllib headers.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

log = logging.getLogger("echolot.wikicorrelate")

WIKICORRELATE_URL = os.getenv("WIKICORRELATE_URL", "").strip().rstrip("/")
WIKICORRELATE_TIMEOUT_S = int(os.getenv("WIKICORRELATE_TIMEOUT_S", "30"))
USER_AGENT = "echolot-wikicorrelate-client/0.1"


def is_enabled() -> bool:
    """True iff WIKICORRELATE_URL is set in the env."""
    return bool(WIKICORRELATE_URL)


def _http_get_json(path: str, params: dict[str, Any], timeout: Optional[int] = None) -> Optional[dict]:
    if not WIKICORRELATE_URL:
        return None
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{WIKICORRELATE_URL}{path}?{qs}" if qs else f"{WIKICORRELATE_URL}{path}"
    req = urllib.request.Request(full, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout or WIKICORRELATE_TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        log.warning("wikicorrelate: HTTP %d %s for %s", exc.code, exc.reason, path)
        return None
    except urllib.error.URLError as exc:
        log.warning("wikicorrelate: transport error for %s: %s", path, exc)
        return None
    except Exception as exc:
        log.warning("wikicorrelate: %s on %s: %s", type(exc).__name__, path, exc)
        return None


def search_correlations(
    topic: str,
    days: int = 365,
    limit: int = 30,
    threshold: float = 0.1,
    method: str = "pearson",
) -> Optional[dict]:
    """GET /api/search — top correlated Wikipedia articles for a topic."""
    return _http_get_json("/api/search", {
        "q": topic,
        "days": days,
        "limit": limit,
        "threshold": threshold,
        "method": method,
    })


def top_movers(limit: int = 20) -> Optional[dict]:
    """GET /api/top-movers — currently trending correlation pairs."""
    return _http_get_json("/api/top-movers", {"limit": limit})


def predictive(topic: Optional[str] = None, days: int = 365) -> Optional[dict]:
    """GET /api/predictive — lag-correlation based forward predictions."""
    params: dict[str, Any] = {"days": days}
    if topic:
        params["q"] = topic
    return _http_get_json("/api/predictive", params)
