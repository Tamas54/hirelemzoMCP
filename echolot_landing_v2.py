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
from datetime import datetime, timezone

from echolot_i18n import t
from echolot_dashboard import (
    _BASE_STYLES,
    _augment_block_html,
    _request_lang,
    _escape,
)
from echolot_seo import public_origin, seo_head_html
from echolot_local_trending import build_local_trending
from echolot_youtube_trends import trending_videos as _yt_trending_videos
from echolot_top_stories import cluster_top_stories
from echolot_blindspot import find_political_blindspots, find_geo_blindspots
from echolot_entity_trending import top_entities_24h
try:
    import echolot_domain_intel as _edi
except Exception as _edi_err:
    log = logging.getLogger("echolot.landing_v2")
    log.warning("domain_intel adapter unavailable: %s", _edi_err)
    _edi = None

import os as _os
# Production sets DB_PATH=/data/echolot.db (Railway volume mount); local
# defaults to the repo-relative echolot.db (matches server.py's DB_PATH).
_REACH_DB_PATH: str = _os.environ.get(
    "DB_PATH",
    str(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "echolot.db")),
)

log = logging.getLogger("echolot.landing_v2")


# Rovat-sphere-halmazok — a Top sztorik alatti tematikus rovatokhoz.
# Kombinálja a global_* topikális csomagokat a nyelvspecifikus *_tech /
# *_sport / *_entertainment szférákkal. A lang-szűrt query lokális preferenciát
# ad; ha nincs elég találat, fallback az összes nyelvre.
TECH_SPHERES = frozenset({
    "global_tech", "global_critical_tech", "global_science", "global_ai", "global_preprint",
    "hu_tech", "yt_tech_ai", "reddit_tech", "mastodon_tech",
})
SPORT_SPHERES = frozenset({
    "global_sport", "global_football", "global_motorsport", "global_basketball",
    "global_americansports", "global_tennis_sport", "hu_sport",
})
TABLOID_SPHERES = frozenset({
    "global_tabloid", "global_celebrity", "global_entertainment",
    "hu_entertainment", "hu_lifestyle",
})
ECONOMY_SPHERES = frozenset({
    "hu_economy", "global_economy", "global_business", "global_finance",
})


# ── Render helpers ────────────────────────────────────────────────────

# Sphere → CSS variable mapping for the v2 mockup card design.
# Unknown spheres fall back to a neutral gray (--fg-2).
_SPHERE_COLOR_MAP: dict[str, str] = {
    # HU
    "hu_politics": "var(--sphere-hu-pol)",
    "hu_pol": "var(--sphere-hu-pol)",
    "hu_economy": "var(--sphere-hu-econ)",
    "hu_econ": "var(--sphere-hu-econ)",
    "hu_society": "var(--sphere-hu-soc)",
    "hu_soc": "var(--sphere-hu-soc)",
    # Tech / science (cross-language)
    "hu_tech": "var(--sphere-tech)",
    "tech": "var(--sphere-tech)",
    "global_tech": "var(--sphere-tech)",
    "global_science": "var(--sphere-tech)",
    "global_ai": "var(--sphere-tech)",
    "global_critical_tech": "var(--sphere-tech)",
    # World
    "world_politics": "var(--sphere-world-pol)",
    "world_pol": "var(--sphere-world-pol)",
    "global_politics": "var(--sphere-world-pol)",
    "world_economy": "var(--sphere-world-econ)",
    "world_econ": "var(--sphere-world-econ)",
    "global_economy": "var(--sphere-world-econ)",
    "global_business": "var(--sphere-world-econ)",
    "global_finance": "var(--sphere-world-econ)",
    # Country accents
    "russia": "var(--sphere-ru)",
    "ru": "var(--sphere-ru)",
    "global_russia": "var(--sphere-ru)",
    "us": "var(--sphere-us)",
    "usa": "var(--sphere-us)",
    "global_us": "var(--sphere-us)",
    "global_usa": "var(--sphere-us)",
}


# UI-language → YouTube `regionCode` (ISO 3166-1 alpha-2). Ha az echolot
# nyelvváltó-rajza nem-támogatott YT-regiót adna, fallback "HU"-ra (mert a
# fő közönség onnan jön).
_LANG_TO_YT_REGION: dict[str, str] = {
    "hu": "HU", "en": "US", "de": "DE", "fr": "FR", "es": "ES",
    "it": "IT", "pl": "PL", "ru": "RU", "uk": "UA",
    "ja": "JP", "ko": "KR", "zh": "CN", "pt": "BR", "tr": "TR",
    "nl": "NL", "cs": "CZ",
}


def _lang_to_yt_region(lang: str | None) -> str:
    if not lang:
        return "HU"
    return _LANG_TO_YT_REGION.get(lang.strip().lower(), "HU")


def _format_views_compact(views: int) -> str:
    """1234 → '1.2K', 1234567 → '1.2M', 1234567890 → '1.2B'."""
    n = int(views or 0)
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n/1000:.1f}K".replace(".0K", "K")
    if n < 1_000_000_000:
        return f"{n/1_000_000:.1f}M".replace(".0M", "M")
    return f"{n/1_000_000_000:.1f}B".replace(".0B", "B")


def _sphere_color(sphere: str | None) -> str:
    """Map an Echolot sphere name to its CSS color variable.

    Case-insensitive; accepts both hyphenated and underscored forms.
    Returns ``var(--fg-2)`` (neutral) for unknown / empty input.
    """
    if not sphere:
        return "var(--fg-2)"
    key = sphere.strip().lower().replace("-", "_")
    return _SPHERE_COLOR_MAP.get(key, "var(--fg-2)")


def _fmt_age(dt: datetime, now: datetime) -> str:
    """Compact Hungarian relative age: '12p' / '5ó' / '3n'.

    Handles mixed naive/aware datetimes by stripping tz info before
    subtraction — both inputs are coerced to naive in UTC.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "most"
    if secs < 60:
        return "most"
    mins = secs // 60
    if mins < 60:
        return f"{mins}p"
    hours = mins // 60
    if hours < 48:
        return f"{hours}ó"
    days = hours // 24
    return f"{days}n"


def _format_reach_window(first_published: str | None,
                        latest_published: str | None) -> str:
    """Compact '2ó–6ó' window string for the reach badge, or '' if unavailable."""
    if not first_published or not latest_published:
        return ""
    try:
        first_dt = datetime.fromisoformat(first_published)
        latest_dt = datetime.fromisoformat(latest_published)
    except (ValueError, TypeError):
        return ""
    now = datetime.now(timezone.utc) if (first_dt.tzinfo or latest_dt.tzinfo) else datetime.now()
    # Convention: 'first' is the oldest, 'latest' is the most recent.
    # Display: latest_age → first_age (newest to oldest), to read naturally.
    # Normalize both to UTC-naive for the span calculation.
    fdt = first_dt.astimezone(timezone.utc).replace(tzinfo=None) if first_dt.tzinfo else first_dt
    ldt = latest_dt.astimezone(timezone.utc).replace(tzinfo=None) if latest_dt.tzinfo else latest_dt
    span_sec = int((ldt - fdt).total_seconds())
    if span_sec < 1800:  # < 30 min span — treat as point-in-time
        return _fmt_age(latest_dt, now)
    return f"{_fmt_age(latest_dt, now)}–{_fmt_age(first_dt, now)}"


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
        <div class="entity-row-label">Legkeresettebb kulcsszavak · 24h</div>
        <div class="entity-chips">{''.join(chips)}</div>
      </div>
    """


_FLAG_BY_CC: dict[str, str] = {
    "HU": "🇭🇺", "US": "🇺🇸", "GB": "🇬🇧", "DE": "🇩🇪", "FR": "🇫🇷", "ES": "🇪🇸",
    "IT": "🇮🇹", "PL": "🇵🇱", "RU": "🇷🇺", "UA": "🇺🇦", "BY": "🇧🇾", "IL": "🇮🇱",
    "IR": "🇮🇷", "TR": "🇹🇷", "JP": "🇯🇵", "CN": "🇨🇳", "KR": "🇰🇷", "IN": "🇮🇳",
    "BR": "🇧🇷", "AR": "🇦🇷", "ZA": "🇿🇦", "AU": "🇦🇺", "CA": "🇨🇦", "MX": "🇲🇽",
    "AE": "🇦🇪", "SA": "🇸🇦", "EG": "🇪🇬", "NL": "🇳🇱", "BE": "🇧🇪", "SE": "🇸🇪",
    "NO": "🇳🇴", "DK": "🇩🇰", "FI": "🇫🇮", "CZ": "🇨🇿", "RO": "🇷🇴", "GR": "🇬🇷",
    "AT": "🇦🇹", "CH": "🇨🇭", "PT": "🇵🇹", "IE": "🇮🇪", "BG": "🇧🇬", "SK": "🇸🇰",
    "HR": "🇭🇷", "SI": "🇸🇮", "RS": "🇷🇸",
}


