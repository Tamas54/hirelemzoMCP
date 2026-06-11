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
        "sent_dist": "Hangulat-eloszlás", "narratives": "Aktív narratívák · 48h",
        "coverage": "elemzett említés", "coverage_of": "szöveges találatból",
        "variants_lbl": "nyelvi alak",
        "coverage_note": "az elemzés folyamatosan bővül",
        "most_pos": "Legpozitívabb narratíva", "most_neg": "Legnegatívabb narratíva",
        "neg": "Negatív", "neu": "Semleges", "pos": "Pozitív",
        "empty": "Még nincs entitás-adat — az elemző most dolgozza fel a cikkeket.",
        "lang_own": "Csak magyar nyelvű", "lang_all": "Minden nyelv",
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
        "sent_dist": "Sentiment distribution", "narratives": "Active narratives · 48h",
        "coverage": "analyzed mentions", "coverage_of": "text matches",
        "variants_lbl": "language forms",
        "coverage_note": "analysis keeps expanding",
        "most_pos": "Most positive narrative", "most_neg": "Most negative narrative",
        "neg": "Negative", "neu": "Neutral", "pos": "Positive",
        "empty": "No entity data yet — the analyzer is processing articles.",
        "lang_own": "This language only", "lang_all": "All languages",
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
                   art_lang: str = "", limit: int = 60,
                   ui_lang: str = "") -> list[dict]:
    """Top entitások az ablakban: említés-szám, átlag-hangulat, forrás-szám.
    art_lang: ha megadva (pl. "hu"), csak az adott NYELVŰ cikkek entitásai —
    különben a worker épp feldolgozott nyelve dominálna (Kommandant: a HU
    oldalon csupa cirill entitás jött, mert a backfill orosz cikkeknél járt)."""
    con = sqlite3.connect(db_path)
    try:
        # QID-dedup (entity-dedup-spec §5): GROUP BY COALESCE(qid, label) —
        # a linkelt nyelvi variánsok ("Trump"/"Трамп") EGY sorba olvadnak,
        # a még linkeletlen labelek változatlanul külön (zéró regresszió).
        sql = """
            SELECT COALESCE(ae.qid, ae.label) COLLATE NOCASE AS gkey,
                   MAX(ae.qid)                    AS qid,
                   MIN(ae.label)                  AS any_label,
                   MAX(ae.entity_type)            AS etype,
                   COUNT(*)                       AS mentions,
                   AVG(ae.sentiment)              AS avg_sent,
                   COUNT(DISTINCT a.source_id)    AS n_sources,
                   COUNT(DISTINCT ae.label COLLATE NOCASE) AS variants
            FROM article_entities ae
            JOIN articles a ON a.article_id = ae.article_id
            WHERE a.fetched_at >= strftime('%Y-%m-%dT%H:%M:%S','now',?)
        """
        params: list = [f"-{int(days)} days"]
        if etype in ("person", "org", "place"):
            sql += " AND ae.entity_type = ?"
            params.append(etype)
        if art_lang:
            sql += " AND a.language = ?"
            params.append(art_lang)
        sql += " GROUP BY gkey ORDER BY mentions DESC LIMIT ?"
        params.append(limit)
        rows = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    out = [{"gkey": r[0], "qid": r[1], "label": r[2], "etype": r[3] or "other",
            "mentions": r[4],
            "avg_sent": round(r[5], 2) if r[5] is not None else None,
            "n_sources": r[6], "variants": r[7]} for r in rows]
    # Kanonikus megjelenítési név az olvasó nyelvén (hu → label_hu, más → en)
    try:
        from echolot_entity_linker import canonical_labels
        canon = canonical_labels(db_path, [e["qid"] for e in out if e["qid"]])
        for e in out:
            c = canon.get(e.get("qid") or "")
            if c:
                e["label"] = (c.get("hu") if (ui_lang or art_lang) == "hu"
                              else None) or c.get("en") or e["label"]
    except Exception:
        pass
    return out


def _label_variants(label: str) -> list[str]:
    """Név-permutációk: 'Magyar Péter' ↔ 'Péter Magyar' (angol cikkek
    fordított szórenddel írják a magyar neveket). Két-szavas neveknél."""
    parts = label.split()
    if len(parts) == 2:
        return [label, f"{parts[1]} {parts[0]}"]
    return [label]


