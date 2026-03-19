"""
HírMagnet MCP Server — AI-powered Hungarian news feed for researchers.
Makronóm Intézet, 2026.

MCP tools for accessing scraped Hungarian & international news sources.
Deployable on Railway with Streamable HTTP transport.

Tools:
  - get_news: Get news by date/category/source/language
  - search_news: Search by keywords in titles and leads
  - get_weekly_digest: Weekly digest grouped by day (for heti jelentés)
  - get_trending: Trending topics covered by multiple sources
  - get_sources: List available news sources
  - get_scrape_status: Scraper health and DB stats
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from collections import Counter, defaultdict

from mcp.server.fastmcp import FastMCP
from starlette.responses import HTMLResponse, JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hirmagnet-mcp")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "hirmagnet_news.db")


@contextmanager
def get_db():
    """Thread-safe SQLite connection."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize database tables."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                lead TEXT,
                url TEXT UNIQUE NOT NULL,
                source_name TEXT NOT NULL,
                source_category TEXT DEFAULT 'egyéb',
                language TEXT DEFAULT 'hu',
                published_at DATETIME,
                scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                content_hash TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(source_category);
            CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_name);
            CREATE INDEX IF NOT EXISTS idx_articles_title ON articles(title);

            CREATE TABLE IF NOT EXISTS scrape_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                articles_found INTEGER DEFAULT 0,
                articles_new INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            );
        """)
        conn.commit()
    logger.info("Database initialized.")


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "HírMagnet",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
)


@mcp.tool()
def get_news(
    date: str = "today",
    category: str = "",
    source: str = "",
    language: str = "",
    limit: int = 30,
) -> str:
    """Get news articles by date, category, or source.

    Args:
        date: "today", "yesterday", or ISO date (YYYY-MM-DD). Default: "today"
        category: Filter by category: "politika", "gazdaság", "világpolitika",
                  "tech", "sport", "kultúra", "tudomány", "belföldi", "EU", etc. Empty = all.
        source: Filter by source name (e.g. "HVG", "Telex", "Reuters"). Empty = all.
        language: Filter by language: "hu", "en", "de". Empty = all.
        limit: Max articles to return (1-100, default: 30)

    Returns:
        JSON with matching articles (title, lead, source, url, published_at)
    """
    limit = max(1, min(100, limit))

    if date == "today":
        date_start = datetime.now().replace(hour=0, minute=0, second=0)
    elif date == "yesterday":
        date_start = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0)
    else:
        try:
            date_start = datetime.fromisoformat(date)
        except ValueError:
            return json.dumps({"error": f"Invalid date format: {date}. Use 'today', 'yesterday', or YYYY-MM-DD"})

    date_end = date_start + timedelta(days=1)

    query = "SELECT title, lead, url, source_name, source_category, language, published_at FROM articles WHERE published_at >= ? AND published_at < ?"
    params = [date_start.isoformat(), date_end.isoformat()]

    if category:
        query += " AND LOWER(source_category) = LOWER(?)"
        params.append(category)
    if source:
        query += " AND LOWER(source_name) LIKE LOWER(?)"
        params.append(f"%{source}%")
    if language:
        query += " AND language = ?"
        params.append(language)

    query += " ORDER BY published_at DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    articles = [dict(r) for r in rows]
    return json.dumps({
        "date": date,
        "filters": {"category": category or "all", "source": source or "all", "language": language or "all"},
        "count": len(articles),
        "articles": articles,
    }, ensure_ascii=False, default=str)


@mcp.tool()
def search_news(
    query: str,
    days: int = 3,
    category: str = "",
    limit: int = 20,
) -> str:
    """Search news by keywords in titles and leads.

    Args:
        query: Search keywords (e.g. "Trump vámok", "MNB kamatdöntés", "EU csúcs")
        days: Search in the last N days (1-21, default: 3)
        category: Optional category filter
        limit: Max results (1-50, default: 20)

    Returns:
        JSON with matching articles sorted by date
    """
    days = max(1, min(21, days))
    limit = max(1, min(50, limit))
    since = (datetime.now() - timedelta(days=days)).isoformat()

    keywords = [k.strip() for k in query.split() if len(k.strip()) > 2]
    if not keywords:
        return json.dumps({"error": "Query too short. Use at least one keyword with 3+ characters."})

    conditions = []
    params = [since]
    for kw in keywords:
        conditions.append("(LOWER(title) LIKE LOWER(?) OR LOWER(COALESCE(lead,'')) LIKE LOWER(?))")
        params.extend([f"%{kw}%", f"%{kw}%"])

    where_clause = " AND ".join(conditions)
    sql = f"""
        SELECT title, lead, url, source_name, source_category, language, published_at
        FROM articles
        WHERE published_at >= ? AND ({where_clause})
    """
    if category:
        sql += " AND LOWER(source_category) = LOWER(?)"
        params.append(category)

    sql += " ORDER BY published_at DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    articles = [dict(r) for r in rows]
    return json.dumps({
        "query": query,
        "keywords": keywords,
        "days": days,
        "count": len(articles),
        "articles": articles,
    }, ensure_ascii=False, default=str)


@mcp.tool()
def get_weekly_digest(
    week: str = "current",
    category: str = "",
    limit: int = 50,
) -> str:
    """Get a weekly digest of news — perfect for weekly reports (heti jelentés) and szikrák.

    Args:
        week: "current", "last", or ISO week (e.g. "2026-W12"). Default: "current"
        category: Optional category filter
        limit: Max articles (1-200, default: 50)

    Returns:
        JSON with articles grouped by day, with daily counts
    """
    limit = max(1, min(200, limit))
    now = datetime.now()

    if week == "current":
        start = now - timedelta(days=now.weekday())
        end = start + timedelta(days=7)
    elif week == "last":
        start = now - timedelta(days=now.weekday() + 7)
        end = start + timedelta(days=7)
    else:
        try:
            start = datetime.strptime(week + "-1", "%G-W%V-%u")
            end = start + timedelta(days=7)
        except ValueError:
            return json.dumps({"error": f"Invalid week format: {week}. Use 'current', 'last', or '2026-W12'"})

    start = start.replace(hour=0, minute=0, second=0)
    end = end.replace(hour=0, minute=0, second=0)

    sql = """
        SELECT title, lead, url, source_name, source_category, language, published_at,
               DATE(published_at) as day
        FROM articles
        WHERE published_at >= ? AND published_at < ?
    """
    params = [start.isoformat(), end.isoformat()]

    if category:
        sql += " AND LOWER(source_category) = LOWER(?)"
        params.append(category)

    sql += " ORDER BY published_at DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    by_day = {}
    for r in rows:
        row = dict(r)
        day = row.pop("day", "unknown")
        by_day.setdefault(day, []).append(row)

    return json.dumps({
        "week": week,
        "period": f"{start.strftime('%Y-%m-%d')} — {end.strftime('%Y-%m-%d')}",
        "category": category or "all",
        "total_articles": len(rows),
        "days": {day: {"count": len(arts), "articles": arts} for day, arts in sorted(by_day.items())},
    }, ensure_ascii=False, default=str)


@mcp.tool()
def get_trending(days: int = 1, min_sources: int = 3, limit: int = 15) -> str:
    """Find trending topics — stories covered by multiple sources.

    Args:
        days: Look back N days (1-7, default: 1)
        min_sources: Minimum number of different sources covering the topic (default: 3)
        limit: Max trending topics (1-30, default: 15)

    Returns:
        JSON with trending topic clusters (keyword + related articles from different sources)
    """
    days = max(1, min(7, days))
    since = (datetime.now() - timedelta(days=days)).isoformat()

    with get_db() as conn:
        rows = conn.execute("""
            SELECT title, lead, url, source_name, source_category, published_at
            FROM articles WHERE published_at >= ?
            ORDER BY published_at DESC
        """, [since]).fetchall()

    articles = [dict(r) for r in rows]

    stop_words = {
        "a", "az", "és", "is", "hogy", "nem", "van", "volt", "lesz", "már",
        "még", "meg", "el", "ki", "be", "fel", "le", "ezt", "azt", "egy",
        "mint", "csak", "vagy", "ide", "oda", "ami", "aki", "amely", "ez",
        "the", "and", "for", "with", "from", "has", "have", "are", "was",
        "will", "but", "not", "its", "can", "into", "over", "about", "after",
        "this", "that", "said", "says", "new", "more", "been", "also",
    }

    def get_keywords(title):
        words = [w.lower().strip(".:,;!?\"'()-–—") for w in title.split()]
        return [w for w in words if len(w) > 3 and w not in stop_words]

    keyword_articles = defaultdict(list)
    for art in articles:
        for kw in get_keywords(art["title"]):
            keyword_articles[kw].append(art)

    trending = []
    seen_urls = set()
    for kw, arts in sorted(keyword_articles.items(), key=lambda x: -len(set(a["source_name"] for a in x[1]))):
        sources = set(a["source_name"] for a in arts)
        if len(sources) < min_sources:
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
            "source_count": len(sources),
            "sources": sorted(sources),
            "article_count": len(unique_arts),
            "articles": unique_arts[:5],
        })

        if len(trending) >= limit:
            break

    return json.dumps({
        "days": days,
        "min_sources": min_sources,
        "trending_count": len(trending),
        "trending": trending,
    }, ensure_ascii=False, default=str)


@mcp.tool()
def get_sources() -> str:
    """List all available news sources and their categories.

    Returns:
        JSON with sources grouped by category, including article counts
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT source_name, source_category, language, COUNT(*) as article_count,
                   MAX(published_at) as last_article
            FROM articles
            GROUP BY source_name, source_category, language
            ORDER BY source_category, source_name
        """).fetchall()

    by_category = {}
    for r in rows:
        row = dict(r)
        cat = row.pop("source_category", "egyéb")
        by_category.setdefault(cat, []).append(row)

    return json.dumps({
        "total_sources": len(rows),
        "categories": {cat: {"count": len(srcs), "sources": srcs} for cat, srcs in sorted(by_category.items())},
    }, ensure_ascii=False, default=str)


@mcp.tool()
def get_scrape_status() -> str:
    """Check the status of the news scraper — when was the last successful scrape.

    Returns:
        JSON with last scrape info and database stats
    """
    with get_db() as conn:
        last_scrape = conn.execute(
            "SELECT * FROM scrape_log ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

        stats = conn.execute("""
            SELECT
                COUNT(*) as total_articles,
                COUNT(DISTINCT source_name) as total_sources,
                MIN(published_at) as oldest_article,
                MAX(published_at) as newest_article,
                SUM(CASE WHEN DATE(published_at) = DATE('now') THEN 1 ELSE 0 END) as today_count,
                SUM(CASE WHEN DATE(published_at) = DATE('now', '-1 day') THEN 1 ELSE 0 END) as yesterday_count
            FROM articles
        """).fetchone()

    result = {
        "database_stats": dict(stats) if stats else {},
        "last_scrape": dict(last_scrape) if last_scrape else {"status": "never run"},
    }
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------
LANDING_HTML = """<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HírMagnet MCP — Makronóm Intézet</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --primary: #e74c3c;
    --primary-dim: rgba(231, 76, 60, 0.15);
    --accent-blue: #3b82f6;
    --accent-gold: #f59e0b;
    --bg: #050505;
    --bg-card: rgba(10, 10, 10, 0.7);
    --text: #f0f0f0;
    --text-dim: #a0a0a0;
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
  .ambient { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 0; pointer-events: none; }
  .orb {
    position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.2;
    animation: orb-float 14s ease-in-out infinite alternate;
  }
  .orb-1 { background: var(--primary); width: 600px; height: 600px; top: -200px; left: -200px; }
  .orb-2 { background: var(--accent-blue); width: 500px; height: 500px; bottom: -150px; right: -150px; animation-delay: 4s; }
  .orb-3 { background: var(--accent-gold); width: 350px; height: 350px; top: 40%; left: 50%; opacity: 0.12; animation-delay: 7s; }
  @keyframes orb-float {
    0% { transform: translate(0,0) scale(1); }
    50% { transform: translate(30px,-40px) scale(1.05); }
    100% { transform: translate(-20px,20px) scale(0.97); }
  }
  .content {
    position: relative; z-index: 1;
    display: flex; flex-direction: column; align-items: center;
    padding: 3rem 1.5rem 2rem;
    min-height: 100vh;
  }
  .hero { text-align: center; max-width: 640px; margin-bottom: 2.5rem; }
  .hero h1 {
    font-size: 2.4rem; font-weight: 800; letter-spacing: -0.03em;
    background: linear-gradient(135deg, var(--primary), #ff6b6b, var(--accent-gold));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 0.6rem;
  }
  .hero .sub { font-size: 1.05rem; color: var(--text-dim); line-height: 1.7; font-weight: 300; }
  .source-badges { display: flex; gap: 0.4rem; flex-wrap: wrap; justify-content: center; margin-top: 1.2rem; }
  .source-badges span {
    background: var(--primary-dim); padding: 0.25rem 0.7rem; border-radius: 999px;
    font-size: 0.75rem; color: var(--primary); border: 1px solid rgba(231,76,60,0.15);
    font-weight: 500;
  }
  /* MCP config cards */
  .config-cards {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1.2rem; max-width: 960px; width: 100%; margin-bottom: 2.5rem;
  }
  .card {
    background: var(--bg-card); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--border); border-radius: 16px; padding: 1.4rem;
    position: relative; overflow: hidden; transition: border-color 0.3s;
  }
  .card::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent);
  }
  .card:hover { border-color: rgba(231, 76, 60, 0.25); }
  .card h3 { font-size: 1rem; font-weight: 600; margin-bottom: 0.4rem; }
  .card p { font-size: 0.82rem; color: var(--text-dim); margin-bottom: 0.8rem; line-height: 1.5; }
  .card code {
    display: block; background: rgba(0,0,0,0.5); padding: 0.65rem; border-radius: 8px;
    font-size: 0.7rem; color: var(--primary); word-break: break-all;
    margin-bottom: 0.7rem; max-height: 110px; overflow-y: auto; white-space: pre-wrap;
    border: 1px solid var(--border);
  }
  .btn {
    display: block; width: 100%; padding: 0.5rem; border-radius: 8px;
    font-size: 0.82rem; font-weight: 500; border: none; cursor: pointer;
    background: linear-gradient(135deg, var(--primary), #ff6b6b);
    color: white; transition: opacity 0.2s; text-align: center;
  }
  .btn:hover { opacity: 0.85; }
  .btn.copied { background: var(--accent-blue); }
  /* News feed */
  .news-section {
    max-width: 960px; width: 100%; margin-bottom: 2.5rem;
  }
  .news-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 1rem;
  }
  .news-header h2 { font-size: 1.2rem; font-weight: 700; }
  .news-header .badge {
    background: var(--primary-dim); color: var(--primary); font-size: 0.72rem;
    padding: 0.2rem 0.6rem; border-radius: 999px; font-weight: 500;
  }
  .cat-tabs {
    display: flex; gap: 0.35rem; flex-wrap: wrap; margin-bottom: 1rem;
  }
  .cat-tab {
    background: rgba(255,255,255,0.04); border: 1px solid var(--border);
    color: var(--text-dim); padding: 0.3rem 0.7rem; border-radius: 999px;
    font-size: 0.72rem; cursor: pointer; transition: all 0.2s; font-family: inherit;
  }
  .cat-tab:hover, .cat-tab.active {
    background: var(--primary-dim); color: var(--primary);
    border-color: rgba(231,76,60,0.2);
  }
  .news-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 0.8rem;
  }
  .news-card {
    background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
    padding: 1rem 1.1rem; transition: border-color 0.2s, transform 0.15s;
    text-decoration: none; color: inherit; display: block;
  }
  .news-card:hover { border-color: rgba(231,76,60,0.2); transform: translateY(-1px); }
  .news-card .nc-source {
    font-size: 0.65rem; color: var(--primary); font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.35rem;
  }
  .news-card .nc-title {
    font-size: 0.85rem; font-weight: 500; line-height: 1.45;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
    overflow: hidden; margin-bottom: 0.4rem;
  }
  .news-card .nc-meta {
    font-size: 0.65rem; color: var(--text-dim);
  }
  .news-card .nc-cat {
    display: inline-block; background: rgba(255,255,255,0.04);
    padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.6rem;
    color: var(--text-dim); margin-left: 0.4rem;
  }
  .news-empty {
    text-align: center; color: var(--text-dim); padding: 2rem;
    font-size: 0.9rem; grid-column: 1 / -1;
  }
  .news-loading {
    text-align: center; color: var(--text-dim); padding: 2rem;
    font-size: 0.85rem; grid-column: 1 / -1;
  }
  .news-loading .spinner {
    display: inline-block; width: 18px; height: 18px;
    border: 2px solid var(--border); border-top-color: var(--primary);
    border-radius: 50%; animation: spin 0.8s linear infinite;
    vertical-align: middle; margin-right: 0.5rem;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  /* Tools */
  .tools {
    max-width: 720px; width: 100%; margin-bottom: 2rem;
    background: var(--bg-card); backdrop-filter: blur(16px);
    border: 1px solid var(--border); border-radius: 16px; padding: 1.5rem;
  }
  .tools h2 { font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem; }
  .tools table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  .tools td, .tools th { padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border); text-align: left; }
  .tools th { color: var(--text-dim); font-weight: 400; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .tools td:first-child { color: var(--primary); font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.75rem; }
  footer { color: rgba(255,255,255,0.2); font-size: 0.7rem; margin-top: auto; padding: 2rem 0 1rem; }
  @media (max-width: 600px) {
    .hero h1 { font-size: 1.6rem; }
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
  <h1>HírMagnet MCP a Makronóm Intézet Kutatóinak</h1>
  <p class="sub">140+ magyar és nemzetközi hírforrás, naponta frissítve.<br>
     Szikrák és heti jelentések írásához — AI asszisztensen keresztül.</p>
  <div class="source-badges">
    <span>Telex</span>
    <span>HVG</span>
    <span>Portfolio</span>
    <span>Index</span>
    <span>Reuters</span>
    <span>BBC</span>
    <span>Bloomberg</span>
    <span>Politico EU</span>
    <span>+130 forrás</span>
  </div>
</div>

<!-- Live news feed -->
<div class="news-section">
  <div class="news-header">
    <h2>Friss hírek</h2>
    <span class="badge" id="news-count"></span>
  </div>
  <div class="cat-tabs" id="cat-tabs">
    <button class="cat-tab active" data-cat="all">Mind</button>
    <button class="cat-tab" data-cat="belföldi">Belföldi</button>
    <button class="cat-tab" data-cat="politika">Politika</button>
    <button class="cat-tab" data-cat="gazdaság">Gazdaság</button>
    <button class="cat-tab" data-cat="világpolitika">Világ</button>
    <button class="cat-tab" data-cat="EU">EU</button>
    <button class="cat-tab" data-cat="tech">Tech</button>
    <button class="cat-tab" data-cat="tudomány">Tudomány</button>
  </div>
  <div class="news-grid" id="news-grid">
    <div class="news-loading"><span class="spinner"></span> Hírek betöltése...</div>
  </div>
</div>

<!-- MCP config cards -->
<div class="config-cards">
  <div class="card">
    <h3>Claude Desktop</h3>
    <p>Settings &rarr; Developer &rarr; Edit Config</p>
    <code id="claude-config">{
  "mcpServers": {
    "hirmagnet": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "MCP_URL"]
    }
  }
}</code>
    <button class="btn" onclick="copyConfig('claude-config', this)">Konfiguráció másolása</button>
  </div>

  <div class="card">
    <h3>Claude Web / Mobil</h3>
    <p>claude.ai &rarr; Settings &rarr; Integrations</p>
    <code id="claude-web-url">MCP_URL</code>
    <button class="btn" onclick="copyConfig('claude-web-url', this)">URL másolása</button>
  </div>

  <div class="card">
    <h3>ChatGPT</h3>
    <p>Settings &rarr; More tools &rarr; Add MCP</p>
    <code id="chatgpt-url">MCP_URL</code>
    <button class="btn" onclick="copyConfig('chatgpt-url', this)">URL másolása</button>
  </div>
