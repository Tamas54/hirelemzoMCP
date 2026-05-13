"""Echolot Twitter / X fast-path.

X status pages serve a JS-required stub to non-browser clients, but the stub
embeds the full tweet text in `og:description` meta tag (for link-preview
cards). A plain HTTP GET pulls it in ~300ms — no headless browser, no
FlareSolverr, no JS render needed.

Use case: scrape_url on x.com/<user>/status/<id> bypasses the slow Brave
chain and returns the tweet text directly.
"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from typing import Optional

log = logging.getLogger("echolot.twitter")

TWITTER_STATUS_RE = re.compile(
    r'^https?://(?:x|twitter)\.com/[^/]+/status/\d+',
    re.IGNORECASE,
)

# Both attribute orders: <meta property="..." content="..."> and reverse.
META_RE_PROP_FIRST = re.compile(
    r'<meta[^>]+(?:property|name)="((?:og|twitter):[^"]+)"[^>]+content="([^"]*)"',
    re.IGNORECASE,
)
META_RE_CONTENT_FIRST = re.compile(
    r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="((?:og|twitter):[^"]+)"',
    re.IGNORECASE,
)

UA_BOT = "Mozilla/5.0 (compatible; OG-link-preview-bot)"


def is_twitter_status_url(url: str) -> bool:
    return bool(TWITTER_STATUS_RE.match(url or ""))


def fetch_tweet_og(url: str, timeout: int = 10) -> Optional[dict]:
    """Fast path for X/Twitter status URLs.

    Returns dict with: content_usable, text, title, block_reason, tweet_meta
    (all OG/Twitter tags). None on transport failure.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA_BOT, "Accept": "text/html,*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        log.warning("twitter fast-path: transport error for %s: %s", url, exc)
        return None
    except Exception as exc:
        log.warning("twitter fast-path: %s: %s", type(exc).__name__, exc)
        return None

    meta: dict[str, str] = {}
    for m in META_RE_PROP_FIRST.finditer(html):
        meta.setdefault(m.group(1), m.group(2))
    for m in META_RE_CONTENT_FIRST.finditer(html):
        meta.setdefault(m.group(2), m.group(1))

    tweet_text = meta.get("og:description") or meta.get("twitter:description") or ""
    tweet_text = tweet_text.strip()
    return {
        "content_usable": bool(tweet_text),
        "block_reason": None if tweet_text else "no_og_description",
        "title": meta.get("og:title") or "",
        "text": tweet_text,
        "tweet_meta": meta,
    }
