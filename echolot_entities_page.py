"""Entitás-oldalak: /entities (kártya-rács) + /entities/{label} (portré).

HírSpektrum-stílusú entitás-felfedező az Echolot dizájnjában: a classifier
által (F1 prompt-bővítés) az `article_entities` táblába írt személyek/
szervezetek/helyszínek aggregált hangulattal, szerep-eloszlással és
forrás-bontással. Pure SQL-aggregáció — render-időben SOSINCS LLM-hívás.

Az adat a classifier haladásával gyűlik: friss cikkek a backfillből + a
story-oldali on-demand osztályozásból kapnak entitásokat.
"""
from __future__ import annotations

import sqlite3
from urllib.parse import quote

from echolot_dashboard import _BASE_STYLES, _escape
from echolot_theme import (
    DAY_THEME_CSS,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_JS,
    theme_html_attr,
    theme_toggle_html,
)

# ─── i18n minimál ───────────────────────────────────────────────────────

_L = {
    "hu": {
        "title": "Entitások", "subtitle":
            "Személyek, szervezetek és helyszínek a hírfolyamban — hogyan "
            "ábrázolják őket a források. Az adat a cikk-elemzéssel folyamatosan bővül.",
        "all": "Összes", "person": "Személyek", "org": "Szervezetek",
        "place": "Helyszínek", "articles": "cikk", "sources": "forrás",
        "back": "Vissza a főoldalra", "back_ent": "Entitások",
        "overall": "Átfogó hangulat", "by_source": "Források szerint",
        "by_source_sub": "Hogyan tudósítanak a források erről az entitásról.",
        "roles": "Szerep-eloszlás", "recent": "Friss említések",
        "empty": "Még nincs entitás-adat — az elemző most dolgozza fel a cikkeket.",
        "not_found": "Nincs ilyen entitás (vagy még nincs adat róla).",
        "sent": {-2: "Nagyon negatív", -1: "Negatív", 0: "Semleges",
                 1: "Pozitív", 2: "Nagyon pozitív"},
        "role": {"protagonist": "Főszereplő", "responsible": "Felelős",
                 "victim": "Áldozat", "commentator": "Kommentátor",
                 "mentioned": "Említett"},
        "days": "nap",
    },
    "en": {
        "title": "Entities", "subtitle":
            "People, organizations and places in the news flow — how sources "
            "portray them. Data grows as articles get classified.",
        "all": "All", "person": "People", "org": "Organizations",
        "place": "Places", "articles": "articles", "sources": "sources",
        "back": "Back to home", "back_ent": "Entities",
        "overall": "Overall sentiment", "by_source": "By source",
        "by_source_sub": "How each source covers this entity.",
        "roles": "Role distribution", "recent": "Recent mentions",
        "empty": "No entity data yet — the analyzer is processing articles.",
        "not_found": "Entity not found (or no data yet).",
        "sent": {-2: "Very negative", -1: "Negative", 0: "Neutral",
                 1: "Positive", 2: "Very positive"},
        "role": {"protagonist": "Protagonist", "responsible": "Responsible",
                 "victim": "Victim", "commentator": "Commentator",
                 "mentioned": "Mentioned"},
        "days": "days",
    },
}


def _t(lang: str) -> dict:
    return _L.get(lang, _L["hu"]) if lang in _L else (_L["hu"] if lang == "hu" else _L["en"])


_TYPE_ICON = {"person": "👤", "org": "🏛", "place": "📍", "other": "▪"}


def _sent_bucket(v: float | None) -> int:
    if v is None:
        return 0
    if v <= -0.5:
        return -2
    if v <= -0.1:
        return -1
    if v >= 0.5:
        return 2
    if v >= 0.1:
        return 1
    return 0


def _sent_color(v: float | None) -> str:
    b = _sent_bucket(v)
    return {-2: "#f85149", -1: "#ff7b72", 0: "#d29922",
            1: "#3fb950", 2: "#2ea043"}[b]


def _sent_bar(v: float | None, width: int = 90) -> str:
    """Mini hangulat-bár: -1..+1 → töltöttség + szín."""
    if v is None:
        v = 0.0
    fill = int(abs(v) * width / 2)
    color = _sent_color(v)
    left = width // 2 - (fill if v < 0 else 0)
    return (
        f'<span class="ent-bar" style="width:{width}px">'
        f'<span class="ent-bar-fill" style="left:{left}px;width:{max(fill,2)}px;'
        f'background:{color}"></span><span class="ent-bar-mid"></span></span>'
    )


# ─── SQL aggregációk ────────────────────────────────────────────────────

