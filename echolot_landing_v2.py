"""Echolot új főoldal — Ground News-szerű layout, mi-dizájnunkkal.

A 2026-05-15 plan_ground_news_layout.md alapján. 4 panel:
  1. Entity-trending chip-row (felső, kb. 15 entity 24h)
  2. Top Stories (közép-bal, ~6-8 cluster bias-bárral)
  3. Helyi Trending (közép, lang-aware Wiki+GoogleNews+sphere-velocity)
  4. Blindspot panel (jobb oldal, politikai + geo aszimmetria)

Plus: a meglévő hero (lokalizált), nav-strip a régi lapokra
(/dashboard, /dashboard/trending, /dashboard/spheres, /dashboard/health,
/landing-legacy), 10-nyelvű lang-selector.

Mi-dizájnunkat tartja: --bg / --primary cyan / JetBrains Mono logo /
ambient orbök.
"""
from __future__ import annotations

import asyncio
import html as _html
import logging

from echolot_i18n import t
from echolot_dashboard import (
    _BASE_STYLES,
    _augment_block_html,
    _request_lang,
    _escape,
)
from echolot_seo import public_origin, seo_head_html
from echolot_local_trending import build_local_trending
from echolot_top_stories import cluster_top_stories
from echolot_blindspot import find_political_blindspots, find_geo_blindspots
from echolot_entity_trending import top_entities_24h

log = logging.getLogger("echolot.landing_v2")


# ── Render helpers ────────────────────────────────────────────────────

def _render_entity_chip_row(entities: list[dict], lang: str) -> str:
    """A felső chip-row entity-trending. Klikkre /dashboard?query=NAME."""
    if not entities:
        return ""
    chips = []
    for e in entities[:15]:
        name = e.get("name") or ""
        if not name:
            continue
        cnt = e.get("article_count", 0)
        href = f"/dashboard?query={_html.escape(name, quote=True)}&lang={lang}"
        chips.append(
            f'<a href="{href}" class="entity-chip" title="{cnt} {_escape(t("landing.stat.fresh_articles", lang))}">'
            f'{_escape(name)}<span class="n">{cnt}</span></a>'
        )
    if not chips:
        return ""
    return f"""
      <div class="entity-row">
        <div class="entity-row-label">📈 {_escape(t('group.world', lang))} · 24h</div>
        <div class="entity-chips">{''.join(chips)}</div>
      </div>
    """


def _render_bias_bar(bias: dict) -> str:
    """L/C/R % bias-bar (Ground News-stílus)."""
    L = int(bias.get("L", 0))
    C = int(bias.get("C", 0))
    R = int(bias.get("R", 0))
    return f"""
      <div class="bias-bar" title="L {L}% · C {C}% · R {R}%">
        <div class="bias-l" style="width:{L}%">L {L}%</div>
        <div class="bias-c" style="width:{C}%">C {C}%</div>
        <div class="bias-r" style="width:{R}%">R {R}%</div>
      </div>
    """