def _render_reach_badge(
    source_ids: list[str] | None,
    first_published: str | None = None,
    latest_published: str | None = None,
) -> str:
    """Compact reach-badge under each story card.

    Renders ≈XXX olvasó with optional top-country flag and an optional
    "mikortól mikorig" relative time window (e.g. ``2ó–6ó`` meaning the
    cluster spans from 2 to 6 hours ago). Returns empty string if
    domain-intel is unavailable, no source_ids provided, or no audience
    could be estimated.
    """
    if not _edi or not source_ids:
        return ""
    try:
        reach = _edi.compute_story_reach(_REACH_DB_PATH, source_ids)
    except Exception:
        return ""
    if not reach or not reach.get("total_readers"):
        return ""
    total = _edi.format_readers_compact(reach["total_readers"])
    bc = reach.get("by_country") or []
    if bc:
        top = bc[0]
        flag = _FLAG_BY_CC.get(top["country_code"], top["country_code"])
        pct = top["pct_of_internet_users"]
        sub = f'<span class="reach-country">{flag} {pct:.1f}%</span>'
        title = f'≈{total} olvasó · top: {top["country_code"]} ({pct:.1f}% of internet users)'
    else:
        sub = '<span class="reach-country reach-global">🌐 global</span>'
        title = f'≈{total} olvasó · global'
    window = _format_reach_window(first_published, latest_published)
    window_html = (
        f' <span class="reach-window" title="cluster aktív: {_escape(window)}">{_escape(window)}</span>'
        if window else ""
    )
    if window:
        title = f"{title} · {window}"
    return (
        f'<div class="reach-badge" title="{_escape(title)}">'
        f'<span class="reach-num">≈{total}</span> '
        f'<span class="reach-label">reach</span>{window_html}{sub}'
        f'</div>'
    )


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


def _render_source_stack(n_sources: int) -> str:
    """Render overlapping colored dots representing N sources.

    Max 5 dots; if N > 5, show 4 dots + an "+N" overflow indicator.
    Uses the s1..s5 gradient color classes defined in the v2 CSS.
    """
    if n_sources <= 0:
        return ""
    if n_sources <= 5:
        dots = "".join(f'<span class="src-dot s{i+1}"></span>' for i in range(n_sources))
        return f'<span class="dots">{dots}</span>'
    overflow = n_sources - 4
    dots = "".join(f'<span class="src-dot s{i+1}"></span>' for i in range(4))
    dots += f'<span class="src-dot overflow">+{overflow}</span>'
    return f'<span class="dots">{dots}</span>'


def _render_pol_bar(bias: dict) -> str:
    """Mockup-style political distribution bar — L/C/R % with flex weights."""
    L = int(bias.get("L", 0))
    C = int(bias.get("C", 0))
    R = int(bias.get("R", 0))
    return (
        '<div class="pol-bar" title="'
        f'L {L}% · C {C}% · R {R}%">'
        f'<span class="seg l" style="flex: {max(L, 1)}">L {L}%</span>'
        f'<span class="seg c" style="flex: {max(C, 1)}">C {C}%</span>'
        f'<span class="seg r" style="flex: {max(R, 1)}">R {R}%</span>'
        '</div>'
    )


def _render_v2_footer_reach(
    source_ids: list[str] | None,
    first_published: str | None,
    latest_published: str | None,
) -> str:
    """Inline reach span for the v2 story footer.

    Same data as ``_render_reach_badge`` but emitted as a single inline
    ``<span class="footer-reach">`` (no surrounding div, no top border)
    so it fits horizontally next to the time stamp in ``.story-footer-v2``.
    """
    if not _edi or not source_ids:
        return ""
    try:
        reach = _edi.compute_story_reach(_REACH_DB_PATH, source_ids)
    except Exception:
        return ""
    if not reach or not reach.get("total_readers"):
        return ""
    total = _edi.format_readers_compact(reach["total_readers"])
    bc = reach.get("by_country") or []
    if bc:
        top = bc[0]
        flag = _FLAG_BY_CC.get(top["country_code"], top["country_code"])
        pct = top["pct_of_internet_users"]
        country_html = f'<span class="reach-country">{flag} {pct:.1f}%</span>'
        title = f'≈{total} olvasó · top: {top["country_code"]} ({pct:.1f}%)'
    else:
        country_html = '<span class="reach-country reach-global">🌐 global</span>'
        title = f'≈{total} olvasó · global'
    window = _format_reach_window(first_published, latest_published)
    window_html = (
        f' <span class="reach-window">{_escape(window)}</span>' if window else ""
    )
    if window:
        title += f" · {window}"
    return (
        f'<span class="footer-reach" title="{_escape(title)}">'
        f'<span class="reach-num">≈{total}</span> '
        f'<span class="reach-label">reach</span>{window_html} {country_html}'
        f'</span>'
    )


def _render_story_v2(s: dict, variant: str, src_label: str) -> str:
    """Render a single story card in the v2 mockup style.

    ``variant`` is 'hero', 'sub', or 'sub compact'. The hero gets a
    larger headline + full lead, regular sub gets a 19px headline +
    2-line lead clamp, compact sub drops the lead entirely and uses a
    15px headline + tighter pol-bar.
    """
    is_compact = "compact" in variant
    title = s.get("lead_title") or (s.get("sample_titles") or [""])[0] or "?"
    lead = "" if is_compact else (s.get("lead_summary") or "")
    url = s.get("lead_url") or "#"
    n_sources = int(s.get("source_count") or 0)
    bias = s.get("bias_dist") or {"L": 0, "C": 0, "R": 0}
    spheres = s.get("sphere_set") or []
    sphere = spheres[0] if spheres else ""
    accent = _sphere_color(sphere)

    # Relative age (from latest_published). Fall back to first_published.
    age_html = ""
    latest = s.get("latest_published")
    first = s.get("first_published")
    if latest:
        try:
            dt = datetime.fromisoformat(latest)
            now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
            age_html = f'<time datetime="{_escape(latest)}">{_fmt_age(dt, now)}</time>'
        except (ValueError, TypeError):
            age_html = ""

    lead_html = (
        f'<p class="story-lead-v2">{_escape(lead)}</p>' if lead else ""
    )

    footer_reach = _render_v2_footer_reach(s.get("source_ids"), first, latest)

    return f"""
      <a href="{_escape(url)}" target="_blank" rel="noopener" class="story {variant}">
        <span class="accent" style="background: {accent}"></span>
        <div class="meta-row">
          <span class="sphere-tag" style="color: {accent}">{_escape(sphere)}</span>
          <span class="source-stack">
            {_render_source_stack(n_sources)}
            <span class="src-count">{n_sources} {src_label}</span>
          </span>
        </div>
        <h2 class="story-title-v2">{_escape(title)}</h2>
        {lead_html}
        {_render_pol_bar(bias)}
        <div class="story-footer-v2">
          {age_html}
          {footer_reach}
        </div>
      </a>
    """


def _render_tv_panel() -> str:
    """Live TV viewer mount-pont a jobb landing-col tetején, a Vakfolt FÖLÖTT.

    Phase 1.x (2026-05-18): a Gemini deep-research javasolta a jobb felső
    1fr pozíciót a bal oszlop mély-olvasási zónájának védelmére. Auto-play
    marad (Kommandant döntés), de prominens minimize + mute kontrol.
    A logikát a /static/echolot-tv.js viszi.
    """
    return """
      <div class="landing-v2-shell tv-panel-wrap">
        <section class="ts-section">
          <div class="ts-section-header">
            <span class="ts-section-icon">▶</span>
            <span class="ts-section-title">Élő TV</span>
            <span class="ts-section-meta" id="tv-header-meta">HLS + YT · 9 csatorna</span>
            <button id="tv-popout-btn" class="tv-popout-btn" type="button"
              aria-label="TV panel kiemelése floating ablakba"
              title="Kiemelés (drag-able, resizable)">↗</button>
            <button id="tv-fullscreen-btn" class="tv-fullscreen-btn" type="button"
              aria-label="Teljes képernyő" title="Teljes képernyő (Esc kilép)">⛶</button>
            <button id="tv-collapse-btn" class="tv-collapse-btn" type="button"
              aria-label="TV panel lekicsinyítése" title="Lekicsinyít / kibont">▽</button>
          </div>
          <div class="echolot-tv" id="tv-root">
            <div class="tv-tabs" id="tv-tabs" role="tablist" aria-label="Live TV csatornák"></div>
            <div class="tv-player-wrap">
              <video id="tv-video" controls playsinline muted autoplay></video>
              <iframe id="tv-iframe"
                allow="autoplay; encrypted-media; picture-in-picture"
                allowfullscreen></iframe>
              <div class="tv-offline" id="tv-offline" hidden>Csatorna offline</div>
            </div>
            <div class="tv-meta">
              <span id="tv-channel-name" class="tv-channel-name"></span>
              <span id="tv-source-badge" class="tv-source-badge"></span>
              <button id="tv-mute-btn" class="tv-mute-btn" type="button" aria-label="Mute toggle">🔇</button>
            </div>
          </div>
        </section>
      </div>
    """