</div>

<div class="tools">
  <h2>MCP eszközök</h2>
  <p style="color: var(--text-dim); font-size: 0.85rem; line-height: 1.6; margin-bottom: 1.2rem;">
    Kérd le a mai híreket, keress témára, vagy kérj heti összefoglalót szikra írásához —
    az MCP automatikusan biztosítja a friss híranyagot a Claude-odnak vagy ChatGPT-dnek.
  </p>
  <table>
    <tr><th>Eszköz</th><th>Leírás</th></tr>
    <tr><td>get_news</td><td>Napi hírek dátum, kategória, forrás szerint</td></tr>
    <tr><td>search_news</td><td>Keresés kulcsszavakra (címben és leadben)</td></tr>
    <tr><td>get_weekly_digest</td><td>Heti összefoglaló naponkénti bontásban</td></tr>
    <tr><td>get_trending</td><td>Trending témák — több forrás által is közölt hírek</td></tr>
    <tr><td>get_sources</td><td>Elérhető hírforrások listája</td></tr>
    <tr><td>get_scrape_status</td><td>Scraper állapot és adatbázis statisztika</td></tr>
  </table>
</div>

<footer>Makronóm Intézet</footer>
</div>

<script>
const MCP_URL = window.location.origin + '/mcp';
document.querySelectorAll('.card code').forEach(el => {
  el.textContent = el.textContent.replace(/MCP_URL/g, MCP_URL);
});