def _render_top_stories(stories: list[dict], lang: str) -> str:
    """Top Stories cluster lista — hero-card + 2-col grid.

    Az ELSŐ cluster (legtöbb-source) nagy hero-kártyaként renderelődik,
    a maradék 5-7 cluster egy 2-oszlopos CSS grid-ben alatta.
    """
    if not stories:
        return f'<div class="empty">{_escape(t("landing.empty_panel", lang))}</div>'

    src_label = _escape(t("article.source", lang)).lower()

    # Hero — stories[0]
    hero = stories[0]
    h_title = hero.get("lead_title") or (hero.get("sample_titles") or [""])[0] or "?"
    h_url = hero.get("lead_url") or "#"
    h_n = hero.get("source_count", 0)
    h_bias = hero.get("bias_dist", {"L": 0, "C": 0, "R": 0})
    h_spheres = hero.get("sphere_set") or []
    h_sphere = h_spheres[0] if h_spheres else ""
    hero_html = f"""
      <a href="{_escape(h_url)}" target="_blank" rel="noopener" class="story-hero">
        <div class="story-meta">
          <span class="story-sphere">{_escape(h_sphere)}</span>
          <span class="story-sources"><strong>{h_n}</strong> {src_label}</span>
        </div>
        <div class="story-title">{_escape(h_title)}</div>
        {_render_bias_bar(h_bias)}
      </a>
    """

    # Grid — stories[1:13] (max 12 a hero alatt 2-oszlopos gridben)
    cards = []
    for s in stories[1:13]:
        title = s.get("lead_title") or (s.get("sample_titles") or [""])[0] or "?"
        url = s.get("lead_url") or "#"
        n_sources = s.get("source_count", 0)
        bias = s.get("bias_dist", {"L": 0, "C": 0, "R": 0})
        spheres = s.get("sphere_set") or []
        sphere_tag = spheres[0] if spheres else ""
        cards.append(f"""
          <a href="{_escape(url)}" target="_blank" rel="noopener" class="story-card">
            <div class="story-meta">
              <span class="story-sphere">{_escape(sphere_tag)}</span>
              <span class="story-sources">{n_sources} {src_label}</span>
            </div>
            <div class="story-title">{_escape(title)}</div>
            {_render_bias_bar(bias)}
          </a>
        """)
    grid_html = f'<div class="story-grid">{"".join(cards)}</div>' if cards else ""
    return hero_html + grid_html


def _render_local_trending(local: dict, lang: str) -> str:
    """Helyi trending blokk — Wiki + Google News + sphere-velocity."""
    geo = local.get("geo", {})
    wiki_geo = geo.get("wiki", "?")
    gnews_geo = geo.get("gnews", "?")

    # Wikipedia top — backend visszaad {"results": [...], "error"?: ...}
    wiki_results = (local.get("wiki") or {}).get("results", []) if isinstance(local.get("wiki"), dict) else (local.get("wiki") or [])
    wiki_items = []
    for w in (wiki_results or [])[:8]:
        title = w.get("title") or w.get("article") or ""
        url = w.get("wiki_url") or "#"
        views = w.get("views", 0)
        wiki_items.append(
            f'<li><a href="{_escape(url)}" target="_blank" rel="noopener">{_escape(title)}</a>'
            f'<span class="n">{int(views):,}</span></li>'
        )

    # Google News — same dict-with-results shape
    gnews_results = (local.get("gnews") or {}).get("results", []) if isinstance(local.get("gnews"), dict) else (local.get("gnews") or [])
    gnews_items = []
    for g in (gnews_results or [])[:8]:
        title = g.get("title") or ""
        url = g.get("link") or "#"
        src = g.get("source") or ""
        gnews_items.append(
            f'<li><a href="{_escape(url)}" target="_blank" rel="noopener">{_escape(title)}</a>'
            f'<span class="src">{_escape(src)}</span></li>'
        )

    # Sphere velocity — backend wraps in {"results": [...]} or {"spheres": [...]}
    vel_blob = local.get("velocity") or {}
    if isinstance(vel_blob, dict):
        vel_results = vel_blob.get("results") or vel_blob.get("spheres") or []
    else:
        vel_results = vel_blob or []
    vel_items = []
    for v in (vel_results or [])[:6]:
        sphere = v.get("sphere") or ""
        ratio = v.get("velocity_ratio")
        ratio_s = f"{ratio:.1f}×" if ratio is not None else "—"
        status = v.get("status", "normal")
        vel_items.append(
            f'<li><a href="/dashboard/sphere/{_escape(sphere)}?lang={lang}">'
            f'{_escape(sphere)}</a><span class="ratio status-{status}">{ratio_s}</span></li>'
        )

    return f"""
      <div class="local-block">
        <h3>📈 Wikipedia ({_escape(wiki_geo)}.wikipedia)</h3>
        <ul class="local-list">{''.join(wiki_items) or '<li class="empty">—</li>'}</ul>
      </div>
      <div class="local-block">
        <h3>📰 Google News ({_escape(gnews_geo)})</h3>
        <ul class="local-list">{''.join(gnews_items) or '<li class="empty">—</li>'}</ul>
      </div>
      <div class="local-block">
        <h3>🔥 {_escape(t('tab.spheres', lang))} velocity</h3>
        <ul class="local-list">{''.join(vel_items) or '<li class="empty">—</li>'}</ul>
      </div>
    """


