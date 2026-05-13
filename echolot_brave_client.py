"""Echolot ↔ Brave-MCP client.

Thin async HTTP client for our own brave-mcp-server (Railway-deployed).
Calls `brave_scrape` (or `brave_scrape_robust`) via MCP JSON-RPC over HTTPS
and returns a normalized dict.

Endpoint default: https://brave-mcp-server-production.up.railway.app/mcp
(override via BRAVE_MCP_URL env var).

The brave-mcp-server has no auth — we still send `X-Client-Id: echolot-fetcher`
for traceability in its logs.

Usage:
    import aiohttp
    from echolot_brave_client import fetch

    async with aiohttp.ClientSession() as session:
        result = await fetch(session, "https://example.com/article")
        if result and result["content_usable"]:
            print(result["text"])
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

import aiohttp

log = logging.getLogger("echolot.brave_client")

BRAVE_MCP_URL = os.getenv(
    "BRAVE_MCP_URL",
    "https://brave-mcp-server-production.up.railway.app/mcp",
)
BRAVE_TIMEOUT_S = int(os.getenv("BRAVE_TIMEOUT_S", "60"))
CLIENT_ID = "echolot-fetcher"


def _parse_mcp_response(body: str) -> Optional[dict[str, Any]]:
    """Parse the JSON-RPC envelope, handling both plain JSON and SSE-style payloads."""
    data_lines = [ln[6:] for ln in body.splitlines() if ln.startswith("data: ")]
    payload = data_lines[0] if data_lines else body
    try:
        envelope = json.loads(payload)
    except json.JSONDecodeError as exc:
        log.warning("brave: response not JSON (%s); first 200 chars: %r",
                    exc, body[:200])
        return None
    if "error" in envelope:
        log.warning("brave: JSON-RPC error: %s", envelope["error"])
        return None
    try:
        inner_text = envelope["result"]["content"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        log.warning("brave: unexpected envelope shape (%s); keys: %s",
                    exc, list(envelope.keys()))
        return None
    try:
        return json.loads(inner_text)
    except json.JSONDecodeError:
        # Some scrape paths return plain markdown text — wrap it minimally.
        return {"markdown": inner_text, "text": inner_text,
                "content_usable": bool(inner_text.strip()), "block_reason": None}


async def _call_tool(
    session: aiohttp.ClientSession,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """One JSON-RPC tools/call to brave-mcp-server. Returns parsed inner payload or None."""
    timeout_s = timeout if timeout is not None else BRAVE_TIMEOUT_S
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Client-Id": CLIENT_ID,
    }
    try:
        async with session.post(
            BRAVE_MCP_URL, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            if resp.status != 200:
                log.warning("brave: HTTP %d for %s", resp.status, tool_name)
                return None
            body = await resp.text()
    except Exception as exc:
        log.warning("brave: transport error for %s: %s: %s",
                    tool_name, type(exc).__name__, exc)
        return None
    return _parse_mcp_response(body)


async def search(
    session: aiohttp.ClientSession,
    query: str,
    count: int = 10,
    timeout: Optional[int] = None,
) -> Optional[list[dict[str, Any]]]:
    """Run a Brave web search via brave-mcp-server.

    Returns a list of {title, url, description} dicts, or None on error.
    Empty list = the engine returned no results for this query.
    """
    result = await _call_tool(session, "brave_search",
                              {"query": query, "limit": int(count)},
                              timeout=timeout)
    if result is None:
        return None
    return result.get("results") or []


def _call_tool_sync(tool_name: str, arguments: dict[str, Any],
                    timeout: Optional[int] = None) -> Optional[dict[str, Any]]:
    """Synchronous MCP tools/call to brave-mcp-server. Returns inner payload or None."""
    timeout_s = timeout if timeout is not None else BRAVE_TIMEOUT_S
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }).encode("utf-8")
    req = urllib.request.Request(
        BRAVE_MCP_URL, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-Client-Id": CLIENT_ID,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        log.warning("brave (sync): transport error for %s: %s", tool_name, exc)
        return None
    except Exception as exc:
        log.warning("brave (sync): %s: %s", type(exc).__name__, exc)
        return None
    return _parse_mcp_response(body)


def search_sync(query: str, count: int = 10,
                timeout: Optional[int] = None) -> Optional[list[dict[str, Any]]]:
    """Synchronous Brave web search — callable from sync code (MCP tool handlers).

    Returns a list of {title, url, description} dicts, or None on transport
    error. An empty list means the engine returned no results.
    """
    result = _call_tool_sync("brave_search",
                             {"query": query, "limit": int(count)},
                             timeout=timeout)
    if result is None:
        return None
    return result.get("results") or []


def fetch_sync(url: str, robust: bool = False,
               timeout: Optional[int] = None) -> Optional[dict[str, Any]]:
    """Synchronous Brave scrape of a single URL — callable from sync MCP tools.

    Works on any URL the brave-mcp-server can handle: news articles, blog
    posts, social-media post pages, etc. Set robust=True to engage the
    7-level anti-bot chain for protected sites.

    Returns the full Brave payload (content_usable, block_reason, text,
    markdown, title, ...) or None on transport error.
    """
    tool_name = "brave_scrape_robust" if robust else "brave_scrape"
    return _call_tool_sync(tool_name, {"url": url}, timeout=timeout)


async def fetch(
    session: aiohttp.ClientSession,
    url: str,
    robust: bool = False,
    timeout: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Fetch full text for a single URL via brave-mcp-server.

    Args:
        session: shared aiohttp.ClientSession (caller owns the lifecycle).
        url: article URL to scrape.
        robust: if True, calls brave_scrape_robust (7-level anti-bot chain).
            Default False (fast Puppeteer-Stealth scrape, ~5s).
        timeout: per-request seconds; defaults to BRAVE_TIMEOUT_S.

    Returns:
        Dict with at least these keys: content_usable (bool), block_reason
        (str|None), text (str), markdown (str), title (str). Returns None on
        transport errors (network, non-200, malformed response).
    """
    tool_name = "brave_scrape_robust" if robust else "brave_scrape"
    return await _call_tool(session, tool_name, {"url": url}, timeout=timeout)
