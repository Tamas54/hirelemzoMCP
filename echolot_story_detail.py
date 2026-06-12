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
from echolot_theme import (
    theme_html_attr,
    DAY_THEME_CSS,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_JS,
    theme_toggle_html,
)


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


def _fmt_combined(ts: str | None, lang: str = "hu") -> str:
    """'4 órája (06:12)' — relatív és abszolút együtt. Üres string ha nincs ts."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return ""
    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
    rel = _fmt_age(dt, now, lang)
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
# Gépi fordítás jelölő (a fordított cím/lead mellett).
_TR_LBL = {
    "hu": "ford.", "en": "transl.", "de": "übers.", "fr": "trad.",
    "ru": "перев.", "uk": "перекл.", "it": "trad.",
}
# Revízió-jelvény: a forrás utólag módosította a cikket.
_REV_LBL = {
    "hu": "módosítva", "en": "edited", "de": "geändert",
    "fr": "modifié", "ru": "изменено", "uk": "змінено",
}
_REV_DETAIL_LBL = {
    "hu": "A forrás módosította a cikket", "en": "The source edited this article",
    "de": "Die Quelle hat den Artikel geändert", "fr": "La source a modifié l'article",
    "ru": "Источник изменил статью", "uk": "Джерело змінило статтю",
}
_REV_TITLE_LBL = {"hu": "Cím", "en": "Title", "de": "Titel", "fr": "Titre",
                  "ru": "Заголовок", "uk": "Заголовок"}
_REV_LEAD_LBL = {"hu": "Lead", "en": "Lead", "de": "Lead", "fr": "Chapeau",
                 "ru": "Лид", "uk": "Лід"}

# Teljes szöveg fordítás-gomb + eredeti/fordítás váltó (keresztfordító 1b).
_FT_BTN = {"hu": "Fordítás magyarra", "en": "Translate to English",
           "de": "Auf Deutsch übersetzen", "fr": "Traduire en français",
           "pl": "Przetłumacz na polski", "ru": "Перевести на русский",
           "uk": "Перекласти українською", "it": "Traduci in italiano",
           "es": "Traducir al español"}
_FT_ORIG_LBL = {"hu": "Eredeti szöveg", "en": "Original text",
                "de": "Originaltext", "fr": "Texte original",
                "pl": "Tekst oryginalny", "ru": "Оригинал", "uk": "Оригінал",
                "it": "Testo originale", "es": "Texto original"}
_FT_TR_LBL = {"hu": "Fordítás", "en": "Translation", "de": "Übersetzung",
              "fr": "Traduction", "pl": "Tłumaczenie", "ru": "Перевод",
              "uk": "Переклад", "it": "Traduzione", "es": "Traducción"}
_FT_LOADING = {"hu": "Fordítás folyamatban…", "en": "Translating…",
               "de": "Übersetzung läuft…", "fr": "Traduction en cours…",
               "pl": "Tłumaczenie…", "ru": "Перевод…", "uk": "Переклад…",
               "it": "Traduzione…", "es": "Traduciendo…"}

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
# CSAK L/C/R — Kommandant-döntés: NINCS külön "Kormányzati" bucket; a
# kormánypropaganda/állami média a kanonikus LEAN_TO_BIAS szerint az R
# oszlopba számít (Ground News-elv, lásd bias-legend módszertan).
_LEAN_BUCKET_LBL = {
    "L": {"hu": "Baloldali sajtó", "en": "Left-leaning"},
    "C": {"hu": "Központi / semleges", "en": "Center / neutral"},
    "R": {"hu": "Jobboldali sajtó", "en": "Right-leaning"},
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


def _paras_html(text: str) -> str:
    """Bekezdésekre tört, escape-elt HTML egy nyers szövegből (cap ~8000)."""
    chunks = [c.strip() for c in (text or "").replace("\r", "").split("\n") if c.strip()]
    paras, total = [], 0
    for c in chunks:
        if total > 8000:
            break
        paras.append(f"<p>{_escape(c)}</p>")
        total += len(c)
    return "\n".join(paras)


def _render_full_text(article: dict, lang: str) -> str:
    """Teljes cikkszöveg kinyitható <details> blokkban — keresztfordítóval.

    - Ha van cache-elt fordítás (_ft_tr[lang]): a fordítás nyílik, de az
      EREDETI mindig egy kattintás (váltógomb, reload nélkül).
    - Ha idegen nyelvű és nincs még fordítás: "Fordítás magyarra" gomb →
      /api/translate_article (kattintásra fordul, cache-be örökre).
    Üres/rövid/bináris szövegnél üres stringet ad."""
    text = (article.get("full_text") or "").strip()
    if len(text) < 200:
        return ""
    sample = text[:4000]
    bad = sum(1 for c in sample if c == "�" or (ord(c) < 32 and c not in "\t\n\r"))
    if bad / len(sample) >= 0.05:
        return ""
    body_orig = _paras_html(text)
    if not body_orig:
        return ""

    aid = article.get("article_id") or ""
    art_lang = (article.get("language") or "").lower()
    ft_tr = (article.get("_ft_tr") or {}).get(lang)
    tr_lbl = _escape(_FT_TR_LBL.get(lang, _FT_TR_LBL["en"]))
    orig_lbl = _escape(_FT_ORIG_LBL.get(lang, _FT_ORIG_LBL["en"]))

    controls = ""
    if ft_tr:
        body_html = (
            f'<div class="ft-body ft-tr">{_paras_html(ft_tr)}</div>'
            f'<div class="ft-body ft-orig" style="display:none">{body_orig}</div>')
        controls = (
            f'<div class="ft-controls">'
            f'<button class="ft-toggle active" data-show="tr">{tr_lbl}</button>'
            f'<button class="ft-toggle" data-show="orig">{orig_lbl}</button></div>')
    else:
        body_html = f'<div class="ft-body ft-orig">{body_orig}</div>'
        if aid and art_lang and lang and art_lang != lang:
            btn_lbl = _escape(_FT_BTN.get(lang, _FT_BTN["en"]))
            loading = _escape(_FT_LOADING.get(lang, _FT_LOADING["en"]))
            controls = (
                f'<div class="ft-controls">'
                f'<button class="ft-translate-btn" data-aid="{_escape(aid)}" '
                f'data-lang="{lang}" data-loading="{loading}" '
                f'data-trlbl="{tr_lbl}" data-origlbl="{orig_lbl}">'
                f'🌐 {btn_lbl}</button></div>')

    return (
        '<details class="src-card-fulltext">'
        f'<summary>{_escape(_readmore_label(lang))} ▾</summary>'
        f'{controls}'
        f'<div class="src-card-fulltext-body">{body_html}</div>'
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

def _render_revisions(article: dict, lang: str) -> str:
    """'✎ módosítva' jelvény + kinyitható régi→új történet, ha a forrás
    utólag átírta a cikket (article_revisions). Üres string ha nincs revízió."""
    revs = article.get("revisions") or []
    if not revs:
        return ""
    badge_lbl = _REV_LBL.get(lang, _REV_LBL["hu"])
    detail_lbl = _REV_DETAIL_LBL.get(lang, _REV_DETAIL_LBL["hu"])
    t_lbl = _REV_TITLE_LBL.get(lang, _REV_TITLE_LBL["hu"])
    l_lbl = _REV_LEAD_LBL.get(lang, _REV_LEAD_LBL["hu"])
    rows = []
    for r in revs:
        when = _escape(_fmt_combined(r.get("revised_at"), lang))
        if r.get("old_title"):
            rows.append(
                f'<li><time>{when}</time><span class="rev-field">{t_lbl}:</span>'
                f'<span class="rev-old">{_escape(r["old_title"])}</span> → '
                f'<span class="rev-new">{_escape(r.get("new_title") or "")}</span></li>')
        if r.get("old_lead"):
            rows.append(
                f'<li><time>{when}</time><span class="rev-field">{l_lbl}:</span>'
                f'<span class="rev-old">{_escape(r["old_lead"])}</span> → '
                f'<span class="rev-new">{_escape(r.get("new_lead") or "")}</span></li>')
    if not rows:
        return ""
    return (
        f'<details class="src-card-revisions">'
        f'<summary><span class="rev-badge">✎ {_escape(badge_lbl)} ({len(revs)})</span></summary>'
        f'<div class="rev-body"><div class="rev-head">{_escape(detail_lbl)}</div>'
        f'<ul>{"".join(rows)}</ul></div></details>'
    )


def _render_source_card(article: dict, lang: str) -> str:
    title = article.get("title") or ""
    lead = (article.get("lead") or "").strip()
    url = article.get("url") or "#"
    src_id = article.get("source_id") or ""
    src_name = article.get("source_name") or src_id or ""
    lean = article.get("source_lean") or ""
    ts = article.get("published_at") or ""
    ts_combined = _fmt_combined(ts, lang)

    # Gépi fordítás (on-demand, háttérben töltődik): ha van a UI-nyelvű
    # fordítás, az a fő cím/lead, az eredeti cím kis betűvel alá kerül.
    tr = (article.get("_tr") or {}).get(lang) or {}
    title_disp = tr.get("title") or title
    lead_disp = tr.get("lead") or lead
    tr_badge = ""
    orig_title_html = ""
    if tr.get("title"):
        tr_badge = (f'<span class="tr-badge" title="{_escape(title)}">'
                    f'{_escape(_TR_LBL.get(lang, _TR_LBL["hu"]))}</span>')
        orig_title_html = f'<div class="src-card-orig-title">{_escape(title)}</div>'

    lead_html = (
        f'<p class="src-card-lead">{_escape(lead_disp)}</p>' if lead_disp else ""
    )
    fulltext_html = _render_full_text(article, lang)
    revisions_html = _render_revisions(article, lang)

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
          {tr_badge}
          <time class="src-card-time" datetime="{_escape(ts)}">{_escape(ts_combined)}</time>
        </header>
        <h3 class="src-card-title">{_escape(title_disp)}</h3>
        {orig_title_html}
        {revisions_html}
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
    """Lean-bucketenként (Bal/Központi/Jobb) megmutatja, hogy az egyes
    oldalak milyen címmel írták meg ugyanazt — ez az Echolot lényege.
    NINCS külön kormányzati bucket: állami média → R (LEAN_TO_BIAS)."""
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


_SPREAD_LBL = {
    "hu": "A hír útja a szférákon át", "en": "How the story travels across spheres",
    "de": "Der Weg der Nachricht durch die Sphären",
    "fr": "Le parcours de l'info à travers les sphères",
    "ru": "Путь новости через сферы", "uk": "Шлях новини крізь сфери",
    "it": "Il percorso della notizia tra le sfere",
}
_SPREAD_SUB = {
    "hu": "Ugyanaz a sztori szféránként más tálalásban — hangulat és domináns keret szféránként.",
    "en": "The same story, framed differently per sphere — sentiment and dominant frame by sphere.",
}
_SPREAD_TH = {
    "hu": ("Szféra", "Cikk", "Hangulat", "Domináns keret", "Beállítottság"),
    "en": ("Sphere", "Art.", "Sentiment", "Dominant frame", "Lean"),
}
_SENT_WORD = {
    "hu": {"pos": "pozitív", "neu": "semleges", "neg": "negatív"},
    "en": {"pos": "positive", "neu": "neutral", "neg": "negative"},
}


def _render_sphere_spread(articles: list[dict], lang: str) -> str:
    """Szféránkénti meta-statisztika (UX-teszter kérés: "ha az a hír, hogy
    Trump szürke zakóját felvette, az a jobboldali amerikai sajtóban pozitív,
    a bal franciában negatív…"). Cikkszám + átlag-hangulat + domináns frame
    + lean-összetétel szféránként — itt látszik, hol hogyan tálalják."""
    from echolot_sphere_labels import sphere_label

    agg: dict[str, dict] = {}
    for a in articles:
        for sp in (a.get("spheres") or []):
            d = agg.setdefault(sp, {"n": 0, "sents": [], "frames": {}, "leans": {}})
            d["n"] += 1
            sv = a.get("sentiment")
            if isinstance(sv, (int, float)):
                d["sents"].append(float(sv))
            fr = a.get("frame")
            if fr:
                d["frames"][fr] = d["frames"].get(fr, 0) + 1
            b = _lean_bucket(a.get("source_lean"))
            d["leans"][b] = d["leans"].get(b, 0) + 1
    # Egy szférás sztorinál nincs "út" — nincs mit összevetni.
    if len(agg) < 2:
        return ""

    th = _SPREAD_TH.get(lang, _SPREAD_TH["en"])
    words = _SENT_WORD.get(lang, _SENT_WORD["en"])
    rows = []
    ranked = sorted(agg.items(), key=lambda kv: -kv[1]["n"])[:12]
    for sp, d in ranked:
        if d["sents"]:
            avg = sum(d["sents"]) / len(d["sents"])
            scol = "#3fb950" if avg > 0.15 else ("#f85149" if avg < -0.15 else "#d29922")
            word = words["pos"] if avg > 0.15 else (words["neg"] if avg < -0.15 else words["neu"])
            sent = (f'<span style="color:{scol};font-weight:700">{avg:+.2f}</span> '
                    f'<span class="spread-word" style="color:{scol}">{word}</span>')
        else:
            sent = '<span style="color:var(--fg-3)">–</span>'
        if d["frames"]:
            top_fr = max(d["frames"].items(), key=lambda kv: kv[1])[0]
            fr_html = (f'<span class="spread-frame" style="border-color:'
                       f'{_SD_FRAME.get(top_fr, ("#8b949e", {}))[0]}">'
                       f'{_escape(_frame_label(top_fr, lang))}</span>')
        else:
            fr_html = '<span style="color:var(--fg-3)">–</span>'
        dots = "".join(
            f'<span class="spread-dot" title="{_escape(_bucket_label(b, lang))}: {d["leans"][b]}" '
            f'style="background:{_BUCKET_COLOR[b]}"></span>'
            f'<span class="spread-dot-n">{d["leans"][b]}</span>'
            for b in _BUCKET_ORDER if d["leans"].get(b)
        )
        rows.append(
            f'<tr><td class="spread-sphere">{_escape(sphere_label(sp, lang))}</td>'
            f'<td class="spread-n">{d["n"]}</td>'
            f'<td>{sent}</td><td>{fr_html}</td>'
            f'<td class="spread-leans">{dots}</td></tr>'
        )

    heading = _escape(_SPREAD_LBL.get(lang, _SPREAD_LBL["en"]))
    sub = _escape(_SPREAD_SUB.get(lang, _SPREAD_SUB["en"]))
    head_cells = "".join(f"<th>{_escape(x)}</th>" for x in th)
    return (
        '<section class="story-spread">'
        f'<h2>🧭 {heading}</h2>'
        f'<p class="spread-sub">{sub}</p>'
        f'<table class="spread-table"><thead><tr>{head_cells}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        '</section>'
    )


def _render_timeline(articles: list[dict], lang: str) -> str:
    """A sztori fejlődése időrendben: melyik forrás mikor vette át."""
    dated = [a for a in articles if (a.get("published_at") or "").strip()]
    if len(dated) < 2:
        return ""
    ordered = sorted(dated, key=lambda a: a.get("published_at") or "")
    rows = "".join(
        f'<li><time class="tl-time">{_escape(_fmt_combined(a.get("published_at"), lang))}</time>'
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
    .story-detail-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 16px;
    }
    .story-detail-back {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--fg-2);
      font-size: 14px;
      text-decoration: none;
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

    /* Gépi fordítás jelölő + eredeti cím */
    .tr-badge {
      font-size: 10px;
      padding: 1px 6px;
      border-radius: 4px;
      border: 1px solid var(--line);
      color: var(--fg-3);
      letter-spacing: 0.05em;
      text-transform: uppercase;
      cursor: help;
    }
    .src-card-orig-title {
      font-size: 12.5px;
      color: var(--fg-3);
      margin: -4px 0 8px 0;
      font-style: italic;
    }

    /* Revízió-jelvény + történet */
    .src-card-revisions { margin: 0 0 10px 0; }
    .src-card-revisions > summary {
      cursor: pointer;
      list-style: none;
      display: inline-block;
      user-select: none;
    }
    .src-card-revisions > summary::-webkit-details-marker { display: none; }
    .rev-badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 4px;
      background: rgba(210, 153, 34, 0.15);
      border: 1px solid rgba(210, 153, 34, 0.45);
      color: var(--rev-fg, #d29922);
      letter-spacing: 0.03em;
      font-weight: 600;
    }
    .rev-body {
      border-left: 2px solid rgba(210, 153, 34, 0.45);
      padding: 6px 0 2px 12px;
      margin-top: 8px;
    }
    .rev-head {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--fg-3);
      margin-bottom: 6px;
    }
    .rev-body ul { list-style: none; margin: 0; padding: 0; }
    .rev-body li {
      font-size: 13px;
      line-height: 1.5;
      margin-bottom: 7px;
      color: var(--fg-2);
    }
    .rev-body li time {
      color: var(--fg-3);
      font-variant-numeric: tabular-nums;
      margin-right: 7px;
      font-size: 12px;
    }
    .rev-field { color: var(--fg-3); margin-right: 5px; font-size: 12px; }
    .rev-old { text-decoration: line-through; opacity: 0.75; }
    .rev-new { color: var(--text); font-weight: 500; }

    /* Cikkszöveg-fordítás gombok (keresztfordító 1b) */
    .ft-controls { display:flex; gap:8px; margin:8px 0 4px; }
    .ft-translate-btn, .ft-toggle {
      background: var(--bg-2, rgba(255,255,255,0.04));
      border: 1px solid var(--line);
      color: var(--accent, #6cb6ff);
      border-radius: 6px; padding: 4px 12px;
      font-size: 12.5px; cursor: pointer; font-family: inherit;
      transition: all .15s ease;
    }
    .ft-translate-btn:hover, .ft-toggle:hover { border-color: var(--accent, #6cb6ff); }
    .ft-translate-btn[disabled] { opacity: .55; cursor: wait; }
    .ft-toggle.active {
      background: var(--accent, #6cb6ff); color: #0d1117;
      border-color: var(--accent, #6cb6ff); font-weight: 600;
    }

    /* Szféra-spread (hír útja) */
    .story-spread { margin: 0 0 var(--sp-5); }
    .spread-sub { font-size: 12px; color: var(--fg-3); margin: -6px 0 10px; }
    .spread-table {
      width: 100%; border-collapse: collapse; font-size: 13px;
    }
    .spread-table th {
      text-align: left; font-size: 11px; text-transform: uppercase;
      letter-spacing: 0.06em; color: var(--fg-3); font-weight: 600;
      padding: 4px 10px 6px 0; border-bottom: 1px solid var(--line);
    }
    .spread-table td {
      padding: 6px 10px 6px 0; border-bottom: 1px solid var(--line);
      vertical-align: middle;
    }
    .spread-sphere { font-weight: 600; color: var(--text); }
    .spread-n { font-family: 'JetBrains Mono', monospace; color: var(--fg-2); }
    .spread-word { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
    .spread-frame {
      display: inline-block; font-size: 11px; padding: 1px 8px;
      border: 1px solid; border-radius: 999px; color: var(--fg-2);
    }
    .spread-dot {
      width: 8px; height: 8px; border-radius: 50%;
      display: inline-block; margin-right: 2px;
    }
    .spread-dot-n {
      font-size: 11px; color: var(--fg-3); margin-right: 8px;
      font-family: 'JetBrains Mono', monospace;
    }

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


# Kliens-JS: fordítás-gomb (fetch → beszúrás) + eredeti/fordítás váltó.
_FT_JS = """
<script>
document.addEventListener('click', function(e){
  var b = e.target.closest('.ft-translate-btn');
  if (b) {
    e.preventDefault();
    b.disabled = true;
    var orig_label = b.textContent;
    b.textContent = b.dataset.loading;
    fetch('/api/translate_article?article_id=' + encodeURIComponent(b.dataset.aid)
          + '&lang=' + encodeURIComponent(b.dataset.lang))
      .then(function(r){ return r.json(); })
      .then(function(d){
        if (!d || !d.html) { b.textContent = '⚠ ' + orig_label; b.disabled = false; return; }
        var box = b.closest('.src-card-fulltext');
        var body = box.querySelector('.src-card-fulltext-body');
        var origDiv = body.querySelector('.ft-orig');
        var trDiv = document.createElement('div');
        trDiv.className = 'ft-body ft-tr';
        trDiv.innerHTML = d.html;
        body.insertBefore(trDiv, origDiv);
        origDiv.style.display = 'none';
        var ctr = b.closest('.ft-controls');
        ctr.innerHTML = '<button class="ft-toggle active" data-show="tr">' + b.dataset.trlbl +
          '</button><button class="ft-toggle" data-show="orig">' + b.dataset.origlbl + '</button>';
      })
      .catch(function(){ b.textContent = '⚠ ' + orig_label; b.disabled = false; });
    return;
  }
  var t = e.target.closest('.ft-toggle');
  if (t) {
    e.preventDefault();
    var box = t.closest('.src-card-fulltext');
    var showTr = t.dataset.show === 'tr';
    var tr = box.querySelector('.ft-tr'), og = box.querySelector('.ft-orig');
    if (tr) tr.style.display = showTr ? '' : 'none';
    if (og) og.style.display = showTr ? 'none' : '';
    box.querySelectorAll('.ft-toggle').forEach(function(x){ x.classList.remove('active'); });
    t.classList.add('active');
  }
});
</script>
"""


# ─── Fő render fv ───────────────────────────────────────────────────────

_SD_FRAME = {
    "conflict":        ("#f85149", {"hu": "Konfliktus", "en": "Conflict", "de": "Konflikt"}),
    "human_interest":  ("#58a6ff", {"hu": "Emberi érdek", "en": "Human interest", "de": "Menschlich"}),
    "economic":        ("#3fb950", {"hu": "Gazdasági", "en": "Economic", "de": "Wirtschaft"}),
    "morality":        ("#bc8cff", {"hu": "Erkölcs", "en": "Morality", "de": "Moral"}),
    "vulnerability":   ("#d29922", {"hu": "Kiszolgáltatottság", "en": "Vulnerability", "de": "Verwundbarkeit"}),
    "responsibility":  ("#ff7b72", {"hu": "Felelősség", "en": "Responsibility", "de": "Verantwortung"}),
    "security_threat": ("#db61a2", {"hu": "Biztonsági fenyegetés", "en": "Security threat", "de": "Sicherheit"}),
    "progress":        ("#2ea043", {"hu": "Fejlődés", "en": "Progress", "de": "Fortschritt"}),
    "crime":           ("#e3633d", {"hu": "Bűncselekmény", "en": "Crime", "de": "Kriminalität"}),
    "other":           ("#8b949e", {"hu": "Egyéb", "en": "Other", "de": "Sonstige"}),
}


def _frame_label(fr: str, lang: str) -> str:
    if fr not in _SD_FRAME:
        return fr
    return _SD_FRAME[fr][1].get(lang) or _SD_FRAME[fr][1]["en"]


def _render_frame_analysis(cluster: dict, articles: list, lang: str) -> str:
    """Per-story F1 analysis: framing donut + sentiment + per-source frame
    breakdown. Renders only when the cluster has classified articles."""
    frame_dist = {k: v for k, v in (cluster.get("frame_dist") or {}).items() if v}
    title = {"hu": "Keretezési elemzés", "en": "Framing analysis",
             "de": "Framing-Analyse", "fr": "Analyse du cadrage",
             "ru": "Анализ фрейминга", "uk": "Аналіз фреймування",
             "it": "Analisi del framing"}.get(lang, "Framing analysis")
    if not frame_dist:
        return ""  # no classified articles in this cluster yet → omit silently

    total = sum(frame_dist.values()) or 1
    import math as _m
    R, C = 54, 2 * _m.pi * 54
    segs, legend, cum = [], [], 0.0
    for fr, n in sorted(frame_dist.items(), key=lambda kv: -kv[1]):
        color = _SD_FRAME.get(fr, ("#8b949e", {}))[0]
        frac = n / total
        seg = frac * C
        segs.append(
            f'<circle cx="70" cy="70" r="{R}" fill="none" stroke="{color}" '
            f'stroke-width="20" stroke-dasharray="{seg:.2f} {C-seg:.2f}" '
            f'stroke-dashoffset="{-cum*C:.2f}" transform="rotate(-90 70 70)"/>')
        cum += frac
        legend.append(
            f'<div style="display:flex;align-items:center;gap:7px;font-size:13px;margin:4px 0">'
            f'<span style="width:11px;height:11px;border-radius:3px;background:{color}"></span>'
            f'{_escape(_frame_label(fr, lang))}'
            f'<span style="margin-left:auto;color:var(--fg-2)">{round(frac*100)}%</span></div>')
    donut = (f'<svg width="140" height="140" viewBox="0 0 140 140">{"".join(segs)}'
             f'<text x="70" y="66" text-anchor="middle" fill="var(--fg)" font-size="18" '
             f'font-weight="700">{total}</text>'
             f'<text x="70" y="82" text-anchor="middle" fill="var(--fg-2)" font-size="9">'
             f'{ {"hu":"osztályozva","en":"classified"}.get(lang,"classified") }</text></svg>')

    avg = cluster.get("avg_sentiment")
    sent_html = ""
    if avg is not None:
        pos = round((avg + 1) / 2 * 100)
        scol = "#3fb950" if avg > 0.15 else ("#f85149" if avg < -0.15 else "#d29922")
        slabel = {"hu": "Átfogó hangulat", "en": "Overall sentiment"}.get(lang, "Overall sentiment")
        sent_html = (
            f'<div style="margin-top:14px"><div style="font-size:12px;color:var(--fg-2);'
            f'text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">{slabel}</div>'
            f'<div style="display:flex;align-items:center;gap:12px">'
            f'<span style="font-size:24px;font-weight:700;color:{scol}">{avg:+.2f}</span>'
            f'<span style="flex:1;height:8px;border-radius:5px;position:relative;'
            f'background:linear-gradient(90deg,#f85149,#d29922,#3fb950)">'
            f'<span style="position:absolute;top:-3px;left:{pos}%;width:3px;height:14px;'
            f'background:var(--fg);transform:translateX(-50%);border-radius:2px"></span></span></div></div>')

    # Per-source frame breakdown (hirspektrum "Forráselemzés").
    rows = []
    for a in articles:
        fr = a.get("frame")
        if not fr:
            continue
        color = _SD_FRAME.get(fr, ("#8b949e", {}))[0]
        sv = a.get("sentiment")
        scol = "#3fb950" if (sv or 0) > 0.15 else ("#f85149" if (sv or 0) < -0.15 else "var(--fg-2)")
        sval = f'{sv:+.2f}' if sv is not None else "—"
        rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;padding:7px 0;'
            f'border-top:1px solid var(--line);font-size:13px">'
            f'<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;'
            f'white-space:nowrap">{_escape(a.get("source_name") or "")}</span>'
            f'<span style="font-size:11px;padding:2px 8px;border-radius:5px;color:#fff;'
            f'background:{color};white-space:nowrap">{_escape(_frame_label(fr, lang))}</span>'
            f'<span style="width:46px;text-align:right;color:{scol}">{sval}</span></div>')
    src_label = {"hu": "Források keretezése", "en": "Framing by source"}.get(lang, "Framing by source")
    src_block = (f'<div style="margin-top:16px"><div style="font-size:12px;color:var(--fg-2);'
                 f'text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">{src_label}</div>'
                 f'{"".join(rows)}</div>') if rows else ""

    return (
        '<section class="story-frame-analysis" style="margin:22px 0;padding:20px;'
        'background:var(--bg-2,rgba(127,127,127,.05));border:1px solid var(--line);border-radius:14px">'
        f'<h2 style="font-size:14px;text-transform:uppercase;letter-spacing:.08em;'
        f'color:var(--fg-2);margin:0 0 14px">{_escape(title)} '
        f'<span style="font-size:11px;text-transform:none;letter-spacing:0">· F1</span></h2>'
        f'<div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">'
        f'<div>{donut}</div><div style="flex:1;min-width:180px">{"".join(legend)}</div></div>'
        f'{sent_html}{src_block}</section>'
    )


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
            f'<span>↪ {first_label}:<strong>{_escape(_fmt_combined(first_published, lang))}</strong></span>'
        )
    if latest_published and latest_published != first_published:
        timeline_parts.append(
            f'<span>⟳ {last_label}:<strong>{_escape(_fmt_combined(latest_published, lang))}</strong></span>'
        )
    timeline_html = (
        f'<div class="story-detail-timeline">{"".join(timeline_parts)}</div>'
        if timeline_parts else ""
    )

    perspective_html = _render_perspective_breakdown(articles, lang)
    sphere_spread_html = _render_sphere_spread(articles, lang)
    frame_analysis_html = _render_frame_analysis(cluster, articles, lang)
    story_timeline_html = _render_timeline(articles, lang)
    cards_html = "".join(_render_source_card(a, lang) for a in articles)
    # Gazdagítottság-számláló az utótöltő scriptnek (server._STORY_LATEFILL_JS):
    # full_textek + erre a nyelvre kész fordítások. Ha a friss render értéke
    # nagyobb, a kliens kicseréli a forrás-listát.
    enrich = (
        sum(1 for a in articles if (a.get("full_text") or "").strip())
        + sum(1 for a in articles if (a.get("_tr") or {}).get(lang))
        + sum(1 for a in articles if a.get("frame"))
    )

    title_html = _escape(title[:80])
    page_title = f"{title_html} — Echolot"
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
  <style>{_BASE_STYLES}{_augment_strip_css()}{_LANDING_V2_EXTRA_CSS}{_STORY_DETAIL_CSS}{DAY_THEME_CSS}{THEME_TOGGLE_CSS}</style>
</head>
<body>
  <main class="story-detail-shell landing-v2-shell">
    <div class="story-detail-topbar">
      <a href="/?lang={lang}" class="story-detail-back">← {back_label}</a>
      {theme_toggle}
    </div>

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

    <div id="frame-analysis-slot">{frame_analysis_html}</div>

    {perspective_html}

    {sphere_spread_html}

    {story_timeline_html}

    <section class="story-sources-section">
      <h2>{sources_label} ({n_sources})</h2>
      <div class="src-card-list" data-enrich="{enrich}">
        {cards_html}
      </div>
    </section>
  </main>
  {THEME_TOGGLE_JS}
  {_FT_JS}
</body>
</html>"""
