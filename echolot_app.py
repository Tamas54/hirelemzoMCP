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


def _metrics_middleware(app: ASGIApp) -> ASGIApp:
    """Olvasó-analytics (plan 7a): minden HTTP kérés puffer-naplózása.

    record() csak memóriába ír (lock + deque), a DB-flush külön szálon fut —
    a kérés útvonalát nem lassítja és nem törheti."""
    from echolot_metrics import record

    async def wrapped(scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("method") in ("GET", "POST"):
            try:
                headers = {k.decode("latin1").lower(): v.decode("latin1")
                           for k, v in (scope.get("headers") or [])}
                # Railway/proxy mögött az X-Forwarded-For az igazi kliens-IP
                ip = (headers.get("x-forwarded-for", "").split(",")[0].strip()
                      or (scope.get("client") or ("?",))[0])
                qs = (scope.get("query_string") or b"").decode("latin1")
                lang = ""
                for part in qs.split("&"):
                    if part.startswith("lang="):
                        lang = part[5:][:5]
                        break
                record(scope.get("path") or "/", lang, ip,
                       headers.get("user-agent", ""))
            except Exception:
                pass
        await app(scope, receive, send)
    return wrapped


def _mcp_key_gate(app: ASGIApp) -> ASGIApp:
    """MCP API-kulcs kapu (plan 3c). Alapból KI (a /mcp nyitva marad) —
    élesítés: MCP_REQUIRE_KEY=true env. Kulcs: X-API-Key fejléc vagy
    ?key= query-param; validálás + napi tier-kvóta az echolot_auth-ban."""
    import asyncio as _aio
    import json as _json
    import os as _os

    async def wrapped(scope: dict, receive: Any, send: Any) -> None:
        if (scope.get("type") == "http" and scope.get("path") == "/mcp"
                and _os.environ.get("MCP_REQUIRE_KEY", "").lower()
                in ("1", "true", "yes")):
            headers = {k.decode("latin1").lower(): v.decode("latin1")
                       for k, v in (scope.get("headers") or [])}
            key = headers.get("x-api-key", "")
            if not key:
                qs = (scope.get("query_string") or b"").decode("latin1")
                for part in qs.split("&"):
                    if part.startswith("key="):
                        key = part[4:]
                        break
            from echolot_auth import validate_api_key
            from scraper import DB_PATH as _dbp
            ok, why = await _aio.to_thread(validate_api_key, str(_dbp), key)
            if not ok:
                status = 429 if why == "quota" else 401
                body = _json.dumps({
                    "error": why,
                    "hint": "Get an API key at /account (register at /signup), "
                            "then pass it as X-API-Key header or ?key= param.",
                }).encode()
                await send({"type": "http.response.start", "status": status,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
                return
        await app(scope, receive, send)
    return wrapped


def build_app() -> ASGIApp:
    """Return the Echolot ASGI app, ready to hand to uvicorn / hypercorn."""
    from server import mcp
    return _metrics_middleware(
        _mcp_key_gate(_normalize_mcp_path(mcp.streamable_http_app())))
