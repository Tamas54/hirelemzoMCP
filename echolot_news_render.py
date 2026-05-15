"""Server-side news-card rendering for the landing page.

The /?lang=… landing page's news-grid div is normally populated client-side
via fetch('/api/news') after the page loads. That's bad for SEO: crawlers
that don't execute JS see an empty grid.

This module renders the same news-card DOM structure that the JS
renderNews() function emits, so we can inject the initial batch into the
HTML server-side. The JS still runs and may overwrite the grid with
fresher data — but the crawler already saw 30 indexable headlines.
"""
from __future__ import annotations

import html as _html
import sqlite3
from datetime import datetime, timezone


def _time_ago(iso: str | None) -> str:
    """Approximate human-readable 'X minutes/hours/days ago' for an ISO timestamp.
    Mirrors the JS timeAgo() in landing-page so the initial+JS-rendered
    cards look identical.
    """
    if not iso:
        return ""
    try:
        # SQLite values like "2026-05-15T07:30:00+00:00" or "...+02:00" or "...Z"
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return ""
    diff = (datetime.now(timezone.utc) - dt).total_seconds()
    if diff < 60:
        return "now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    if diff < 86400 * 30:
        return f"{int(diff // 86400)}d ago"
    return dt.strftime("%Y-%m-%d")


def _esc(s) -> str:
    return _html.escape(str(s or ""), quote=True)


def render_initial_news_html(db_path: str, limit: int = 30) -> str:
    """Render `limit` most-recent news cards as HTML, matching the JS
    renderNews() DOM structure.

    Uses fetched_at + strftime comparator (devlog20260513 timezone-elv)
    so the published_at mixed-tz issue doesn't filter everything out.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT a.title, a.url, a.source_name, a.language,
                   a.published_at, s.source_type
            FROM articles a JOIN sources s ON s.id = a.source_id
            WHERE a.fetched_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')
              AND a.title IS NOT NULL AND a.url IS NOT NULL
            ORDER BY a.fetched_at DESC
            LIMIT ?
        """, (int(limit),)).fetchall()
        conn.close()
    except Exception:
        return ""  # gracefully degrade: JS will populate the grid

    if not rows:
        return ""

    cards: list[str] = []
    for r in rows:
        url = _esc(r["url"])
        src = _esc(r["source_name"])
        lang = _esc(r["language"])
        title = _esc(r["title"])
        ago = _esc(_time_ago(r["published_at"]))
        tg_badge = (
            '<span class="nc-lang" style="background:rgba(20,184,166,0.15);color:#14b8a6">TG</span>'
            if (r["source_type"] or "") == "telegram"
            else ""
        )
        cards.append(
            f'<a class="news-card" href="{url}" target="_blank" rel="noopener">'
            f'<div class="nc-meta-top">'
            f'<div class="nc-source">{src}</div>'
            f'<div class="nc-lang">{lang}</div>'
            f'{tg_badge}'
            f'</div>'
            f'<div class="nc-title">{title}</div>'
            f'<div class="nc-meta">{ago}</div>'
            f'</a>'
        )
    return "".join(cards)
