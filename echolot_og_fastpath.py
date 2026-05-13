"""Echolot OG-meta fast-path for social-media and short-post URLs.

Many platforms (Twitter/X, Reddit, LinkedIn, Threads, Instagram, Facebook,
Mastodon, Bluesky) serve a small stub HTML to non-browser clients that
embeds the post text in og:description / twitter:description meta tags —
because link-preview cards need them. A 300ms HTTP GET extracts the post,
no headless browser, no JS render, no FlareSolverr.

Used as a fast-path in scrape_url BEFORE falling through to the Brave
7-level chain. Returns same shape regardless of platform so callers don't
care which path served them — only the `fast_path` field tells.

To add a new platform: append (regex, name) to PLATFORM_PATTERNS. If a
platform serves OG meta in the standard way, no other changes needed.

NOTE: this is the SAME mechanic the brave-mcp-server should bake in
natively, so every MCP client benefits without re-implementing. See
brave_mcp_og_fastpath_todo memory note.
"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from typing import Optional

log = logging.getLogger("echolot.og_fastpath")

# Order matters: most-specific first. `name` is informational, used in
# the fast_path field of the scrape_url response.
PLATFORM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'^https?://(?:x|twitter)\.com/[^/]+/status/\d+', re.IGNORECASE), "twitter"),
    (re.compile(r'^https?://(?:www\.)?reddit\.com/r/[^/]+/comments/', re.IGNORECASE), "reddit"),
    (re.compile(r'^https?://old\.reddit\.com/r/[^/]+/comments/', re.IGNORECASE), "reddit"),
    (re.compile(r'^https?://(?:www\.)?linkedin\.com/(?:posts|feed/update)/', re.IGNORECASE), "linkedin"),
    (re.compile(r'^https?://(?:www\.)?threads\.(?:net|com)/@[^/]+/post/', re.IGNORECASE), "threads"),
    (re.compile(r'^https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/', re.IGNORECASE), "instagram"),
    (re.compile(r'^https?://(?:www\.)?facebook\.com/[^/]+/posts/', re.IGNORECASE), "facebook"),
    (re.compile(r'^https?://bsky\.app/profile/[^/]+/post/', re.IGNORECASE), "bluesky"),
    (re.compile(r'^https?://[^/]+/@[^/]+/\d+', re.IGNORECASE), "mastodon"),
    (re.compile(r'^https?://news\.ycombinator\.com/item\?id=', re.IGNORECASE), "hackernews"),
]

META_RE_PROP_FIRST = re.compile(
    r'<meta[^>]+(?:property|name)="((?:og|twitter):[^"]+)"[^>]+content="([^"]*)"',
    re.IGNORECASE,
)
META_RE_CONTENT_FIRST = re.compile(
    r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="((?:og|twitter):[^"]+)"',
    re.IGNORECASE,
)

# Some platforms (e.g. mastodon) serve <meta property="og:..." content='single quotes'>
META_RE_PROP_FIRST_SQ = re.compile(
    r"<meta[^>]+(?:property|name)='((?:og|twitter):[^']+)'[^>]+content='([^']*)'",
    re.IGNORECASE,
)

UA_BOT = "Mozilla/5.0 (compatible; OG-link-preview-bot)"


def match_platform(url: str) -> Optional[str]:
    """Return platform name (twitter, reddit, …) if the URL matches a known
    SM/post pattern, else None.
    """
    if not url:
        return None
    for pat, name in PLATFORM_PATTERNS:
        if pat.match(url):
            return name
    return None


def fetch_og(url: str, timeout: int = 10) -> Optional[dict]:
    """Generic OG-meta fast-path: GET the URL, extract og:/twitter: meta tags.

    Returns dict with: content_usable, text, title, block_reason, og_meta.
    Returns None on transport failure (caller can fall back to Brave).
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA_BOT, "Accept": "text/html,*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        log.warning("og-fast-path: transport error for %s: %s", url, exc)
        return None
    except Exception as exc:
        log.warning("og-fast-path: %s: %s", type(exc).__name__, exc)
        return None

    meta: dict[str, str] = {}
    for m in META_RE_PROP_FIRST.finditer(html):
        meta.setdefault(m.group(1), m.group(2))
    for m in META_RE_CONTENT_FIRST.finditer(html):
        meta.setdefault(m.group(2), m.group(1))
    for m in META_RE_PROP_FIRST_SQ.finditer(html):
        meta.setdefault(m.group(1), m.group(2))

    text = (
        meta.get("og:description")
        or meta.get("twitter:description")
        or ""
    ).strip()
    return {
        "content_usable": bool(text),
        "block_reason": None if text else "no_og_description",
        "title": meta.get("og:title") or meta.get("twitter:title") or "",
        "text": text,
        "og_meta": meta,
    }
