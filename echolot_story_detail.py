"""Story detail page: same-site /story/<cluster_id> view.

A felhasználó a főoldali sztori-kártyára kattintva NE menjen el az
oldalról — ehelyett egy saját dizájnú lap nyíljon, ami felsorolja az
adott cluster MINDEN forrását (cikk-cím, lead, source-név, lean badge,
publikálási idő, link az eredeti cikkre).

A cluster_id stabil: a cluster legkisebb article_id-jának első 12
karaktere ("a" prefix-szel) — lásd echolot_top_stories._aggregate_cluster.
"""
from __future__ import annotations

from datetime import datetime, timezone

from echolot_dashboard import _BASE_STYLES, _augment_strip_css, _escape
from echolot_i18n import t
from echolot_landing_v2 import (
    _LANDING_V2_EXTRA_CSS,
    _fmt_age,
    _render_pol_bar,
    _render_source_stack,
    _sphere_color,
)
from echolot_seo import public_origin


# ─── Idő-formátum: "4 órája (06:12)" stílus ──────────────────────────────

def _fmt_clock(dt: datetime) -> str:
    """Helyi-idő HH:MM (ha ma) vagy MM-DD HH:MM (ha régebbi)."""
    now_local = datetime.now()
    if dt.tzinfo is not None:
        dt_local = dt.astimezone()
    else:
        dt_local = dt
    if dt_local.date() == now_local.date():
        return dt_local.strftime("%H:%M")
    if dt_local.year == now_local.year:
        return dt_local.strftime("%m-%d %H:%M")
    return dt_local.strftime("%Y-%m-%d %H:%M")


