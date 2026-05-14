"""
ECHOLOT MCP Server — global narrative intelligence for researchers.
(Formerly HírMagnet — now extended with multi-sphere global news.)

MCP tools:
  - get_news               Daily news by date/category/sphere/lean/language/source
  - search_news            Full-text search across titles + leads (FTS5)
  - get_weekly_digest      Day-by-day weekly recap for reports
  - get_trending           Cross-source trending topics
  - get_sources            Available sources, grouped by sphere/category
  - get_spheres            Sphere taxonomy + per-sphere coverage stats
  - narrative_divergence   "What does each sphere say about topic X?" — Echolot payoff
  - get_scrape_status      Scraper health, last run, DB stats

REST routes (for landing page):
  - /              landing page
  - /api/news      latest articles (paginated)
  - /api/spheres   sphere stats
  - /health        liveness probe
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from echolot_health import compute_health
from echolot_diversity import diversify
from echolot_velocity import compute_sphere_velocity
from echolot_entities import resolve as resolve_entity
from echolot_brave_client import search_sync as brave_search_sync
from echolot_brave_client import fetch_sync as brave_fetch_sync
from echolot_og_fastpath import match_platform, fetch_og
# Wikicorrelate engine (in-process, ported from Tamas54/wikicorrelate Phase A)
from wikicorrelate.services.correlate import search_and_correlate as _wiki_search
from wikicorrelate.database import init_db as _wiki_init_db, get_top_movers as _wiki_db_top_movers
from echolot_wiki_daily_top import top_pageviews as _wiki_top_pageviews
try:
    from wikicorrelate.services.predictive import find_predictive_signals_expanded as _wiki_predictive
except Exception:  # optional path
    _wiki_predictive = None

_wiki_db_inited = False

async def _ensure_wiki_db_async():
    """One-time wikicorrelate DB init; safe to call repeatedly."""
    global _wiki_db_inited
    if _wiki_db_inited:
        return
    try:
        await _wiki_init_db()
        _wiki_db_inited = True
    except Exception as exc:
        logger.warning("wikicorrelate init_db failed: %s", exc)
from echolot_gnews_trends import (
    fetch_country_trending as gnews_trending,
    cross_source_supertrends as gnews_supertrends,
    GEO_FEEDS as GNEWS_GEO_FEEDS,
)
from echolot_dashboard import (
    augment_landing,
    render_dashboard,
    render_divergence_partial,
    render_spheres_page,
    render_sphere_detail_page,
    render_health_page,
    render_trending_page,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("echolot-mcp")

DB_PATH = Path(os.environ.get("DB_PATH", "echolot.db"))


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Echolot",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
)


# ---------------------------------------------------------------------------
# Helper: parse date arg
# ---------------------------------------------------------------------------
def _parse_date_arg(date: str) -> tuple[datetime, datetime] | tuple[None, str]:
    if date == "today":
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    elif date == "yesterday":
        start = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        try:
            start = datetime.fromisoformat(date)
        except ValueError:
            return (None, f"Invalid date format: {date}. Use 'today', 'yesterday', or YYYY-MM-DD")
    return (start, start + timedelta(days=1))


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "spheres_json" in d:
        try:
            d["spheres"] = json.loads(d.pop("spheres_json"))
        except Exception:
            d["spheres"] = []
            d.pop("spheres_json", None)
    return d


# ===========================================================================
# MCP TOOLS
# ===========================================================================

@mcp.tool()
def get_news(
    date: str = "today",
    category: str = "",
    source: str = "",
    language: str = "",
    sphere: str = "",
    lean: str = "",
    limit: int = 30,
    diversify_results: bool = True,
    max_per_source: int = 3,
    max_per_sphere: int = 5,
) -> str:
    """Get news articles by date and various filters.

    Args:
        date: "today", "yesterday", or ISO YYYY-MM-DD. Default: "today"
        category: Hirmagnet category — politika, gazdaság, foreign, tech, sport,
                  general, lifestyle, entertainment, cars, EU, vélemény, global. Empty = all.
        source: Substring match on source name (e.g. "HVG", "Reuters").
        language: ISO code (hu, en, de, ru, zh, ja, fr, uk).
        sphere: Sphere tag — hu_press, hu_economy, global_anchor, cn_state,
                ru_milblog_pro, ua_front_osint, etc. See get_spheres for the full list.
        lean: gov | opposition | left | right | center | analytical | unknown.
        limit: 1–100 (default: 30)
        diversify_results: round-robin across sources/spheres so one prolific
                feed (e.g. Sydney Morning Herald) cannot dominate the result.
                Default: True. Set False for raw recency.
        max_per_source: when diversify_results=True, max articles from one source (default 3).
        max_per_sphere: when diversify_results=True, max articles from one primary sphere (default 5).

    Returns:
        JSON with matching articles + a `diversity` block showing what the
        balancing did (pool size, distinct sources/spheres, etc.).
    """
    limit = max(1, min(100, limit))
    parsed = _parse_date_arg(date)
    if parsed[0] is None:
        return json.dumps({"error": parsed[1]})
    start, end = parsed

    sql = """SELECT a.title, a.lead, a.url, a.source_name,
                    a.category, a.language, a.published_at, a.spheres_json,
                    s.lean, s.trust_tier
             FROM articles a JOIN sources s ON s.id = a.source_id
             WHERE a.published_at >= ? AND a.published_at < ?"""
    params: list = [start.isoformat(), end.isoformat()]

    if category:
        sql += " AND LOWER(a.category) = LOWER(?)"
        params.append(category)
    if source:
        sql += " AND LOWER(a.source_name) LIKE LOWER(?)"
        params.append(f"%{source}%")
    if language:
        sql += " AND a.language = ?"
        params.append(language)
    if sphere:
        sql += " AND a.spheres_json LIKE ?"
        params.append(f'%"{sphere}"%')
    if lean:
        sql += " AND s.lean = ?"
        params.append(lean)

    # Fetch a larger pool when diversifying so round-robin has something to pick from.
    fetch_limit = limit * 5 if diversify_results else limit
    fetch_limit = min(fetch_limit, 500)

    sql += " ORDER BY a.published_at DESC LIMIT ?"
    params.append(fetch_limit)

    with get_db() as conn:
        rows = [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]

    selected, diversity_stats = diversify(
        rows, limit=limit,
        max_per_source=max_per_source,
        max_per_sphere=max_per_sphere,
        enabled=diversify_results,
    )

    return json.dumps({
        "date": date,
        "filters": {"category": category or "all", "source": source or "all",
                    "language": language or "all", "sphere": sphere or "all",
                    "lean": lean or "all"},
        "count": len(selected),
        "diversity": diversity_stats,
        "articles": selected,
    }, ensure_ascii=False, default=str)


@mcp.tool()
def search_news(
    query: str,
    days: int = 3,
    category: str = "",
    sphere: str = "",
    language: str = "",
    limit: int = 20,
    diversify_results: bool = True,
    max_per_source: int = 3,
    max_per_sphere: int = 5,
    include_full_text: bool = True,
    include_web: bool = False,
    web_count: int = 5,
) -> str:
    """Full-text search news (FTS5 across title, lead, and full article text).

    Args:
        query: Search keywords (e.g. "Trump tariffs", "MNB kamatdöntés", "iran nuclear")
        days: Look back 1–21 days (default: 3)
        category: Optional Hirmagnet category filter
        sphere: Optional sphere filter
        language: Optional language filter
        limit: 1–50 (default: 20)
        diversify_results: round-robin across sources/spheres so one prolific
                feed cannot dominate the result. Default: True.
        max_per_source: when diversify_results=True, max articles from one source (default 3).
        max_per_sphere: when diversify_results=True, max articles from one primary sphere (default 5).
        include_full_text: search article bodies (Brave-fetched) too, not just
                title and lead. Default: True. Set False for strict headline matching.
        include_web: also run a Brave web search and return the results under
                `web_results` in the response. Default: False (the corpus is
                primary; web is opt-in augmentation).
        web_count: when include_web=True, how many web results to return (default 5).
    """
    days = max(1, min(21, days))
    limit = max(1, min(50, limit))
    since = (datetime.now() - timedelta(days=days)).isoformat()

    if not query.strip():
        return json.dumps({"error": "Empty query"})

    # FTS5 query — quote each term, OR them so partial matches work.
    # When include_full_text=False, restrict to title+lead columns via FTS5 column-filter.
    terms = [t for t in query.split() if len(t) > 2]
    if not terms:
        return json.dumps({"error": "Query too short — use 3+ char terms"})
    if include_full_text:
        fts_query = " OR ".join(f'"{t}"' for t in terms)
    else:
        fts_query = " OR ".join(f'{{title lead}}:"{t}"' for t in terms)

    sql = """SELECT a.title, a.lead, a.url, a.source_name,
                    a.category, a.language, a.published_at, a.spheres_json,
                    s.lean, s.trust_tier
             FROM articles a
             JOIN articles_fts fts ON fts.article_id = a.article_id
             JOIN sources s ON s.id = a.source_id
             WHERE articles_fts MATCH ?
               AND a.published_at >= ?"""
    params: list = [fts_query, since]
    if category:
        sql += " AND LOWER(a.category) = LOWER(?)"
        params.append(category)
    if sphere:
        sql += " AND a.spheres_json LIKE ?"
        params.append(f'%"{sphere}"%')
    if language:
        sql += " AND a.language = ?"
        params.append(language)

    fetch_limit = limit * 5 if diversify_results else limit
    fetch_limit = min(fetch_limit, 300)

    sql += " ORDER BY a.published_at DESC LIMIT ?"
    params.append(fetch_limit)

    with get_db() as conn:
        try:
            rows = [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError as e:
            return json.dumps({"error": f"FTS query error: {e}"})

    selected, diversity_stats = diversify(
        rows, limit=limit,
        max_per_source=max_per_source,
        max_per_sphere=max_per_sphere,
        enabled=diversify_results,
    )

    web_results = None
    if include_web:
        web_count = max(1, min(20, web_count))
        try:
            web_results = brave_search_sync(query, count=web_count) or []
        except Exception as exc:
            logger.warning("web search failed for %r: %s", query, exc)
            web_results = []

    response: dict = {
        "query": query, "fts_query": fts_query, "days": days,
        "count": len(selected),
        "diversity": diversity_stats,
        "articles": selected,
    }
    if include_web:
        response["web_results"] = web_results
        response["web_count"] = len(web_results) if web_results else 0
    return json.dumps(response, ensure_ascii=False, default=str)


@mcp.tool()
def get_weekly_digest(week: str = "current", category: str = "",
                     sphere: str = "", limit: int = 50) -> str:
    """Weekly digest grouped by day — for weekly reports (heti jelentés).

    Args:
        week: "current", "last", or ISO week (e.g. "2026-W12")
        category: Optional category filter
        sphere: Optional sphere filter
        limit: 1–200 (default: 50)
    """
    limit = max(1, min(200, limit))
    now = datetime.now()
    if week == "current":
        start = now - timedelta(days=now.weekday())
    elif week == "last":
        start = now - timedelta(days=now.weekday() + 7)
    else:
        try:
            start = datetime.strptime(week + "-1", "%G-W%V-%u")
        except ValueError:
            return json.dumps({"error": f"Invalid week: {week}. Use 'current', 'last', or '2026-W12'"})
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)

    sql = """SELECT a.title, a.lead, a.url, a.source_name,
                    a.category, a.language, a.published_at, a.spheres_json,
                    DATE(a.published_at) AS day
             FROM articles a JOIN sources s ON s.id = a.source_id
             WHERE a.published_at >= ? AND a.published_at < ?"""
    params: list = [start.isoformat(), end.isoformat()]
    if category:
        sql += " AND LOWER(a.category) = LOWER(?)"
        params.append(category)
    if sphere:
        sql += " AND a.spheres_json LIKE ?"
        params.append(f'%"{sphere}"%')
    sql += " ORDER BY a.published_at DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    by_day: dict[str, list[dict]] = {}
    for r in rows:
        d = _row_to_dict(r)
        day = d.pop("day", "unknown")
        by_day.setdefault(day, []).append(d)

    return json.dumps({
        "week": week,
        "period": f"{start.strftime('%Y-%m-%d')} — {end.strftime('%Y-%m-%d')}",
        "category": category or "all", "sphere": sphere or "all",
        "total_articles": len(rows),
        "days": {day: {"count": len(arts), "articles": arts}
                 for day, arts in sorted(by_day.items())},
    }, ensure_ascii=False, default=str)


@mcp.tool()
def get_trending(days: int = 1, min_sources: int = 3, limit: int = 15,
                 sphere: str = "") -> str:
    """Trending topics — keywords mentioned by multiple sources.

    Args:
        days: Look back 1–7 days (default: 1)
        min_sources: Minimum distinct sources for a topic (default: 3)
        limit: Max trending topics (1–30, default: 15)
        sphere: Restrict to a specific sphere (default: all)
    """
    days = max(1, min(7, days))
    since = (datetime.now() - timedelta(days=days)).isoformat()

    sql = """SELECT a.title, a.lead, a.url, a.source_name, a.category,
                    a.language, a.published_at, a.spheres_json
             FROM articles a WHERE a.published_at >= ?"""
    params: list = [since]
    if sphere:
        sql += " AND a.spheres_json LIKE ?"
        params.append(f'%"{sphere}"%')
    sql += " ORDER BY a.published_at DESC"

    with get_db() as conn:
        articles = [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]

    stop_words = {
        "a", "az", "és", "is", "hogy", "nem", "van", "volt", "lesz", "már",
        "még", "meg", "el", "ki", "be", "fel", "le", "ezt", "azt", "egy",
        "mint", "csak", "vagy", "ide", "oda", "ami", "aki", "amely", "ez",
        "the", "and", "for", "with", "from", "has", "have", "are", "was",
        "will", "but", "not", "its", "can", "into", "over", "about", "after",
        "this", "that", "said", "says", "new", "more", "been", "also", "their",
        "than", "what", "when", "where", "which", "would", "could", "should",
    }

    def keywords(title: str) -> list[str]:
        words = [w.lower().strip(".:,;!?\"'()-–—") for w in (title or "").split()]
        return [w for w in words if len(w) > 3 and w not in stop_words]

    by_kw: dict[str, list[dict]] = defaultdict(list)
    for a in articles:
        for kw in keywords(a.get("title") or ""):
            by_kw[kw].append(a)

    trending = []
    seen_urls: set[str] = set()
    for kw, arts in sorted(by_kw.items(), key=lambda x: -len({a["source_name"] for a in x[1]})):
        sources_set = {a["source_name"] for a in arts}
        if len(sources_set) < min_sources:
            continue
        unique_arts = []
        for a in arts:
            if a["url"] not in seen_urls:
                unique_arts.append(a)
                seen_urls.add(a["url"])
        if not unique_arts:
            continue
        trending.append({
            "keyword": kw,
            "source_count": len(sources_set),
            "sources": sorted(sources_set),
            "article_count": len(unique_arts),
            "articles": unique_arts[:5],
        })
        if len(trending) >= limit:
            break

    return json.dumps({
        "days": days, "min_sources": min_sources, "sphere": sphere or "all",
        "trending_count": len(trending), "trending": trending,
    }, ensure_ascii=False, default=str)


@mcp.tool()
def get_sources() -> str:
    """List all configured sources, grouped by category and sphere, with article counts."""
    with get_db() as conn:
        srcs = conn.execute("""
            SELECT s.id, s.name, s.url, s.language, s.lean, s.trust_tier,
                   s.category, s.source_type, s.spheres_json,
                   (SELECT COUNT(*) FROM articles a WHERE a.source_id = s.id) AS article_count,
                   (SELECT MAX(published_at) FROM articles a WHERE a.source_id = s.id) AS last_article
            FROM sources s
            ORDER BY s.category, s.name
        """).fetchall()

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in srcs:
        d = _row_to_dict(r)
        cat = d.get("category", "general")
        by_cat[cat].append(d)

    return json.dumps({
        "total_sources": len(srcs),
        "categories": {cat: {"count": len(items), "sources": items}
                       for cat, items in sorted(by_cat.items())},
    }, ensure_ascii=False, default=str)


@mcp.tool()
def get_spheres() -> str:
    """List narrative spheres — what they are, which sources feed them, recent activity.

    Spheres group sources by editorial perspective / region / regime alignment so you
    can ask "what does sphere X say about topic Y?" via narrative_divergence.
    """
    with get_db() as conn:
        srcs = conn.execute("SELECT id, name, language, lean, trust_tier, spheres_json FROM sources").fetchall()
        arts = conn.execute("""
            SELECT spheres_json, COUNT(*) AS n, MAX(published_at) AS latest
            FROM articles GROUP BY spheres_json
        """).fetchall()

    sphere_sources: dict[str, list[str]] = defaultdict(list)
    for r in srcs:
        for sph in json.loads(r["spheres_json"]):
            sphere_sources[sph].append(r["name"])

    sphere_counts: dict[str, dict] = {}
    for r in arts:
        for sph in json.loads(r["spheres_json"]):
            cur = sphere_counts.setdefault(sph, {"articles": 0, "latest": None})
            cur["articles"] += r["n"]
            if r["latest"] and (cur["latest"] is None or r["latest"] > cur["latest"]):
                cur["latest"] = r["latest"]

    spheres = sorted(set(list(sphere_sources.keys()) + list(sphere_counts.keys())))
    out = {sph: {
        "source_count": len(sphere_sources.get(sph, [])),
        "sources": sphere_sources.get(sph, []),
        "article_count": sphere_counts.get(sph, {}).get("articles", 0),
        "latest_article": sphere_counts.get(sph, {}).get("latest"),
    } for sph in spheres}

    return json.dumps({"spheres_count": len(spheres), "spheres": out},
                      ensure_ascii=False, default=str)


@mcp.tool()
def narrative_divergence(query: str, days: int = 3, per_sphere_limit: int = 5,
                         include_full_text: bool = True) -> str:
    """Across-sphere narrative comparison: "what does each sphere say about X?"

    Searches FTS5 across title, lead, and (Brave-fetched) full article text,
    then groups results by sphere — so you can see e.g. how cn_state,
    iran_regime, iran_opposition, ua_front_osint, and us_liberal_press cover
    the same topic side by side.

    Args:
        query: FTS terms (e.g. "iran nuclear", "taiwan", "trump powell")
        days: Look back N days (default: 3, max 21)
        per_sphere_limit: Max items per sphere (default: 5, max 20)
        include_full_text: search article bodies too (default: True). Set
                False to restrict matching to title+lead only.
    """
    days = max(1, min(21, days))
    per_sphere_limit = max(1, min(20, per_sphere_limit))
    if not query.strip():
        return json.dumps({"error": "Empty query"})

    terms = [t for t in query.split() if len(t) > 2]
    if not terms:
        return json.dumps({"error": "Query too short"})
    if include_full_text:
        fts_query = " OR ".join(f'"{t}"' for t in terms)
    else:
        fts_query = " OR ".join(f'{{title lead}}:"{t}"' for t in terms)
    since = (datetime.now() - timedelta(days=days)).isoformat()

    sql = """
        SELECT a.title, a.lead, a.url, a.source_name,
               a.published_at, a.language, a.spheres_json,
               s.lean, s.trust_tier
        FROM articles a
        JOIN articles_fts fts ON fts.article_id = a.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE articles_fts MATCH ?
          AND a.published_at >= ?
        ORDER BY a.published_at DESC
        LIMIT 1000
    """
    with get_db() as conn:
        try:
            rows = conn.execute(sql, (fts_query, since)).fetchall()
        except sqlite3.OperationalError as e:
            return json.dumps({"error": f"FTS error: {e}"})

    by_sphere: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        spheres = json.loads(r["spheres_json"])
        entry = {
            "title": r["title"],
            "lead": (r["lead"] or "")[:400],
            "source": r["source_name"], "lean": r["lean"], "trust_tier": r["trust_tier"],
            "language": r["language"], "url": r["url"], "published_at": r["published_at"],
        }
        for sph in spheres:
            by_sphere[sph].append(entry)

    out = {sph: items[:per_sphere_limit]
           for sph, items in sorted(by_sphere.items(), key=lambda kv: -len(kv[1]))}

    return json.dumps({
        "query": query, "fts_query": fts_query, "days": days,
        "spheres_found": len(out),
        "by_sphere": out,
    }, ensure_ascii=False, default=str)


@mcp.tool()
def echolot_health(
    green_max_minutes: int = 120,
    yellow_max_minutes: int = 1440,
    top_n: int = 10,
) -> str:
    """Sphere-by-sphere health check — which spheres are alive, slowing, or dead.

    Use this to spot dead RSS feeds, dying sources, or broken sphere coverage.

    Args:
        green_max_minutes: latest article newer than this -> green (default 120 = 2h)
        yellow_max_minutes: latest article newer than this -> yellow (default 1440 = 24h)
        top_n: how many top-active and slowest sources to list (default 10)

    Returns JSON with:
        summary: {green, yellow, red, total}
        spheres: per-sphere status, article counts (24h, 7d), latest article age
        top_active_sources_24h: most prolific sources in the last 24h
        slowest_sources: sources with oldest/no recent articles (candidates for fixing)
    """
    report = compute_health(
        DB_PATH,
        green_max_minutes=green_max_minutes,
        yellow_max_minutes=yellow_max_minutes,
        top_n=top_n,
    )
    return json.dumps(report, ensure_ascii=False, default=str)


@mcp.tool()
def echolot_velocity(
    window_hours: int = 6,
    baseline_offset_hours: int = 24,
    min_baseline: int = 2,
    limit: int = 30,
) -> str:
    """Which spheres are spiking right now? — sphere-level news velocity.

    For each sphere, compares article volume in a recent window (default
    last 6h) against a baseline window (default same hours yesterday).
    Returns velocity_ratio + a status: spike / rising / normal / quiet.

    Use this to spot "the Iran-opposition sphere is unusually loud in the
    last 6h" or "global_climate is dead quiet today vs yesterday".

    Args:
        window_hours: recent window size, default 6
        baseline_offset_hours: how far back the baseline starts (24 = same
                hours yesterday), default 24
        min_baseline: skip spheres with fewer than this many baseline
                articles (avoids ratio noise on tiny spheres), default 2
        limit: max spheres to return, default 30

    Returns JSON with `spheres`: list of {sphere, current_count,
    baseline_count, velocity_ratio, status}, ordered by velocity_ratio desc
    (spikes first).
    """
    window_hours = max(1, min(48, window_hours))
    baseline_offset_hours = max(1, min(168, baseline_offset_hours))
    limit = max(1, min(63, limit))
    report = compute_sphere_velocity(
        DB_PATH,
        window_hours=window_hours,
        baseline_offset_hours=baseline_offset_hours,
        min_baseline=min_baseline,
        limit=limit,
    )
    return json.dumps(report, ensure_ascii=False, default=str)


@mcp.tool()
def entity_search(
    name_or_qid: str,
    days: int = 7,
    limit: int = 20,
    sphere: str = "",
    diversify_results: bool = True,
    max_per_source: int = 3,
    max_per_sphere: int = 5,
) -> str:
    """Find articles about an entity across languages — Wikidata-backed.

    Resolves a name ("Trump", "Orbán Viktor") or Wikidata QID ("Q22686")
    to ALL multilingual aliases (HU, EN, DE, RU, ZH, JA, FR, UK), then
    full-text searches the corpus for any of them. So a search for "Trump"
    finds Чешские / Trump / Donald Trump / 唐纳德·特朗普 / ドナルド・トランプ
    articles together, regardless of language.

    Tip: pass a QID for precision — name lookup picks the top Wikidata hit
    which is occasionally a different entity (e.g. "Trump" -> the surname
    entity, not the politician). The entity's resolved primary_label and
    matched_aliases are returned in the response so callers can verify.

    Args:
        name_or_qid: free-form name or Wikidata QID (e.g. "Q22686")
        days: look back N days, 1-21 (default 7)
        limit: max articles, 1-50 (default 20)
        sphere: optional sphere filter
        diversify_results: round-robin across source/sphere (default True)
        max_per_source: cap when diversifying (default 3)
        max_per_sphere: cap when diversifying (default 5)
    """
    name_or_qid = (name_or_qid or "").strip()
    if not name_or_qid:
        return json.dumps({"error": "Empty name_or_qid"})
    days = max(1, min(21, days))
    limit = max(1, min(50, limit))

    entity = resolve_entity(name_or_qid)
    if entity is None:
        return json.dumps({
            "error": "Entity not found on Wikidata",
            "input": name_or_qid,
        }, ensure_ascii=False)

    aliases = entity["filtered_aliases"]
    if not aliases:
        return json.dumps({
            "error": "Entity resolved but no usable aliases (all too short / filtered)",
            "qid": entity["qid"],
            "primary_label": entity["primary_label"],
        }, ensure_ascii=False)

    # Build FTS5 OR-query from quoted aliases.
    quoted = [f'"{a["label"]}"' for a in aliases]
    fts_query = " OR ".join(quoted)
    since = (datetime.now() - timedelta(days=days)).isoformat()

    sql = """SELECT a.title, a.lead, a.url, a.source_name,
                    a.category, a.language, a.published_at, a.spheres_json,
                    s.lean, s.trust_tier
             FROM articles a
             JOIN articles_fts fts ON fts.article_id = a.article_id
             JOIN sources s ON s.id = a.source_id
             WHERE articles_fts MATCH ?
               AND a.published_at >= ?"""
    params: list = [fts_query, since]
    if sphere:
        sql += " AND a.spheres_json LIKE ?"
        params.append(f'%"{sphere}"%')
    fetch_limit = limit * 5 if diversify_results else limit
    fetch_limit = min(fetch_limit, 300)
    sql += " ORDER BY a.published_at DESC LIMIT ?"
    params.append(fetch_limit)

    with get_db() as conn:
        try:
            rows = [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError as exc:
            return json.dumps({"error": f"FTS error: {exc}",
                               "qid": entity["qid"],
                               "alias_count": len(aliases)})

    selected, diversity_stats = diversify(
        rows, limit=limit,
        max_per_source=max_per_source,
        max_per_sphere=max_per_sphere,
        enabled=diversify_results,
    )

    return json.dumps({
        "input": name_or_qid,
        "qid": entity["qid"],
        "primary_label": entity["primary_label"],
        "alias_count": len(aliases),
        "matched_aliases": [a["label"] for a in aliases],
        "days": days,
        "count": len(selected),
        "diversity": diversity_stats,
        "articles": selected,
    }, ensure_ascii=False, default=str)


@mcp.tool()
async def wiki_trends(
    topic: str = "",
    days: int = 365,
    limit: int = 15,
    mode: str = "auto",
    geo_wiki: str = "en",
    include_predictive: bool = False,
) -> str:
    """Wikipedia-pageview-based trending, correlations & lag-predictions.

    Backed by the wikicorrelate engine, ported in-process (2026-05-14).
    Hits the Wikipedia REST API directly; no external service needed.

    Three modes:
      - mode="pageviews" — Wikipedia's top-read articles yesterday in the
        given language wiki (geo_wiki). Free, fresh, multilingual.
      - mode="correlations" (or any topic given) — Pearson correlation
        of `topic`'s pageview series against thousands of candidate
        articles over `days`. Returns top correlated topics.
      - mode="movers" — DB-stored top-movers (pairs whose correlation is
        spiking right now; needs the nightly daily_correlation indexer
        to have run).
      - mode="auto" (default) — pageviews if no topic, correlations if topic.

    Args:
        topic: search term (any non-empty → correlations mode auto-triggers)
        days: history window 30-3650 (default 365)
        limit: max results 1-100 (default 15)
        mode: 'auto' | 'pageviews' | 'correlations' | 'movers'
        geo_wiki: language-prefix for the Wikipedia to read top-pageviews from
            ('en','hu','de','fr','es','it','pl','ru','uk','ja','zh','ar', ...)
        include_predictive: also fetch lag-correlation predictions
            (correlations mode only)
    """
    days = max(30, min(3650, days))
    limit = max(1, min(100, limit))
    topic = (topic or "").strip()

    # Resolve mode
    if mode == "auto":
        mode = "correlations" if topic else "pageviews"

    out: dict = {"backed_by": "wikicorrelate (in-process)", "mode": mode}

    if mode == "pageviews":
        try:
            items = await _wiki_top_pageviews(geo_wiki=geo_wiki, limit=limit)
            out["geo_wiki"] = geo_wiki
            out["results"] = items
        except Exception as exc:
            logger.warning("wiki top_pageviews failed: %s", exc)
            out["error"] = f"{type(exc).__name__}: {exc}"
            out["results"] = []
        return json.dumps(out, ensure_ascii=False, default=str)

    if mode == "movers":
        await _ensure_wiki_db_async()
        try:
            rows = await _wiki_db_top_movers(limit)
            out["top_movers"] = [dict(r) if hasattr(r, "keys") else r for r in (rows or [])]
        except Exception as exc:
            logger.warning("wiki top_movers failed: %s", exc)
            out["error"] = f"{type(exc).__name__}: {exc}"
            out["top_movers"] = []
        return json.dumps(out, ensure_ascii=False, default=str)

    # mode == "correlations" — needs a topic
    if not topic:
        out["error"] = "correlations mode requires a `topic`"
        out["results"] = []
        return json.dumps(out, ensure_ascii=False, default=str)

    await _ensure_wiki_db_async()
    out["topic"] = topic
    try:
        data = await _wiki_search(query=topic, days=days, max_results=limit)
        out["results"] = (
            (data or {}).get("correlations")
            or (data or {}).get("results")
            or []
        )
        if data and data.get("error"):
            out["engine_error"] = data["error"]
        if data and "candidates_tested" in data:
            out["candidates_tested"] = data["candidates_tested"]
    except Exception as exc:
        logger.warning("wiki_search failed for %r: %s", topic, exc)
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["results"] = []

    if include_predictive and _wiki_predictive is not None:
        try:
            pred = await _wiki_predictive(
                target_topic=topic, days=days,
                min_correlation=0.4, min_occurrences=3, max_results=limit,
            )
            out["predictive"] = (pred or {}).get("results", [])
        except Exception as exc:
            logger.warning("wiki_predictive failed for %r: %s", topic, exc)
            out["predictive"] = []

    return json.dumps(out, ensure_ascii=False, default=str)


@mcp.tool()
def google_trends(
    geo: str = "HU",
    limit: int = 15,
    super_trends: bool = False,
    super_geos: list[str] | None = None,
    super_min_overlap: int = 2,
) -> str:
    """Trending stories from Google News RSS — free, no API key.

    The pytrends library is broken since Google blocked its scraping path,
    and SerpAPI's google_trends engine costs money. Trendinghub solved
    the problem with Google News RSS feeds per country — the country's
    Top Stories feed effectively reflects what's trending there, and
    cross-source overlap detects global super-trends.

    Args:
        geo: 2-letter country code (HU, US, GB, DE, FR, ES, IT, PL, RU,
             UA, JP, CN, BR, MX). Default 'HU'.
        limit: max items, 1-30 (default 15)
        super_trends: if True, instead of one country's feed, compare
             multiple countries (super_geos) and return topics that
             appear in at least super_min_overlap of them — the actual
             global trending signal.
        super_geos: list of geos for super-trend detection. Default
             ['HU','US','GB','DE','FR'].
        super_min_overlap: min country overlap for a super-trend. Default 2.

    Returns JSON with: mode, geo(s), results (or supertrends),
    backed_by ('google_news_rss').
    """
    limit = max(1, min(30, limit))
    out: dict = {"backed_by": "google_news_rss"}

    if super_trends:
        out["mode"] = "supertrends"
        out["geos"] = super_geos or ["HU", "US", "GB", "DE", "FR"]
        out["min_overlap"] = super_min_overlap
        try:
            out["supertrends"] = gnews_supertrends(
                geos=out["geos"],
                min_overlap=super_min_overlap,
                limit=limit,
            )
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
            out["supertrends"] = []
    else:
        geo_u = geo.upper()
        if geo_u not in GNEWS_GEO_FEEDS:
            return json.dumps({
                "error": f"Unknown geo {geo!r}",
                "available": list(GNEWS_GEO_FEEDS.keys()),
            }, ensure_ascii=False)
        out["mode"] = "trending_now"
        out["geo"] = geo_u
        try:
            out["results"] = gnews_trending(geo=geo_u, limit=limit)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
            out["results"] = []

    return json.dumps(out, ensure_ascii=False, default=str)


@mcp.tool()
def search_web(query: str, count: int = 10) -> str:
    """Web search via our brave-mcp-server — independent of the Echolot corpus.

    Use this when you need fresh internet results (current events, niche
    topics, anything outside our 315 RSS sources). Returns Brave web search
    hits as plain {title, url, description} dicts.

    Args:
        query: free-form search query (any language)
        count: number of results to return, 1–30 (default: 10)
    """
    count = max(1, min(30, count))
    if not query.strip():
        return json.dumps({"error": "Empty query"})

    results = brave_search_sync(query, count=count)
    if results is None:
        return json.dumps({"error": "Brave search unavailable",
                           "query": query, "count": 0, "results": []},
                          ensure_ascii=False)

    return json.dumps({
        "query": query, "engine": "brave", "count": len(results),
        "results": results,
    }, ensure_ascii=False, default=str)


PLATFORM_SITE_FILTERS = {
    "x":          "(site:x.com OR site:twitter.com)",
    "facebook":   "site:facebook.com",
    "reddit":     "(site:reddit.com OR site:old.reddit.com)",
    "threads":    "(site:threads.net OR site:threads.com)",
    "linkedin":   "site:linkedin.com",
    "instagram":  "site:instagram.com",
    "bluesky":    "site:bsky.app",
    "hackernews": "site:news.ycombinator.com",
}


@mcp.tool()
def search_social(
    query: str,
    platforms: list[str] | None = None,
    count: int = 10,
    per_platform_limit: int = 3,
    brave_fallback: bool = True,
) -> str:
    """Search social-media posts across platforms via Brave + OG fast-path.

    X's keyword search is Premium-only ($8-16/mo) and Facebook/Instagram/
    LinkedIn don't expose a free search at all. We reach the same goal by
    Brave-searching with site:-restriction, then OG-meta-scraping each hit
    in ~300ms (no JS render, no API key, no auth-token-rot).

    Per platform we keep up to `per_platform_limit` results so a noisy
    platform (e.g. lots of Reddit links) can't crowd out the others.

    Two-tier extraction per URL:
      1. OG fast-path (~300ms) — works for X, Threads, Facebook, LinkedIn
      2. Brave scrape (~5-15s) — fallback for Reddit, HackerNews, Bluesky
         where the OG description is empty by design. Set
         brave_fallback=False to skip and save time.

    Args:
        query: free-form search terms (any language)
        platforms: list of platforms to search. Default = all 8:
            ['x', 'facebook', 'reddit', 'threads', 'linkedin',
             'instagram', 'bluesky', 'hackernews']
        count: total max posts across all platforms, 1-30 (default 10)
        per_platform_limit: max posts per platform, 1-10 (default 3)
        brave_fallback: if True (default), Brave-scrape URLs where the OG
            fast-path returned nothing usable. Slows the call by ~5-15s
            per fallback URL.

    Returns JSON with:
        query, platforms_queried, urls_found_per_platform,
        posts_extracted, posts: [{platform, url, text, title,
        preview_title, via}]. `via` is "og_fastpath" or "brave_scrape".
    """
    if not query.strip():
        return json.dumps({"error": "Empty query"})

    count = max(1, min(30, count))
    per_platform_limit = max(1, min(10, per_platform_limit))

    if not platforms:
        platforms = list(PLATFORM_SITE_FILTERS.keys())
    else:
        invalid = [p for p in platforms if p not in PLATFORM_SITE_FILTERS]
        platforms = [p for p in platforms if p in PLATFORM_SITE_FILTERS]
        if not platforms:
            return json.dumps({
                "error": "No valid platforms",
                "invalid": invalid,
                "available": list(PLATFORM_SITE_FILTERS.keys()),
            }, ensure_ascii=False)

    urls_per_platform: dict[str, int] = {}
    posts: list[dict] = []

    for platform in platforms:
        if len(posts) >= count:
            break
        site_filter = PLATFORM_SITE_FILTERS[platform]
        full_query = f"{site_filter} {query}"
        web_results = brave_search_sync(full_query, count=per_platform_limit * 3)
        if not web_results:
            urls_per_platform[platform] = 0
            continue

        seen: set[str] = set()
        candidates: list[dict] = []
        for r in web_results:
            url = r.get("url", "")
            if match_platform(url) != platform:
                continue
            if url in seen:
                continue
            seen.add(url)
            candidates.append({"url": url, "preview_title": r.get("title", "")})
            if len(candidates) >= per_platform_limit:
                break
        urls_per_platform[platform] = len(candidates)

        for c in candidates:
            if len(posts) >= count:
                break
            # Tier 1: fast-path (300ms)
            og = fetch_og(c["url"])
            if og and og.get("content_usable"):
                posts.append({
                    "platform": platform,
                    "url": c["url"],
                    "text": og.get("text", ""),
                    "title": og.get("title", ""),
                    "preview_title": c["preview_title"],
                    "via": "og_fastpath",
                })
                continue
            # Tier 2: Brave scrape fallback (5-15s) — for Reddit/HN/Bluesky
            # where OG description is empty by site policy.
            if not brave_fallback:
                continue
            try:
                brave = brave_fetch_sync(c["url"], robust=False)
            except Exception as exc:
                logger.warning("brave fallback failed for %s: %s", c["url"], exc)
                brave = None
            if brave and brave.get("content_usable"):
                text = brave.get("text") or brave.get("markdown") or ""
                # Cap to keep the response readable
                if len(text) > 1000:
                    text = text[:1000] + f"…[truncated, full {len(text)} chars]"
                posts.append({
                    "platform": platform,
                    "url": c["url"],
                    "text": text,
                    "title": brave.get("title", ""),
                    "preview_title": c["preview_title"],
                    "via": "brave_scrape",
                })

    return json.dumps({
        "query": query,
        "platforms_queried": platforms,
        "urls_found_per_platform": urls_per_platform,
        "posts_extracted": len(posts),
        "posts": posts,
    }, ensure_ascii=False, default=str)


@mcp.tool()
def scrape_url(url: str, robust: bool = False, max_chars: int = 8000) -> str:
    """Scrape any URL via our brave-mcp-server and return its main text.

    Works for news articles, blog posts, social-media post pages (Twitter/X,
    Reddit, etc.), forums, paywalled sites at varying success rates. Set
    robust=True for tough sites (Reuters, Cloudflare-protected) — engages
    the 7-level anti-bot chain (slower).

    Args:
        url: any HTTP/HTTPS URL to scrape
        robust: True = use the 7-level anti-bot escalation chain (slower
                but works on Reuters/DataDome/Cloudflare). Default False.
        max_chars: cap the returned text length to keep responses agent-friendly.
                Default 8000. Set 0 for no cap.

    Returns:
        JSON with: content_usable, block_reason, title, text (truncated),
        text_len_total, url. Empty/blocked content sets content_usable=false
        and explains via block_reason ("paywall_banner", "cloudflare_challenge",
        "empty_response", etc.).
    """
    if not url.strip():
        return json.dumps({"error": "Empty url"})

    # Social-media / short-post fast-path: many platforms (Twitter/X, Reddit,
    # LinkedIn, Threads, Instagram, Mastodon, Bluesky, HN, …) embed the full
    # post text in og:description for link-preview cards. A 300ms HTTP GET
    # extracts it — beats the 30-180s Brave-chain render path.
    platform = match_platform(url)
    if platform:
        og = fetch_og(url)
        if og is not None and og["content_usable"]:
            text = og["text"]
            total = len(text)
            if max_chars and total > max_chars:
                text = text[:max_chars] + f"\n…[truncated, full length {total} chars]"
            return json.dumps({
                "url": url,
                "robust": False,
                "fast_path": f"og:{platform}",
                "content_usable": True,
                "block_reason": None,
                "title": og["title"],
                "text": text,
                "text_len_total": total,
                "og_meta": og["og_meta"],
            }, ensure_ascii=False, default=str)
        # OG-fetch failed or empty — fall through to Brave as fallback.

    result = brave_fetch_sync(url, robust=robust)
    if result is None:
        return json.dumps({"error": "Brave scrape unavailable",
                           "url": url, "content_usable": False},
                          ensure_ascii=False)

    text = result.get("text") or result.get("markdown") or ""
    total = len(text)
    if max_chars and total > max_chars:
        text = text[:max_chars] + f"\n…[truncated, full length {total} chars]"

    return json.dumps({
        "url": url,
        "robust": robust,
        "content_usable": result.get("content_usable"),
        "block_reason": result.get("block_reason"),
        "title": result.get("title"),
        "text": text,
        "text_len_total": total,
        "escalation_path": result.get("escalation_path"),
    }, ensure_ascii=False, default=str)


@mcp.tool()
def get_scrape_status() -> str:
    """Scraper health — last run + DB stats. Use to verify the pipeline is alive."""
    with get_db() as conn:
        last = conn.execute("SELECT * FROM scrape_log ORDER BY started_at DESC LIMIT 1").fetchone()
        stats = conn.execute("""
            SELECT COUNT(*) AS total_articles,
                   COUNT(DISTINCT source_id) AS active_sources,
                   MIN(published_at) AS oldest,
                   MAX(published_at) AS newest,
                   SUM(CASE WHEN DATE(published_at) = DATE('now') THEN 1 ELSE 0 END) AS today,
                   SUM(CASE WHEN DATE(published_at) = DATE('now', '-1 day') THEN 1 ELSE 0 END) AS yesterday
            FROM articles
        """).fetchone()
        recent_failures = conn.execute("""
            SELECT source_id, error, started_at FROM fetch_log
            WHERE status='failed' AND started_at >= datetime('now', '-2 hours')
            ORDER BY started_at DESC LIMIT 30
        """).fetchall()
        total_sources = conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"]

    return json.dumps({
        "database_stats": {**dict(stats), "configured_sources": total_sources} if stats else {},
        "last_scrape": dict(last) if last else {"status": "never run"},
        "recent_failures": [dict(r) for r in recent_failures],
    }, ensure_ascii=False, default=str)


# ===========================================================================
# REST routes (for landing page)
# ===========================================================================

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    """Liveness probe — DB readable + scraper status."""
    try:
        with get_db() as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"]
            last = conn.execute(
                "SELECT MAX(published_at) AS m FROM articles"
            ).fetchone()["m"]
        return JSONResponse({"status": "ok", "articles": n, "newest": last})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@mcp.custom_route("/api/news", methods=["GET"])
async def api_news(request):
    """Latest articles for landing page.

    Query params:
        spheres   comma-separated sphere list (OR semantics), or single ?sphere=
        language  ISO code
        source_type  rss | telegram
        days      lookback window (1..21, default 7)
        limit     1..100 (default 60)
    """
    spheres_raw = request.query_params.get("spheres") or request.query_params.get("sphere", "")
    spheres_list = [s.strip() for s in spheres_raw.split(",") if s.strip()]
    language = request.query_params.get("language", "")
    source_type = request.query_params.get("source_type", "")
    days = max(1, min(21, int(request.query_params.get("days", "7"))))
    limit = max(1, min(100, int(request.query_params.get("limit", "60"))))
    since = (datetime.now() - timedelta(days=days)).replace(hour=0, minute=0, second=0)

    sql = """SELECT a.title, a.url, a.source_name, a.category, a.language,
                    a.published_at, a.spheres_json, s.source_type
             FROM articles a JOIN sources s ON s.id = a.source_id
             WHERE a.published_at >= ?"""
    params: list = [since.isoformat()]
    if spheres_list:
        ors = " OR ".join(["a.spheres_json LIKE ?"] * len(spheres_list))
        sql += f" AND ({ors})"
        for sph in spheres_list:
            params.append(f'%"{sph}"%')
    if language:
        sql += " AND a.language = ?"
        params.append(language)
    if source_type:
        sql += " AND s.source_type = ?"
        params.append(source_type)
    sql += " ORDER BY a.published_at DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]

    return JSONResponse({"count": len(rows), "articles": rows})


@mcp.custom_route("/api/spheres", methods=["GET"])
async def api_spheres(request):
    """Sphere stats for the landing page selector."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT spheres_json, COUNT(*) AS n FROM articles
            WHERE published_at >= datetime('now', '-7 days')
            GROUP BY spheres_json
        """).fetchall()
    counter: Counter[str] = Counter()
    for r in rows:
        for sph in json.loads(r["spheres_json"]):
            counter[sph] += r["n"]
    return JSONResponse({"spheres": counter.most_common()})


@mcp.custom_route("/api/search", methods=["GET"])
async def api_search(request):
    """FTS5 keyword search.

    Query params:
        query     required — search keywords (3+ char terms)
        days      lookback 1..21 (default 3)
        sphere    optional sphere filter
        category  optional category filter
        language  optional ISO code
        limit     1..50 (default 20)
    """
    query = request.query_params.get("query", "").strip()
    if not query:
        return JSONResponse({"error": "Empty query"}, status_code=400)
    terms = [t for t in query.split() if len(t) > 2]
    if not terms:
        return JSONResponse({"error": "Query too short — use 3+ char terms"}, status_code=400)
    fts_query = " OR ".join(f'"{t}"' for t in terms)

    days = max(1, min(21, int(request.query_params.get("days", "3"))))
    limit = max(1, min(50, int(request.query_params.get("limit", "20"))))
    sphere = request.query_params.get("sphere", "")
    category = request.query_params.get("category", "")
    language = request.query_params.get("language", "")
    since = (datetime.now() - timedelta(days=days)).isoformat()

    sql = """SELECT a.title, a.lead, a.url, a.source_name,
                    a.category, a.language, a.published_at, a.spheres_json,
                    s.lean, s.trust_tier
             FROM articles a
             JOIN articles_fts fts ON fts.article_id = a.article_id
             JOIN sources s ON s.id = a.source_id
             WHERE articles_fts MATCH ?
               AND a.published_at >= ?"""
    params: list = [fts_query, since]
    if category:
        sql += " AND LOWER(a.category) = LOWER(?)"
        params.append(category)
    if sphere:
        sql += " AND a.spheres_json LIKE ?"
        params.append(f'%"{sphere}"%')
    if language:
        sql += " AND a.language = ?"
        params.append(language)
    sql += " ORDER BY a.published_at DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        try:
            rows = [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError as e:
            return JSONResponse({"error": f"FTS query error: {e}"}, status_code=400)

    return JSONResponse({
        "query": query, "fts_query": fts_query, "days": days,
        "count": len(rows), "articles": rows,
    })


@mcp.custom_route("/api/narrative_divergence", methods=["GET"])
async def api_narrative_divergence(request):
    """Across-sphere narrative comparison: "what does each sphere say about X?"

    Query params:
        query              required
        days               lookback 1..21 (default 3)
        per_sphere_limit   max items per sphere 1..20 (default 5)
    """
    query = request.query_params.get("query", "").strip()
    if not query:
        return JSONResponse({"error": "Empty query"}, status_code=400)
    terms = [t for t in query.split() if len(t) > 2]
    if not terms:
        return JSONResponse({"error": "Query too short"}, status_code=400)
    fts_query = " OR ".join(f'"{t}"' for t in terms)

    days = max(1, min(21, int(request.query_params.get("days", "3"))))
    per_sphere_limit = max(1, min(20, int(request.query_params.get("per_sphere_limit", "5"))))
    since = (datetime.now() - timedelta(days=days)).isoformat()

    sql = """
        SELECT a.title, a.lead, a.url, a.source_name,
               a.published_at, a.language, a.spheres_json,
               s.lean, s.trust_tier
        FROM articles a
        JOIN articles_fts fts ON fts.article_id = a.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE articles_fts MATCH ?
          AND a.published_at >= ?
        ORDER BY a.published_at DESC
        LIMIT 1000
    """
    with get_db() as conn:
        try:
            rows = conn.execute(sql, (fts_query, since)).fetchall()
        except sqlite3.OperationalError as e:
            return JSONResponse({"error": f"FTS error: {e}"}, status_code=400)

    by_sphere: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        spheres = json.loads(r["spheres_json"])
        entry = {
            "title": r["title"],
            "lead": (r["lead"] or "")[:400],
            "source": r["source_name"], "lean": r["lean"], "trust_tier": r["trust_tier"],
            "language": r["language"], "url": r["url"], "published_at": r["published_at"],
        }
        for sph in spheres:
            by_sphere[sph].append(entry)

    out = {sph: items[:per_sphere_limit]
           for sph, items in sorted(by_sphere.items(), key=lambda kv: -len(kv[1]))}

    return JSONResponse({
        "query": query, "fts_query": fts_query, "days": days,
        "spheres_found": len(out),
        "by_sphere": out,
    })


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------
LANDING_HTML = r"""<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Echolot — Globális narratíva-térkép</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --primary: #14b8a6;          /* teal — sonar / echo */
    --primary-dim: rgba(20, 184, 166, 0.15);
    --accent-amber: #f59e0b;
    --accent-rose: #f43f5e;
    --accent-blue: #3b82f6;
    --bg: #050608;
    --bg-card: rgba(12, 14, 18, 0.7);
    --text: #e8eef0;
    --text-dim: #8a9499;
    --border: rgba(255, 255, 255, 0.06);
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    overflow-x: hidden;
  }
  .ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; }
  .orb { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18;
         animation: orb-float 16s ease-in-out infinite alternate; }
  .orb-1 { background: var(--primary); width: 600px; height: 600px; top: -200px; left: -200px; }
  .orb-2 { background: var(--accent-rose); width: 500px; height: 500px; bottom: -150px; right: -150px; animation-delay: 4s; }
  .orb-3 { background: var(--accent-amber); width: 350px; height: 350px; top: 40%; left: 50%; opacity: 0.1; animation-delay: 7s; }
  @keyframes orb-float {
    0% { transform: translate(0,0) scale(1); }
    50% { transform: translate(30px,-40px) scale(1.05); }
    100% { transform: translate(-20px,20px) scale(0.97); }
  }
  .content { position: relative; z-index: 1; display: flex; flex-direction: column;
             align-items: center; padding: 3rem 1.5rem 2rem; min-height: 100vh; }
  .hero { text-align: center; max-width: 720px; margin-bottom: 2.5rem; }
  .hero .logo { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;
                color: var(--primary); letter-spacing: 0.3em; margin-bottom: 0.6rem; opacity: 0.9; }
  .hero h1 {
    font-size: 2.6rem; font-weight: 800; letter-spacing: -0.03em;
    background: linear-gradient(135deg, #14b8a6, #06b6d4, #3b82f6);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 0.7rem;
  }
  .hero .sub { font-size: 1.05rem; color: var(--text-dim); line-height: 1.7; font-weight: 300; }
  .stat-row { display: flex; gap: 1.4rem; justify-content: center; margin-top: 1.4rem; flex-wrap: wrap; }
  .stat { font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; color: var(--text-dim); }
  .stat strong { color: var(--primary); font-weight: 600; }

  /* Sphere selector */
  .sphere-bar {
    max-width: 1100px; width: 100%; margin-bottom: 1.5rem;
    display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center;
  }
  .sphere-bar .label { font-size: 0.72rem; color: var(--text-dim);
                       text-transform: uppercase; letter-spacing: 0.08em; margin-right: 0.5rem; }
  .sphere-tab {
    background: rgba(255,255,255,0.04); border: 1px solid var(--border);
    color: var(--text-dim); padding: 0.32rem 0.75rem; border-radius: 999px;
    font-size: 0.74rem; cursor: pointer; transition: all 0.2s; font-family: inherit;
    display: inline-flex; align-items: center; gap: 0.35rem;
  }
  .sphere-tab .n { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; opacity: 0.6; }
  .sphere-tab:hover, .sphere-tab.active {
    background: var(--primary-dim); color: var(--primary);
    border-color: rgba(20,184,166,0.3);
  }

  /* News feed */
  .news-section { max-width: 1100px; width: 100%; margin-bottom: 2.5rem; }
  .news-header { display: flex; align-items: center; justify-content: space-between;
                 margin-bottom: 1rem; }
  .news-header h2 { font-size: 1.2rem; font-weight: 700; }
  .news-header .badge {
    background: var(--primary-dim); color: var(--primary); font-size: 0.72rem;
    padding: 0.2rem 0.7rem; border-radius: 999px; font-weight: 500;
    font-family: 'JetBrains Mono', monospace;
  }
  .news-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    gap: 0.8rem;
  }
  .news-card {
    background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
    padding: 1rem 1.1rem; transition: border-color 0.2s, transform 0.15s;
    text-decoration: none; color: inherit; display: block;
  }
  .news-card:hover { border-color: rgba(20,184,166,0.25); transform: translateY(-1px); }
  .nc-meta-top { display: flex; gap: 0.4rem; align-items: center; margin-bottom: 0.4rem; }
  .nc-source { font-size: 0.65rem; color: var(--primary); font-weight: 600;
               text-transform: uppercase; letter-spacing: 0.04em; }
  .nc-lang { font-family: 'JetBrains Mono', monospace; font-size: 0.6rem;
             color: var(--text-dim); padding: 0.1rem 0.4rem; background: rgba(255,255,255,0.05);
             border-radius: 4px; text-transform: uppercase; }
  .news-card .nc-title {
    font-size: 0.88rem; font-weight: 500; line-height: 1.45;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
    overflow: hidden; margin-bottom: 0.4rem;
  }
  .news-card .nc-orig { font-size: 0.72rem; color: var(--text-dim); font-style: italic;
                        margin-bottom: 0.4rem; line-height: 1.4;
                        display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
                        overflow: hidden; }
  .news-card .nc-meta { font-size: 0.65rem; color: var(--text-dim); }
  .news-empty, .news-loading { text-align: center; color: var(--text-dim);
                                padding: 2rem; font-size: 0.9rem; grid-column: 1 / -1; }
  .news-loading .spinner { display: inline-block; width: 18px; height: 18px;
                           border: 2px solid var(--border); border-top-color: var(--primary);
                           border-radius: 50%; animation: spin 0.8s linear infinite;
                           vertical-align: middle; margin-right: 0.5rem; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* MCP config */
  .config-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                  gap: 1.2rem; max-width: 1100px; width: 100%; margin-bottom: 2.5rem; }
  .card { background: var(--bg-card); backdrop-filter: blur(16px);
          border: 1px solid var(--border); border-radius: 16px; padding: 1.4rem;
          position: relative; overflow: hidden; transition: border-color 0.3s; }
  .card:hover { border-color: rgba(20,184,166,0.25); }
  .card h3 { font-size: 1rem; font-weight: 600; margin-bottom: 0.4rem; }
  .card p { font-size: 0.82rem; color: var(--text-dim); margin-bottom: 0.8rem; line-height: 1.5; }
  .card code {
    display: block; background: rgba(0,0,0,0.5); padding: 0.7rem; border-radius: 8px;
    font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: var(--primary);
    word-break: break-all; margin-bottom: 0.7rem; max-height: 110px; overflow-y: auto;
    white-space: pre-wrap; border: 1px solid var(--border);
  }
  .btn { display: block; width: 100%; padding: 0.55rem; border-radius: 8px;
         font-size: 0.82rem; font-weight: 500; border: none; cursor: pointer;
         background: linear-gradient(135deg, var(--primary), #06b6d4);
         color: white; transition: opacity 0.2s; text-align: center; font-family: inherit; }
  .btn:hover { opacity: 0.85; }
  .btn.copied { background: var(--accent-blue); }

  /* Tools table */
  .tools { max-width: 800px; width: 100%; margin-bottom: 2rem;
           background: var(--bg-card); backdrop-filter: blur(16px);
           border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem; }
  .tools h2 { font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; }
  .tools table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  .tools td, .tools th { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border);
                          text-align: left; vertical-align: top; }
  .tools th { color: var(--text-dim); font-weight: 400; font-size: 0.72rem;
              text-transform: uppercase; letter-spacing: 0.06em; }
  .tools td:first-child { color: var(--primary); font-family: 'JetBrains Mono', monospace;
                          font-size: 0.74rem; white-space: nowrap; }

  footer { color: rgba(255,255,255,0.25); font-size: 0.7rem;
           margin-top: auto; padding: 2rem 0 1rem; text-align: center; }
  footer .sig { font-family: 'JetBrains Mono', monospace; opacity: 0.7; }

  @media (max-width: 600px) {
    .hero h1 { font-size: 1.8rem; }
    .config-cards { grid-template-columns: 1fr; }
    .news-grid { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="ambient">
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  <div class="orb orb-3"></div>
</div>

<div class="content">
<div class="hero">
  <div class="logo">▷  E C H O L O T  ◁</div>
  <h1>Globális narratíva-térkép</h1>
  <p class="sub">315 forrás 63 információs szférából — magyar sajtó, globális anchor lapok,
     kínai állami média, izraeli bal/jobb, iráni rezsim/ellenzék, ukrán front-OSINT,
     orosz milblog/ellenzék, japán/koreai/indiai/török/arab/dél-amerikai sajtó, US partisan szubsztakok,
     AI / climate / health / OSINT topikális csomagok, Telegram-csatornák.<br>
     Eredeti nyelven — az olvasó AI minden nyelvet ért.</p>
  <div class="stat-row">
    <div class="stat">📡 <strong id="stat-articles">…</strong> friss cikk</div>
    <div class="stat">🌐 <strong id="stat-spheres">…</strong> szféra</div>
    <div class="stat">🗞 <strong id="stat-sources">315</strong> forrás</div>
  </div>
</div>

<!-- Top-level grouped tabs (HU UI labels) -->
<div class="sphere-bar" id="group-bar">
  <span class="label">téma</span>
  <!-- populated by JS -->
</div>

<!-- Detailed sphere selector (collapsible) -->
<div class="sphere-bar" id="sphere-bar" style="display:none;">
  <span class="label">szféra</span>
  <button class="sphere-tab active" data-sphere="">Mind</button>
  <!-- populated dynamically from /api/spheres -->
</div>

<div style="max-width:1100px; width:100%; margin-bottom:1rem;">
  <button id="toggle-spheres" class="sphere-tab" style="font-size:0.7rem;">▼ részletes szféra-lista (63)</button>
</div>

<!-- News feed -->
<div class="news-section">
  <div class="news-header">
    <h2>Élő hírfolyam</h2>
    <span class="badge" id="news-count"></span>
  </div>
  <div class="news-grid" id="news-grid">
    <div class="news-loading"><span class="spinner"></span> Hírek betöltése...</div>
  </div>
</div>

<!-- MCP config cards -->
<div class="config-cards">
  <div class="card">
    <h3>Claude Desktop</h3>
    <p>Settings → Developer → Edit Config</p>
    <code id="claude-config">{
  "mcpServers": {
    "echolot": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "MCP_URL"]
    }
  }
}</code>
    <button class="btn" onclick="copyConfig('claude-config', this)">Konfiguráció másolása</button>
  </div>

  <div class="card">
    <h3>Claude Web / Mobil</h3>
    <p>claude.ai → Settings → Integrations</p>
    <code id="claude-web-url">MCP_URL</code>
    <button class="btn" onclick="copyConfig('claude-web-url', this)">URL másolása</button>
  </div>

  <div class="card">
    <h3>ChatGPT</h3>
    <p>Settings → More tools → Add MCP</p>
    <code id="chatgpt-url">MCP_URL</code>
    <button class="btn" onclick="copyConfig('chatgpt-url', this)">URL másolása</button>
  </div>
