"""Source page: same-site /source/<source_id> view.

A story-detail oldalon (echolot_story_detail) minden forrás-kártyáról
LENT az "Eredeti cikk" a konkrét külső cikkre visz — FENT viszont a
forrás nevére / "Forrás összes híre" linkre kattintva ide jutunk: egy
gyűjtőoldal, ami az adott FORRÁS (pl. Telex, 24.hu, Financial Times)
híreit listázza egy konfigurálható időablakban (1 / 3 / 7 nap).

Mintaadó: a Hírkereső "forrás-doboza", ami egy orgánum aznapi híreit
sorolja fel. Itt ugyanaz, de a mi dizájnunkkal és időablak-választóval.
"""
from __future__ import annotations

import sqlite3

from echolot_dashboard import _BASE_STYLES, _augment_strip_css, _escape
from echolot_landing_v2 import _LANDING_V2_EXTRA_CSS, _sphere_color
from echolot_theme import (
    theme_html_attr,
    DAY_THEME_CSS,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_JS,
    theme_toggle_html,
)
from echolot_story_detail import (
    _STORY_DETAIL_CSS,
    _fmt_combined,
    _orig_label,
    _render_lean_badge,
)

# Engedélyezett időablakok (nap). Az URL ?days= paramétere ezekre szűkül.
SOURCE_WINDOW_DAYS = (1, 3, 7)
DEFAULT_WINDOW_DAYS = 1
MAX_ARTICLES = 200


# ─── Adat-lekérdezés ─────────────────────────────────────────────────────

def query_source(db_path: str, source_id: str) -> dict | None:
    """Forrás meta-adat a sources táblából. None ha nincs ilyen id."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT id, name, url, language, lean, category, spheres_json "
            "FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    return dict(row)


def query_source_articles(db_path: str, source_id: str, days: int) -> list[dict]:
    """A forrás cikkei az utolsó `days` napból, publikálás szerint csökkenő.

    A `julianday` helyesen parse-olja a vegyes-időzónás ISO published_at
    értékeket (offset → UTC), így az időablak megbízható.
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT title, lead, url, published_at, category, spheres_json "
            "FROM articles "
            "WHERE source_id = ? "
            "  AND published_at IS NOT NULL "
            "  AND julianday('now') - julianday(published_at) <= ? "
            "ORDER BY published_at DESC "
            "LIMIT ?",
            (source_id, days, MAX_ARTICLES),
        ).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


# ─── Oldal-specifikus CSS ───────────────────────────────────────────────

_SOURCE_PAGE_CSS = """
    .source-page-head {
      border-bottom: 1px solid var(--line);
      padding-bottom: var(--sp-4);
      margin-bottom: var(--sp-4);
    }
    .source-page-eyebrow {
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--fg-3);
      margin-bottom: 10px;
    }
    .source-page-titlerow {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .source-page-name {
      font-size: 28px;
      line-height: 1.2;
      font-weight: 700;
      color: var(--text);
      margin: 0;
    }
    .source-page-home {
      color: var(--fg-3);
      font-size: 13px;
      text-decoration: none;
      letter-spacing: 0.02em;
    }
    .source-page-home:hover { color: var(--text); text-decoration: underline; }

    .source-window {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 16px 0 4px;
      flex-wrap: wrap;
    }
    .source-window-label {
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--fg-3);
      margin-right: 4px;
    }
    .source-window a {
      display: inline-block;
      padding: 5px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      font-size: 13px;
      color: var(--fg-2);
      text-decoration: none;
      transition: border-color .15s ease, color .15s ease, background .15s ease;
    }
    .source-window a:hover {
      border-color: var(--line-strong, rgba(255,255,255,0.18));
      color: var(--text);
    }
    .source-window a.is-active {
      background: var(--accent, #6cb6ff);
      border-color: var(--accent, #6cb6ff);
      color: #08121e;
      font-weight: 600;
    }

    .source-empty {
      color: var(--fg-3);
      font-size: 15px;
      padding: 28px 0;
      text-align: center;
    }
"""


# ─── Címkék ─────────────────────────────────────────────────────────────

_LBL = {
    "hu": {"back": "Vissza a főoldalra", "eyebrow": "Forrás", "window": "Időablak",
           "day": "nap", "visit": "Forrás weboldala", "empty": "Nincs hír ebben az időablakban.",
           "count": "hír"},
    "en": {"back": "Back to home", "eyebrow": "Source", "window": "Time window",
           "day": "day(s)", "visit": "Source website", "empty": "No articles in this window.",
           "count": "articles"},
    "de": {"back": "Zur Startseite", "eyebrow": "Quelle", "window": "Zeitfenster",
           "day": "Tag(e)", "visit": "Webseite der Quelle", "empty": "Keine Artikel in diesem Fenster.",
           "count": "Artikel"},
    "fr": {"back": "Retour à l'accueil", "eyebrow": "Source", "window": "Fenêtre",
           "day": "jour(s)", "visit": "Site de la source", "empty": "Aucun article dans cette fenêtre.",
           "count": "articles"},
    "ru": {"back": "На главную", "eyebrow": "Источник", "window": "Период",
           "day": "дн.", "visit": "Сайт источника", "empty": "Нет статей за этот период.",
           "count": "статей"},
    "uk": {"back": "На головну", "eyebrow": "Джерело", "window": "Період",
           "day": "дн.", "visit": "Сайт джерела", "empty": "Немає статей за цей період.",
           "count": "статей"},
}