def query_entity_detail(db_path: str, label: str, days: int = 30) -> dict | None:
    """Egy entitás portréja: átfogó hangulat, forrás-bontás, szerepek, friss cikkek.

    QID-dedup: a bemenet lehet label VAGY Wikidata-azonosító (Q22686). Ha a
    label linkelve van, a TELJES nyelvközi csoport jön (Trump = Трамп);
    linkeletlen labelnél a régi variáns-illesztés (zéró regresszió).
    A 'lefedettség' is visszamegy: nyers FTS-találat vs elemzett említés."""
    import re as _re
    qid = label if _re.match(r"^Q\d+$", label) else None
    if not qid:
        try:
            from echolot_entity_linker import lookup_qid
            qid = lookup_qid(db_path, label)
        except Exception:
            qid = None
    variants = _label_variants(label)
    if qid:
        cond = "(ae.qid = ? OR ae.label = ? COLLATE NOCASE)"
        cond_params = [qid, label]
    else:
        cond = "(" + " OR ".join("ae.label = ? COLLATE NOCASE" for _ in variants) + ")"
        cond_params = list(variants)
    con = sqlite3.connect(db_path)
    try:
        base = f"""
            FROM article_entities ae
            JOIN articles a ON a.article_id = ae.article_id
            WHERE {cond}
              AND a.fetched_at >= strftime('%Y-%m-%dT%H:%M:%S','now',?)
        """
        params = [*cond_params, f"-{int(days)} days"]
        head = con.execute(
            f"SELECT COUNT(*), AVG(ae.sentiment), MAX(ae.entity_type), "
            f"COUNT(DISTINCT ae.label COLLATE NOCASE) {base}",
            params).fetchone()
        if not head or not head[0]:
            return None
        fts_total = 0
        try:
            fts_terms = list(variants)
            if qid:
                try:
                    al = con.execute(
                        "SELECT alias FROM entity_alias WHERE qid=? AND hits>0",
                        (qid,)).fetchall()
                    fts_terms = list(dict.fromkeys(
                        [label] + [a[0] for a in al]))[:8]
                except sqlite3.OperationalError:
                    pass
            fq = " OR ".join(f'"{v}"' for v in fts_terms)
            fts_total = con.execute(
                """SELECT COUNT(*) FROM articles a
                   JOIN articles_fts f ON f.article_id = a.article_id
                   WHERE articles_fts MATCH ?
                     AND a.fetched_at >= strftime('%Y-%m-%dT%H:%M:%S','now',?)""",
                (fq, f"-{int(days)} days")).fetchone()[0]
        except sqlite3.OperationalError:
            pass
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
        sent_dist = con.execute(
            f"""SELECT
                  SUM(CASE WHEN ae.sentiment <= -0.1 THEN 1 ELSE 0 END),
                  SUM(CASE WHEN ae.sentiment > -0.1 AND ae.sentiment < 0.1 THEN 1 ELSE 0 END),
                  SUM(CASE WHEN ae.sentiment >= 0.1 THEN 1 ELSE 0 END)
                {base}""", params).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    disp = label
    if qid:
        try:
            from echolot_entity_linker import canonical_labels
            c = canonical_labels(db_path, [qid]).get(qid) or {}
            disp = c.get("hu") or c.get("en") or label
        except Exception:
            pass
    return {
        "label": disp, "qid": qid, "variants": head[3],
        "mentions": head[0], "fts_total": fts_total,
        "avg_sent": round(head[1], 2) if head[1] is not None else None,
        "etype": head[2] or "other",
        "by_source": [{"source": r[0], "n": r[1],
                       "sent": round(r[2], 2) if r[2] is not None else None}
                      for r in by_source],
        "roles": [{"role": r[0] or "mentioned", "n": r[1]} for r in roles],
        "sent_dist": {"neg": sent_dist[0] or 0, "neu": sent_dist[1] or 0,
                      "pos": sent_dist[2] or 0},
        "recent": [{"title": r[0], "url": r[1], "source": r[2],
                    "published_at": r[3], "sent": r[4], "role": r[5]}
                   for r in recent],
    }