def _render_top_stories(stories: list[dict], lang: str) -> str:
    """Top Stories — eredeti layout (hero + 2-col sub-grid) mockup v2 vizuálisan.

    Az ELSŐ cluster (legtöbb-source) teljes szélességű hero-kártya, a
    maradék 1-12 cluster 2-oszlopos rácsban alatta (a klasszikus echolot
    elrendezés). Mind az új mockup-style designt használja
    (.landing-v2-shell scope-ban).
    """
    if not stories:
        return f'<div class="empty">{_escape(t("landing.empty_panel", lang))}</div>'

    src_label = _escape(t("article.source", lang)).lower()
    section_label = _escape(t("landing.section.top_stories", lang))

    hero_html = _render_story_v2(stories[0], "hero", src_label)
    # Lépcsős méretcsökkentés: első 4 sub-medium, utána sub-compact (cím-only)
    sub_cards = []
    for i, s in enumerate(stories[1:13]):
        variant = "sub" if i < 4 else "sub compact"
        sub_cards.append(_render_story_v2(s, variant, src_label))
    sub_html = (
        f'<div class="stories-grid">{"".join(sub_cards)}</div>' if sub_cards else ""
    )

    return f"""
      <div class="landing-v2-shell">
        <section class="ts-section">
          <div class="ts-section-header">
            <span class="ts-section-icon">★</span>
            <span class="ts-section-title">{section_label}</span>
            <span class="ts-section-meta">FRISSÍTVE · 24H</span>
          </div>
          <div class="stories">{hero_html}</div>
          {sub_html}
        </section>
      </div>
    """


def _render_local_trending(local: dict, lang: str) -> str:
    """Helyi trending blokk — 3 vizuálisan elkülönülő szekció.

    Kommandant döntés szerint a forrás-nevek (Wikipedia / Google News)
    nem jelennek meg explicit alcímként; helyettük neutrális magyar
    címkék (KULCSSZAVAK / HÍREK / SZFÉRA VELOCITY). A hírek (Google News)
    az új v2 stílusú kis kártyákban renderelődnek, cím + lead-szöveggel.
    Wiki és Velocity sima text-sor listákban (ahogy az eredeti elrendezés).
    """
    # ── Wikipedia top — sima text-sor (mint az eredeti) ──────────────
    wiki_results = (local.get("wiki") or {}).get("results", []) if isinstance(local.get("wiki"), dict) else (local.get("wiki") or [])
    wiki_items = []
    for w in (wiki_results or [])[:8]:
        title = w.get("title") or w.get("article") or ""
        url = w.get("wiki_url") or "#"
        views = w.get("views", 0)
        wiki_items.append(
            f'<li class="lt-row">'
            f'<a href="{_escape(url)}" target="_blank" rel="noopener">'
            f'<span class="lt-row-title">{_escape(title)}</span>'
            f'<span class="lt-row-meta">{int(views):,}</span>'
            f'</a></li>'
        )

    # ── Google News — új v2 stílusú kis kártyák, lead-del ────────────
    gnews_results = (local.get("gnews") or {}).get("results", []) if isinstance(local.get("gnews"), dict) else (local.get("gnews") or [])
    gnews_items = []
    for g in (gnews_results or [])[:8]:
        title = g.get("title") or ""
        url = g.get("link") or "#"
        src = g.get("source") or ""
        summary = (g.get("summary") or "").strip()
        lead_html = (
            f'<p class="lt-news-lead">{_escape(summary)}</p>' if summary else ""
        )
        gnews_items.append(
            f'<li class="lt-news-card">'
            f'<a href="{_escape(url)}" target="_blank" rel="noopener">'
            f'<h4 class="lt-news-title">{_escape(title)}</h4>'
            f'{lead_html}'
            f'<span class="lt-news-host">{_escape(src.lower())}</span>'
            f'</a></li>'
        )

    # ── Sphere velocity — opció C: mindig mutatunk valamit ────────────
    # Ha van mérhető velocity ratio: "sphere · 1.5×" (status-szal színezve).
    # Ha nincs baseline (ratio=None): fallback a current_count cikkek számára:
    # "sphere · 247 cikk" — kevésbé "intelligens", de informatív és nem üres.
    # Skip csak akkor, ha current_count is 0 (semmi cikk a window-ban).
    vel_blob = local.get("velocity") or {}
    if isinstance(vel_blob, dict):
        vel_results = vel_blob.get("results") or vel_blob.get("spheres") or []
    else:
        vel_results = vel_blob or []
    vel_items = []
    for v in (vel_results or []):
        sphere = v.get("sphere") or ""
        if not sphere:
            continue
        ratio = v.get("velocity_ratio")
        current_count = int(v.get("current_count") or 0)
        # Skip ha semmi friss aktivitás — "ez halott" jelzés értelmetlen
        if current_count == 0:
            continue
        if ratio is not None and ratio > 0:
            # Van mérhető velocity → ratio kijelzés
            ratio_s = f"{ratio:.1f}×"
            status = v.get("status", "normal")
        else:
            # Nincs baseline (vagy 0) → count fallback
            ratio_s = f"{current_count} cikk"
            status = "count"
        vel_items.append(
            f'<li class="lt-row lt-row-velocity">'
            f'<a href="/dashboard/sphere/{_escape(sphere)}?lang={lang}">'
            f'<span class="lt-row-title">{_escape(sphere)}</span>'
            f'<span class="lt-row-ratio status-{_escape(status)}">{_escape(ratio_s)}</span>'
            f'</a></li>'
        )
        if len(vel_items) >= 6:
            break

    empty = '<li class="lt-empty">—</li>'
    # Velocity szekciót csak akkor mutatjuk, ha van mérhető spike
    velocity_section_html = (
        f"""
        <div class="lt-section">
          <div class="lt-section-label"><span class="lt-icon">◆</span>MOST PÖRGŐ TÉMÁK · 24H</div>
          <ul class="lt-list">{''.join(vel_items)}</ul>
        </div>
        """
        if vel_items else ""
    )
    return f"""
      <div class="lt-shell">
        <div class="lt-section">
          <div class="lt-section-label"><span class="lt-icon">◆</span>KULCSSZAVAK · 24H</div>
          <ul class="lt-list">{''.join(wiki_items) or empty}</ul>
        </div>
        <div class="lt-section">
          <div class="lt-section-label"><span class="lt-icon">◆</span>HÍREK · MA</div>
          <small class="lt-section-sub">a legfontosabb magyar hír-főcímek ma — eltér a Top sztoriktól, mert nem klaszterezett</small>
          <ul class="lt-news-cards">{''.join(gnews_items) or empty}</ul>
        </div>
        {velocity_section_html}
      </div>
    """


def _render_rovat(stories: list[dict], lang: str) -> str:
    """Tematikus rovat-oszlop — v2 mockup stílus, sub.compact kártyák.

    Az új v2 design tokenrendszerre kapcsolva: a kártyák `_render_story_v2`
    'sub compact' variánssal renderelődnek (Newsreader cím, sphere-accent
    bal-sáv, mockup pol-bar, footer reach időablakkal).
    """
    if not stories:
        return f'<div class="empty">{_escape(t("landing.empty_panel", lang))}</div>'
    src_label = _escape(t("article.source", lang)).lower()
    cards = [
        _render_story_v2(s, "sub compact", src_label) for s in stories[:6]
    ]
    return f"""
      <div class="rovat-shell">
        <div class="stories">{''.join(cards)}</div>
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
            {_render_reach_badge(p.get("source_ids"), p.get("first_published"), p.get("latest_published"))}
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
            {_render_reach_badge(g.get("source_ids"), g.get("first_published"), g.get("latest_published"))}
          </a>
        """)
    if not cards:
        return f'<div class="empty">{_escape(t("msg.no_results", lang))}</div>'
    return "".join(cards)


def _render_youtube_trending(videos: list[dict] | None, lang: str, region: str) -> str:
    """YouTube trending videók panel — kis kártyák thumbnaillel.

    `videos` az echolot_youtube_trends.trending_videos() eredménye (lehet
    None ha nincs API-key vagy hiba). A felülvizsgált kártyák megegyezőek
    a Helyi Trending hír-kártyák stílusával, csak a `lt-` prefix helyett
    `yt-` osztályokkal.
    """
    if not videos:
        return (
            '<div class="yt-shell"><div class="yt-empty">'
            'Nincs adat — YOUTUBE_API_KEY hiányzik vagy a YT API kvóta kimerült.'
            '</div></div>'
        )
    cards = []
    for v in videos[:8]:
        title = v.get("title") or ""
        url = v.get("url") or "#"
        video_id = v.get("video_id") or ""
        channel = v.get("channel") or ""
        views = int(v.get("views") or 0)
        thumb = v.get("thumbnail") or ""
        # Description-snippet — 200 char-os preview a YT API-tól, 2 sorra
        # CSS line-clamp-pal vágva. Plain-text only, escape elég.
        description = (v.get("description") or "").strip()
        views_html = _format_views_compact(views)
        thumb_html = (
            f'<img class="yt-thumb" src="{_escape(thumb)}" alt="" loading="lazy">'
            if thumb else '<div class="yt-thumb yt-thumb-empty">▶</div>'
        )
        desc_html = (
            f'<p class="yt-desc">{_escape(description)}</p>' if description else ""
        )
        # Transcript-actions: inline-expand gomb + új-tab ikon. A
        # data-video-id-t a JS olvassa ki és a panelt alá renderelt
        # ".yt-transcript-panel"-be feszíti.
        actions_html = (
            f'<div class="yt-actions">'
            f'<button class="yt-transcript-btn" type="button" '
            f'data-video-id="{_escape(video_id)}" '
            f'aria-label="Leirat ki/be kapcsolása">▽ Leirat</button>'
            f'<a class="yt-transcript-link" '
            f'href="/transcript/{_escape(video_id)}" target="_blank" rel="noopener" '
            f'title="Leirat megnyitása külön oldalon">↗</a>'
            f'</div>'
        ) if video_id else ""
        cards.append(
            f'<li class="yt-card">'
            f'<a class="yt-main-link" href="{_escape(url)}" target="_blank" rel="noopener">'
            f'{thumb_html}'
            f'<div class="yt-card-body">'
            f'<h4 class="yt-title">{_escape(title)}</h4>'
            f'{desc_html}'
            f'<span class="yt-meta">{_escape(channel)} · {views_html} megtekintés</span>'
            f'</div>'
            f'</a>'
            f'{actions_html}'
            f'<div class="yt-transcript-panel" data-for-video="{_escape(video_id)}" hidden></div>'
            f'</li>'
        )
    region_label = _escape(region)
    return f"""
      <div class="yt-shell">
        <div class="yt-section-label">
          <span class="yt-icon">▶</span>YOUTUBE TRENDING · {region_label}
        </div>
        <ul class="yt-cards">{"".join(cards)}</ul>
      </div>
    """