def _render_bias_legend(lang: str) -> str:
    """Bias-bar magyarázó legend — L/C/R swatch + hover-info."""
    label = _escape(t("landing.bias.label", lang))
    lbl_l = _escape(t("landing.bias.left", lang))
    lbl_c = _escape(t("landing.bias.center", lang))
    lbl_r = _escape(t("landing.bias.right", lang))
    help_text = _escape(t("landing.bias.help", lang))
    return f"""
      <div class="bias-legend">
        <span class="bias-legend-label">{label}</span>
        <span class="bias-legend-item"><span class="bias-legend-swatch l"></span>{lbl_l} (L)</span>
        <span class="bias-legend-item"><span class="bias-legend-swatch c"></span>{lbl_c} (C)</span>
        <span class="bias-legend-item"><span class="bias-legend-swatch r"></span>{lbl_r} (R)</span>
        <span class="bias-legend-help" title="{help_text}">?</span>
      </div>
    """


def _render_blindspots(political: list[dict], geo: list[dict], lang: str) -> str:
    """Blindspot panel — politikai + geo aszimmetria."""
    cards = []
    for p in political[:3]:
        title = p.get("lead_title") or (p.get("sample_titles") or [""])[0] or "?"
        url = p.get("lead_url") or "#"
        bias = p.get("bias_dist", {})
        side = p.get("dominant_side", "?")
        side_label = "Right blindspot" if side == "R" else "Left blindspot"
        side_class = "blindspot-r" if side == "R" else "blindspot-l"
        cards.append(f"""
          <a href="{_escape(url)}" target="_blank" rel="noopener" class="blindspot-card {side_class}">
            <div class="blindspot-tag">{side_label}</div>
            <div class="blindspot-title">{_escape(title)}</div>
            {_render_bias_bar(bias)}
            <div class="blindspot-meta">{p.get('source_count', 0)} {_escape(t('article.source', lang)).lower()}</div>
          </a>
        """)
    for g in geo[:2]:
        title = g.get("lead_title") or (g.get("sample_titles") or [""])[0] or "?"
        url = g.get("lead_url") or "#"
        dom = g.get("dominant_geo") or "?"
        cards.append(f"""
          <a href="{_escape(url)}" target="_blank" rel="noopener" class="blindspot-card blindspot-geo">
            <div class="blindspot-tag">Geo blindspot · only {_escape(dom)}</div>
            <div class="blindspot-title">{_escape(title)}</div>
            <div class="blindspot-meta">{g.get('source_count', 0)} {_escape(t('article.source', lang)).lower()}</div>
          </a>
        """)
    if not cards:
        return f'<div class="empty">{_escape(t("msg.no_results", lang))}</div>'
    return "".join(cards)


# ── Stylesheet az új blokkokhoz ───────────────────────────────────────