def _lbl(lang: str) -> dict:
    return _LBL.get(lang, _LBL["hu"])


# ─── Cikk-kártya (a story-oldal .src-card stílusát újrahasználva) ────────

def _render_article_card(article: dict, lang: str) -> str:
    title = article.get("title") or ""
    lead = (article.get("lead") or "").strip()
    url = article.get("url") or "#"
    ts = article.get("published_at") or ""
    ts_combined = _fmt_combined(ts)

    lead_html = f'<p class="src-card-lead">{_escape(lead)}</p>' if lead else ""
    return f"""
      <article class="src-card">
        <header class="src-card-head">
          <time class="src-card-time" datetime="{_escape(ts)}">{_escape(ts_combined)}</time>
        </header>
        <h3 class="src-card-title">{_escape(title)}</h3>
        {lead_html}
        <a href="{_escape(url)}" target="_blank" rel="noopener" class="src-card-link">
          {_escape(_orig_label(lang))} ↗
        </a>
      </article>
    """


# ─── Időablak-választó ───────────────────────────────────────────────────

def _render_window_selector(source_id: str, days: int, lang: str) -> str:
    lbl = _lbl(lang)
    links = []
    for d in SOURCE_WINDOW_DAYS:
        cls = "is-active" if d == days else ""
        href = f"/source/{_escape(source_id)}?days={d}&lang={lang}"
        links.append(f'<a href="{href}" class="{cls}">{d} {_escape(lbl["day"])}</a>')
    return (
        f'<div class="source-window">'
        f'<span class="source-window-label">{_escape(lbl["window"])}</span>'
        f'{"".join(links)}</div>'
    )


# ─── Fő render fv ───────────────────────────────────────────────────────

def render_source_page(
    source: dict, articles: list[dict], days: int, lang: str, request=None
) -> str:
    """Teljes HTML-lap egy forrás híreivel az adott időablakban."""
    lbl = _lbl(lang)
    source_id = source.get("id") or ""
    name = source.get("name") or source_id
    site_url = source.get("url") or ""
    lean = source.get("lean") or ""

    spheres = []
    sj = source.get("spheres_json")
    if sj:
        try:
            import json
            spheres = json.loads(sj) or []
        except (ValueError, TypeError):
            spheres = []
    sphere = spheres[0] if spheres else ""
    accent = _sphere_color(sphere) if sphere else "var(--accent, #6cb6ff)"

    home_link = (
        f'<a href="{_escape(site_url)}" target="_blank" rel="noopener" '
        f'class="source-page-home">{_escape(lbl["visit"])} ↗</a>'
        if site_url else ""
    )

    selector_html = _render_window_selector(source_id, days, lang)

    if articles:
        cards_html = "".join(_render_article_card(a, lang) for a in articles)
        body_html = f'<div class="src-card-list">{cards_html}</div>'
    else:
        body_html = f'<div class="source-empty">{_escape(lbl["empty"])}</div>'

    n = len(articles)
    count_html = f'<span class="src-count">{n} {_escape(lbl["count"])}</span>'

    page_title = f"{_escape(name[:60])} — Echolot"
    theme_attr = theme_html_attr(request)
    theme_toggle = theme_toggle_html(lang)

    return f"""<!doctype html>
<html lang="{lang}"{theme_attr}>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>{_BASE_STYLES}{_augment_strip_css()}{_LANDING_V2_EXTRA_CSS}{_STORY_DETAIL_CSS}{_SOURCE_PAGE_CSS}{DAY_THEME_CSS}{THEME_TOGGLE_CSS}</style>
</head>
<body>
  <main class="story-detail-shell landing-v2-shell">
    <div class="story-detail-topbar">
      <a href="/?lang={lang}" class="story-detail-back">← {_escape(lbl["back"])}</a>
      {theme_toggle}
    </div>

    <header class="source-page-head">
      <div class="source-page-eyebrow" style="color: {accent}">
        {_escape(lbl["eyebrow"])}{(" · " + _escape(sphere)) if sphere else ""}
      </div>
      <div class="source-page-titlerow">
        {_render_lean_badge(lean)}
        <h1 class="source-page-name">{_escape(name)}</h1>
        {home_link}
      </div>
      {selector_html}
      <div class="story-detail-meta" style="margin-top:10px">{count_html}</div>
    </header>

    <section class="story-sources-section">
      {body_html}
    </section>
  </main>
  {THEME_TOGGLE_JS}
</body>
</html>"""
