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
from echolot_top_stories import LEAN_TO_BIAS


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

_ORIG_LBL = {
    "hu": "Eredeti cikk", "en": "Original article", "de": "Originalartikel",
    "fr": "Article original", "ru": "Оригинал статьи", "uk": "Оригінал статті",
}

# "Forrás összes híre" — a forrás belső gyűjtőoldalára (/source/<id>) mutató link.
_SRC_ALL_LBL = {
    "hu": "Forrás összes híre", "en": "All news from source",
    "de": "Alle Nachrichten der Quelle", "fr": "Toutes les actus de la source",
    "ru": "Все новости источника", "uk": "Усі новини джерела",
}


# "Tovább olvasom" — a teljes (extrahált) cikkszöveget kinyitó details/summary.
_READMORE_LBL = {
    "hu": "Tovább olvasom", "en": "Read full text", "de": "Volltext lesen",
    "fr": "Lire le texte complet", "ru": "Читать полностью", "uk": "Читати повністю",
}
_COLLAPSE_LBL = {
    "hu": "Összecsukom", "en": "Collapse", "de": "Einklappen",
    "fr": "Réduire", "ru": "Свернуть", "uk": "Згорнути",
}
# Perspektíva-bontás + idővonal szekció-címkék.
_PERSP_LBL = {
    "hu": "Így írták meg", "en": "How each side framed it",
    "de": "So berichteten die Seiten", "fr": "Comment chaque camp l'a présenté",
    "ru": "Как подали разные стороны", "uk": "Як подали різні сторони",
}
_TIMELINE_LBL = {
    "hu": "Idővonal", "en": "Timeline", "de": "Zeitleiste",
    "fr": "Chronologie", "ru": "Хронология", "uk": "Хронологія",
}
# Lean-bucket emberi név (nyelvfüggetlen kulcs → HU/EN).
_LEAN_BUCKET_LBL = {
    "L": {"hu": "Baloldali sajtó", "en": "Left-leaning"},
    "C": {"hu": "Központi / semleges", "en": "Center / neutral"},
    "R": {"hu": "Jobboldali sajtó", "en": "Right-leaning"},
    "G": {"hu": "Kormányzati", "en": "Government"},
}


# Bias-bucket → színek és badge-betűk (a pol-bar logikájával egyezően).
_BUCKET_COLOR = {
    "L": "var(--pol-l, #c25a5a)", "C": "var(--pol-c, #8e8e8e)",
    "R": "var(--pol-r, #4d7ec8)",
}
_BUCKET_BADGE = {"L": "B", "C": "K", "R": "J"}


def _lean_bucket(lean: str | None) -> str:
    """Forrás-lean → L/C/R bias-bucket a KANONIKUS LEAN_TO_BIAS mappinggel.

    Fontos: a DB lean-szókincse 'opposition'/'gov'/'unknown'/'center'/... — NEM
    'left'/'right'/'government'. A bias-bar is ezt a mappinget használja, így a
    perspektíva-bontás és a lean-badge mostantól egyezik vele."""
    key = (lean or "").strip().lower()
    return LEAN_TO_BIAS.get(key, "C")


def _readmore_label(lang: str) -> str:
    return _READMORE_LBL.get(lang, _READMORE_LBL["hu"])


def _render_full_text(full_text: str, lang: str) -> str:
    """A kinyert teljes cikkszöveget bekezdésekre bontva, kinyitható
    <details> blokkban adja vissza. Üres/rövid szövegnél üres stringet ad."""
    text = (full_text or "").strip()
    if len(text) < 200:
        return ""
    # Defense in depth: never render binary/garbage (undecoded brotli etc.).
    # Real article text has ~no U+FFFD replacement chars; garbage is full of them.
    sample = text[:4000]
    bad = sum(1 for c in sample if c == "�" or (ord(c) < 32 and c not in "\t\n\r"))
    if bad / len(sample) >= 0.05:
        return ""
    # Bekezdésekre bontás: dupla, majd egyszeres sortörés mentén.
    chunks = [c.strip() for c in text.replace("\r", "").split("\n") if c.strip()]
    if not chunks:
        return ""
    # Védőkorlát: ne dőljön be óriás szövegtől (kb. 8000 karakter).
    paras, total = [], 0
    for c in chunks:
        if total > 8000:
            break
        paras.append(f"<p>{_escape(c)}</p>")
        total += len(c)
    body = "\n".join(paras)
    return (
        '<details class="src-card-fulltext">'
        f'<summary>{_escape(_readmore_label(lang))} ▾</summary>'
        f'<div class="src-card-fulltext-body">{body}</div>'
        "</details>"
    )


def _orig_label(lang: str) -> str:
    return _ORIG_LBL.get(lang, _ORIG_LBL["hu"])


def _src_all_label(lang: str) -> str:
    return _SRC_ALL_LBL.get(lang, _SRC_ALL_LBL["hu"])