_LANDING_V2_EXTRA_CSS = """
    .entity-row {
      max-width: 1280px; margin: 1.2rem auto 0; padding: 0 1rem;
      display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
    }
    .entity-row-label {
      font-family: 'JetBrains Mono', monospace; font-size: 0.7rem;
      color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.15em;
    }
    .entity-chips { display: flex; gap: 0.4rem; flex-wrap: wrap; }
    .entity-chip {
      display: inline-flex; align-items: center; gap: 0.35rem;
      padding: 0.3rem 0.65rem; border-radius: 999px;
      background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
      color: var(--text); font-size: 0.78rem; text-decoration: none;
      transition: all 0.15s;
    }
    .entity-chip:hover { background: var(--primary-dim); border-color: var(--primary); color: var(--primary); }
    .entity-chip .n { font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: var(--text-dim); }

    .landing-grid {
      max-width: 1280px; margin: 1.5rem auto; padding: 0 1rem;
      display: grid; grid-template-columns: 2fr 1.2fr 1fr; gap: 1.5rem;
    }
    @media (max-width: 1024px) { .landing-grid { grid-template-columns: 1fr; } }

    .landing-col h2 {
      font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.2em;
      color: var(--text-dim); margin: 0 0 0.8rem;
      font-family: 'JetBrains Mono', monospace;
    }
    .landing-col h3 {
      font-size: 0.85rem; margin: 1.2rem 0 0.4rem; color: var(--text);
      font-weight: 600;
    }

    .story-card, .blindspot-card, .story-hero {
      display: block; text-decoration: none; color: var(--text);
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; padding: 0.85rem 1rem; margin-bottom: 0.7rem;
      transition: all 0.15s;
    }
    .story-card:hover, .blindspot-card:hover, .story-hero:hover {
      border-color: rgba(20,184,166,0.3); transform: translateY(-1px);
    }
    .story-meta {
      display: flex; justify-content: space-between; align-items: center;
      font-size: 0.65rem; color: var(--text-dim);
      font-family: 'JetBrains Mono', monospace; text-transform: uppercase;
      letter-spacing: 0.1em; margin-bottom: 0.4rem;
    }
    .story-sphere { color: var(--primary); }
    .story-title {
      font-size: 0.95rem; font-weight: 600; line-height: 1.35;
      margin-bottom: 0.5rem;
    }

    /* Hero cluster card — dupla méret, hangsúlyos cím + bias-bar */
    .story-hero {
      padding: 1.4rem 1.5rem; margin-bottom: 1rem;
      border-color: rgba(20,184,166,0.18);
    }
    .story-hero .story-meta {
      font-size: 0.72rem; margin-bottom: 0.7rem;
    }
    .story-hero .story-sources { color: var(--text); }
    .story-hero .story-sources strong {
      color: var(--primary); font-weight: 700;
      font-family: 'JetBrains Mono', monospace; font-size: 0.9rem;
    }
    .story-hero .story-title {
      font-size: 1.25rem; line-height: 1.3; margin-bottom: 0.8rem;
    }
    .story-hero .bias-bar {
      height: 24px; font-size: 0.7rem; margin-top: 0.5rem;
    }

    /* 2-col grid a hero alatt */
    .story-grid {
      display: grid; grid-template-columns: 1fr 1fr; gap: 0.7rem;
    }
    .story-grid .story-card { margin-bottom: 0; }
    @media (max-width: 600px) {
      .story-grid { grid-template-columns: 1fr; }
    }

    /* Bias-bar magyarázó legend — entity-row alatt, landing-grid felett */
    .bias-legend {
      max-width: 1280px; margin: 0.6rem auto 0; padding: 0.45rem 1rem;
      display: flex; align-items: center; gap: 0.9rem; flex-wrap: wrap;
      font-size: 0.7rem; color: var(--text-dim);
      font-family: 'JetBrains Mono', monospace;
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border); border-radius: 6px;
    }
    .bias-legend-label {
      text-transform: uppercase; letter-spacing: 0.15em;
    }
    .bias-legend-item {
      display: inline-flex; align-items: center; gap: 0.35rem;
    }
    .bias-legend-swatch {
      display: inline-block; width: 14px; height: 14px; border-radius: 3px;
    }
    .bias-legend-swatch.l { background: #b91c1c; }
    .bias-legend-swatch.c { background: #57534e; }
    .bias-legend-swatch.r { background: #1d4ed8; }
    .bias-legend-help {
      margin-left: auto; cursor: help; color: var(--text-dim);
      width: 18px; height: 18px; border: 1px solid var(--border);
      border-radius: 50%; display: inline-flex; align-items: center;
      justify-content: center; font-size: 0.7rem;
    }
    .bias-legend-help:hover { color: var(--primary); border-color: var(--primary); }

    .bias-bar {
      display: flex; height: 18px; border-radius: 4px; overflow: hidden;
      font-size: 0.55rem; font-family: 'JetBrains Mono', monospace;
      font-weight: 600; color: rgba(255,255,255,0.95);
      margin-top: 0.3rem; background: rgba(255,255,255,0.04);
    }
    .bias-bar > div {
      display: flex; align-items: center; justify-content: center;
      min-width: 0; overflow: hidden; white-space: nowrap;
    }
    .bias-l { background: #b91c1c; }
    .bias-c { background: #57534e; color: #f5f5f4; }
    .bias-r { background: #1d4ed8; }

    .local-block { margin-bottom: 1.2rem; }
    .local-list { list-style: none; padding: 0; margin: 0; }
    .local-list li {
      display: flex; justify-content: space-between; align-items: baseline;
      gap: 0.5rem; padding: 0.4rem 0;
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }
    .local-list li a {
      color: var(--text); text-decoration: none; flex: 1; font-size: 0.85rem;
      line-height: 1.3;
    }
    .local-list li a:hover { color: var(--primary); }
    .local-list .n {
      font-family: 'JetBrains Mono', monospace; font-size: 0.7rem;
      color: var(--text-dim); white-space: nowrap;
    }
    .local-list .src { font-size: 0.7rem; color: var(--text-dim); white-space: nowrap; }
    .local-list .ratio {
      font-family: 'JetBrains Mono', monospace; font-size: 0.7rem;
      padding: 0.1rem 0.4rem; border-radius: 3px;
    }
    .local-list .status-spike { background: rgba(244,63,94,0.2); color: #fda4af; }
    .local-list .status-rising { background: rgba(245,158,11,0.2); color: #fcd34d; }
    .local-list .status-normal { color: var(--text-dim); }
    .local-list .empty { color: var(--text-dim); font-style: italic; }

    .blindspot-card.blindspot-r { border-left: 3px solid #1d4ed8; }
    .blindspot-card.blindspot-l { border-left: 3px solid #b91c1c; }
    .blindspot-card.blindspot-geo { border-left: 3px solid var(--accent-amber); }
    .blindspot-tag {
      font-family: 'JetBrains Mono', monospace; font-size: 0.6rem;
      text-transform: uppercase; letter-spacing: 0.15em;
      color: var(--text-dim); margin-bottom: 0.3rem;
    }
    .blindspot-title {
      font-size: 0.85rem; font-weight: 600; line-height: 1.35;
      margin-bottom: 0.4rem;
    }
    .blindspot-meta {
      font-size: 0.65rem; color: var(--text-dim);
      font-family: 'JetBrains Mono', monospace;
    }

    .empty { color: var(--text-dim); font-style: italic; padding: 1rem 0; }
    .legacy-link {
      max-width: 1280px; margin: 2rem auto 4rem; padding: 0 1rem;
      text-align: center; font-size: 0.8rem; color: var(--text-dim);
    }
    .legacy-link a { color: var(--primary); text-decoration: none; }
    .legacy-link a:hover { text-decoration: underline; }

    /* Top-right floating action buttons — duplázza a lent lévő legacy-link-et */
    .top-actions {
      position: absolute; top: 1rem; right: 1.5rem; z-index: 10;
      display: flex; gap: 0.5rem; align-items: center;
    }
    .top-actions a {
      display: inline-flex; align-items: center; gap: 0.35rem;
      padding: 0.55rem 1rem; border-radius: 6px;
      font-family: 'JetBrains Mono', monospace; font-size: 0.78rem;
      font-weight: 600; text-decoration: none; letter-spacing: 0.05em;
      transition: all 0.15s; white-space: nowrap;
    }
    .top-actions .btn-primary {
      background: var(--primary); color: #0a0f14;
      border: 1px solid var(--primary);
    }
    .top-actions .btn-primary:hover {
      background: transparent; color: var(--primary);
    }
    .top-actions .btn-secondary {
      background: rgba(255,255,255,0.04); color: var(--text);
      border: 1px solid var(--border);
    }
    .top-actions .btn-secondary:hover {
      border-color: var(--primary); color: var(--primary);
    }
    @media (max-width: 700px) {
      .top-actions { position: static; padding: 0.7rem 1rem 0;
                     justify-content: flex-end; }
    }
"""


