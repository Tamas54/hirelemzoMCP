"""Echolot dashboard — server-rendered HTML for human users.

Zero-build stack: inline HTML, Tailwind CSS via CDN, HTMX for live search.
The 6-language i18n is driven by echolot_i18n.

Routes (registered into server.py's FastMCP app):
    GET  /dashboard            — main dashboard page (or /dashboard?lang=en)
    GET  /dashboard/divergence — narrative_divergence partial (HTMX target)

The partial endpoints return HTML fragments that HTMX swaps into the page,
so no JS bundle is needed and the dashboard works without JavaScript too
(forms submit, full page reloads).
"""
from __future__ import annotations

import html
import json
from urllib.parse import quote

from echolot_i18n import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    lang_options,
    resolve_lang,
    t,
)


def _request_lang(request) -> str:
    """Pick a language from the request: ?lang= > cookie > Accept-Language."""
    query_lang = request.query_params.get("lang")
    cookie_lang = request.cookies.get("echolot_lang")
    accept = request.headers.get("accept-language")
    return resolve_lang(query_lang, cookie_lang, accept)


def _escape(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def _lang_selector_html(current: str, target: str = "/") -> str:
    """Render a small language-dropdown form for the header."""
    opts = []
    for code, native in lang_options():
        sel = " selected" if code == current else ""
        opts.append(f'<option value="{code}"{sel}>{_escape(native)}</option>')
    return f"""
    <form method="get" action="{target}" class="inline-block">
      <label class="text-xs text-gray-400 mr-1">{_escape(t('lang.label', current))}:</label>
      <select name="lang" onchange="this.form.submit()"
              class="bg-gray-800 text-gray-200 text-sm rounded px-2 py-1 border border-gray-700">
        {''.join(opts)}
      </select>
    </form>
    """


def _nav_html(lang: str, active: str) -> str:
    """Top tab-nav: divergence / trending / spheres / health."""
    tabs = [
        ("divergence", "/",                "tab.divergence"),
        ("trending",   "/dashboard/trending", "tab.trending"),
        ("spheres",    "/dashboard/spheres",  "tab.spheres"),
        ("health",     "/dashboard/health",   "tab.health"),
    ]
    parts = []
    for key, url, t_key in tabs:
        active_cls = "bg-indigo-700 text-white" if key == active else "text-gray-400 hover:text-gray-100 hover:bg-gray-800"
        parts.append(
            f'<a href="{url}?lang={lang}" class="px-3 py-1.5 rounded text-sm {active_cls}">'
            f'{_escape(t(t_key, lang))}</a>'
        )
    return '<nav class="flex flex-wrap gap-1">' + "".join(parts) + "</nav>"


_BASE_STYLES = """
    body { background: #0a0a0f; color: #e5e7eb; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }
    .sphere-card { background: #14141c; border: 1px solid #1f2937; }
    .sphere-card:hover { border-color: #374151; }
    .lean-left      { color: #93c5fd; }
    .lean-right     { color: #fca5a5; }
    .lean-center    { color: #d1d5db; }
    .lean-analytical{ color: #fde68a; }
    .lean-gov       { color: #c4b5fd; }
    .lean-opposition{ color: #f9a8d4; }
    .lean-unknown   { color: #9ca3af; }
    .trust-1 { background: #064e3b; }
    .trust-2 { background: #1e3a8a; }
    .trust-3 { background: #7c2d12; }
    .status-green  { background: #064e3b; color: #6ee7b7; }
    .status-yellow { background: #78350f; color: #fcd34d; }
    .status-red    { background: #7f1d1d; color: #fca5a5; }
    .htmx-indicator { display: none; }
    .htmx-request .htmx-indicator { display: inline; }
    .htmx-request.htmx-indicator   { display: inline; }
"""


def _page_shell(lang: str, active_tab: str, body_html: str) -> str:
    """Wrap a body in the standard dashboard chrome (header, nav, footer)."""
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(t('site.title', lang))}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <style>{_BASE_STYLES}</style>
</head>
<body class="min-h-screen">
  <header class="border-b border-gray-800 bg-gray-900/50 sticky top-0 backdrop-blur z-10">
    <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
      <div>
        <a href="/?lang={lang}" class="block">
          <h1 class="text-xl font-semibold">{_escape(t('site.title', lang))}</h1>
          <p class="text-xs text-gray-400 mt-0.5">{_escape(t('site.subtitle', lang))}</p>
        </a>
      </div>
      <div class="flex items-center gap-3">
        {_nav_html(lang, active_tab)}
        {_lang_selector_html(lang)}
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 py-6">
    {body_html}
  </main>

  <footer class="border-t border-gray-800 mt-12 py-6 text-center text-xs text-gray-500">
    <p>{_escape(t('footer.about', lang))}</p>
    <p class="mt-2 text-gray-600">
      <a href="/landing-legacy" class="hover:text-gray-400 underline">Old view</a>
    </p>
  </footer>