</div>

<div class="tools">
  <h2>MCP eszközök</h2>
  <p style="color: var(--text-dim); font-size: 0.85rem; line-height: 1.6; margin-bottom: 1.2rem;">
    Klasszikus napi/heti hírlekérés, FTS-keresés és trending — plus a payoff: a
    <code>narrative_divergence</code>, ami megmondja, ugyanarról a témáról mit ír a kínai
    állami sajtó, az iráni ellenzék, az ukrán front, az amerikai MAGA-szubsztak — egymás mellett.
  </p>
  <table>
    <tr><th>Eszköz</th><th>Leírás</th></tr>
    <tr><td>get_news</td><td>Hírek dátum / kategória / nyelv / szféra / lean szerint</td></tr>
    <tr><td>search_news</td><td>FTS-keresés (cím + lead, eredeti és angol)</td></tr>
    <tr><td>get_weekly_digest</td><td>Heti összefoglaló naponkénti bontásban</td></tr>
    <tr><td>get_trending</td><td>Trending témák — több forrás által közölt hírek</td></tr>
    <tr><td>narrative_divergence</td><td><strong>★ payoff:</strong> mit mond minden szféra ugyanarról a témáról</td></tr>
    <tr><td>get_spheres</td><td>Szféra-taxonómia + cikkszámok</td></tr>
    <tr><td>get_sources</td><td>Elérhető hírforrások listája</td></tr>
    <tr><td>get_scrape_status</td><td>Scraper állapot, utolsó futás, hibák</td></tr>
  </table>
