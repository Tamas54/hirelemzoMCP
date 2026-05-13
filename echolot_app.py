"""Echolot MCP HTTP app builder.

FastMCP registers the MCP endpoint as a Starlette `Route("/mcp", ...)` — an
exact-match route. Starlette's default `redirect_slashes=True` then turns any
request to `/mcp/` into a 307 redirect.

Most HTTP clients follow 307 transparently, but minimal MCP clients in some
agent frameworks (and a few corporate proxies) do not. We want both `/mcp` and
`/mcp/` to return 200 directly, so the tool behaves identically regardless of
how the URL is spelled at the caller.

Solution: a tiny ASGI wrapper that rewrites the request path from `/mcp/` to
`/mcp` BEFORE routing. No FastMCP internals patched, no extra Starlette
configuration needed.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable


ASGIApp = Callable[[dict, Callable[[], Awaitable[dict]], Callable[[dict], Awaitable[None]]], Awaitable[None]]


def _normalize_mcp_path(app: ASGIApp) -> ASGIApp:
    """ASGI middleware: rewrite /mcp/ → /mcp before routing.

    Leaves all other paths untouched. Forwards lifespan / websocket scopes
    transparently.
    """
    async def wrapped(scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path") == "/mcp/":
            scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
        await app(scope, receive, send)
    return wrapped


def build_app() -> ASGIApp:
    """Return the Echolot ASGI app, ready to hand to uvicorn / hypercorn."""
    from server import mcp
    return _normalize_mcp_path(mcp.streamable_http_app())