# ── Stylesheet az új blokkokhoz ───────────────────────────────────────

_LANDING_V2_EXTRA_CSS = """
    .entity-row {
      max-width: 1500px; margin: 1.2rem auto 0; padding: 0 1rem;
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
      max-width: 1500px; margin: 1.5rem auto; padding: 0 1rem;
      display: grid; grid-template-columns: 2fr 1.2fr 1fr; gap: 1.5rem;
    }
    @media (max-width: 1024px) { .landing-grid { grid-template-columns: 1fr; } }

    /* Min-width: 0 a grid-blowout megakadályozására — különben az
       intrinsic-min-content (TV-tabs, hosszú headline-ok) szétfeszíti
       a 2fr/1.2fr/1fr arányokat, és a jobb oszlop indokolatlanul
       szélesre nő. */
    .landing-col { min-width: 0; }
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
      max-width: 1500px; margin: 0.6rem auto 0; padding: 0.45rem 1rem;
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

    /* Reach-badge — sor a bias-bar alatt. Egy fokkal hangsúlyosabb a
       bias-barnál, mert OSINT-szempontból ez a kulcs-szignál (mekkora
       közönség látta a sztorit). Tooltip-en (title) megy a teljes
       country-breakdown. */
    .reach-badge {
      display: flex; align-items: center; gap: 0.5rem;
      margin-top: 0.45rem; padding-top: 0.4rem;
      border-top: 1px solid rgba(255,255,255,0.06);
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.7rem; line-height: 1.1;
      color: var(--text);
      letter-spacing: 0.04em;
    }
    .reach-badge .reach-num {
      color: var(--primary);
      font-weight: 700;
      font-size: 0.95rem;
      letter-spacing: 0.02em;
    }
    .reach-badge .reach-label {
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 0.6rem;
      opacity: 0.8;
    }
    .reach-badge .reach-country {
      margin-left: auto;
      font-size: 0.8rem;
      opacity: 0.95;
    }
    .reach-badge .reach-global { opacity: 0.55; font-size: 0.7rem; }
    .blindspot-card .reach-badge,
    .rovat-card .reach-badge {
      font-size: 0.65rem;
      margin-top: 0.35rem; padding-top: 0.3rem;
    }
    .blindspot-card .reach-badge .reach-num,
    .rovat-card .reach-badge .reach-num {
      font-size: 0.85rem;
    }

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

    /* Rovatok — Tech / Gazdaság / Sport / Bulvár 4-oszlopos szekció */
    .rovatok-grid {
      max-width: 1500px; margin: 0.5rem auto 1.5rem; padding: 0 1rem;
      display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 1.5rem;
    }
    @media (max-width: 1100px) { .rovatok-grid { grid-template-columns: 1fr 1fr; } }
    @media (max-width: 600px) { .rovatok-grid { grid-template-columns: 1fr; } }
    .rovat-col h2 {
      font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.2em;
      color: var(--text-dim); margin: 0 0 0.7rem;
      font-family: 'JetBrains Mono', monospace;
      padding-bottom: 0.4rem;
      border-bottom: 1px solid var(--border);
    }
    .rovat-card {
      display: block; text-decoration: none; color: var(--text);
      padding: 0.6rem 0; border-bottom: 1px solid rgba(255,255,255,0.04);
      transition: all 0.15s;
    }
    .rovat-card:last-child { border-bottom: none; }
    .rovat-card:hover .rovat-title { color: var(--primary); }
    .rovat-title {
      font-size: 0.82rem; font-weight: 500; line-height: 1.35;
      margin-bottom: 0.35rem;
    }
    .rovat-meta {
      display: flex; align-items: center; gap: 0.6rem;
      font-size: 0.65rem; color: var(--text-dim);
      font-family: 'JetBrains Mono', monospace;
    }
    .rovat-meta .bias-bar {
      flex: 1; height: 10px; font-size: 0.5rem; margin-top: 0;
    }
    .rovat-meta .bias-bar > div {
      /* Belül kis bárban nincs hely a "L 12%" feliratra — elrejtjük */
      font-size: 0; padding: 0;
    }

    .empty { color: var(--text-dim); font-style: italic; padding: 1rem 0; }
    .legacy-link {
      max-width: 1500px; margin: 2rem auto 4rem; padding: 0 1rem;
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

    /* =====================================================================
       LANDING V2 — MOCKUP TOKEN SYSTEM
       Scoped under .landing-v2-shell so it doesn't leak into the existing
       dashboard / sphere / blindspot pages. Editorial / intelligence-terminal
       hybrid design — Newsreader serif headlines + JetBrains Mono labels.
       ===================================================================== */
    /* Shared design tokens — all v2 panels (Top Stories + Helyi Trending + Rovat + YT) */
    .landing-v2-shell,
    .lt-shell,
    .yt-shell,
    .rovat-shell {
      /* Base palette — deep slate, never pure black (premium feel) */
      --bg-0: #0a0d12;
      --bg-1: #11151c;
      --bg-2: #1a1f29;
      --bg-3: #232a36;
      --line: #2a323f;
      --line-soft: #1c2230;

      /* Warm off-white text scale */
      --fg-0: #f4f1ea;
      --fg-1: #c9c4b8;
      --fg-2: #8a8478;
      --fg-3: #5a5448;

      /* Sphere accent colors (8 anchor — fallback to --fg-2 for the rest) */
      --sphere-hu-pol:     #e0524f;
      --sphere-hu-econ:    #2dd4bf;
      --sphere-hu-soc:     #f59e0b;
      --sphere-world-pol:  #d4a574;
      --sphere-world-econ: #5b9eff;
      --sphere-tech:       #a78bfa;
      --sphere-ru:         #ef4444;
      --sphere-us:         #4ade80;

      /* Political distribution */
      --pol-l: #c84a47;
      --pol-c: #7a7163;
      --pol-r: #4a6ad4;

      /* Typography */
      --font-display: 'Newsreader', Georgia, 'Times New Roman', serif;
      --font-body:    'Inter Tight', -apple-system, system-ui, sans-serif;
      --font-mono:    'JetBrains Mono', ui-monospace, monospace;

      /* Spacing scale (4px base) */
      --sp-1: 4px;
      --sp-2: 8px;
      --sp-3: 12px;
      --sp-4: 16px;
      --sp-5: 24px;
      --sp-6: 32px;
      --sp-7: 48px;

      /* Radii */
      --r-sm: 6px;
      --r-md: 10px;
      --r-lg: 14px;
      --r-xl: 20px;
      --r-pill: 999px;
    }
    /* Top Stories shell gets atmospheric background + vertical padding;
       lt-shell stays plain (inherits column width, no gradient). */
    .landing-v2-shell {
      background:
        radial-gradient(ellipse 80% 50% at 20% 0%, rgba(45,212,191,0.06), transparent 60%),
        radial-gradient(ellipse 60% 40% at 90% 30%, rgba(224,82,79,0.04), transparent 60%);
      padding: var(--sp-5) 0 var(--sp-7);
    }

    /* Section header (mono label + meta) */
    :is(.landing-v2-shell, .rovat-shell) .ts-section { padding: var(--sp-5) var(--sp-5) 0; max-width: 980px; margin: 0 auto; }
    :is(.landing-v2-shell, .rovat-shell) .ts-section-header {
      display: flex; align-items: baseline; gap: var(--sp-3);
      margin-bottom: var(--sp-4);
    }
    :is(.landing-v2-shell, .rovat-shell) .ts-section-icon {
      color: var(--sphere-hu-econ); font-size: 14px;
    }
    :is(.landing-v2-shell, .rovat-shell) .ts-section-title {
      font-family: var(--font-mono); font-size: 11px;
      text-transform: uppercase; letter-spacing: 0.18em;
      color: var(--fg-1); font-weight: 600;
    }
    :is(.landing-v2-shell, .rovat-shell) .ts-section-meta {
      margin-left: auto; font-family: var(--font-mono); font-size: 10px;
      letter-spacing: 0.15em; color: var(--fg-2); text-transform: uppercase;
    }

    /* Story list — hero (single column, full width) */
    :is(.landing-v2-shell, .rovat-shell) .stories {
      display: flex; flex-direction: column; gap: var(--sp-3);
      margin-top: var(--sp-4);
    }
    /* 2-col sub-grid alatta — klasszikus echolot elrendezés */
    :is(.landing-v2-shell, .rovat-shell) .stories-grid {
      display: grid; grid-template-columns: 1fr 1fr;
      gap: var(--sp-3); margin-top: var(--sp-3);
    }
    @media (max-width: 600px) {
      :is(.landing-v2-shell, .rovat-shell) .stories-grid { grid-template-columns: 1fr; }
    }

    :is(.landing-v2-shell, .rovat-shell) .story {
      position: relative;
      display: block;
      background: var(--bg-1);
      border: 1px solid var(--line-soft);
      border-radius: var(--r-lg);
      padding: 18px 18px 16px 22px;
      overflow: hidden;
      color: var(--fg-0);
      text-decoration: none;
      transition: border-color 0.2s, transform 0.15s;
    }
    :is(.landing-v2-shell, .rovat-shell) .story:hover { border-color: var(--line); }
    :is(.landing-v2-shell, .rovat-shell) .story:active { transform: scale(0.995); }

    :is(.landing-v2-shell, .rovat-shell) .story .accent {
      position: absolute;
      left: 0; top: 14px; bottom: 14px;
      width: 3px;
      border-radius: 0 2px 2px 0;
    }

    :is(.landing-v2-shell, .rovat-shell) .story .meta-row {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 10px; gap: var(--sp-3);
    }
    :is(.landing-v2-shell, .rovat-shell) .sphere-tag {
      font-family: var(--font-mono); font-size: 10px;
      letter-spacing: 0.18em; text-transform: uppercase; font-weight: 600;
    }
    :is(.landing-v2-shell, .rovat-shell) .source-stack {
      display: inline-flex; align-items: center; gap: var(--sp-2);
      font-family: var(--font-mono); font-size: 10px;
      letter-spacing: 0.12em; color: var(--fg-2); text-transform: uppercase;
    }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots { display: inline-flex; align-items: center; }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots .src-dot {
      width: 16px; height: 16px; border-radius: 50%;
      border: 1.5px solid var(--bg-1);
      margin-left: -6px;
      background: linear-gradient(135deg, #3a4250, #1e242e);
      display: inline-block;
    }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots .src-dot:first-child { margin-left: 0; }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots .src-dot.s1 { background: linear-gradient(135deg, #e0524f, #8a2a28); }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots .src-dot.s2 { background: linear-gradient(135deg, #5b9eff, #2a4ea0); }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots .src-dot.s3 { background: linear-gradient(135deg, #f59e0b, #8a5806); }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots .src-dot.s4 { background: linear-gradient(135deg, #2dd4bf, #117a6e); }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots .src-dot.s5 { background: linear-gradient(135deg, #a78bfa, #4c2da8); }
    :is(.landing-v2-shell, .rovat-shell) .source-stack .dots .src-dot.overflow {
      background: var(--bg-3); color: var(--fg-1);
      font-size: 9px; font-family: var(--font-mono); font-weight: 600;
      display: inline-flex; align-items: center; justify-content: center;
      letter-spacing: 0;
    }

    :is(.landing-v2-shell, .rovat-shell) .story-title-v2 {
      font-family: var(--font-display);
      color: var(--fg-0);
      line-height: 1.2;
      letter-spacing: -0.015em;
      margin-bottom: var(--sp-2);
      display: block;
    }

    :is(.landing-v2-shell, .rovat-shell) .story-lead-v2 {
      color: var(--fg-1);
      font-size: 14px;
      line-height: 1.5;
      margin-bottom: var(--sp-3);
    }

    /* Political distribution bar (DISTINCT from existing .bias-bar) */
    :is(.landing-v2-shell, .rovat-shell) .pol-bar {
      display: flex; height: 28px; border-radius: var(--r-sm);
      overflow: hidden;
      font-family: var(--font-mono); font-size: 11px; font-weight: 600;
      letter-spacing: 0.05em; margin-bottom: var(--sp-3);
    }
    :is(.landing-v2-shell, .rovat-shell) .pol-bar .seg {
      display: flex; align-items: center; justify-content: center;
      color: rgba(255,255,255,0.95); padding: 0 var(--sp-2);
      white-space: nowrap;
    }
    :is(.landing-v2-shell, .rovat-shell) .pol-bar .seg.l { background: var(--pol-l); }
    :is(.landing-v2-shell, .rovat-shell) .pol-bar .seg.c { background: var(--pol-c); }
    :is(.landing-v2-shell, .rovat-shell) .pol-bar .seg.r { background: var(--pol-r); }

    /* Bottom row — time on left, reach in middle, actions on right */
    :is(.landing-v2-shell, .rovat-shell) .story-footer-v2 {
      display: flex; align-items: center; gap: var(--sp-3);
      font-family: var(--font-mono); font-size: 10px;
      color: var(--fg-2); letter-spacing: 0.1em; text-transform: uppercase;
    }
    :is(.landing-v2-shell, .rovat-shell) .story-footer-v2 time { white-space: nowrap; }
    :is(.landing-v2-shell, .rovat-shell) .story-footer-v2 .footer-reach {
      margin-left: auto; display: inline-flex; align-items: center;
      gap: var(--sp-2); text-transform: none; letter-spacing: 0.04em;
      font-size: 11px; color: var(--fg-1);
    }
    :is(.landing-v2-shell, .rovat-shell) .story-footer-v2 .footer-reach .reach-num {
      color: var(--sphere-hu-econ); font-weight: 700; font-size: 12px;
    }
    :is(.landing-v2-shell, .rovat-shell) .story-footer-v2 .footer-reach .reach-label {
      text-transform: uppercase; letter-spacing: 0.16em; font-size: 9px;
      opacity: 0.7;
    }
    :is(.landing-v2-shell, .rovat-shell) .story-footer-v2 .footer-reach .reach-window {
      color: var(--fg-2); font-size: 10px;
    }
    :is(.landing-v2-shell, .rovat-shell) .story-footer-v2 .footer-reach .reach-country {
      font-size: 11px;
    }

    /* HERO variant — first card, much larger */
    :is(.landing-v2-shell, .rovat-shell) .story.hero {
      padding: 24px 22px 20px 26px;
      background:
        linear-gradient(180deg, rgba(224,82,79,0.05), transparent 40%),
        var(--bg-2);
      border: 1px solid var(--line);
    }
    :is(.landing-v2-shell, .rovat-shell) .story.hero .accent { width: 4px; top: 18px; bottom: 18px; }
    :is(.landing-v2-shell, .rovat-shell) .story.hero .story-title-v2 {
      font-size: 28px; font-weight: 600; line-height: 1.15;
    }
    :is(.landing-v2-shell, .rovat-shell) .story.hero .story-lead-v2 { font-size: 15px; }
    :is(.landing-v2-shell, .rovat-shell) .story.hero .source-stack { font-size: 11px; color: var(--fg-1); }
    :is(.landing-v2-shell, .rovat-shell) .story.hero .source-stack .src-count { color: var(--fg-0); font-weight: 600; }

    /* SUB variant — smaller cards */
    :is(.landing-v2-shell, .rovat-shell) .story.sub .story-title-v2 {
      font-size: 19px; font-weight: 500; line-height: 1.25;
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub .story-lead-v2 {
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      overflow: hidden;
      font-size: 13px; margin-bottom: var(--sp-3);
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub .pol-bar { height: 22px; font-size: 10px; }

    /* COMPACT sub variant — lépcsős méretcsökkentés a 4. sub után.
       Cím-only kártya, nincs lead-szöveg, kisebb font + tighter pol-bar. */
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact {
      padding: 12px 12px 12px 16px;
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .accent {
      top: 10px; bottom: 10px;
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .meta-row {
      margin-bottom: var(--sp-2);
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .sphere-tag { font-size: 9px; }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .source-stack { font-size: 9px; }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .source-stack .dots .src-dot {
      width: 12px; height: 12px; margin-left: -4px;
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .story-title-v2 {
      font-size: 15px; font-weight: 500; line-height: 1.3;
      margin-bottom: var(--sp-2);
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .pol-bar {
      height: 16px; font-size: 9px; margin-bottom: var(--sp-2);
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .story-footer-v2 {
      font-size: 9px;
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .story-footer-v2 .footer-reach {
      font-size: 10px;
    }
    :is(.landing-v2-shell, .rovat-shell) .story.sub.compact .story-footer-v2 .footer-reach .reach-num {
      font-size: 11px;
    }

    /* Entry fade-up animation */
    @keyframes fadeUpV2 {
      from { opacity: 0; transform: translateY(8px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    :is(.landing-v2-shell, .rovat-shell) .story { animation: fadeUpV2 0.5s ease-out both; }
    :is(.landing-v2-shell, .rovat-shell) .story:nth-child(1) { animation-delay: 0.06s; }
    :is(.landing-v2-shell, .rovat-shell) .story:nth-child(2) { animation-delay: 0.12s; }
    :is(.landing-v2-shell, .rovat-shell) .story:nth-child(3) { animation-delay: 0.18s; }
    :is(.landing-v2-shell, .rovat-shell) .story:nth-child(4) { animation-delay: 0.24s; }
    :is(.landing-v2-shell, .rovat-shell) .story:nth-child(5) { animation-delay: 0.30s; }
    :is(.landing-v2-shell, .rovat-shell) .story:nth-child(6) { animation-delay: 0.36s; }
    :is(.landing-v2-shell, .rovat-shell) .story:nth-child(7) { animation-delay: 0.42s; }
    :is(.landing-v2-shell, .rovat-shell) .story:nth-child(8) { animation-delay: 0.48s; }

    /* Responsive */
    @media (max-width: 700px) {
      :is(.landing-v2-shell, .rovat-shell) .ts-section { padding: var(--sp-4) var(--sp-4) 0; }
      :is(.landing-v2-shell, .rovat-shell) .story { padding: 14px 14px 14px 18px; }
      :is(.landing-v2-shell, .rovat-shell) .story.hero { padding: 18px 16px 16px 22px; }
      :is(.landing-v2-shell, .rovat-shell) .story.hero .story-title-v2 { font-size: 24px; }
    }

    /* =====================================================================
       LANDING V2 — HELYI TRENDING (lt-shell)
       3 vizuálisan elkülönülő szekció — KULCSSZAVAK (Wikipedia top, sima
       lista), HÍREK (Google News, kis kártyákban lead-del), SZFÉRA
       VELOCITY (sphere név + ratio, sima lista). Az eredeti szélességet
       megtartjuk — semmi extra padding a shell-en.
       ===================================================================== */
    .lt-shell .lt-section { margin-bottom: var(--sp-5); }
    .lt-shell .lt-section:last-child { margin-bottom: 0; }
    .lt-shell .lt-section-label {
      font-family: var(--font-mono);
      font-size: 10px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.18em;
      color: var(--fg-2);
      margin-bottom: var(--sp-3);
      padding-bottom: var(--sp-2);
      border-bottom: 1px solid var(--line-soft);
      display: flex; align-items: center; gap: var(--sp-2);
    }
    .lt-shell .lt-section-label .lt-icon {
      color: var(--sphere-hu-econ); font-size: 11px;
    }
    .lt-shell .lt-section-sub {
      display: block;
      font-family: var(--font-body);
      font-size: 11px;
      font-style: italic;
      color: var(--fg-2);
      margin: -8px 0 var(--sp-3) 0;
      line-height: 1.4;
    }

    /* Sima text-sor lista (Wiki, Velocity) — közeli az eredetihez, csak
       v2 tipográfia. NEM kártya, csak border-bottom separator. */
    .lt-shell .lt-list {
      list-style: none; padding: 0; margin: 0;
    }
    .lt-shell .lt-row {
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }
    .lt-shell .lt-row:last-child { border-bottom: none; }
    .lt-shell .lt-row a {
      display: flex; align-items: baseline; gap: var(--sp-3);
      padding: 8px 0;
      text-decoration: none; color: var(--fg-0);
      font-family: var(--font-body); font-size: 13px;
      line-height: 1.35;
      transition: color 0.15s;
    }
    .lt-shell .lt-row a:hover { color: var(--sphere-hu-econ); }
    .lt-shell .lt-row-title {
      flex: 1; min-width: 0;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .lt-shell .lt-row-meta {
      font-family: var(--font-mono);
      font-size: 11px; color: var(--fg-2);
      white-space: nowrap; letter-spacing: 0.04em;
    }
    .lt-shell .lt-row-velocity a { font-family: var(--font-mono); font-size: 12px; letter-spacing: 0.04em; }
    .lt-shell .lt-row-ratio {
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 2px 8px; border-radius: var(--r-sm);
      background: var(--bg-3); color: var(--fg-1);
      letter-spacing: 0.04em;
    }
    .lt-shell .lt-row-ratio.status-spike {
      background: rgba(224,82,79,0.18); color: var(--sphere-hu-pol);
    }
    .lt-shell .lt-row-ratio.status-rising {
      background: rgba(245,158,11,0.18); color: var(--sphere-hu-soc);
    }
    .lt-shell .lt-row-ratio.status-count {
      background: var(--bg-3); color: var(--fg-2);
      font-weight: 400;
    }

    /* HÍREK — kis kártyák lead-del (új v2 stílus a hírecskéknek) */
    .lt-shell .lt-news-cards {
      list-style: none; padding: 0; margin: 0;
      display: flex; flex-direction: column; gap: var(--sp-2);
    }
    .lt-shell .lt-news-card {
      background: var(--bg-1);
      border: 1px solid var(--line-soft);
      border-radius: var(--r-md);
      transition: border-color 0.15s, transform 0.1s;
    }
    .lt-shell .lt-news-card:hover { border-color: var(--line); }
    .lt-shell .lt-news-card:active { transform: scale(0.995); }
    .lt-shell .lt-news-card a {
      display: block;
      padding: 10px 12px;
      text-decoration: none; color: var(--fg-0);
    }
    .lt-shell .lt-news-title {
      font-family: var(--font-body);
      font-size: 13px; font-weight: 600;
      line-height: 1.3; margin: 0 0 4px 0;
      color: var(--fg-0);
    }
    .lt-shell .lt-news-lead {
      font-family: var(--font-body);
      font-size: 11.5px; line-height: 1.4;
      color: var(--fg-1);
      margin: 0 0 6px 0;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .lt-shell .lt-news-host {
      font-family: var(--font-mono);
      font-size: 9px; color: var(--fg-2);
      letter-spacing: 0.1em;
      text-transform: lowercase;
    }

    .lt-shell .lt-empty {
      color: var(--fg-3); font-style: italic;
      padding: var(--sp-2) 0; list-style: none;
    }

    /* =====================================================================
       LANDING V2 — LIVE TV PANEL (.tv-panel-wrap)
       A bal landing-col-ban a Top Stories ALATT. 9 csatorna, HLS+YT.
       A logikát a /static/echolot-tv.js viszi.
       ===================================================================== */
    .tv-panel-wrap { padding-top: 0; padding-bottom: var(--sp-5); }
    .tv-panel-wrap .ts-section { padding: var(--sp-5) var(--sp-5) 0; max-width: none; }

    :is(.landing-v2-shell, .rovat-shell) .echolot-tv {
      background: var(--bg-1);
      border: 1px solid var(--line-soft);
      border-radius: var(--r-lg);
      overflow: hidden;
      margin-top: var(--sp-4);
    }

    :is(.landing-v2-shell, .rovat-shell) .tv-tabs {
      display: flex;
      gap: var(--sp-1);
      padding: var(--sp-3) var(--sp-3) 0;
      overflow-x: auto;
      border-bottom: 1px solid var(--line-soft);
      scrollbar-width: thin;
      scrollbar-color: var(--line) transparent;
      /* min-width: 0 a flex-item-eken, hogy a hosszú tab-strip ne feszítse
         szét a grid-oszlopot — ne ki, hanem belül scrollozzon. */
      min-width: 0;
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-tabs::-webkit-scrollbar { height: 4px; }
    :is(.landing-v2-shell, .rovat-shell) .tv-tabs::-webkit-scrollbar-thumb { background: var(--line); border-radius: 2px; }
    :is(.landing-v2-shell, .rovat-shell) .tv-tabs::-webkit-scrollbar-track { background: transparent; }

    :is(.landing-v2-shell, .rovat-shell) .tv-tab {
      flex: 0 0 auto;
      font-family: var(--font-mono);
      font-size: 10px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      font-weight: 600;
      padding: var(--sp-2) var(--sp-3);
      background: transparent;
      color: var(--fg-2);
      border: 1px solid var(--line-soft);
      border-radius: var(--r-md) var(--r-md) 0 0;
      transition: color 0.15s, border-color 0.15s, background 0.15s;
      margin-bottom: -1px;
      cursor: pointer;
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-tab:hover { color: var(--fg-1); border-color: var(--line); }
    :is(.landing-v2-shell, .rovat-shell) .tv-tab.is-active {
      color: var(--fg-0);
      border-color: var(--sphere-hu-econ);
      background: rgba(45,212,191,0.08);
    }

    :is(.landing-v2-shell, .rovat-shell) .tv-player-wrap {
      position: relative;
      background: var(--bg-0);
      aspect-ratio: 16 / 9;
      width: 100%;
      overflow: hidden;
    }
    :is(.landing-v2-shell, .rovat-shell) #tv-video,
    :is(.landing-v2-shell, .rovat-shell) #tv-iframe {
      position: absolute; inset: 0;
      width: 100%; height: 100%; border: 0;
      background: var(--bg-0);
      display: none;
    }
    :is(.landing-v2-shell, .rovat-shell) #tv-video.is-active,
    :is(.landing-v2-shell, .rovat-shell) #tv-iframe.is-active { display: block; }

    :is(.landing-v2-shell, .rovat-shell) .tv-offline {
      position: absolute; inset: 0;
      display: flex; align-items: center; justify-content: center;
      font-family: var(--font-mono);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      color: var(--fg-2);
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-offline[hidden] { display: none; }

    :is(.landing-v2-shell, .rovat-shell) .tv-meta {
      display: flex; align-items: center;
      gap: var(--sp-3);
      padding: var(--sp-2) var(--sp-3);
      border-top: 1px solid var(--line-soft);
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--fg-2);
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-channel-name {
      font-family: var(--font-display);
      font-weight: 500;
      font-size: 14px;
      color: var(--fg-0);
      text-transform: none;
      letter-spacing: 0;
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-source-badge {
      font-family: var(--font-mono);
      font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase;
      font-weight: 600;
      padding: 2px var(--sp-2);
      border-radius: var(--r-sm);
      background: var(--bg-3); color: var(--fg-1);
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-source-badge.badge-hls { background: rgba(45,212,191,0.18); color: var(--sphere-hu-econ); }
    :is(.landing-v2-shell, .rovat-shell) .tv-source-badge.badge-yt  { background: rgba(224,82,79,0.18); color: var(--sphere-hu-pol); }
    :is(.landing-v2-shell, .rovat-shell) .tv-source-badge.badge-fb  { background: rgba(245,158,11,0.18); color: var(--sphere-hu-soc); }
    :is(.landing-v2-shell, .rovat-shell) .tv-source-badge.badge-off { background: var(--bg-3); color: var(--fg-2); }

    :is(.landing-v2-shell, .rovat-shell) .tv-mute-btn {
      margin-left: auto;
      background: transparent;
      border: 1px solid var(--line-soft);
      border-radius: var(--r-sm);
      padding: var(--sp-1) var(--sp-3);
      color: var(--fg-1);
      font-size: 14px;
      cursor: pointer;
      transition: border-color 0.15s, color 0.15s;
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-mute-btn:hover { border-color: var(--fg-2); color: var(--fg-0); }

    /* Minimize / kibont gomb a section-header jobb szélén */
    :is(.landing-v2-shell, .rovat-shell) .tv-collapse-btn {
      margin-left: var(--sp-2);
      background: transparent;
      border: 1px solid var(--line-soft);
      border-radius: var(--r-sm);
      width: 24px;
      height: 22px;
      color: var(--fg-1);
      font-size: 13px;
      line-height: 1;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: border-color 0.15s, color 0.15s, background 0.15s;
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-collapse-btn:hover {
      border-color: var(--sphere-hu-econ); color: var(--fg-0);
      background: rgba(45,212,191,0.08);
    }
    /* Lekicsinyített állapot: csak a section-header látszik, a player+tabs+meta
       eltűnik. A gomb ikonja "▷" (kibont) lesz. */
    .tv-panel-wrap.is-collapsed .echolot-tv {
      max-height: 0;
      overflow: hidden;
      border-color: transparent;
      margin-top: 0;
      opacity: 0;
      transition: max-height 0.25s ease, opacity 0.2s, margin-top 0.25s;
    }
    .tv-panel-wrap:not(.is-collapsed) .echolot-tv {
      max-height: 1000px;
      transition: max-height 0.3s ease, opacity 0.2s;
    }

    /* Pop-out gomb a section-header-en */
    :is(.landing-v2-shell, .rovat-shell) .tv-popout-btn {
      margin-left: var(--sp-2);
      background: transparent;
      border: 1px solid var(--line-soft);
      border-radius: var(--r-sm);
      width: 24px;
      height: 22px;
      color: var(--fg-1);
      font-size: 12px;
      line-height: 1;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: border-color 0.15s, color 0.15s, background 0.15s;
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-popout-btn:hover {
      border-color: var(--sphere-hu-econ); color: var(--fg-0);
      background: rgba(45,212,191,0.08);
    }

    /* ════════════════════════════════════════════════════════════════════
       POPPED-OUT ÁLLAPOT — az egész oldal FÖLÉ helyezve, drag-elhető,
       jobb-alsó sarokban natív CSS resize-handle. Pozíció+méret
       localStorage-ban perzisztálva.
       ════════════════════════════════════════════════════════════════════ */
    .tv-panel-wrap.is-popped-out {
      position: fixed;
      top: 80px;
      left: auto;
      right: 80px;
      width: 480px;
      height: 360px;
      z-index: 9999;
      padding: 0;
      margin: 0;
      background: var(--bg-1);
      border: 1px solid var(--line);
      border-radius: var(--r-lg);
      box-shadow: 0 16px 48px rgba(0,0,0,0.55), 0 0 0 1px rgba(45,212,191,0.15);
      overflow: hidden;
      resize: both;
      min-width: 320px;
      min-height: 240px;
      max-width: 95vw;
      max-height: 95vh;
    }
    /* A wrapper section veszi át a teljes terület-méretezést */
    .tv-panel-wrap.is-popped-out .ts-section {
      padding: 0;
      max-width: none;
      height: 100%;
      display: flex;
      flex-direction: column;
    }
    /* A section-header lesz a drag-handle */
    .tv-panel-wrap.is-popped-out .ts-section-header {
      cursor: move;
      user-select: none;
      padding: 10px 14px;
      background: var(--bg-2);
      border-bottom: 1px solid var(--line-soft);
      margin-bottom: 0;
      flex-shrink: 0;
    }
    /* A player wrapper kitölti a maradék vertikális teret —
       aspect-ratio-t felülírjuk, hogy a felhasználó szabadon méretezhessen. */
    .tv-panel-wrap.is-popped-out .echolot-tv {
      flex: 1;
      min-height: 0;
      max-height: none;
      margin-top: 0;
      border: 0;
      border-radius: 0;
      display: flex;
      flex-direction: column;
    }
    .tv-panel-wrap.is-popped-out .tv-tabs {
      flex-shrink: 0;
    }
    .tv-panel-wrap.is-popped-out .tv-player-wrap {
      flex: 1;
      min-height: 0;
      aspect-ratio: unset;
    }
    .tv-panel-wrap.is-popped-out .tv-meta {
      flex-shrink: 0;
    }
    /* Pop-out közben a collapse-gomb értelmét veszti — elrejtjük */
    .tv-panel-wrap.is-popped-out .tv-collapse-btn { display: none; }
    /* A popout-gomb ikonja "↘" (dock back) lesz */
    .tv-panel-wrap.is-popped-out .tv-popout-btn {
      border-color: var(--sphere-hu-econ);
      color: var(--sphere-hu-econ);
      background: rgba(45,212,191,0.12);
    }

    /* Fullscreen-gomb — ugyanolyan mint a popout/collapse */
    :is(.landing-v2-shell, .rovat-shell) .tv-fullscreen-btn {
      margin-left: var(--sp-2);
      background: transparent;
      border: 1px solid var(--line-soft);
      border-radius: var(--r-sm);
      width: 24px;
      height: 22px;
      color: var(--fg-1);
      font-size: 12px;
      line-height: 1;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: border-color 0.15s, color 0.15s, background 0.15s;
    }
    :is(.landing-v2-shell, .rovat-shell) .tv-fullscreen-btn:hover {
      border-color: var(--sphere-hu-econ); color: var(--fg-0);
      background: rgba(45,212,191,0.08);
    }

    /* ════════════════════════════════════════════════════════════════════
       FULLSCREEN ÁLLAPOT — natív Fullscreen API. A panel a teljes
       böngészőablakot kitölti, Esc-re kilép. A többi action-gomb
       (popout, collapse) elrejtve, csak a mute marad elérhető.
       ════════════════════════════════════════════════════════════════════ */
    .tv-panel-wrap:fullscreen {
      background: var(--bg-0);
      padding: 0;
      margin: 0;
      border: 0;
      border-radius: 0;
      width: 100vw;
      height: 100vh;
    }
    .tv-panel-wrap:fullscreen .ts-section {
      padding: 0;
      max-width: none;
      height: 100%;
      display: flex;
      flex-direction: column;
    }
    .tv-panel-wrap:fullscreen .ts-section-header {
      padding: 10px 16px;
      background: var(--bg-2);
      border-bottom: 1px solid var(--line-soft);
      margin-bottom: 0;
      flex-shrink: 0;
      cursor: default;
    }
    .tv-panel-wrap:fullscreen .echolot-tv {
      flex: 1;
      min-height: 0;
      max-height: none;
      margin-top: 0;
      border: 0;
      border-radius: 0;
      display: flex;
      flex-direction: column;
    }
    .tv-panel-wrap:fullscreen .tv-tabs { flex-shrink: 0; }
    .tv-panel-wrap:fullscreen .tv-player-wrap {
      flex: 1;
      min-height: 0;
      aspect-ratio: unset;
    }
    .tv-panel-wrap:fullscreen .tv-meta { flex-shrink: 0; }
    /* Fullscreen alatt a popout + collapse értelmetlen — elrejtjük */
    .tv-panel-wrap:fullscreen .tv-popout-btn,
    .tv-panel-wrap:fullscreen .tv-collapse-btn { display: none; }
    /* A fullscreen-gomb látványosabb formára vált — szöveg + zöld háttér,
       hogy a felhasználó ne csak Esc-re számítson a kilépéshez. */
    .tv-panel-wrap:fullscreen .tv-fullscreen-btn {
      width: auto;
      height: auto;
      padding: 6px 14px;
      font-size: 11px;
      font-family: var(--font-mono);
      font-weight: 600;
      letter-spacing: 0.08em;
      border-color: var(--sphere-hu-econ);
      color: var(--bg-0);
      background: var(--sphere-hu-econ);
    }
    .tv-panel-wrap:fullscreen .tv-fullscreen-btn:hover {
      background: #34e6cf;
      color: var(--bg-0);
    }

    /* =====================================================================
       YOUTUBE TRENDING PANEL — jobb landing-col, blindspot ALATT
       Kis kártyák thumbnaillel; cím + csatorna · nézettség. A Helyi
       Trending HÍREK kártyáihoz hasonló stílus, de thumbnail + view-count.
       ===================================================================== */
    .yt-shell { margin-top: var(--sp-5); }
    .yt-shell .yt-section-label {
      font-family: var(--font-mono);
      font-size: 10px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.18em;
      color: var(--fg-2);
      margin-bottom: var(--sp-3);
      padding-bottom: var(--sp-2);
      border-bottom: 1px solid var(--line-soft);
      display: flex; align-items: center; gap: var(--sp-2);
    }
    .yt-shell .yt-icon {
      color: var(--sphere-hu-pol); font-size: 11px;
    }
    .yt-shell .yt-cards {
      list-style: none; padding: 0; margin: 0;
      display: flex; flex-direction: column; gap: var(--sp-2);
    }
    .yt-shell .yt-card {
      background: var(--bg-1);
      border: 1px solid var(--line-soft);
      border-radius: var(--r-md);
      transition: border-color 0.15s, transform 0.1s;
    }
    .yt-shell .yt-card:hover { border-color: var(--line); }
    .yt-shell .yt-card:active { transform: scale(0.995); }
    .yt-shell .yt-card a {
      display: flex;
      gap: var(--sp-2);
      padding: 8px;
      text-decoration: none;
      color: var(--fg-0);
      align-items: flex-start;
    }
    .yt-shell .yt-thumb {
      flex-shrink: 0;
      width: 80px;
      height: 45px;
      object-fit: cover;
      border-radius: var(--r-sm);
      background: var(--bg-0);
    }
    .yt-shell .yt-thumb-empty {
      display: flex; align-items: center; justify-content: center;
      color: var(--sphere-hu-pol);
      font-size: 16px;
    }
    .yt-shell .yt-card-body {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .yt-shell .yt-title {
      font-family: var(--font-body);
      font-size: 12px;
      font-weight: 600;
      line-height: 1.3;
      margin: 0;
      color: var(--fg-0);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .yt-shell .yt-desc {
      font-family: var(--font-body);
      font-size: 11px;
      line-height: 1.4;
      color: var(--fg-1);
      margin: 0;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .yt-shell .yt-meta {
      font-family: var(--font-mono);
      font-size: 9px;
      color: var(--fg-2);
      letter-spacing: 0.04em;
      text-transform: lowercase;
    }
    /* Transcript-actions row a thumbnail-és-szöveg link ALATT */
    .yt-shell .yt-actions {
      display: flex;
      align-items: center;
      gap: var(--sp-2);
      padding: 4px 8px 8px 8px;
      border-top: 1px solid var(--line-soft);
      margin-top: 0;
    }
    .yt-shell .yt-transcript-btn {
      flex: 1;
      background: transparent;
      border: 1px solid var(--line-soft);
      border-radius: var(--r-sm);
      padding: 4px 8px;
      font-family: var(--font-mono);
      font-size: 9px;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--fg-2);
      cursor: pointer;
      transition: border-color 0.15s, color 0.15s, background 0.15s;
    }
    .yt-shell .yt-transcript-btn:hover {
      border-color: var(--sphere-hu-econ);
      color: var(--fg-0);
      background: rgba(45,212,191,0.08);
    }
    .yt-shell .yt-transcript-btn.is-expanded {
      border-color: var(--sphere-hu-econ);
      color: var(--sphere-hu-econ);
      background: rgba(45,212,191,0.12);
    }
    .yt-shell .yt-transcript-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      border: 1px solid var(--line-soft);
      border-radius: var(--r-sm);
      color: var(--fg-2);
      text-decoration: none;
      font-size: 11px;
      transition: border-color 0.15s, color 0.15s, background 0.15s;
    }
    .yt-shell .yt-transcript-link:hover {
      border-color: var(--sphere-hu-econ);
      color: var(--fg-0);
      background: rgba(45,212,191,0.08);
    }
    /* Inline-expanded transcript panel — a kártyán belül, scrollozható */
    .yt-shell .yt-transcript-panel {
      max-height: 280px;
      overflow-y: auto;
      padding: var(--sp-3) var(--sp-3);
      border-top: 1px solid var(--line-soft);
      background: var(--bg-0);
      font-family: var(--font-body);
      font-size: 12px;
      line-height: 1.55;
      color: var(--fg-1);
      white-space: pre-wrap;
    }
    .yt-shell .yt-transcript-panel[hidden] { display: none; }
    .yt-shell .yt-transcript-panel.is-loading {
      color: var(--fg-3); font-style: italic;
    }
    /* "Nincs leirat" — normál eset, sok YT-videónak nincs feliratja.
       Neutral szürke, NEM piros — nem hiba. */
    .yt-shell .yt-transcript-panel.is-unavailable {
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: lowercase;
      text-align: center;
      padding: 14px var(--sp-3);
      white-space: normal;
    }
    /* Tényleges hiba — pol-pink, mint az eddig is. */
    .yt-shell .yt-transcript-panel.is-error {
      color: var(--sphere-hu-pol);
      font-style: italic;
      background: rgba(224,82,79,0.04);
    }
    /* Scrollbar styling */
    .yt-shell .yt-transcript-panel::-webkit-scrollbar { width: 6px; }
    .yt-shell .yt-transcript-panel::-webkit-scrollbar-thumb {
      background: var(--line); border-radius: 3px;
    }
    .yt-shell .yt-transcript-panel::-webkit-scrollbar-track { background: transparent; }
    .yt-shell .yt-empty {
      color: var(--fg-3);
      font-style: italic;
      padding: var(--sp-3);
      border: 1px dashed var(--line-soft);
      border-radius: var(--r-md);
      font-size: 12px;
      line-height: 1.4;
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

    # YouTube trending — region-aware. Ha nincs YOUTUBE_API_KEY env, None
    # jön vissza és a renderelt panel "no-data" magyarázó-kártyát mutat.
    yt_region = _lang_to_yt_region(lang)
    try:
        yt_videos = await _yt_trending_videos(region=yt_region, count=8, category="all")
    except Exception as exc:
        log.warning("youtube_trending failed (region=%s): %s", yt_region, exc)
        yt_videos = None

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

    # Rovatok: Tech / Sport / Bulvár. Először lang-szűrt, ha üres → all-lang.
    def _rovat(spheres: frozenset[str], label: str) -> list[dict]:
        try:
            res = cluster_top_stories(db_path, hours=24, min_sources=1, limit=6,
                                       lang=lang, sphere_filter=spheres)
            if not res:
                res = cluster_top_stories(db_path, hours=24, min_sources=1, limit=6,
                                           lang=None, sphere_filter=spheres)
            return res
        except Exception as exc:
            log.warning("rovat %s failed: %s", label, exc)
            return []

    tech_stories = _rovat(TECH_SPHERES, "tech")
    sport_stories = _rovat(SPORT_SPHERES, "sport")
    tabloid_stories = _rovat(TABLOID_SPHERES, "tabloid")
    economy_stories = _rovat(ECONOMY_SPHERES, "economy")

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
    yt_trending_html = _render_youtube_trending(yt_videos, lang, yt_region)

    title_html = _escape(t("landing.hero_title", lang))
    legacy_label = _escape(t("landing.legacy_view", lang))
    dashboard_label = _escape(t("landing.dashboard_link", lang))
    section_top = _escape(t("landing.section.top_stories", lang))
    section_local = _escape(t("landing.section.local", lang))
    section_blind = _escape(t("landing.section.blindspot", lang))
    section_tech = _escape(t("landing.section.tech", lang))
    section_sport = _escape(t("landing.section.sport", lang))
    section_tabloid = _escape(t("landing.section.tabloid", lang))
    section_economy = _escape(t("landing.section.economy", lang))

    tech_html = _render_rovat(tech_stories, lang)
    sport_html = _render_rovat(sport_stories, lang)
    tabloid_html = _render_rovat(tabloid_stories, lang)
    economy_html = _render_rovat(economy_stories, lang)

    # Live TV panel — bal landing-col, Top Stories ALATT (Kommandant döntés)
    tv_panel_html = _render_tv_panel()

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
      <h2>{section_top}</h2>
      {top_stories_html}
    </div>
    <div class="landing-col">
      <h2>{section_local} · {_escape(local.get('geo', {}).get('gnews', ''))}</h2>
      {local_trending_html}
    </div>
    <div class="landing-col">
      {tv_panel_html}
      <h2>Egyoldalas hírek</h2>
      {blindspot_html}
      {yt_trending_html}
    </div>
  </div>

  <div class="rovatok-grid">
    <div class="rovat-col">
      <h2>{section_tech}</h2>
      {tech_html}
    </div>
    <div class="rovat-col">
      <h2>{section_economy}</h2>
      {economy_html}
    </div>
    <div class="rovat-col">
      <h2>{section_sport}</h2>
      {sport_html}
    </div>
    <div class="rovat-col">
      <h2>{section_tabloid}</h2>
      {tabloid_html}
    </div>
  </div>

  <div class="legacy-link">
    <a href="/landing-classic?lang={lang}">▷ {legacy_label} ◁</a>
    <span> · </span>
    <a href="/dashboard?lang={lang}">▷ {dashboard_label} ◁</a>
  </div>

  <script src="/static/echolot-tv.js" defer></script>
  <script src="/static/echolot-yt-transcript.js" defer></script>
</body>
</html>""", lang)