def query_entity_narratives(db_path: str, label: str, hours: int = 48) -> list[dict]:
    """Aktív narratívák (= sztori-clusterek) amelyekben az entitás szerepel.

    A 48h-s clustering futást használja (ugyanaz, amit a /story route — cache-elt),
    és a cluster cikkeit metszi az entitás cikkeivel. Per-narratíva az entitás-
    irányú átlag-hangulatot adja (article_entities.sentiment), NEM a cikkekét."""
    con = sqlite3.connect(db_path)
    try:
        import re as _re
        qid = label if _re.match(r"^Q\d+$", label) else None
        if not qid:
            try:
                r0 = con.execute(
                    "SELECT qid FROM entity_alias WHERE alias=? COLLATE NOCASE "
                    "AND qid IS NOT NULL LIMIT 1", (label,)).fetchone()
                qid = r0[0] if r0 else None
            except sqlite3.OperationalError:
                qid = None
        cond = "(ae.qid = ? OR ae.label = ? COLLATE NOCASE)" if qid \
            else "ae.label = ? COLLATE NOCASE"
        cp = [qid, label] if qid else [label]
        rows = con.execute(
            f"""SELECT ae.article_id, ae.sentiment FROM article_entities ae
               JOIN articles a ON a.article_id = ae.article_id
               WHERE {cond}
                 AND a.fetched_at >= strftime('%Y-%m-%dT%H:%M:%S','now',?)""",
            (*cp, f"-{int(hours)} hours")).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    sent_by_aid = {r[0]: r[1] for r in rows}
    if not sent_by_aid:
        return []
    from echolot_top_stories import cluster_top_stories
    clusters = cluster_top_stories(db_path, hours=hours, min_sources=1,
                                   limit=500, lang=None)
    out = []
    for c in clusters:
        hits = [a for a in (c.get("articles") or [])
                if a.get("article_id") in sent_by_aid]
        if not hits:
            continue
        sents = [sent_by_aid[a["article_id"]] for a in hits
                 if sent_by_aid.get(a["article_id"]) is not None]
        out.append({
            "cluster_id": c.get("cluster_id"),
            "title": c.get("title") or "",
            "frame": c.get("dominant_frame"),
            "sent": round(sum(sents) / len(sents), 2) if sents else None,
            "n_articles": len(hits),
            "latest": c.get("latest_published") or "",
        })
    out.sort(key=lambda x: (x["sent"] is None, x["sent"] if x["sent"] is not None else 0))
    return out


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
                         days: int = 7, art_lang: str = "", request=None) -> str:
    t = _t(lang)
    al_q = f"&artlang={art_lang}" if art_lang else "&artlang=all"
    chips = []
    for key, lbl in (("", t["all"]), ("person", t["person"]),
                     ("org", t["org"]), ("place", t["place"])):
        active = " active" if key == etype else ""
        href = f"/entities?lang={lang}" + (f"&type={key}" if key else "") + al_q
        chips.append(f'<a class="ent-chip{active}" href="{href}">{_escape(lbl)}</a>')
    # Nyelv-szűrő: saját nyelvű cikkek (default) ↔ minden nyelv. E nélkül a
    # backfill épp futó nyelve dominálná a listát (pl. cirill a HU oldalon).
    type_q = f"&type={etype}" if etype else ""
    chips.append('<span style="width:10px"></span>')
    for key, lbl in ((lang, t["lang_own"]), ("all", t["lang_all"])):
        active = " active" if (art_lang or "all") == key else ""
        chips.append(
            f'<a class="ent-chip{active}" '
            f'href="/entities?lang={lang}{type_q}&artlang={key}">{_escape(lbl)}</a>')

    if not entities:
        cards = f'<div class="ent-empty">{_escape(t["empty"])}</div>'
    else:
        items = []
        for e in entities:
            sent = e["avg_sent"]
            scol = _sent_color(sent)
            slbl = t["sent"][_sent_bucket(sent)]
            href = f"/entities/{quote(e.get('qid') or e['label'])}?lang={lang}"
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
                  {f'<span title="Wikidata: {e["qid"]}">🌐 {e["variants"]} {_escape(t["variants_lbl"])}</span>' if e.get("variants", 1) > 1 else ''}
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

def _sent_donut(dist: dict, t: dict) -> str:
    """Negatív/semleges/pozitív SVG donut (HírSpektrum 'Hangulat eloszlás')."""
    import math as _m
    total = (dist.get("neg", 0) + dist.get("neu", 0) + dist.get("pos", 0)) or 1
    R, C = 44, 2 * _m.pi * 44
    segs, legend, cum = [], [], 0.0
    for key, color in (("neg", "#f85149"), ("neu", "#d29922"), ("pos", "#3fb950")):
        n = dist.get(key, 0)
        if not n:
            continue
        frac = n / total
        seg = frac * C
        segs.append(
            f'<circle cx="60" cy="60" r="{R}" fill="none" stroke="{color}" '
            f'stroke-width="18" stroke-dasharray="{seg:.2f} {C-seg:.2f}" '
            f'stroke-dashoffset="{-cum*C:.2f}" transform="rotate(-90 60 60)"/>')
        cum += frac
        legend.append(
            f'<div style="display:flex;align-items:center;gap:7px;font-size:13px;margin:3px 0">'
            f'<span style="width:10px;height:10px;border-radius:3px;background:{color}"></span>'
            f'{t[key]}<span style="margin-left:auto;color:var(--fg-2)">{round(frac*100)}%</span></div>')
    donut = (f'<svg width="120" height="120" viewBox="0 0 120 120">{"".join(segs)}'
             f'<text x="60" y="66" text-anchor="middle" fill="var(--text)" '
             f'font-size="17" font-weight="700">{total}</text></svg>')
    return (f'<div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">'
            f'<div>{donut}</div><div style="flex:1;min-width:150px">{"".join(legend)}</div></div>')