# ── Main render fn ────────────────────────────────────────────────────

async def render_landing_v2(request, db_path: str) -> tuple[str, str]:
    """Render the new Ground News-style landing. Returns (html, lang).

    Async because we `await build_local_trending` directly — calling
    asyncio.run() from inside the Starlette event loop fails with
    "cannot be called from a running event loop".
    """
    lang = _request_lang(request)
    log.info("landing_v2 render: lang=%s", lang)
    origin = public_origin(request)

    # Backend lekérések — local_trending async-ben fut, await-eljük.
    try:
        local = await build_local_trending(lang, db_path)
    except Exception as exc:
        log.warning("local_trending failed: %s", exc)
        local = {"wiki": [], "gnews": [], "velocity": [], "geo": {}}

    # min_sources lang-filtered query-re lazább (kevesebb forrás van nyelvenként):
    # 2 source elég hogy "story" legyen. Limit 13 = hero + 12-grid (6×2 sor).
    try:
        stories = cluster_top_stories(db_path, hours=24, min_sources=2, limit=13, lang=lang)
        if len(stories) < 4:
            # Fallback: egyetlen-source clusterek is jelennek meg (egyedi cikkek)
            stories = cluster_top_stories(db_path, hours=24, min_sources=1, limit=13, lang=lang)
    except Exception as exc:
        log.warning("top_stories failed: %s", exc)
        stories = []

    try:
        # Blindspot lang-filtered: 5→3 min_sources (kevesebb adat nyelvenként)
        political_blind = find_political_blindspots(db_path, hours=24, min_sources=3, limit=3, lang=lang)
    except Exception as exc:
        log.warning("political_blindspots failed: %s", exc)
        political_blind = []
    try:
        geo_blind = find_geo_blindspots(db_path, hours=24, min_sources=2, limit=2, lang=lang)
    except Exception as exc:
        log.warning("geo_blindspots failed: %s", exc)
        geo_blind = []

    try:
        entities = top_entities_24h(db_path, hours=24, limit=15, lang=lang)
    except Exception as exc:
        log.warning("top_entities failed: %s", exc)
        entities = []

    # SEO head (megőrzött, ugyanaz mint az augment_landing-ben)
    seo_head = seo_head_html(
        origin=origin, lang=lang, path="/",
        description=t("seo.site.description", lang),
        og_title=f"Echolot — {t('landing.hero_title', lang)}",
    )

    # Nav-strip (megőrzött)
    nav_strip = _augment_block_html(lang, active="feed")
    if not nav_strip:
        log.warning("nav_strip empty for lang=%s", lang)

    # Render blokkok
    entity_chips = _render_entity_chip_row(entities, lang)
    bias_legend = _render_bias_legend(lang)
    top_stories_html = _render_top_stories(stories, lang)
    local_trending_html = _render_local_trending(local, lang)
    blindspot_html = _render_blindspots(political_blind, geo_blind, lang)

    title_html = _escape(t("landing.hero_title", lang))
    legacy_label = _escape(t("landing.legacy_view", lang))
    dashboard_label = _escape(t("landing.dashboard_link", lang))
    section_top = _escape(t("landing.section.top_stories", lang))
    section_local = _escape(t("landing.section.local", lang))
    section_blind = _escape(t("landing.section.blindspot", lang))

    return (f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="600">
  <title>Echolot — {title_html}</title>
  {seo_head}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>{_BASE_STYLES}{_LANDING_V2_EXTRA_CSS}</style>
</head>
<body>
  <div class="ambient" aria-hidden="true">
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>
  </div>

  <div class="top-actions">
    <a href="/landing-classic?lang={lang}" class="btn-secondary">{legacy_label} →</a>
    <a href="/dashboard?lang={lang}" class="btn-primary">{dashboard_label} →</a>
  </div>

  {nav_strip}

  {entity_chips}

  {bias_legend}

  <div class="landing-grid">
    <div class="landing-col">
      <h2>📰 {section_top}</h2>
      {top_stories_html}
    </div>
    <div class="landing-col">
      <h2>🌍 {section_local} · {_escape(local.get('geo', {}).get('gnews', ''))}</h2>
      {local_trending_html}
    </div>
    <div class="landing-col">
      <h2>🔍 {section_blind}</h2>
      {blindspot_html}
    </div>
  </div>

  <div class="legacy-link">
    <a href="/landing-classic?lang={lang}">▷ {legacy_label} ◁</a>
    <span> · </span>
    <a href="/dashboard?lang={lang}">▷ {dashboard_label} ◁</a>
  </div>
</body>
</html>""", lang)