def _render_lean_badge(lean: str | None) -> str:
    if not lean:
        return ""
    bucket = _lean_bucket(lean)
    label = _BUCKET_BADGE.get(bucket, "")
    color = _BUCKET_COLOR.get(bucket, "var(--fg-3)")
    if not label:
        return ""
    return f'<span class="lean-badge" style="background:{color}" title="{_escape(lean)}">{label}</span>'


# ─── Source-card a listához ─────────────────────────────────────────────

def _render_source_card(article: dict, lang: str) -> str:
    title = article.get("title") or ""
    lead = (article.get("lead") or "").strip()
    url = article.get("url") or "#"
    src_id = article.get("source_id") or ""
    src_name = article.get("source_name") or src_id or ""
    lean = article.get("source_lean") or ""
    ts = article.get("published_at") or ""
    ts_combined = _fmt_combined(ts)

    lead_html = (
        f'<p class="src-card-lead">{_escape(lead)}</p>' if lead else ""
    )
    fulltext_html = _render_full_text(article.get("full_text") or "", lang)

    # FENT: a forrás neve belső link a forrás-kártyára (aznapi hírei).
    src_href = f"/source/{_escape(src_id)}?lang={lang}" if src_id else ""
    if src_href:
        name_html = (
            f'<a href="{src_href}" class="src-card-name src-card-name-link">'
            f'{_escape(src_name)}</a>'
        )
    else:
        name_html = f'<span class="src-card-name">{_escape(src_name)}</span>'

    # LENT: az "Eredeti cikk" mellett a "Forrás összes híre" belső link.
    src_all_html = (
        f'<a href="{src_href}" class="src-card-link src-card-link-internal">'
        f'{_escape(_src_all_label(lang))} →</a>'
        if src_href else ""
    )

    return f"""
      <article class="src-card">
        <header class="src-card-head">
          {_render_lean_badge(lean)}
          {name_html}
          <time class="src-card-time" datetime="{_escape(ts)}">{_escape(ts_combined)}</time>
        </header>
        <h3 class="src-card-title">{_escape(title)}</h3>
        {lead_html}
        {fulltext_html}
        <div class="src-card-actions">
          <a href="{_escape(url)}" target="_blank" rel="noopener" class="src-card-link">
            {_escape(_orig_label(lang))} ↗
          </a>
          {src_all_html}
        </div>
      </article>
    """


# ─── Perspektíva-bontás (lean szerint) ──────────────────────────────────

_BUCKET_ORDER = ["L", "C", "R"]


def _bucket_label(bucket: str, lang: str) -> str:
    d = _LEAN_BUCKET_LBL.get(bucket, {})
    return d.get(lang, d.get("hu", bucket))


def _render_perspective_breakdown(articles: list[dict], lang: str) -> str:
    """Lean-bucketenként (Bal/Központi/Jobb/Kormányzati) megmutatja, hogy az
    egyes oldalak milyen címmel írták meg ugyanazt — ez az Echolot lényege."""
    groups: dict[str, list[dict]] = {b: [] for b in _BUCKET_ORDER}
    for a in articles:
        groups[_lean_bucket(a.get("source_lean"))].append(a)
    present = [b for b in _BUCKET_ORDER if groups[b]]
    # Ha minden forrás egy bucketben van, nincs mit kontrasztba állítani.
    if len(present) < 2:
        return ""

    cols = []
    for b in present:
        items = groups[b]
        lis = "".join(
            f'<li><span class="persp-src">{_escape(a.get("source_name") or "")}</span>'
            f'<span class="persp-title">{_escape((a.get("title") or "").strip())}</span></li>'
            for a in items[:4]
        )
        more = (f'<li class="persp-more">+{len(items) - 4}</li>'
                if len(items) > 4 else "")
        cols.append(
            f'<div class="persp-col">'
            f'<div class="persp-head" style="color:{_BUCKET_COLOR[b]}">'
            f'<span class="persp-dot" style="background:{_BUCKET_COLOR[b]}"></span>'
            f'{_escape(_bucket_label(b, lang))} · {len(items)}</div>'
            f'<ul class="persp-items">{lis}{more}</ul>'
            f'</div>'
        )
    heading = _escape(_PERSP_LBL.get(lang, _PERSP_LBL["hu"]))
    return (
        '<section class="story-perspective">'
        f'<h2>{heading}</h2>'
        f'<div class="persp-grid">{"".join(cols)}</div>'
        '</section>'
    )