def _narrative_row(n: dict, lang: str, t: dict) -> str:
    from echolot_story_detail import _SD_FRAME, _frame_label
    fr = n.get("frame")
    badge = ""
    if fr and fr in _SD_FRAME:
        badge = (f'<span style="font-size:10.5px;padding:2px 8px;border-radius:4px;'
                 f'color:#fff;background:{_SD_FRAME[fr][0]};white-space:nowrap">'
                 f'{_escape(_frame_label(fr, lang))}</span>')
    sent = n.get("sent")
    scol = _sent_color(sent)
    sval = f"{sent:+.2f}" if sent is not None else "—"
    href = f'/story/{n["cluster_id"]}?lang={lang}' if n.get("cluster_id") else "#"
    return (f'<li style="display:flex;align-items:center;gap:10px;padding:10px 0;'
            f'border-top:1px solid var(--line);list-style:none">'
            f'{badge}<a href="{href}" style="flex:1;min-width:0;color:var(--text);'
            f'text-decoration:none">{_escape(n["title"][:110])}</a>'
            f'{_sent_bar(sent, 70)}<span style="width:50px;text-align:right;'
            f'color:{scol};font-weight:600;font-size:13px">{sval}</span></li>')


def render_entity_detail_page(d: dict, lang: str, days: int = 30,
                              narratives: list[dict] | None = None,
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

    narratives = narratives or []
    qlabel = quote(d["label"])
    day_btns = "".join(
        f'<a class="ent-chip{" active" if days == dd else ""}" '
        f'href="/entities/{qlabel}?lang={lang}&days={dd}">{dd} {_escape(t["days"])}</a>'
        for dd in (7, 14, 30, 90))

    pos_neg_html = ""
    with_sent = [n for n in narratives if n.get("sent") is not None]
    if with_sent:
        most_neg, most_pos = with_sent[0], with_sent[-1]
        def _pn_card(title_lbl, n):
            c = _sent_color(n["sent"])
            href = f'/story/{n["cluster_id"]}?lang={lang}' if n.get("cluster_id") else "#"
            return (f'<div class="ent-src-card" style="flex:1;min-width:240px">'
                    f'<div style="font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:.07em;color:var(--fg-3);margin-bottom:7px">{title_lbl}</div>'
                    f'<a href="{href}" style="color:var(--text);text-decoration:none;'
                    f'font-size:14.5px;line-height:1.4">{_escape(n["title"][:120])}</a>'
                    f'<div style="margin-top:7px;color:{c};font-weight:700">{n["sent"]:+.2f}</div></div>')
        cards = _pn_card(_escape(t["most_pos"]), most_pos)
        if most_neg is not most_pos:
            cards = _pn_card(_escape(t["most_neg"]), most_neg) + cards
        pos_neg_html = (f'<div style="display:flex;gap:12px;flex-wrap:wrap;'
                        f'margin:0 0 24px">{cards}</div>')

    narr_html = ""
    if narratives:
        by_date = sorted(narratives, key=lambda n: n.get("latest") or "", reverse=True)
        rows_n = "".join(_narrative_row(n, lang, t) for n in by_date[:10])
        narr_html = (f'<section class="ent-sec"><h2>{_escape(t["narratives"])}'
                     f' ({len(narratives)})</h2><ul style="padding:0;margin:0">{rows_n}</ul></section>')

    body = f"""
    <div class="ent-topbar">
      <a class="ent-back" href="/entities?lang={lang}">← {_escape(t["back_ent"])}</a>
      {theme_toggle_html(lang)}
    </div>
    <div class="ent-det-head">
      <h1 class="ent-h1">{_TYPE_ICON.get(d["etype"], "▪")} {_escape(d["label"])}
        {f'<span style="font-size:13px;color:var(--fg-3);font-weight:400">🌐 {d["variants"]} {_escape(t["variants_lbl"])} · <a href="https://www.wikidata.org/wiki/{d["qid"]}" target="_blank" rel="noopener" style="color:var(--fg-3)">{d["qid"]}</a></span>' if d.get("qid") else ''}</h1>
      <div class="ent-det-stats">
        <span>{_escape(t["overall"])}:
          <strong style="color:{scol}">{_escape(slbl)}
          ({f"{sent:+.2f}" if sent is not None else "—"})</strong></span>
        <span>📰 {d["mentions"]} {_escape(t["coverage"])}
          {f' / {d["fts_total"]} {_escape(t["coverage_of"])} — {_escape(t["coverage_note"])}' if d.get("fts_total", 0) > d["mentions"] else ""}
          · {days} {_escape(t["days"])}</span>
        {_sent_bar(sent, 120)}
        <span style="display:inline-flex;gap:6px;margin-left:auto">{day_btns}</span>
      </div>
    </div>
    {pos_neg_html}
    <section class="ent-sec">
      <h2>{_escape(t["sent_dist"])}</h2>
      {_sent_donut(d.get("sent_dist") or {}, t)}
    </section>
    {narr_html}
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