</body>
</html>"""


def render_dashboard(request) -> tuple[str, str]:
    """Return (html, lang) for the main page (= divergence tab)."""
    lang = _request_lang(request)
    body = f"""
    <form hx-get="/dashboard/divergence"
          hx-target="#results"
          hx-indicator="#search-spinner"
          hx-include="[name='lang']"
          class="mb-6">
      <input type="hidden" name="lang" value="{lang}">
      <div class="flex gap-2 flex-wrap">
        <input type="text" name="query" required
               placeholder="{_escape(t('search.placeholder', lang))}"
               class="flex-1 min-w-[200px] bg-gray-800 text-gray-100 px-3 py-2 rounded border border-gray-700 focus:border-indigo-500 focus:outline-none">
        <input type="number" name="days" value="3" min="1" max="21"
               title="{_escape(t('search.days_label', lang))}"
               class="w-20 bg-gray-800 text-gray-100 px-3 py-2 rounded border border-gray-700">
        <button type="submit"
                class="bg-indigo-600 hover:bg-indigo-500 px-5 py-2 rounded font-medium">
          {_escape(t('search.button', lang))}
          <span id="search-spinner" class="htmx-indicator ml-2">…</span>
        </button>
      </div>
    </form>

    <div id="results">
      <p class="text-gray-500 text-sm">{_escape(t('msg.empty_query', lang))}</p>
    </div>
    """
    return _page_shell(lang, "divergence", body), lang


def render_spheres_page(request, conn_factory) -> tuple[str, str]:
    """Sphere browser — list every sphere with article-count + sample sources."""
    lang = _request_lang(request)
    sql = """
        SELECT je.value AS sphere,
               COUNT(DISTINCT a.article_id) AS article_count,
               MAX(a.published_at) AS latest_at,
               COUNT(DISTINCT a.source_id) AS source_count
        FROM articles a, json_each(a.spheres_json) je
        GROUP BY je.value
        ORDER BY article_count DESC
    """
    with conn_factory() as conn:
        rows = conn.execute(sql).fetchall()
    cards = []
    for r in rows:
        sphere = r["sphere"]
        latest = (r["latest_at"] or "")[:16].replace("T", " ")
        cards.append(f"""
          <a href="/?lang={lang}#sphere={_escape(sphere)}"
             class="sphere-card rounded p-3 block hover:border-indigo-500">
            <div class="font-mono text-sm text-indigo-300">{_escape(sphere)}</div>
            <div class="text-xs text-gray-500 mt-1">
              {r['article_count']} {_escape(t('article.source', lang))} ·
              {r['source_count']} src · {_escape(latest)}
            </div>
          </a>""")
    body = f"""
      <h2 class="text-lg font-semibold mb-4">{_escape(t('tab.spheres', lang))}</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {''.join(cards)}
      </div>
    """
    return _page_shell(lang, "spheres", body), lang


def render_health_page(request, compute_health_fn, db_path) -> tuple[str, str]:
    """Sphere health page — green/yellow/red status grid."""
    lang = _request_lang(request)
    try:
        report = compute_health_fn(db_path, top_n=10)
    except Exception as exc:
        body = f'<p class="text-red-400">Error: {_escape(str(exc))}</p>'
        return _page_shell(lang, "health", body), lang
    summary = report.get("summary", {})
    cards = []
    for s in report.get("spheres", []):
        status = s.get("status", "red")
        cards.append(f"""
          <div class="sphere-card rounded p-3">
            <div class="flex items-center justify-between gap-2">
              <span class="font-mono text-xs text-indigo-300">{_escape(s['sphere'])}</span>
              <span class="status-{status} px-2 py-0.5 rounded text-[10px] uppercase">{status}</span>
            </div>
            <div class="text-xs text-gray-500 mt-1">
              24h: {s.get('article_count_24h', 0)} · 7d: {s.get('article_count_7d', 0)} ·
              {_escape(s.get('latest_article_age_human', '—'))}
            </div>
          </div>""")
    xh = report.get("x_sources_health") or {}
    x_block = ""
    if xh:
        x_alert = xh.get("alert")
        alert_html = f'<div class="text-yellow-400 text-sm mb-2">⚠️ {_escape(x_alert)}</div>' if x_alert else ""
        x_block = f"""
        <div class="mb-6">
          <h3 class="text-sm uppercase text-gray-400 mb-2">X / Twitter via RSSHub</h3>
          {alert_html}
          <div class="text-xs text-gray-500">
            Last 24h across x_* spheres: <b class="text-gray-300">{xh.get('total_articles_24h', 0)}</b> tweets
          </div>
        </div>"""
    body = f"""
      <h2 class="text-lg font-semibold mb-4">{_escape(t('tab.health', lang))}</h2>
      <div class="flex gap-3 mb-4 text-sm">
        <span class="status-green px-2 py-0.5 rounded">{summary.get('green', 0)} green</span>
        <span class="status-yellow px-2 py-0.5 rounded">{summary.get('yellow', 0)} yellow</span>
        <span class="status-red px-2 py-0.5 rounded">{summary.get('red', 0)} red</span>
      </div>
      {x_block}
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {''.join(cards)}
      </div>
    """
    return _page_shell(lang, "health", body), lang


def render_trending_page(request, compute_velocity_fn, db_path) -> tuple[str, str]:
    """Trending sphere-velocity — which spheres are spiking now."""
    lang = _request_lang(request)
    try:
        report = compute_velocity_fn(db_path, window_hours=6, baseline_offset_hours=24, limit=30)
    except Exception as exc:
        body = f'<p class="text-red-400">Error: {_escape(str(exc))}</p>'
        return _page_shell(lang, "trending", body), lang
    rows = []
    for s in report.get("spheres", []):
        status = s.get("status", "normal")
        # map velocity status to the green/yellow/red palette
        color = {"spike": "red", "rising": "yellow", "normal": "green",
                 "quiet": "yellow", "no_baseline": "yellow"}.get(status, "yellow")
        ratio = s.get("velocity_ratio")
        ratio_s = f"{ratio:.2f}×" if ratio is not None else "—"
        rows.append(f"""
          <tr class="border-b border-gray-800 hover:bg-gray-900/50">
            <td class="py-2 font-mono text-xs text-indigo-300">{_escape(s['sphere'])}</td>
            <td class="py-2 text-sm">{s.get('current_count', 0)}</td>
            <td class="py-2 text-sm text-gray-500">{s.get('baseline_count', 0)}</td>
            <td class="py-2 text-sm font-mono">{ratio_s}</td>
            <td class="py-2">
              <span class="status-{color} px-2 py-0.5 rounded text-[10px] uppercase">{status}</span>
            </td>
          </tr>""")
    body = f"""
      <h2 class="text-lg font-semibold mb-1">{_escape(t('tab.trending', lang))}</h2>
      <p class="text-xs text-gray-500 mb-4">
        {report.get('window_hours', 6)}h vs {report.get('baseline_window', '?')}
      </p>
      <div class="overflow-x-auto">
        <table class="w-full text-left">
          <thead class="border-b border-gray-700 text-xs uppercase text-gray-400">
            <tr><th class="py-2">{_escape(t('tab.spheres', lang))}</th>
                <th class="py-2">current</th>
                <th class="py-2">baseline</th>
                <th class="py-2">ratio</th>
                <th class="py-2">status</th></tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    """
    return _page_shell(lang, "trending", body), lang


def render_divergence_partial(request, conn_factory) -> str:
    """HTMX partial: run narrative_divergence and render sphere-cards.

    Args:
        request: Starlette Request
        conn_factory: a callable returning a sqlite3 connection context manager
            (same as server.py's get_db)
    """
    lang = _request_lang(request)
    query = (request.query_params.get("query") or "").strip()
    try:
        days = max(1, min(21, int(request.query_params.get("days") or 3)))
    except ValueError:
        days = 3

    if not query:
        return f'<p class="text-gray-500 text-sm">{_escape(t("msg.empty_query", lang))}</p>'

    terms = [tt for tt in query.split() if len(tt) > 2]
    if not terms:
        return f'<p class="text-yellow-400 text-sm">{_escape(t("msg.empty_query", lang))}</p>'
    fts_query = " OR ".join(f'"{tt}"' for tt in terms)

    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(days=days)).isoformat()

    sql = """
        SELECT a.title, a.lead, a.url, a.source_name, a.published_at,
               a.language, a.spheres_json, s.lean, s.trust_tier
        FROM articles a
        JOIN articles_fts fts ON fts.article_id = a.article_id
        JOIN sources s ON s.id = a.source_id
        WHERE articles_fts MATCH ? AND a.published_at >= ?
        ORDER BY a.published_at DESC
        LIMIT 500
    """
    try:
        with conn_factory() as conn:
            rows = conn.execute(sql, (fts_query, since)).fetchall()
    except Exception as exc:
        return f'<p class="text-red-400 text-sm">{_escape(t("msg.error", lang))}: {_escape(str(exc))}</p>'

    if not rows:
        return f'<p class="text-gray-500 text-sm">{_escape(t("msg.no_results", lang))} — <code>{_escape(query)}</code></p>'

    # Group by sphere
    from collections import defaultdict
    by_sphere: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d = dict(r)
        try:
            spheres = json.loads(d.get("spheres_json") or "[]")
        except Exception:
            spheres = []
        for sph in spheres:
            by_sphere[sph].append(d)

    # Sort spheres by article count, take top 8 to keep the page reasonable
    sorted_spheres = sorted(by_sphere.items(), key=lambda kv: -len(kv[1]))[:8]

    cards = []
    for sphere, items in sorted_spheres:
        items_sorted = sorted(items, key=lambda x: (x.get("published_at") or ""), reverse=True)[:6]
        item_html = []
        for it in items_sorted:
            lean = (it.get("lean") or "unknown").replace(" ", "_")
            trust = it.get("trust_tier") or 2
            published = (it.get("published_at") or "")[:16].replace("T", " ")
            item_html.append(f"""
                <li class="border-l-2 border-gray-800 pl-3 py-1 hover:border-indigo-500">
                  <a href="{_escape(it.get('url') or '#')}" target="_blank" rel="noopener"
                     class="block text-sm hover:text-indigo-300">{_escape(it.get('title') or '')}</a>
                  <div class="text-xs text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
                    <span>{_escape(it.get('source_name') or '')}</span>
                    <span class="trust-{trust} px-1.5 rounded text-[10px] uppercase">T{trust}</span>
                    <span class="lean-{lean}">{_escape(lean)}</span>
                    <span class="text-gray-600">{_escape(published)}</span>
                  </div>
                </li>""")
        cards.append(f"""
            <div class="sphere-card rounded p-4">
              <div class="flex items-center justify-between mb-2">
                <h3 class="font-mono text-sm text-indigo-300">{_escape(sphere)}</h3>
                <span class="text-xs text-gray-500">{len(items)} {_escape(t('article.source', lang))}</span>
              </div>
              <ul class="space-y-1">{''.join(item_html)}</ul>
            </div>""")

    return f"""
      <div class="mb-3 text-xs text-gray-500">
        <code class="bg-gray-800 px-2 py-0.5 rounded">{_escape(query)}</code> ·
        {days} {_escape(t('search.days_label', lang))} ·
        {len(rows)} {_escape(t('article.source', lang))} ·
        {len(by_sphere)} {_escape(t('tab.spheres', lang))}
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {''.join(cards)}
      </div>
    """