def query_entities(db_path: str, days: int = 7, etype: str = "",
                   limit: int = 60) -> list[dict]:
    """Top entitások az ablakban: említés-szám, átlag-hangulat, forrás-szám."""
    con = sqlite3.connect(db_path)
    try:
        sql = """
            SELECT ae.label,
                   MAX(ae.entity_type)            AS etype,
                   COUNT(*)                       AS mentions,
                   AVG(ae.sentiment)              AS avg_sent,
                   COUNT(DISTINCT a.source_id)    AS n_sources
            FROM article_entities ae
            JOIN articles a ON a.article_id = ae.article_id
            WHERE a.fetched_at >= strftime('%Y-%m-%dT%H:%M:%S','now',?)
        """
        params: list = [f"-{int(days)} days"]
        if etype in ("person", "org", "place"):
            sql += " AND ae.entity_type = ?"
            params.append(etype)
        sql += " GROUP BY ae.label COLLATE NOCASE ORDER BY mentions DESC LIMIT ?"
        params.append(limit)
        rows = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    return [{"label": r[0], "etype": r[1] or "other", "mentions": r[2],
             "avg_sent": round(r[3], 2) if r[3] is not None else None,
             "n_sources": r[4]} for r in rows]


def query_entity_detail(db_path: str, label: str, days: int = 30) -> dict | None:
    """Egy entitás portréja: átfogó hangulat, forrás-bontás, szerepek, friss cikkek."""
    con = sqlite3.connect(db_path)
    try:
        base = """
            FROM article_entities ae
            JOIN articles a ON a.article_id = ae.article_id
            WHERE ae.label = ? COLLATE NOCASE
              AND a.fetched_at >= strftime('%Y-%m-%dT%H:%M:%S','now',?)
        """
        params = [label, f"-{int(days)} days"]
        head = con.execute(
            f"SELECT COUNT(*), AVG(ae.sentiment), MAX(ae.entity_type) {base}",
            params).fetchone()
        if not head or not head[0]:
            return None
        by_source = con.execute(
            f"""SELECT a.source_name, COUNT(*) n, AVG(ae.sentiment) s {base}
                GROUP BY a.source_id ORDER BY n DESC LIMIT 12""", params).fetchall()
        roles = con.execute(
            f"SELECT ae.role, COUNT(*) n {base} GROUP BY ae.role ORDER BY n DESC",
            params).fetchall()
        recent = con.execute(
            f"""SELECT a.title, a.url, a.source_name, a.published_at,
                       ae.sentiment, ae.role {base}
                ORDER BY a.published_at DESC LIMIT 15""", params).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    return {
        "label": label, "mentions": head[0],
        "avg_sent": round(head[1], 2) if head[1] is not None else None,
        "etype": head[2] or "other",
        "by_source": [{"source": r[0], "n": r[1],
                       "sent": round(r[2], 2) if r[2] is not None else None}
                      for r in by_source],
        "roles": [{"role": r[0] or "mentioned", "n": r[1]} for r in roles],
        "recent": [{"title": r[0], "url": r[1], "source": r[2],
                    "published_at": r[3], "sent": r[4], "role": r[5]}
                   for r in recent],
    }


# ─── CSS ────────────────────────────────────────────────────────────────

