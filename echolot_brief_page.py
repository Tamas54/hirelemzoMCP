"""Vezetői brief UI — landing-blokk + /brief oldal napi archívummal.

A tartalmat az echolot_daily_brief modul állítja elő és cache-eli; itt
csak renderelés van. A landing-blokk 3 sorra csukott (line-clamp), a
kattintás a /brief oldalra visz, ahol a teljes brief + a korábbi napok
érhetők el — a témák trend-jelölővel (új/erősödik/stabil/laposodik), így
követhető, melyik téma tör előre és melyik laposodik nap-nap után.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from echolot_daily_brief import (
    get_brief, is_stale, kick_async, list_dates, today_str,
)
from echolot_i18n import t
from echolot_dashboard import (
    _BASE_STYLES,
    _augment_block_html,
    _augment_strip_css,
    _request_lang,
    _escape,
)
from echolot_theme import (
    theme_html_attr,
    DAY_THEME_CSS,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_JS,
    theme_toggle_html,
)
from echolot_seo import public_origin, seo_head_html

log = logging.getLogger("echolot.brief_page")

# trend → (ikon, CSS-osztály)
_TREND_ICON = {
    "new":    ("●", "trend-new"),
    "rising": ("▲", "trend-rising"),
    "steady": ("→", "trend-steady"),
    "fading": ("▼", "trend-fading"),
}

_BRIEF_CSS = """
.brief-block {
  display: block; text-decoration: none; color: inherit;
  border: 1px solid var(--border, rgba(255,255,255,0.1));
  border-left: 3px solid var(--accent, #6cb6ff);
  border-radius: 12px; padding: 0.9rem 1.1rem; margin: 0 0 1.2rem;
  background: var(--bg-card, rgba(255,255,255,0.02));
  transition: border-color 0.15s, background 0.15s;
}
.brief-block:hover { border-color: var(--accent, #6cb6ff); }
.brief-block-label {
  font-family: 'JetBrains Mono', monospace; font-size: 0.68rem;
  letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--accent, #6cb6ff); margin-bottom: 0.45rem;
  display: flex; align-items: baseline; gap: 0.6em; flex-wrap: wrap;
}
.brief-block-label .brief-date { color: var(--text-dim); letter-spacing: 0.06em; }
.brief-block-headline {
  font-size: 1.02rem; font-weight: 650; line-height: 1.35; margin: 0 0 0.35rem;
}
.brief-block-lead {
  font-size: 0.85rem; line-height: 1.5; color: var(--text-dim); margin: 0;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
  overflow: hidden;
}
.brief-block-more {
  display: inline-block; margin-top: 0.5rem; font-size: 0.78rem;
  color: var(--accent, #6cb6ff);
}
.brief-page-wrap { max-width: 820px; margin: 0 auto 3rem; padding: 0 1rem; }
.brief-page-wrap h1 {
  font-size: 1.15rem; text-transform: uppercase; letter-spacing: 0.2em;
  font-family: 'JetBrains Mono', monospace; color: var(--text-dim);
  border-bottom: 1px solid var(--border); padding-bottom: 0.5rem;
}
.brief-page-sub { font-size: 0.8rem; color: var(--text-dim); margin: 0.4rem 0 1.2rem; }
.brief-datenav {
  display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0 0 1.4rem;
  font-family: 'JetBrains Mono', monospace; font-size: 0.78rem;
}
.brief-datenav a, .brief-datenav span.cur {
  padding: 0.3rem 0.7rem; border-radius: 999px; text-decoration: none;
  border: 1px solid var(--border); color: var(--text-dim);
}
.brief-datenav a:hover { color: var(--accent, #6cb6ff); border-color: var(--accent, #6cb6ff); }
.brief-datenav span.cur { color: var(--accent, #6cb6ff); border-color: var(--accent, #6cb6ff); }
.brief-headline { font-size: 1.45rem; font-weight: 700; line-height: 1.3; margin: 0 0 0.6rem; }
.brief-lead { font-size: 1rem; line-height: 1.6; color: var(--text); opacity: 0.92; margin: 0 0 1.4rem; }
.brief-topic {
  border: 1px solid var(--border); border-radius: 10px;
  padding: 0.8rem 1rem; margin: 0 0 0.7rem;
  background: var(--bg-card, rgba(255,255,255,0.02));
}
.brief-topic-head { display: flex; align-items: baseline; gap: 0.6em; flex-wrap: wrap; }
.brief-topic-title { font-weight: 650; font-size: 0.98rem; }
.brief-topic-title a { color: inherit; text-decoration: none; }
.brief-topic-title a:hover { color: var(--accent, #6cb6ff); }
.brief-trend {
  font-family: 'JetBrains Mono', monospace; font-size: 0.68rem;
  padding: 0.12rem 0.55rem; border-radius: 999px; letter-spacing: 0.08em;
  text-transform: uppercase; white-space: nowrap;
}
.trend-new    { color: #58a6ff; border: 1px solid #58a6ff55; }
.trend-rising { color: #3fb950; border: 1px solid #3fb95055; }
.trend-steady { color: #8b949e; border: 1px solid #8b949e44; }
.trend-fading { color: #d29922; border: 1px solid #d2992255; }
.brief-topic-summary { font-size: 0.86rem; line-height: 1.55; color: var(--text-dim); margin: 0.4rem 0 0; }
.brief-outlook {
  margin-top: 1.4rem; padding: 0.9rem 1.1rem; border-radius: 10px;
  border: 1px dashed var(--border); font-size: 0.88rem; line-height: 1.55;
  color: var(--text-dim);
}
.brief-local-title {
  margin: 2rem 0 0.6rem; padding-top: 1.2rem; border-top: 2px solid var(--border);
  font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.1em;
  color: var(--primary); font-weight: 700;
}
.brief-outlook strong { color: var(--text); }
.brief-meta { margin-top: 1rem; font-size: 0.7rem; color: var(--text-dim); font-family: 'JetBrains Mono', monospace; }
.brief-pending { padding: 2rem 1rem; text-align: center; color: var(--text-dim); }
"""


def _fmt_date_human(date_s: str, lang: str) -> str:
    try:
        d = datetime.fromisoformat(date_s).date()
    except (ValueError, TypeError):
        return date_s
    if lang == "hu":
        months = ("január", "február", "március", "április", "május", "június",
                  "július", "augusztus", "szeptember", "október", "november", "december")
        return f"{d.year}. {months[d.month - 1]} {d.day}."
    return d.strftime("%Y-%m-%d")


def _trend_badge(trend: str, lang: str) -> str:
    icon, cls = _TREND_ICON.get(trend, _TREND_ICON["steady"])
    label = t(f"brief.trend.{trend}", lang)
    return f'<span class="brief-trend {cls}">{icon} {_escape(label)}</span>'


def render_brief_landing_block(db_path: str, lang: str) -> str:
    """Csukott (3 soros) brief-blokk a landing Top sztorik fölé.

    Ha a mai brief hiányzik/öreg, háttérben elindítja a generálást és a
    legutóbbi elérhetőt mutatja (vagy semmit). SOHA nem blokkol."""
    d = today_str()
    brief = get_brief(db_path, d, lang)
    if is_stale(brief, d):
        kick_async(db_path, d, lang)
    if not brief or brief.get("status") != "ok":
        # fallback: legutóbbi kész nap (a tegnapi brief jobb, mint a semmi)
        for prev in list_dates(db_path, limit=3):
            b2 = get_brief(db_path, prev, lang)
            if b2 and b2.get("status") == "ok":
                brief = b2
                break
    if not brief or brief.get("status") != "ok" or not brief.get("headline"):
        return ""
    label = _escape(t("brief.title", lang)).upper()
    date_h = _escape(_fmt_date_human(brief["brief_date"], lang))
    more = _escape(t("brief.read_more", lang))
    return f"""
      <a class="brief-block" href="/brief?lang={lang}">
        <div class="brief-block-label">📋 {label} <span class="brief-date">{date_h}</span></div>
        <div class="brief-block-headline">{_escape(brief.get("headline") or "")}</div>
        <p class="brief-block-lead">{_escape(brief.get("lead") or "")}</p>
        <span class="brief-block-more">{more} →</span>
      </a>
    """


def _render_topics(topics: list, lang: str) -> str:
    rows = []
    for tp in topics or []:
        title = _escape(tp.get("title") or "")
        if tp.get("story_id"):
            title = f'<a href="/story/{_escape(tp["story_id"])}?lang={lang}">{title}</a>'
        rows.append(f"""
          <div class="brief-topic">
            <div class="brief-topic-head">
              <span class="brief-topic-title">{title}</span>
              {_trend_badge(tp.get("trend") or "steady", lang)}
            </div>
            <p class="brief-topic-summary">{_escape(tp.get("summary") or "")}</p>
          </div>
        """)
    return "".join(rows)


async def render_brief_page(request, db_path: str) -> tuple[str, str]:
    """A /brief oldal. ?date=YYYY-MM-DD a napi archívumhoz."""
    lang = _request_lang(request)
    date_q = (request.query_params.get("date") or "").strip()
    d = today_str()
    try:
        if date_q:
            d = datetime.fromisoformat(date_q).date().isoformat()
    except (ValueError, TypeError):
        pass

    brief = await asyncio.to_thread(get_brief, db_path, d, lang)
    pending = False
    if is_stale(brief, d):
        if d == today_str() or brief is None or brief.get("status") != "ok":
            started = kick_async(db_path, d, lang)
            pending = started or (brief is not None and brief.get("status") == "pending")
    dates = await asyncio.to_thread(list_dates, db_path, 10)
    if d not in dates and d == today_str():
        dates = [d] + dates

    title_lbl = _escape(t("brief.title", lang))
    sub_lbl = _escape(t("brief.subtitle", lang))
    date_h = _escape(_fmt_date_human(d, lang))

    # dátum-navigáció (utolsó 10 nap, amelyre van brief)
    nav_items = []
    for dd in dates[:10]:
        lab = _escape(dd[5:].replace("-", "."))  # MM.DD
        if dd == d:
            nav_items.append(f'<span class="cur">{lab}</span>')
        else:
            nav_items.append(f'<a href="/brief?date={dd}&lang={lang}">{lab}</a>')
    datenav = f'<div class="brief-datenav">{"".join(nav_items)}</div>' if nav_items else ""

    refresh_meta = ""
    if brief and brief.get("status") == "ok" and brief.get("headline"):
        upd = _escape(t("brief.updated", lang))
        created = (brief.get("created_at") or "")[:16].replace("T", " ")
        local_html = ""
        if brief.get("local_topics"):
            local_lead = (f'<p class="brief-lead">{_escape(brief.get("local_lead") or "")}</p>'
                          if brief.get("local_lead") else "")
            local_html = f"""
          <h2 class="brief-local-title">{_escape(t("brief.local_title", lang))}</h2>
          {local_lead}
          {_render_topics(brief["local_topics"], lang)}
            """
        body = f"""
          <div class="brief-headline">{_escape(brief["headline"])}</div>
          <p class="brief-lead">{_escape(brief.get("lead") or "")}</p>
          {_render_topics(brief.get("topics") or [], lang)}
          {f'<div class="brief-outlook"><strong>{_escape(t("brief.outlook", lang))}:</strong> {_escape(brief["outlook"])}</div>' if brief.get("outlook") else ''}
          {local_html}
          <div class="brief-meta">{upd}: {created} UTC · Echolot AI</div>
        """
    elif pending:
        refresh_meta = '<meta http-equiv="refresh" content="20">'
        body = f'<div class="brief-pending">⏳ {_escape(t("brief.pending", lang))}</div>'
    else:
        body = f'<div class="brief-pending">{_escape(t("brief.unavailable", lang))}</div>'

    nav_strip = _augment_block_html(lang, active="brief")
    theme_attr = theme_html_attr(request)
    theme_toggle = theme_toggle_html(lang)
    origin = public_origin(request)
    seo_head = seo_head_html(
        origin=origin, lang=lang, path="/brief",
        description=f"{t('brief.title', lang)} — {t('brief.subtitle', lang)}",
        og_title=f"{t('brief.title', lang)} — Echolot",
        og_description=t("brief.subtitle", lang),
    )

    return (f"""<!DOCTYPE html>
<html lang="{lang}"{theme_attr}>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>{title_lbl} · {date_h} — Echolot</title>
  {seo_head}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>{_BASE_STYLES}{_augment_strip_css()}{_BRIEF_CSS}{DAY_THEME_CSS}{THEME_TOGGLE_CSS}</style>
</head>
<body>
  <div class="top-actions">
    {theme_toggle}
  </div>
  {nav_strip}
  <div class="brief-page-wrap">
    <h1>📋 {title_lbl} · {date_h}</h1>
    <p class="brief-page-sub">{sub_lbl}</p>
    {datenav}
    {body}
  </div>
  {THEME_TOGGLE_JS}
</body>
</html>""", lang)