function copyConfig(id, btn) {
  const text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = 'Másolva!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = btn.dataset.orig || 'Másolás'; btn.classList.remove('copied'); }, 2000);
  });
  btn.dataset.orig = btn.dataset.orig || btn.textContent;
}

// --- Live news feed ---
let allArticles = [];
let activeCategory = 'all';

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const now = new Date();
  const mins = Math.floor((now - d) / 60000);
  if (mins < 1) return 'most';
  if (mins < 60) return mins + ' perce';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + ' órája';
  const days = Math.floor(hrs / 24);
  return days + ' napja';
}

function renderNews(articles) {
  const grid = document.getElementById('news-grid');
  if (!articles.length) {
    grid.innerHTML = '<div class="news-empty">Még nincsenek hírek — a scraper hamarosan frissít.</div>';
    return;
  }
  grid.innerHTML = articles.slice(0, 30).map(a => `
    <a class="news-card" href="${a.url}" target="_blank" rel="noopener">
      <div class="nc-source">${a.source_name}</div>
      <div class="nc-title">${a.title}</div>
      <div class="nc-meta">${timeAgo(a.published_at)}<span class="nc-cat">${a.source_category}</span></div>
    </a>
  `).join('');
}

function filterNews(cat) {
  activeCategory = cat;
  document.querySelectorAll('.cat-tab').forEach(t => t.classList.toggle('active', t.dataset.cat === cat));
  const filtered = cat === 'all' ? allArticles : allArticles.filter(a => a.source_category === cat);
  renderNews(filtered);
}