</div>

<footer>
  <div>Echolot · globális hírelemző MCP</div>
  <div class="sig">Makronóm Intézet · v1.0 · 2026</div>
</footer>
</div>

<script>
const MCP_URL = window.location.origin + '/mcp';
document.querySelectorAll('.card code').forEach(el => {
  el.textContent = el.textContent.replace(/MCP_URL/g, MCP_URL);
});

function copyConfig(id, btn) {
  const text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.dataset.orig || btn.textContent;
    btn.dataset.orig = orig;
    btn.textContent = 'Másolva!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = orig; btn.classList.remove('copied'); }, 2000);
  });
}

// ===== Grouped tab definitions (HU UI labels → sphere lists) =====
const TAB_GROUPS = [
  { label: 'Mind', spheres: '', extra: '' },
  // --- magyar belföld + topikális csoportok ---
  { label: 'Magyar', spheres: 'hu_press,hu_premium,hu_foreign_commentary' },
  { label: 'Belföldi', spheres: 'hu_press' },
  { label: 'Magyar gazdaság', spheres: 'hu_economy' },
  { label: 'Magyar tech', spheres: 'hu_tech' },
  { label: 'Sport', spheres: 'hu_sport' },
  { label: 'Életmód', spheres: 'hu_lifestyle,hu_cars' },
  { label: 'Szórakoztató', spheres: 'hu_entertainment,global_entertainment,asia_entertainment' },
  // --- globális topikális ---
  { label: 'Világ', spheres: 'global_anchor,global_press' },
  { label: 'Gazdaság', spheres: 'global_economy' },
  { label: 'Tech', spheres: 'global_tech' },
  { label: 'AI', spheres: 'global_ai' },
  { label: 'Tudomány', spheres: 'global_science' },
  { label: 'Klíma', spheres: 'global_climate' },
  { label: 'Egészségügy', spheres: 'global_health' },
  { label: 'Elemzés', spheres: 'global_analysis,global_investigative' },
  { label: 'Konfliktus', spheres: 'global_conflict,ua_front_osint' },
  { label: 'OSINT', spheres: 'global_osint,global_investigative' },
  // --- regionális ---
  { label: 'Kína', spheres: 'regional_chinese,cn_state,cn_state_aligned,cn_hk,cn_tw,cn_diaspora_analysis,cn_weibo_pulse' },
  { label: 'Oroszország', spheres: 'regional_russian,ru_state_media,ru_opposition,ru_milblog_pro' },
  { label: 'USA', spheres: 'regional_us,us_maga_blog,us_maga_substack,us_liberal_press,us_liberal_substack' },
  { label: 'UK', spheres: 'regional_uk' },
  { label: 'Németország', spheres: 'regional_german' },
  { label: 'Franciaország', spheres: 'regional_french' },
  { label: 'Spanyolország', spheres: 'regional_spanish' },
  { label: 'Dél-Amerika', spheres: 'regional_south_american' },
  { label: 'Japán', spheres: 'regional_japanese,jp_press_english,jp_press_native' },
  { label: 'Korea', spheres: 'regional_korean,kr_press_english' },
  { label: 'India', spheres: 'regional_indian' },
  { label: 'Ausztrália', spheres: 'regional_australian' },
  { label: 'V4 / Közép-Európa', spheres: 'regional_v4' },
  { label: 'Izrael', spheres: 'regional_israeli,israel_press_left,israel_press_center,israel_press_right' },
  { label: 'Irán', spheres: 'regional_iranian,iran_regime,iran_opposition' },
  { label: 'Ukrajna', spheres: 'regional_ukrainian,ua_front_osint' },
  { label: 'Törökország', spheres: 'regional_turkish' },
  { label: 'Arab világ', spheres: 'regional_arabic' },
  { label: 'Afrika', spheres: 'regional_african' },
  // --- forrástípus ---
  { label: 'Telegram', spheres: '', extra: 'source_type=telegram' },
];