def _fmt_combined(ts: str | None) -> str:
    """'4 órája (06:12)' — relatív és abszolút együtt. Üres string ha nincs ts."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return ""
    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
    rel = _fmt_age(dt, now)
    abs_str = _fmt_clock(dt)
    return f"{rel} ({abs_str})"


# ─── Lean badge ──────────────────────────────────────────────────────────

_LEAN_LABEL = {
    "left": "B",
    "lean_left": "B",
    "center": "K",
    "lean_right": "J",
    "right": "J",
    "government": "K+",
}
_LEAN_COLOR = {
    "left": "var(--pol-l, #c25a5a)",
    "lean_left": "var(--pol-l, #c25a5a)",
    "center": "var(--pol-c, #8e8e8e)",
    "lean_right": "var(--pol-r, #4d7ec8)",
    "right": "var(--pol-r, #4d7ec8)",
    "government": "var(--pol-g, #b48a3a)",
}


_ORIG_LBL = {
    "hu": "Eredeti cikk", "en": "Original article", "de": "Originalartikel",
    "fr": "Article original", "ru": "Оригинал статьи", "uk": "Оригінал статті",
}


def _orig_label(lang: str) -> str:
    return _ORIG_LBL.get(lang, _ORIG_LBL["hu"])


def _render_lean_badge(lean: str | None) -> str:
    if not lean:
        return ""
    key = (lean or "").strip().lower().replace("-", "_")
    label = _LEAN_LABEL.get(key, "")
    color = _LEAN_COLOR.get(key, "var(--fg-3)")
    if not label:
        return ""
    return f'<span class="lean-badge" style="background:{color}" title="{_escape(lean)}">{label}</span>'


# ─── Source-card a listához ─────────────────────────────────────────────

def _render_source_card(article: dict, lang: str) -> str:
    title = article.get("title") or ""
    lead = (article.get("lead") or "").strip()
    url = article.get("url") or "#"
    src_name = article.get("source_name") or article.get("source_id") or ""
    lean = article.get("source_lean") or ""
    ts = article.get("published_at") or ""
    ts_combined = _fmt_combined(ts)

    lead_html = (
        f'<p class="src-card-lead">{_escape(lead)}</p>' if lead else ""
    )
    return f"""
      <article class="src-card">
        <header class="src-card-head">
          {_render_lean_badge(lean)}
          <span class="src-card-name">{_escape(src_name)}</span>
          <time class="src-card-time" datetime="{_escape(ts)}">{_escape(ts_combined)}</time>
        </header>
        <h3 class="src-card-title">{_escape(title)}</h3>
        {lead_html}
        <a href="{_escape(url)}" target="_blank" rel="noopener" class="src-card-link">
          {_escape(_orig_label(lang))} ↗
        </a>
      </article>
    """


# ─── Oldal-specifikus CSS ───────────────────────────────────────────────

_STORY_DETAIL_CSS = """
    .story-detail-shell {
      max-width: 920px;
      margin: 24px auto 80px;
      padding: 0 var(--sp-4);
    }
    .story-detail-back {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--fg-2);
      font-size: 14px;
      text-decoration: none;
      margin-bottom: 16px;
      transition: color .15s ease;
    }
    .story-detail-back:hover { color: var(--text); }

    .story-detail-header {
      border-bottom: 1px solid var(--line);
      padding-bottom: var(--sp-4);
      margin-bottom: var(--sp-5);
    }
    .story-detail-meta {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 12px;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--fg-3);
    }
    .story-detail-meta .sphere-tag { font-weight: 600; }
    .story-detail-meta .src-count {
      color: var(--text);
      font-weight: 600;
      letter-spacing: 0.04em;
    }
    .story-detail-title {
      font-size: 28px;
      line-height: 1.25;
      font-weight: 700;
      color: var(--text);
      margin: 0 0 12px 0;
    }
    .story-detail-lead {
      font-size: 16px;
      line-height: 1.6;
      color: var(--fg-2);
      margin: 0 0 16px 0;
    }
    .story-detail-pol-bar { margin-bottom: 12px; }
    .story-detail-timeline {
      display: flex;
      gap: 18px;
      font-size: 13px;
      color: var(--fg-3);
      flex-wrap: wrap;
    }
    .story-detail-timeline strong {
      color: var(--text);
      font-weight: 600;
      margin-left: 4px;
    }

    .story-sources-section h2 {
      font-size: 14px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--fg-3);
      margin: 0 0 var(--sp-3) 0;
      font-weight: 600;
    }
    .src-card-list {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .src-card {
      background: var(--bg-2, rgba(255,255,255,0.02));
      border: 1px solid var(--line);
      border-radius: var(--r-md, 8px);
      padding: 16px 18px;
      transition: border-color .15s ease, background .15s ease;
    }
    .src-card:hover {
      border-color: var(--line-strong, rgba(255,255,255,0.18));
      background: var(--bg-3, rgba(255,255,255,0.04));
    }
    .src-card-head {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
      font-size: 12px;
      color: var(--fg-3);
    }
    .src-card-name {
      color: var(--text);
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    .src-card-time {
      margin-left: auto;
      color: var(--fg-3);
      font-variant-numeric: tabular-nums;
    }
    .src-card-title {
      font-size: 18px;
      line-height: 1.35;
      color: var(--text);
      margin: 0 0 8px 0;
      font-weight: 600;
    }
    .src-card-lead {
      font-size: 14px;
      line-height: 1.55;
      color: var(--fg-2);
      margin: 0 0 10px 0;
    }
    .src-card-link {
      display: inline-block;
      color: var(--accent, #6cb6ff);
      text-decoration: none;
      font-size: 13px;
      letter-spacing: 0.03em;
    }
    .src-card-link:hover { text-decoration: underline; }

    .lean-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 22px;
      height: 22px;
      padding: 0 6px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      color: #fff;
      letter-spacing: 0.04em;
    }

    @media (max-width: 720px) {
      .story-detail-title { font-size: 22px; }
      .src-card-title { font-size: 16px; }
    }
"""


# ─── Fő render fv ───────────────────────────────────────────────────────

def render_story_detail_page(cluster: dict, lang: str, request=None) -> str:
    """Visszaad egy teljes HTML-lapot egy adott cluster source-listájával."""
    title = cluster.get("title") or cluster.get("lead_title") or "?"
    lead = (cluster.get("lead_summary") or "").strip()
    bias = cluster.get("bias_dist") or {"L": 0, "C": 0, "R": 0}
    spheres = cluster.get("sphere_set") or []
    sphere = spheres[0] if spheres else ""
    accent = _sphere_color(sphere)
    n_sources = int(cluster.get("source_count") or 0)
    first_published = cluster.get("first_published") or ""
    latest_published = cluster.get("latest_published") or ""
    articles = cluster.get("articles") or []

    src_label = _escape(t("article.source", lang)).lower()
    # Story-detail oldal labelek — Kommandant kérés, magyar default;
    # később ha kell, betehető az echolot_i18n szótárba is.
    _LBL = {
        "hu": {"back": "Vissza a főoldalra", "first": "Első forrás",
               "last": "Frissítve", "sources": "Források"},
        "en": {"back": "Back to home", "first": "First source",
               "last": "Updated", "sources": "Sources"},
        "de": {"back": "Zur Startseite", "first": "Erste Quelle",
               "last": "Aktualisiert", "sources": "Quellen"},
        "fr": {"back": "Retour à l'accueil", "first": "Première source",
               "last": "Mis à jour", "sources": "Sources"},
        "ru": {"back": "Назад на главную", "first": "Первый источник",
               "last": "Обновлено", "sources": "Источники"},
        "uk": {"back": "Назад на головну", "first": "Перше джерело",
               "last": "Оновлено", "sources": "Джерела"},
    }
    lbl = _LBL.get(lang, _LBL["hu"])
    back_label = _escape(lbl["back"])
    first_label = _escape(lbl["first"])
    last_label = _escape(lbl["last"])
    sources_label = _escape(lbl["sources"])

    lead_html = f'<p class="story-detail-lead">{_escape(lead)}</p>' if lead else ""

    timeline_parts = []
    if first_published:
        timeline_parts.append(
            f'<span>↪ {first_label}:<strong>{_escape(_fmt_combined(first_published))}</strong></span>'
        )
    if latest_published and latest_published != first_published:
        timeline_parts.append(
            f'<span>⟳ {last_label}:<strong>{_escape(_fmt_combined(latest_published))}</strong></span>'
        )
    timeline_html = (
        f'<div class="story-detail-timeline">{"".join(timeline_parts)}</div>'
        if timeline_parts else ""
    )

    cards_html = "".join(_render_source_card(a, lang) for a in articles)

    title_html = _escape(title[:80])
    page_title = f"{title_html} — Echolot"

    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>{_BASE_STYLES}{_augment_strip_css()}{_LANDING_V2_EXTRA_CSS}{_STORY_DETAIL_CSS}</style>
</head>
<body>
  <main class="story-detail-shell landing-v2-shell">
    <a href="/?lang={lang}" class="story-detail-back">← {back_label}</a>

    <header class="story-detail-header">
      <div class="story-detail-meta">
        <span class="sphere-tag" style="color: {accent}">{_escape(sphere)}</span>
        <span class="source-stack">
          {_render_source_stack(n_sources)}
          <span class="src-count">{n_sources} {src_label}</span>
        </span>
      </div>
      <h1 class="story-detail-title">{_escape(title)}</h1>
      {lead_html}
      <div class="story-detail-pol-bar">{_render_pol_bar(bias)}</div>
      {timeline_html}
    </header>

    <section class="story-sources-section">
      <h2>{sources_label} ({n_sources})</h2>
      <div class="src-card-list">
        {cards_html}
      </div>
    </section>
  </main>
</body>
</html>"""