_ENT_CSS = """
    .ent-shell { max-width: 1080px; margin: 24px auto 80px; padding: 0 16px; }
    .ent-topbar { display:flex; align-items:center; justify-content:space-between;
                  gap:12px; margin-bottom:14px; }
    .ent-back { color: var(--fg-2); font-size:14px; text-decoration:none; }
    .ent-back:hover { color: var(--text); }
    .ent-h1 { font-size:30px; font-weight:700; margin:8px 0 6px; color:var(--text); }
    .ent-sub { color:var(--fg-2); font-size:14.5px; line-height:1.55; margin:0 0 18px;
               max-width:640px; }
    .ent-filters { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:20px; }
    .ent-chip { padding:6px 14px; border-radius:18px; border:1px solid var(--line);
                color:var(--fg-2); font-size:13px; text-decoration:none;
                transition: all .15s ease; }
    .ent-chip:hover { color:var(--text); border-color:var(--line-strong, #555); }
    .ent-chip.active { background:var(--text); color:var(--bg, #0d1117);
                       border-color:var(--text); font-weight:600; }
    .ent-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr));
                gap:14px; }
    .ent-card { display:block; background:var(--bg-2, rgba(255,255,255,0.02));
                border:1px solid var(--line); border-radius:10px; padding:16px 18px;
                text-decoration:none; transition: all .15s ease; }
    .ent-card:hover { border-color: var(--accent, #6cb6ff);
                      background: var(--bg-3, rgba(255,255,255,0.04)); }
    .ent-card-head { display:flex; align-items:center; gap:8px; margin-bottom:10px;
                     font-size:12px; color:var(--fg-3); }
    .ent-card-type { padding:2px 8px; border-radius:5px; font-size:11px;
                     background:rgba(108,182,255,.12); color:var(--accent, #6cb6ff); }
    .ent-card-sent-lbl { margin-left:auto; font-size:11.5px; font-weight:600; }
    .ent-card-name { font-size:17px; font-weight:700; color:var(--text);
                     margin:0 0 10px; }
    .ent-card-meta { font-size:12.5px; color:var(--fg-3); margin-top:8px;
                     display:flex; gap:12px; }
    .ent-bar { position:relative; display:inline-block; height:7px;
               background:var(--line); border-radius:4px; vertical-align:middle; }
    .ent-bar-fill { position:absolute; top:0; height:7px; border-radius:4px; }
    .ent-bar-mid { position:absolute; left:50%; top:-2px; width:1px; height:11px;
                   background:var(--fg-3); opacity:.6; }
    .ent-sent-val { font-size:12.5px; margin-left:8px; font-weight:600;
                    font-variant-numeric:tabular-nums; }
    .ent-empty { color:var(--fg-2); padding:36px 0; font-size:15px; }

    /* Detail */
    .ent-det-head { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
                    border-bottom:1px solid var(--line); padding-bottom:16px;
                    margin-bottom:20px; }
    .ent-det-stats { display:flex; gap:18px; flex-wrap:wrap; font-size:14px;
                     color:var(--fg-2); align-items:center; }
    .ent-sec { margin:0 0 26px; }
    .ent-sec h2 { font-size:13px; letter-spacing:.1em; text-transform:uppercase;
                  color:var(--fg-3); margin:0 0 4px; font-weight:600; }
    .ent-sec .sec-sub { font-size:12.5px; color:var(--fg-3); margin:0 0 12px; }
    .ent-src-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
                    gap:10px; }
    .ent-src-card { border:1px solid var(--line); border-radius:8px; padding:12px 14px;
                    background:var(--bg-2, rgba(255,255,255,0.02)); }
    .ent-src-name { font-weight:600; color:var(--text); font-size:14px;
                    margin-bottom:6px; }
    .ent-src-row { font-size:12.5px; color:var(--fg-3); display:flex;
                   align-items:center; gap:6px; margin-top:4px; }
    .ent-role-row { display:flex; align-items:center; gap:10px; margin:6px 0;
                    font-size:13.5px; }
    .ent-role-name { width:120px; color:var(--fg-2); }
    .ent-role-bar { height:14px; border-radius:4px; background:var(--accent, #6cb6ff);
                    min-width:3px; }
    .ent-role-n { color:var(--fg-3); font-size:12.5px; }
    .ent-recent li { margin-bottom:12px; font-size:14px; line-height:1.45;
                     list-style:none; }
    .ent-recent { padding:0; margin:0; }
    .ent-recent .src { color:var(--fg-3); font-size:12.5px; margin-right:8px; }
    .ent-recent a { color:var(--text); text-decoration:none; }
    .ent-recent a:hover { color:var(--accent, #6cb6ff); }
    .ent-recent .role-tag { font-size:10.5px; padding:1px 7px; border-radius:4px;
                            border:1px solid var(--line); color:var(--fg-3);
                            margin-left:8px; }
    @media (max-width:720px){ .ent-h1{font-size:24px;} }
"""


def _page_frame(title: str, body: str, lang: str, request=None) -> str:
    theme_attr = theme_html_attr(request)
    return f"""<!doctype html>
<html lang="{lang}"{theme_attr}>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} — Echolot</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{_BASE_STYLES}{_ENT_CSS}{DAY_THEME_CSS}{THEME_TOGGLE_CSS}</style>
</head>
<body>
  <main class="ent-shell">
    {body}
  </main>
  {THEME_TOGGLE_JS}
</body>
</html>"""


# ─── Lista-oldal ────────────────────────────────────────────────────────