let activeQuery = '';

function timeAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const mins = Math.floor((Date.now() - d) / 60000);
  if (mins < 1) return 'most';
  if (mins < 60) return mins + ' perce';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + ' órája';
  const days = Math.floor(hrs / 24);
  return days + ' napja';
}

function escapeHTML(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderNews(arts) {
  const grid = document.getElementById('news-grid');
  if (!arts.length) {
    grid.innerHTML = '<div class="news-empty">Nincs cikk ebben a szelekcióban a vizsgált időablakon belül.</div>';
    return;
  }
  grid.innerHTML = arts.slice(0, 80).map(a => {
    const tg = a.source_type === 'telegram' ? '<span class="nc-lang" style="background:rgba(20,184,166,0.15);color:#14b8a6">TG</span>' : '';
    return `<a class="news-card" href="${escapeHTML(a.url)}" target="_blank" rel="noopener">
      <div class="nc-meta-top">
        <div class="nc-source">${escapeHTML(a.source_name)}</div>
        <div class="nc-lang">${escapeHTML(a.language || '')}</div>
        ${tg}
      </div>
      <div class="nc-title">${escapeHTML(a.title)}</div>
      <div class="nc-meta">${timeAgo(a.published_at)}</div>
    </a>`;
  }).join('');
}

function fetchNews(query, label) {
  activeQuery = query;
  document.querySelectorAll('#group-bar .sphere-tab, #sphere-bar .sphere-tab').forEach(t =>
    t.classList.toggle('active', (t.dataset.query || '') === query));
  let url = '/api/news?limit=80';
  if (query) url += '&' + query;
  fetch(url)
    .then(r => r.json())
    .then(d => {
      const arts = d.articles || [];
      document.getElementById('news-count').textContent = arts.length + ' cikk' + (label ? ' — ' + label : '');
      document.getElementById('stat-articles').textContent = arts.length;
      renderNews(arts);
    })
    .catch(() => {
      document.getElementById('news-grid').innerHTML =
        '<div class="news-empty">Hírek betöltése sikertelen — próbáld újra később.</div>';
    });
}

// Build top-level group bar
(function buildGroupBar() {
  const bar = document.getElementById('group-bar');
  TAB_GROUPS.forEach((g, i) => {
    const btn = document.createElement('button');
    btn.className = 'sphere-tab' + (i === 0 ? ' active' : '');
    let q = '';
    if (g.spheres) q = 'spheres=' + encodeURIComponent(g.spheres);
    if (g.extra)   q = q ? q + '&' + g.extra : g.extra;
    btn.dataset.query = q;
    btn.textContent = g.label;
    btn.onclick = () => fetchNews(q, g.label);
    bar.appendChild(btn);
  });
})();

// Detailed sphere bar — populated from /api/spheres
fetch('/api/spheres')
  .then(r => r.json())
  .then(d => {
    const bar = document.getElementById('sphere-bar');
    document.getElementById('stat-spheres').textContent = (d.spheres || []).length;
    document.getElementById('toggle-spheres').textContent =
      `▼ részletes szféra-lista (${(d.spheres || []).length})`;
    (d.spheres || []).forEach(([sph, n]) => {
      const btn = document.createElement('button');
      btn.className = 'sphere-tab';
      const q = 'spheres=' + encodeURIComponent(sph);
      btn.dataset.query = q;
      btn.innerHTML = `${sph}<span class="n">${n}</span>`;
      btn.onclick = () => fetchNews(q, sph);
      bar.appendChild(btn);
    });
  });

document.getElementById('toggle-spheres').onclick = () => {
  const bar = document.getElementById('sphere-bar');
  const btn = document.getElementById('toggle-spheres');
  const visible = bar.style.display !== 'none';
  bar.style.display = visible ? 'none' : 'flex';
  btn.textContent = (visible ? '▼' : '▲') + btn.textContent.slice(1);
};

fetchNews('', 'Mind');
</script>
</body>
</html>"""


@mcp.custom_route("/dashboard", methods=["GET"])
async def dashboard(request):
    """New-style polished dashboard (divergence search front-and-center)."""
    page, lang = render_dashboard(request)
    resp = HTMLResponse(page)
    resp.set_cookie("echolot_lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@mcp.custom_route("/dashboard/divergence", methods=["GET"])
async def dashboard_divergence(request):
    """HTMX partial — sphere-cards for one divergence query."""
    return HTMLResponse(render_divergence_partial(request, get_db))


@mcp.custom_route("/dashboard/spheres", methods=["GET"])
async def dashboard_spheres(request):
    page, lang = render_spheres_page(request, get_db)
    resp = HTMLResponse(page)
    resp.set_cookie("echolot_lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@mcp.custom_route("/dashboard/sphere/{name}", methods=["GET"])
async def dashboard_sphere_detail(request):
    name = request.path_params.get("name", "")
    page, lang = render_sphere_detail_page(request, name, get_db)
    resp = HTMLResponse(page)
    resp.set_cookie("echolot_lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@mcp.custom_route("/dashboard/health", methods=["GET"])
async def dashboard_health(request):
    page, lang = render_health_page(request, compute_health, DB_PATH)
    resp = HTMLResponse(page)
    resp.set_cookie("echolot_lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@mcp.custom_route("/dashboard/trending", methods=["GET"])
async def dashboard_trending(request):
    # Pre-fetch async data sources in this async route, then pass cached
    # results to the sync render helper.
    await _ensure_wiki_db_async()

    # Wikipedia top-movers (from local DB; empty until cache-warmer runs)
    wiki_cached = {"results": []}
    try:
        rows = await _wiki_db_top_movers(15)
        wiki_cached = {"results": [dict(r) if hasattr(r, "keys") else r for r in (rows or [])]}
    except Exception as exc:
        logger.warning("dashboard wiki movers: %s", exc)

    # Wikipedia top daily pageviews — language follows the dashboard's lang cookie
    # (with a sensible map: e.g. 'hu'→'hu', else 'en' for international audience)
    lang_for_wiki = (request.cookies.get("echolot_lang") or "hu").lower()
    if lang_for_wiki not in ("en", "hu", "de", "fr", "es", "it", "pl", "ru", "uk", "ja", "zh"):
        lang_for_wiki = "en"
    pageviews_cached = []
    try:
        pageviews_cached = await _wiki_top_pageviews(geo_wiki=lang_for_wiki, limit=15)
    except Exception as exc:
        logger.warning("dashboard wiki pageviews: %s", exc)

    def wiki_fn(limit: int = 15):
        return wiki_cached

    def wiki_pageviews_fn(limit: int = 15):
        return pageviews_cached

    page, lang = render_trending_page(
        request, compute_sphere_velocity, DB_PATH,
        wiki_top_movers_fn=wiki_fn,
        google_trends_fn=gnews_trending,
        wiki_pageviews_fn=wiki_pageviews_fn,
        wiki_pageviews_lang=lang_for_wiki,
    )
    resp = HTMLResponse(page)
    resp.set_cookie("echolot_lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@mcp.custom_route("/", methods=["GET"])
async def landing(request):
    """The original Echolot landing page, augmented with a language
    selector + a top-level tab-bar that links to the new sub-pages."""
    page, lang = augment_landing(request, LANDING_HTML)
    resp = HTMLResponse(page)
    resp.set_cookie("echolot_lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@mcp.custom_route("/landing-legacy", methods=["GET"])
async def landing_legacy(request):
    """The original landing page without any augmentation — for reference."""
    return HTMLResponse(LANDING_HTML)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
# DB schema is owned by scraper.py; just confirm the file is reachable.
if not DB_PATH.exists():
    logger.warning("DB %s does not exist yet — scraper will create it on first run", DB_PATH)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