def _render_timeline(articles: list[dict], lang: str) -> str:
    """A sztori fejlődése időrendben: melyik forrás mikor vette át."""
    dated = [a for a in articles if (a.get("published_at") or "").strip()]
    if len(dated) < 2:
        return ""
    ordered = sorted(dated, key=lambda a: a.get("published_at") or "")
    rows = "".join(
        f'<li><time class="tl-time">{_escape(_fmt_combined(a.get("published_at")))}</time>'
        f'<span class="tl-src">{_escape(a.get("source_name") or "")}</span>'
        f'<span class="tl-title">{_escape((a.get("title") or "").strip())}</span></li>'
        for a in ordered
    )
    heading = _escape(_TIMELINE_LBL.get(lang, _TIMELINE_LBL["hu"]))
    return (
        '<section class="story-timeline">'
        f'<h2>{heading}</h2>'
        f'<ol class="tl-list">{rows}</ol>'
        '</section>'
    )


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
    .src-card-name-link {
      color: var(--text);
      text-decoration: none;
      transition: color .15s ease;
    }
    .src-card-name-link:hover {
      color: var(--accent, #6cb6ff);
      text-decoration: underline;
    }
    .src-card-actions {
      display: flex;
      align-items: center;
      gap: 18px;
      flex-wrap: wrap;
    }
    .src-card-link {
      display: inline-block;
      color: var(--accent, #6cb6ff);
      text-decoration: none;
      font-size: 13px;
      letter-spacing: 0.03em;
    }
    .src-card-link:hover { text-decoration: underline; }
    .src-card-link-internal { color: var(--fg-2); }
    .src-card-link-internal:hover { color: var(--text); }

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

    /* Teljes cikkszöveg — kinyitható details/summary */
    .src-card-fulltext { margin: 4px 0 10px 0; }
    .src-card-fulltext > summary {
      cursor: pointer;
      color: var(--accent, #6cb6ff);
      font-size: 13px;
      letter-spacing: 0.03em;
      list-style: none;
      user-select: none;
      display: inline-block;
      padding: 2px 0;
    }
    .src-card-fulltext > summary::-webkit-details-marker { display: none; }
    .src-card-fulltext[open] > summary { color: var(--fg-2); margin-bottom: 8px; }
    .src-card-fulltext-body {
      border-left: 2px solid var(--line);
      padding-left: 14px;
      margin-top: 6px;
    }
    .src-card-fulltext-body p {
      font-size: 14.5px;
      line-height: 1.7;
      color: var(--fg-2);
      margin: 0 0 12px 0;
    }
    .src-card-fulltext-body p:last-child { margin-bottom: 0; }

    /* Perspektíva-bontás */
    .story-perspective, .story-timeline { margin: 0 0 var(--sp-5); }
    .story-perspective > h2, .story-timeline > h2 {
      font-size: 14px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--fg-3);
      margin: 0 0 var(--sp-3);
      font-weight: 600;
    }
    .persp-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
    }
    .persp-col {
      background: var(--bg-2, rgba(255,255,255,0.02));
      border: 1px solid var(--line);
      border-radius: var(--r-md, 8px);
      padding: 12px 14px;
    }
    .persp-head {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }
    .persp-dot {
      width: 8px; height: 8px; border-radius: 50%;
      display: inline-block; flex: 0 0 auto;
    }
    .persp-items { list-style: none; margin: 0; padding: 0; }
    .persp-items li {
      font-size: 13px;
      line-height: 1.45;
      margin-bottom: 9px;
      color: var(--fg-2);
    }
    .persp-items li:last-child { margin-bottom: 0; }
    .persp-src {
      display: block;
      color: var(--text);
      font-weight: 600;
      font-size: 12px;
      margin-bottom: 1px;
    }
    .persp-title { display: block; color: var(--fg-2); }
    .persp-more { color: var(--fg-3); font-size: 12px; }

    /* Idővonal */
    .tl-list {
      list-style: none;
      margin: 0;
      padding: 0;
      border-left: 2px solid var(--line);
    }
    .tl-list li {
      position: relative;
      padding: 0 0 14px 18px;
      font-size: 13.5px;
      line-height: 1.4;
    }
    .tl-list li::before {
      content: "";
      position: absolute;
      left: -5px; top: 5px;
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--accent, #6cb6ff);
    }
    .tl-list li:last-child { padding-bottom: 0; }
    .tl-time {
      color: var(--fg-3);
      font-variant-numeric: tabular-nums;
      margin-right: 8px;
    }
    .tl-src { color: var(--text); font-weight: 600; margin-right: 8px; }
    .tl-title { color: var(--fg-2); }

    @media (max-width: 720px) {
      .story-detail-title { font-size: 22px; }
      .src-card-title { font-size: 16px; }
      .persp-grid { grid-template-columns: 1fr; }
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

    perspective_html = _render_perspective_breakdown(articles, lang)
    story_timeline_html = _render_timeline(articles, lang)
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

    {perspective_html}

    {story_timeline_html}

    <section class="story-sources-section">
      <h2>{sources_label} ({n_sources})</h2>
      <div class="src-card-list">
        {cards_html}
      </div>
    </section>
  </main>
</body>
</html>"""
