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
import re
from urllib.parse import quote

from echolot_i18n import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    lang_options,
    resolve_lang,
    t,
)
from echolot_tab_groups import build_tab_groups
from echolot_seo import public_origin, seo_head_html


def _augment_strip_css() -> str:
    """Inline CSS for the multilingual nav-strip + search form injected
    at the very top of the original LANDING_HTML."""
    return """
    .echolot-augment {
      max-width: 1100px; width: 100%; margin: 1rem auto 0;
      display: flex; align-items: center; justify-content: space-between;
      gap: 1rem; flex-wrap: wrap; padding: 0 1.5rem;
      position: relative; z-index: 5;
    }
    .echolot-augment nav { display: flex; gap: 0.4rem; flex-wrap: wrap; }
    .echolot-augment .augment-tab {
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.06);
      color: #8a9499; padding: 0.32rem 0.85rem; border-radius: 999px;
      font-size: 0.74rem; text-decoration: none; transition: all 0.2s;
      font-family: 'JetBrains Mono', monospace;
    }
    .echolot-augment .augment-tab:hover,
    .echolot-augment .augment-tab.active {
      background: rgba(20, 184, 166, 0.15); color: #14b8a6;
      border-color: rgba(20, 184, 166, 0.3);
    }
    .echolot-augment select {
      background: rgba(255,255,255,0.04); color: #e8eef0;
      border: 1px solid rgba(255,255,255,0.06); border-radius: 6px;
      padding: 0.3rem 0.6rem; font-family: inherit; font-size: 0.78rem;
    }
    .echolot-search-form {
      max-width: 1100px; width: calc(100% - 3rem);
      margin: 1rem auto 0.5rem;
      display: flex; gap: 0.5rem; flex-wrap: wrap;
      padding: 0 1.5rem;
      position: relative; z-index: 5;
    }
    .echolot-search-input {
      flex: 1; min-width: 240px;
      background: rgba(12, 14, 18, 0.7); backdrop-filter: blur(16px);
      color: #e8eef0;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 10px;
      padding: 0.7rem 1rem;
      font-family: inherit; font-size: 0.95rem;
      transition: border-color 0.18s, box-shadow 0.18s;
    }
    .echolot-search-input:focus {
      outline: none;
      border-color: rgba(20, 184, 166, 0.5);
      box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.12);
    }
    .echolot-search-input::placeholder { color: #5b6266; }
    .echolot-search-days {
      width: 70px;
      background: rgba(12, 14, 18, 0.7); backdrop-filter: blur(16px);
      color: #e8eef0;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 10px;
      padding: 0.7rem 0.6rem;
      font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;
      text-align: center;
    }
    .echolot-search-btn {
      background: linear-gradient(135deg, #14b8a6, #06b6d4);
      color: white; font-weight: 600;
      padding: 0.7rem 1.4rem; border-radius: 10px;
      border: none; cursor: pointer;
      font-family: inherit; font-size: 0.92rem;
      transition: opacity 0.18s, transform 0.12s;
    }
    .echolot-search-btn:hover { opacity: 0.9; transform: translateY(-1px); }
    .echolot-search-btn:active { transform: translateY(0); }
    """


def _augment_block_html(lang: str, active: str = "feed") -> str:
    """The nav-bar + lang-selector + search HTML to inject into LANDING_HTML."""
    tabs = [
        ("feed",     "/",                     "Hírfolyam" if lang == "hu" else t("tab.divergence", lang)),
        ("trending", "/dashboard/trending",   t("tab.trending", lang)),
        ("spheres",  "/dashboard/spheres",    t("tab.spheres", lang)),
        ("health",   "/dashboard/health",     t("tab.health", lang)),
    ]
    tab_html = []
    for key, url, label in tabs:
        cls = "augment-tab active" if key == active else "augment-tab"
        tab_html.append(f'<a href="{url}?lang={lang}" class="{cls}">{html.escape(label, quote=True)}</a>')
    opts = []
    for code, native in lang_options():
        sel = " selected" if code == lang else ""
        opts.append(f'<option value="{code}"{sel}>{html.escape(native, quote=True)}</option>')
    return f"""
    <div class="echolot-augment">
      <nav>{''.join(tab_html)}</nav>
      <form method="get" action="/" class="inline-flex items-center gap-2">
        <select name="lang" onchange="this.form.submit()" aria-label="{html.escape(t('lang.label', lang), quote=True)}">
          {''.join(opts)}
        </select>
      </form>
    </div>
    <form method="get" action="/dashboard" class="echolot-search-form">
      <input type="hidden" name="lang" value="{lang}">
      <input type="text" name="query" required
             placeholder="{html.escape(t('search.placeholder', lang), quote=True)}"
             class="echolot-search-input"
             autocomplete="off">
      <input type="number" name="days" value="3" min="1" max="21"
             title="{html.escape(t('search.days_label', lang), quote=True)}"
             class="echolot-search-days">
      <button type="submit" class="echolot-search-btn">
        {html.escape(t('search.button', lang), quote=True)} →
      </button>
    </form>
    """