def render_entities_page(entities: list[dict], lang: str, etype: str = "",
                         days: int = 7, request=None) -> str:
    t = _t(lang)
    chips = []
    for key, lbl in (("", t["all"]), ("person", t["person"]),
                     ("org", t["org"]), ("place", t["place"])):
        active = " active" if key == etype else ""
        href = f"/entities?lang={lang}" + (f"&type={key}" if key else "")
        chips.append(f'<a class="ent-chip{active}" href="{href}">{_escape(lbl)}</a>')

    if not entities:
        cards = f'<div class="ent-empty">{_escape(t["empty"])}</div>'
    else:
        items = []
        for e in entities:
            sent = e["avg_sent"]
            scol = _sent_color(sent)
            slbl = t["sent"][_sent_bucket(sent)]
            href = f"/entities/{quote(e['label'])}?lang={lang}"
            items.append(f"""
              <a class="ent-card" href="{href}">
                <div class="ent-card-head">
                  <span>{_TYPE_ICON.get(e["etype"], "▪")}</span>
                  <span class="ent-card-type">{_escape(t.get(e["etype"], e["etype"]))}</span>
                  <span class="ent-card-sent-lbl" style="color:{scol}">{_escape(slbl)}</span>
                </div>
                <div class="ent-card-name">{_escape(e["label"])}</div>
                <div>{_sent_bar(sent)}<span class="ent-sent-val" style="color:{scol}">
                  {f"{sent:+.2f}" if sent is not None else "—"}</span></div>
                <div class="ent-card-meta">
                  <span>📰 {e["mentions"]} {_escape(t["articles"])}</span>
                  <span>{e["n_sources"]} {_escape(t["sources"])}</span>
                </div>
              </a>""")
        cards = f'<div class="ent-grid">{"".join(items)}</div>'

    body = f"""
    <div class="ent-topbar">
      <a class="ent-back" href="/?lang={lang}">← {_escape(t["back"])}</a>
      {theme_toggle_html(lang)}
    </div>
    <h1 class="ent-h1">{_escape(t["title"])}</h1>
    <p class="ent-sub">{_escape(t["subtitle"])}</p>
    <div class="ent-filters">{"".join(chips)}</div>
    {cards}
    """
    return _page_frame(t["title"], body, lang, request)


# ─── Portré-oldal ───────────────────────────────────────────────────────

def render_entity_detail_page(d: dict, lang: str, days: int = 30,
                              request=None) -> str:
    t = _t(lang)
    sent = d["avg_sent"]
    scol = _sent_color(sent)
    slbl = t["sent"][_sent_bucket(sent)]

    src_cards = "".join(
        f'<div class="ent-src-card"><div class="ent-src-name">{_escape(s["source"] or "")}</div>'
        f'<div class="ent-src-row">📰 {s["n"]} {_escape(t["articles"])}</div>'
        f'<div class="ent-src-row">{_sent_bar(s["sent"], 70)}'
        f'<span style="color:{_sent_color(s["sent"])};font-weight:600">'
        f'{f"{s['sent']:+.2f}" if s["sent"] is not None else "—"}</span></div></div>'
        for s in d["by_source"])

    max_role = max((r["n"] for r in d["roles"]), default=1)
    role_rows = "".join(
        f'<div class="ent-role-row"><span class="ent-role-name">'
        f'{_escape(t["role"].get(r["role"], r["role"]))}</span>'
        f'<span class="ent-role-bar" style="width:{int(r["n"] / max_role * 240)}px"></span>'
        f'<span class="ent-role-n">{r["n"]}</span></div>'
        for r in d["roles"])

    recent = "".join(
        f'<li><span class="src">{_escape(a["source"] or "")}</span>'
        f'<a href="{_escape(a["url"] or "#")}" target="_blank" rel="noopener">'
        f'{_escape(a["title"] or "")}</a>'
        f'<span class="role-tag">{_escape(t["role"].get(a["role"] or "mentioned", a["role"] or ""))}</span>'
        f'<span class="ent-sent-val" style="color:{_sent_color(a["sent"])}">'
        f'{f"{a['sent']:+.1f}" if a["sent"] is not None else ""}</span></li>'
        for a in d["recent"])

    body = f"""
    <div class="ent-topbar">
      <a class="ent-back" href="/entities?lang={lang}">← {_escape(t["back_ent"])}</a>
      {theme_toggle_html(lang)}
    </div>
    <div class="ent-det-head">
      <h1 class="ent-h1">{_TYPE_ICON.get(d["etype"], "▪")} {_escape(d["label"])}</h1>
      <div class="ent-det-stats">
        <span>{_escape(t["overall"])}:
          <strong style="color:{scol}">{_escape(slbl)}
          ({f"{sent:+.2f}" if sent is not None else "—"})</strong></span>
        <span>📰 {d["mentions"]} {_escape(t["articles"])} · {days} {_escape(t["days"])}</span>
        {_sent_bar(sent, 120)}
      </div>
    </div>
    <section class="ent-sec">
      <h2>{_escape(t["by_source"])}</h2>
      <p class="sec-sub">{_escape(t["by_source_sub"])}</p>
      <div class="ent-src-grid">{src_cards}</div>
    </section>
    <section class="ent-sec">
      <h2>{_escape(t["roles"])}</h2>
      {role_rows}
    </section>
    <section class="ent-sec">
      <h2>{_escape(t["recent"])}</h2>
      <ul class="ent-recent">{recent}</ul>
    </section>
    """
    return _page_frame(d["label"], body, lang, request)