document.getElementById('cat-tabs').addEventListener('click', e => {
  if (e.target.classList.contains('cat-tab')) filterNews(e.target.dataset.cat);
});

// Fetch from REST API
fetch('/api/news')
  .then(r => r.json())
  .then(data => {
    allArticles = data.articles || [];
    document.getElementById('news-count').textContent = allArticles.length + ' cikk';
    renderNews(allArticles);
  })
  .catch(() => {
    document.getElementById('news-grid').innerHTML =
      '<div class="news-empty">Hírek betöltése sikertelen — próbáld újra később.</div>';
  });
</script>
</body>
</html>"""


@mcp.custom_route("/", methods=["GET"])
async def landing_page(request):
    return HTMLResponse(LANDING_HTML)


@mcp.custom_route("/api/news", methods=["GET"])
async def api_news(request):
    """Simple REST endpoint for the landing page to fetch recent articles."""
    now = datetime.now()
    # Try today first, fall back to yesterday if today is empty
    since = (now - timedelta(days=2)).replace(hour=0, minute=0, second=0)

    with get_db() as conn:
        rows = conn.execute("""
            SELECT title, url, source_name, source_category, published_at
            FROM articles
            WHERE published_at >= ?
            ORDER BY published_at DESC
            LIMIT 60
        """, [since.isoformat()]).fetchall()

    articles = [dict(r) for r in rows]
    return JSONResponse({"count": len(articles), "articles": articles})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
init_db()

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