def augment_landing(request, landing_html: str) -> tuple[str, str]:
    """Inject the lang-selector + tab-bar AND localize the hero, stat-row,
    sphere-bars, news-section, MCP-config buttons, MCP-tools block, and
    footer of the original LANDING_HTML.

    Returns (html, resolved_lang).
    """
    lang = _request_lang(request)
    css = _augment_strip_css()
    block = _augment_block_html(lang, active="feed")
    out = landing_html.replace("</style>", css + "\n</style>", 1)
    out = out.replace("<body>", "<body>\n" + block, 1)
    out = out.replace('<html lang="hu">', f'<html lang="{lang}">', 1)

    # SEO head block (meta description + canonical + hreflang × 6 + OG + Twitter)
    seo_head = seo_head_html(
        origin=public_origin(request), lang=lang, path="/",
        description=t("seo.site.description", lang),
        og_title=f"Echolot — {t('landing.hero_title', lang)}",
    )
    # Inject after the <title>…</title> line
    out = re.sub(
        r"(<title>[^<]*</title>)",
        lambda m: m.group(1) + "\n" + seo_head,
        out,
        count=1,
    )

    # ── Localize the static landing strings (Hungarian originals → t(lang)) ──
    hero_title = t("landing.hero_title", lang)
    out = out.replace(
        "<title>Echolot — Globális narratíva-térkép</title>",
        f"<title>Echolot — {html.escape(hero_title)}</title>",
        1,
    )
    out = out.replace(
        "<h1>Globális narratíva-térkép</h1>",
        f"<h1>{html.escape(hero_title)}</h1>",
        1,
    )

    # Hero subtitle: replace the entire 5-line <p class="sub">…</p> block
    hero_sub_old = (
        '<p class="sub">315 forrás 63 információs szférából — magyar sajtó, globális anchor lapok,\n'
        '     kínai állami média, izraeli bal/jobb, iráni rezsim/ellenzék, ukrán front-OSINT,\n'
        '     orosz milblog/ellenzék, japán/koreai/indiai/török/arab/dél-amerikai sajtó, US partisan szubsztakok,\n'
        '     AI / climate / health / OSINT topikális csomagok, Telegram-csatornák.<br>\n'
        '     Eredeti nyelven — az olvasó AI minden nyelvet ért.</p>'
    )
    hero_sub_new = (
        f'<p class="sub">{html.escape(t("landing.hero_description", lang))}<br>\n'
        f'     {html.escape(t("landing.hero_native_note", lang))}</p>'
    )
    out = out.replace(hero_sub_old, hero_sub_new, 1)

    # Stat row labels (suffix-text after the <strong>…</strong>)
    out = out.replace("</strong> friss cikk</div>",
                      f"</strong> {html.escape(t('landing.stat.fresh_articles', lang))}</div>", 1)
    out = out.replace("</strong> szféra</div>",
                      f"</strong> {html.escape(t('landing.stat.spheres', lang))}</div>", 1)
    out = out.replace("</strong> forrás</div>",
                      f"</strong> {html.escape(t('landing.stat.sources', lang))}</div>", 1)

    # Sphere-bar labels + "Mind" button + toggle
    out = out.replace('<span class="label">téma</span>',
                      f'<span class="label">{html.escape(t("landing.bar.theme", lang))}</span>', 1)
    out = out.replace('<span class="label">szféra</span>',
                      f'<span class="label">{html.escape(t("landing.stat.spheres", lang))}</span>', 1)
    out = out.replace('data-sphere="">Mind</button>',
                      f'data-sphere="">{html.escape(t("landing.bar.all", lang))}</button>', 1)
    out = out.replace('▼ részletes szféra-lista (63)</button>',
                      f'{html.escape(t("landing.bar.toggle_detailed", lang))}</button>', 1)

    # News section
    out = out.replace("<h2>Élő hírfolyam</h2>",
                      f"<h2>{html.escape(t('landing.news.title', lang))}</h2>", 1)
    out = out.replace('<span class="spinner"></span> Hírek betöltése...',
                      f'<span class="spinner"></span> {html.escape(t("landing.news.loading", lang))}', 1)

    # MCP-config card buttons (3 buttons, all unique strings)
    out = out.replace(">Konfiguráció másolása</button>",
                      f">{html.escape(t('landing.config.copy_button', lang))}</button>", 1)
    # The two "URL másolása" buttons are identical strings — replace_all not used
    # (each call replaces only first occurrence), so chain two .replace calls.
    out = out.replace(">URL másolása</button>",
                      f">{html.escape(t('landing.config.copy_url_button', lang))}</button>", 2)

    # JS "Másolva!" ack message inside the script
    out = out.replace("btn.textContent = 'Másolva!';",
                      f"btn.textContent = '{html.escape(t('landing.config.copied_ack', lang))}';", 1)

    # MCP tools block (h2 + intro + col headers + footer)
    out = out.replace("<h2>MCP eszközök</h2>",
                      f"<h2>{html.escape(t('landing.tools.title', lang))}</h2>", 1)
    out = out.replace(
        "Klasszikus napi/heti hírlekérés, FTS-keresés és trending — plus a payoff: a\n"
        "    <code>narrative_divergence</code>, ami megmondja, ugyanarról a témáról mit ír a kínai\n"
        "    állami sajtó, az iráni ellenzék, az ukrán front, az amerikai MAGA-szubsztak — egymás mellett.",
        t("landing.tools.intro", lang),
        1,
    )
    out = out.replace("<tr><th>Eszköz</th><th>Leírás</th></tr>",
                      f"<tr><th>{html.escape(t('landing.tools.col_tool', lang))}</th>"
                      f"<th>{html.escape(t('landing.tools.col_desc', lang))}</th></tr>", 1)

    # Footer tagline
    out = out.replace("Echolot · globális hírelemző MCP",
                      f"Echolot · {html.escape(t('landing.footer.tagline', lang))}", 1)

    # ── Replace the hard-coded TAB_GROUPS JS array with a server-rendered,
    #    language-aware version (lang-specific Domestic block + universal
    #    Topical + Geo perspectives minus reader's own geo). ──
    groups_data = build_tab_groups(lang)
    js_items = []
    for g in groups_data:
        item = {"label": t(g["label_key"], lang), "spheres": g["spheres"]}
        if g.get("extra"):
            item["extra"] = g["extra"]
        js_items.append(item)
    new_tab_groups_js = "const TAB_GROUPS = " + json.dumps(js_items, ensure_ascii=False) + ";"
    out = re.sub(
        r"const TAB_GROUPS = \[.*?\];",
        lambda m: new_tab_groups_js,
        out,
        count=1,
        flags=re.DOTALL,
    )

    return out, lang


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
    <form method="get" action="{target}" class="inline-flex items-center gap-2">
      <select name="lang" onchange="this.form.submit()" class="lang-select" aria-label="{_escape(t('lang.label', current))}">
        {''.join(opts)}
      </select>
    </form>
    """


def _nav_html(lang: str, active: str) -> str:
    """Top tab-nav: divergence / trending / spheres / health."""
    tabs = [
        ("divergence", "/",                    "tab.divergence"),
        ("trending",   "/dashboard/trending",  "tab.trending"),
        ("spheres",    "/dashboard/spheres",   "tab.spheres"),
        ("health",     "/dashboard/health",    "tab.health"),
    ]
    parts = []
    for key, url, t_key in tabs:
        active_cls = " active" if key == active else ""
        parts.append(
            f'<a href="{url}?lang={lang}" class="nav-tab{active_cls}">'
            f'{_escape(t(t_key, lang))}</a>'
        )
    return '<nav class="flex flex-wrap gap-2">' + "".join(parts) + "</nav>"


_BASE_STYLES = """
    :root {
      --primary: #14b8a6;
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
    * { box-sizing: border-box; }
    body {
      font-family: 'Inter', -apple-system, system-ui, sans-serif;
      background: var(--bg); color: var(--text);
      min-height: 100vh; overflow-x: hidden; margin: 0;
    }
    .ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; }
    .orb { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18;
           animation: orb-float 16s ease-in-out infinite alternate; }
    .orb-1 { background: var(--primary);     width: 600px; height: 600px; top: -200px; left: -200px; }
    .orb-2 { background: var(--accent-rose); width: 500px; height: 500px; bottom: -150px; right: -150px; animation-delay: 4s; }
    .orb-3 { background: var(--accent-amber);width: 350px; height: 350px; top: 40%; left: 50%; opacity: 0.1; animation-delay: 7s; }
    @keyframes orb-float {
      0%   { transform: translate(0,0) scale(1); }
      50%  { transform: translate(30px,-40px) scale(1.05); }
      100% { transform: translate(-20px,20px) scale(0.97); }
    }
    .echolot-logo {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 0.85rem; color: var(--primary);
      letter-spacing: 0.3em; opacity: 0.9;
    }
    .echolot-title {
      font-weight: 800; letter-spacing: -0.03em;
      background: linear-gradient(135deg, #14b8a6, #06b6d4, #3b82f6);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text; color: transparent;
    }
    .header-bar {
      position: relative; z-index: 10;
      border-bottom: 1px solid var(--border);
      background: rgba(5, 6, 8, 0.7); backdrop-filter: blur(10px);
    }
    .nav-tab {
      padding: 0.4rem 0.85rem; border-radius: 999px; font-size: 0.78rem;
      text-decoration: none; color: var(--text-dim);
      border: 1px solid transparent; transition: all 0.18s;
    }
    .nav-tab:hover { background: rgba(255,255,255,0.04); color: var(--text); }
    .nav-tab.active {
      background: var(--primary-dim); color: var(--primary);
      border-color: rgba(20,184,166,0.3);
    }
    .lang-select {
      background: rgba(255,255,255,0.04); color: var(--text);
      border: 1px solid var(--border); border-radius: 6px;
      padding: 0.3rem 0.5rem; font-size: 0.78rem; font-family: inherit;
    }
    .card {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 12px; padding: 1rem 1.1rem;
      transition: border-color 0.2s, transform 0.15s;
      text-decoration: none; color: inherit; display: block;
    }
    .card:hover { border-color: rgba(20,184,166,0.25); transform: translateY(-1px); }
    .card-mono { font-family: 'JetBrains Mono', ui-monospace, monospace;
                 color: var(--primary); font-size: 0.85rem; }
    .pill {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 0.62rem; text-transform: uppercase;
      padding: 0.15rem 0.45rem; border-radius: 999px; letter-spacing: 0.05em;
    }
    .lean-left       { color: #93c5fd; }
    .lean-right      { color: #fca5a5; }
    .lean-center     { color: #d1d5db; }
    .lean-analytical { color: #fde68a; }
    .lean-gov        { color: #c4b5fd; }
    .lean-opposition { color: #f9a8d4; }
    .lean-unknown    { color: #9ca3af; }
    .trust-1 { background: rgba(6, 78, 59, 0.6); color: #6ee7b7; }
    .trust-2 { background: rgba(30, 58, 138, 0.5); color: #93c5fd; }
    .trust-3 { background: rgba(124, 45, 18, 0.5); color: #fdba74; }
    .status-green  { background: rgba(6, 78, 59, 0.6);  color: #6ee7b7; }
    .status-yellow { background: rgba(120, 53, 15, 0.6); color: #fcd34d; }
    .status-red    { background: rgba(127, 29, 29, 0.6); color: #fca5a5; }
    .input {
      background: rgba(255,255,255,0.04); color: var(--text);
      border: 1px solid var(--border); border-radius: 8px;
      padding: 0.6rem 0.85rem; font-size: 0.92rem; font-family: inherit;
    }
    .input:focus { outline: none; border-color: var(--primary); }
    .btn-primary {
      background: var(--primary); color: #042821; font-weight: 600;
      padding: 0.6rem 1.2rem; border-radius: 8px; border: none;
      cursor: pointer; font-family: inherit; font-size: 0.92rem;
    }
    .btn-primary:hover { background: #0ea5a3; }
    a { color: var(--text); }
    a:hover { color: var(--primary); }
    .htmx-indicator { display: none; }
    .htmx-request .htmx-indicator { display: inline; }
"""


def _page_shell(
    lang: str,
    active_tab: str,
    body_html: str,
    request=None,
    seo_path: str | None = None,
    seo_description: str | None = None,
    seo_og_title: str | None = None,
) -> str:
    """Wrap a body in the standard dashboard chrome (header, nav, footer).

    If `request` and `seo_path` are provided, inject a full SEO <head>
    block (meta description, canonical, hreflang alternates, Open Graph,
    Twitter Card).
    """
    seo_head = ""
    if request is not None and seo_path is not None:
        origin = public_origin(request)
        desc = seo_description or t("seo.site.description", lang)
        og_title = seo_og_title or f"Echolot — {t('site.title', lang)}"
        seo_head = seo_head_html(
            origin=origin, lang=lang, path=seo_path,
            description=desc, og_title=og_title,
        )
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(t('site.title', lang))}</title>
  {seo_head}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <style>{_BASE_STYLES}</style>
</head>
<body>
  <div class="ambient" aria-hidden="true">
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>
  </div>

  <header class="header-bar sticky top-0">
    <div class="max-w-7xl mx-auto px-4 py-4">
      <div class="flex items-start justify-between gap-4 flex-wrap">
        <a href="/?lang={lang}" class="block no-underline">
          <div class="echolot-logo">ECHOLOT</div>
          <h1 class="echolot-title text-2xl md:text-3xl mt-1">{_escape(t('site.title', lang))}</h1>
          <p class="text-sm text-[color:var(--text-dim)] mt-1 max-w-xl">{_escape(t('site.subtitle', lang))}</p>
        </a>
        <div class="lang-selector-wrap">
          {_lang_selector_html(lang)}
        </div>
      </div>
      <div class="mt-4">
        {_nav_html(lang, active_tab)}
      </div>
    </div>
  </header>

  <main class="relative z-1 max-w-7xl mx-auto px-4 py-8">
    {body_html}
  </main>

  <footer class="relative z-1 border-t border-[color:var(--border)] mt-16 py-8 text-center text-xs text-[color:var(--text-dim)]">
    <p class="max-w-2xl mx-auto px-4">{_escape(t('footer.about', lang))}</p>
    <p class="mt-3">
      <a href="/landing-legacy" class="opacity-70 hover:opacity-100">Old view</a>
    </p>
  </footer>
</body>
</html>"""


def render_dashboard(request) -> tuple[str, str]:
    """Return (html, lang) for the main page (= divergence tab).

    If ?query=... is set in the URL (e.g. when the user submits the
    search form on the landing page), trigger an automatic search on
    page load — saves a click and supports shareable links.
    """
    lang = _request_lang(request)
    query = (request.query_params.get("query") or "").strip()
    try:
        days = max(1, min(21, int(request.query_params.get("days") or 3)))
    except ValueError:
        days = 3

    if query:
        # HTMX trigger="load" → fires the divergence partial immediately on render
        results_block = f"""
        <div id="results"
             hx-get="/dashboard/divergence?query={quote(query)}&days={days}&lang={lang}"
             hx-trigger="load"
             hx-swap="innerHTML">
          <p class="text-sm text-[color:var(--text-dim)]">⏳ {_escape(t('msg.loading', lang))}</p>
        </div>
        """
    else:
        results_block = f'<div id="results"><p class="text-sm text-[color:var(--text-dim)]">{_escape(t("msg.empty_query", lang))}</p></div>'

    body = f"""
    <form hx-get="/dashboard/divergence"
          hx-target="#results"
          hx-indicator="#search-spinner"
          hx-include="[name='lang']"
          class="mb-6">
      <input type="hidden" name="lang" value="{lang}">
      <div class="flex gap-2 flex-wrap">
        <input type="text" name="query" required
               value="{_escape(query)}"
               placeholder="{_escape(t('search.placeholder', lang))}"
               class="input flex-1 min-w-[240px]">
        <input type="number" name="days" value="{days}" min="1" max="21"
               title="{_escape(t('search.days_label', lang))}"
               class="input w-20">
        <button type="submit" class="btn-primary">
          {_escape(t('search.button', lang))}
          <span id="search-spinner" class="htmx-indicator ml-2">…</span>
        </button>
      </div>
    </form>

    {results_block}
    """
    return _page_shell(lang, "divergence", body, request=request,
                       seo_path="/dashboard"), lang


def render_spheres_page(request, conn_factory) -> tuple[str, str]:
    """Sphere browser — list every sphere with article-count + sample sources.
    Cards link to /dashboard/sphere/<name> for the full feed.
    """
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
          <a href="/dashboard/sphere/{quote(sphere)}?lang={lang}" class="card">
            <div class="card-mono">{_escape(sphere)}</div>
            <div class="text-xs text-[color:var(--text-dim)] mt-2 flex items-center gap-2 flex-wrap">
              <span>{r['article_count']} cikk</span>
              <span class="opacity-50">·</span>
              <span>{r['source_count']} forrás</span>
              <span class="opacity-50">·</span>
              <span>{_escape(latest)}</span>
            </div>
          </a>""")
    body = f"""
      <h2 class="text-xl font-semibold mb-1">{_escape(t('tab.spheres', lang))}</h2>
      <p class="text-sm text-[color:var(--text-dim)] mb-5">
        {len(rows)} {_escape(t('tab.spheres', lang)).lower()}
      </p>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {''.join(cards)}
      </div>
    """
    return _page_shell(lang, "spheres", body, request=request,
                       seo_path="/dashboard/spheres",
                       seo_description=t("seo.page.spheres.description", lang)), lang


def render_sphere_detail_page(request, sphere_name: str, conn_factory) -> tuple[str, str]:
    """Single-sphere detail: recent articles + source list."""
    lang = _request_lang(request)
    # Recent articles in this sphere
    art_sql = """
        SELECT a.title, a.lead, a.url, a.source_name, a.published_at,
               a.language, s.lean, s.trust_tier
        FROM articles a
        JOIN sources s ON s.id = a.source_id, json_each(a.spheres_json) je
        WHERE je.value = ?
        ORDER BY a.published_at DESC
        LIMIT 40
    """
    src_sql = """
        SELECT s.id, s.name, s.lean, s.trust_tier, s.language,
               COUNT(a.article_id) AS n
        FROM sources s, json_each(s.spheres_json) je
        LEFT JOIN articles a ON a.source_id = s.id
        WHERE je.value = ?
        GROUP BY s.id
        ORDER BY n DESC
    """
    with conn_factory() as conn:
        articles = conn.execute(art_sql, (sphere_name,)).fetchall()
        sources = conn.execute(src_sql, (sphere_name,)).fetchall()

    art_html = []
    for a in articles:
        a = dict(a)
        lean = (a.get("lean") or "unknown").replace(" ", "_")
        trust = a.get("trust_tier") or 2
        published = (a.get("published_at") or "")[:16].replace("T", " ")
        art_html.append(f"""
          <a href="{_escape(a['url'])}" target="_blank" rel="noopener" class="card">
            <div class="flex items-center gap-2 flex-wrap text-xs mb-2">
              <span class="card-mono text-[0.7rem]">{_escape(a['source_name'] or '')}</span>
              <span class="pill trust-{trust}">T{trust}</span>
              <span class="lean-{lean} text-[0.7rem]">{_escape(lean)}</span>
              <span class="text-[color:var(--text-dim)] text-[0.7rem]">{_escape(a.get('language',''))}</span>
              <span class="text-[color:var(--text-dim)] text-[0.7rem] ml-auto">{_escape(published)}</span>
            </div>
            <div class="text-sm font-medium leading-snug">{_escape(a.get('title') or '')}</div>
            <div class="text-xs text-[color:var(--text-dim)] mt-2 line-clamp-2">{_escape((a.get('lead') or '')[:200])}</div>
          </a>""")

    src_html = []
    for s in sources:
        s = dict(s)
        lean = (s.get("lean") or "unknown").replace(" ", "_")
        src_html.append(f"""
          <li class="py-1.5 flex items-center gap-3 text-sm border-b border-[color:var(--border)]">
            <span class="flex-1">{_escape(s['name'])}</span>
            <span class="pill trust-{s.get('trust_tier', 2)}">T{s.get('trust_tier', 2)}</span>
            <span class="lean-{lean} text-[0.7rem]">{_escape(lean)}</span>
            <span class="text-[color:var(--text-dim)] text-[0.75rem] w-12 text-right">{s['n']}</span>
          </li>""")

    body = f"""
      <div class="mb-5">
        <a href="/dashboard/spheres?lang={lang}" class="text-xs text-[color:var(--text-dim)] hover:text-[color:var(--primary)]">
          ← {_escape(t('tab.spheres', lang))}
        </a>
        <h2 class="echolot-title text-2xl mt-2">{_escape(sphere_name)}</h2>
        <p class="text-sm text-[color:var(--text-dim)] mt-1">
          {len(articles)} {_escape(t('article.source', lang)).lower()} · {len(sources)} src
        </p>
      </div>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section class="lg:col-span-2">
          <h3 class="text-sm uppercase tracking-wider text-[color:var(--text-dim)] mb-3">
            {_escape(t('tab.search', lang))} → {_escape(sphere_name)}
          </h3>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            {''.join(art_html) or '<p class="text-sm text-[color:var(--text-dim)]">'+_escape(t('msg.no_results', lang))+'</p>'}
          </div>
        </section>
        <aside>
          <h3 class="text-sm uppercase tracking-wider text-[color:var(--text-dim)] mb-3">
            {_escape(t('article.source', lang))} ({len(sources)})
          </h3>
          <ul>{''.join(src_html)}</ul>
        </aside>
      </div>
    """
    sphere_desc = t("seo.page.sphere_detail.description_tpl", lang).replace("{sphere}", sphere_name)
    return _page_shell(lang, "spheres", body, request=request,
                       seo_path=f"/dashboard/sphere/{sphere_name}",
                       seo_description=sphere_desc,
                       seo_og_title=f"Echolot — {sphere_name}"), lang


def render_health_page(request, compute_health_fn, db_path) -> tuple[str, str]:
    """Sphere health page — green/yellow/red status grid."""
    lang = _request_lang(request)
    try:
        report = compute_health_fn(db_path, top_n=10)
    except Exception as exc:
        body = f'<p class="text-red-400">Error: {_escape(str(exc))}</p>'
        return _page_shell(lang, "health", body, request=request,
                           seo_path="/dashboard/health",
                           seo_description=t("seo.page.health.description", lang)), lang
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
    return _page_shell(lang, "health", body, request=request,
                       seo_path="/dashboard/health",
                       seo_description=t("seo.page.health.description", lang)), lang


def render_trending_page(request, compute_velocity_fn, db_path,
                          wiki_top_movers_fn=None,
                          google_trends_fn=None,
                          wiki_pageviews_fn=None,
                          wiki_pageviews_lang="en",
                          youtube_trends_fn=None,
                          youtube_region="HU") -> tuple[str, str]:
    """Trending sphere-velocity — which spheres are spiking now.

    Optional panels below the velocity table when those data sources
    are configured:
    - wiki_top_movers_fn:  Wikipedia top-movers (wikicorrelate DB)
    - google_trends_fn:    Google News RSS (free, country-scoped)
    - wiki_pageviews_fn:   Wikipedia daily top-pageviews (multilingual)
    - youtube_trends_fn:   YouTube Data API v3 trending videos
    """
    lang = _request_lang(request)
    try:
        report = compute_velocity_fn(db_path, window_hours=6, baseline_offset_hours=24, limit=30)
    except Exception as exc:
        body = f'<p class="text-red-400">Error: {_escape(str(exc))}</p>'
        return _page_shell(lang, "trending", body, request=request,
                           seo_path="/dashboard/trending",
                           seo_description=t("seo.page.trending.description", lang)), lang
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
    # Optional Wikipedia top-movers panel
    wiki_panel = ""
    if wiki_top_movers_fn is not None:
        try:
            data = wiki_top_movers_fn(limit=15)
        except Exception:
            data = None
        if data and data.get("results"):
            wiki_rows = []
            for r in data["results"][:15]:
                title = r.get("topic_a") or r.get("title") or r.get("topic") or "?"
                corr = r.get("correlation") or r.get("score") or 0
                pair = r.get("topic_b") or ""
                wiki_rows.append(f"""
                  <tr class="border-b border-[color:var(--border)] hover:bg-white/[0.02]">
                    <td class="py-2 text-sm">{_escape(str(title))}</td>
                    <td class="py-2 text-sm text-[color:var(--text-dim)]">{_escape(str(pair))}</td>
                    <td class="py-2 text-sm font-mono text-[color:var(--primary)]">{corr:.2f}</td>
                  </tr>""" if isinstance(corr, (int, float)) else f"""
                  <tr class="border-b border-[color:var(--border)]">
                    <td class="py-2 text-sm">{_escape(str(title))}</td>
                    <td class="py-2 text-sm">{_escape(str(pair))}</td>
                    <td class="py-2 text-sm">{_escape(str(corr))}</td>
                  </tr>""")
            wiki_panel = f"""
              <h3 class="text-lg font-semibold mt-10 mb-2">Wikipedia top-movers</h3>
              <p class="text-xs text-[color:var(--text-dim)] mb-4">
                Pageview-correlation pairs spiking right now · backed by wikicorrelate
              </p>
              <div class="overflow-x-auto">
                <table class="w-full text-left">
                  <thead class="border-b border-[color:var(--border)] text-xs uppercase text-[color:var(--text-dim)]">
                    <tr><th class="py-2">Topic</th><th class="py-2">Correlated with</th><th class="py-2">r</th></tr>
                  </thead>
                  <tbody>{''.join(wiki_rows)}</tbody>
                </table>
              </div>
            """

    # Optional Google News trending panel (free, no API key)
    google_panel = ""
    if google_trends_fn is not None:
        geo = (request.query_params.get("geo") or "HU").upper()
        try:
            items = google_trends_fn(geo=geo, limit=15)
        except Exception:
            items = []
        if items:
            g_rows = []
            for it in items:
                title = it.get("title", "")
                src = it.get("source", "")
                link = it.get("link", "")
                title_html = (
                    f'<a href="{_escape(link)}" target="_blank" rel="noopener" class="hover:text-[color:var(--primary)]">{_escape(title)}</a>'
                    if link else _escape(title)
                )
                g_rows.append(f"""
                  <tr class="border-b border-[color:var(--border)] hover:bg-white/[0.02]">
                    <td class="py-2 text-sm">{title_html}</td>
                    <td class="py-2 text-sm text-[color:var(--text-dim)]">{_escape(src)}</td>
                  </tr>""")
            google_panel = f"""
              <h3 class="text-lg font-semibold mt-10 mb-2">Google News — {_escape(geo)}</h3>
              <p class="text-xs text-[color:var(--text-dim)] mb-4">
                Top stories trending right now in {_escape(geo)} · via Google News RSS
              </p>
              <div class="overflow-x-auto">
                <table class="w-full text-left">
                  <thead class="border-b border-[color:var(--border)] text-xs uppercase text-[color:var(--text-dim)]">
                    <tr><th class="py-2">Story</th>
                        <th class="py-2">Source</th></tr>
                  </thead>
                  <tbody>{''.join(g_rows)}</tbody>
                </table>
              </div>
            """

    # Optional Wikipedia daily top-pageviews panel (multilingual)
    pageviews_panel = ""
    if wiki_pageviews_fn is not None:
        try:
            pv_items = wiki_pageviews_fn(limit=15) or []
        except Exception:
            pv_items = []
        if pv_items:
            pv_rows = []
            for it in pv_items[:15]:
                article = it.get("article", "")
                title = it.get("title", "")
                views = it.get("views", 0)
                rank = it.get("rank", "")
                wiki = it.get("wiki", f"{wiki_pageviews_lang}.wikipedia")
                wiki_url = f"https://{wiki}/wiki/{article}"
                pv_rows.append(f"""
                  <tr class="border-b border-[color:var(--border)] hover:bg-white/[0.02]">
                    <td class="py-2 text-sm text-[color:var(--text-dim)] font-mono w-12">#{rank}</td>
                    <td class="py-2 text-sm">
                      <a href="{_escape(wiki_url)}" target="_blank" rel="noopener" class="hover:text-[color:var(--primary)]">{_escape(title)}</a>
                    </td>
                    <td class="py-2 text-sm font-mono text-[color:var(--primary)] text-right">{int(views):,}</td>
                  </tr>""")
            pageviews_panel = f"""
              <h3 class="text-lg font-semibold mt-10 mb-2">Wikipedia top — {_escape(wiki_pageviews_lang)}.wikipedia</h3>
              <p class="text-xs text-[color:var(--text-dim)] mb-4">
                Most-read articles yesterday · daily pageviews via Wikimedia API
              </p>
              <div class="overflow-x-auto">
                <table class="w-full text-left">
                  <thead class="border-b border-[color:var(--border)] text-xs uppercase text-[color:var(--text-dim)]">
                    <tr><th class="py-2 w-12">#</th>
                        <th class="py-2">Article</th>
                        <th class="py-2 text-right">Views</th></tr>
                  </thead>
                  <tbody>{''.join(pv_rows)}</tbody>
                </table>
              </div>
            """

    # Optional YouTube trending videos panel
    youtube_panel = ""
    if youtube_trends_fn is not None:
        try:
            yt_items = youtube_trends_fn(region=youtube_region, count=12) or []
        except Exception:
            yt_items = []
        if yt_items:
            yt_cards = []
            for v in yt_items[:12]:
                title = v.get("title", "")
                channel = v.get("channel", "")
                url = v.get("url", "")
                thumb = v.get("thumbnail", "")
                views = v.get("views", 0)
                yt_cards.append(f"""
                  <a href="{_escape(url)}" target="_blank" rel="noopener"
                     class="card flex gap-3 items-start">
                    {'<img src="' + _escape(thumb) + '" class="w-32 rounded shrink-0" loading="lazy">' if thumb else ''}
                    <div class="flex-1 min-w-0">
                      <div class="text-sm font-medium leading-snug">{_escape(title)[:120]}</div>
                      <div class="text-xs text-[color:var(--text-dim)] mt-1">{_escape(channel)}</div>
                      <div class="text-xs font-mono text-[color:var(--primary)] mt-1">{views:,} views</div>
                    </div>
                  </a>""")
            youtube_panel = f"""
              <h3 class="text-lg font-semibold mt-10 mb-2">YouTube trending — {_escape(youtube_region)}</h3>
              <p class="text-xs text-[color:var(--text-dim)] mb-4">
                Most-popular videos right now · via YouTube Data API v3
              </p>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                {''.join(yt_cards)}
              </div>
            """

    body = f"""
      <h2 class="text-lg font-semibold mb-1">{_escape(t('tab.trending', lang))}</h2>
      <p class="text-xs text-[color:var(--text-dim)] mb-4">
        {report.get('window_hours', 6)}h vs {report.get('baseline_window', '?')}
      </p>
      <div class="overflow-x-auto">
        <table class="w-full text-left">
          <thead class="border-b border-[color:var(--border)] text-xs uppercase text-[color:var(--text-dim)]">
            <tr><th class="py-2">{_escape(t('tab.spheres', lang))}</th>
                <th class="py-2">current</th>
                <th class="py-2">baseline</th>
                <th class="py-2">ratio</th>
                <th class="py-2">status</th></tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
      {google_panel}
      {pageviews_panel}
      {youtube_panel}
      {wiki_panel}
    """
    return _page_shell(lang, "trending", body, request=request,
                       seo_path="/dashboard/trending",
                       seo_description=t("seo.page.trending.description", lang)), lang


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
