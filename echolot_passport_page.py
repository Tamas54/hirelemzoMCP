"""Human-facing /passport page — the browser view of a narrative_passport.

Renders a single self-contained HTML page (inline CSS + inline SVG, no external
fetch) following spec §3 layout:
  - top:    verdict bar (corroboration_level color + one_line)
  - middle: propagation timeline (origin -> pickups, delay + similarity)
  - bottom: corroboration matrix mini-heatmap (confirms=green, silent=grey —
            the "grey sea of silence" reads visually)
Plus an input form, origin block, and citations. This is the shareable artifact
(spec §9.1) — the screenshot people click in the directory.

Pure rendering; the data comes from echolot_passport.build_passport().
"""
from __future__ import annotations

import math
from html import escape as _esc

_LEVEL_STYLE = {
    "confirmed":     ("#1f9d55", "Confirmed"),
    "contested":     ("#d97706", "Contested"),
    "unverified":    ("#6b7280", "Unverified"),
    "single_source": ("#c2613a", "Single source"),
    "not_found":     ("#9b2c2c", "Not found"),
}

_PAGE_CSS = """
:root{
  --bg:#0d1117; --panel:#161b22; --panel2:#1c232d; --border:#2d333b;
  --text:#e6edf3; --muted:#8b949e; --accent:#58a6ff;
  --green:#1f9d55; --green-dim:#1a3a2a; --grey-sea:#21262d; --red:#9b2c2c;
}
[data-theme="day"]{
  --bg:#f6f8fa; --panel:#ffffff; --panel2:#f0f3f6; --border:#d0d7de;
  --text:#1f2328; --muted:#656d76; --accent:#0969da;
  --green-dim:#dafbe1; --grey-sea:#eaeef2;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:880px;margin:0 auto;padding:28px 20px 80px}
.topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}
.brand{font-weight:700;font-size:20px;letter-spacing:.3px}
.brand small{color:var(--muted);font-weight:400;font-size:13px}
.theme-toggle{background:var(--panel);border:1px solid var(--border);color:var(--text);
  border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px}
form.q{display:flex;gap:10px;flex-wrap:wrap;background:var(--panel);
  border:1px solid var(--border);border-radius:12px;padding:14px;margin-bottom:24px}
form.q input[type=text]{flex:1;min-width:260px;background:var(--panel2);
  border:1px solid var(--border);color:var(--text);border-radius:8px;padding:10px 12px;font-size:15px}
form.q select,form.q button{background:var(--panel2);border:1px solid var(--border);
  color:var(--text);border-radius:8px;padding:10px 12px;font-size:14px;cursor:pointer}
form.q button{background:var(--accent);color:#fff;border:none;font-weight:600;padding:10px 20px}
.hint{color:var(--muted);font-size:12.5px;margin:-14px 2px 24px}
.verdict{border-radius:12px;padding:18px 20px;margin-bottom:22px;color:#fff;
  box-shadow:0 1px 0 rgba(0,0,0,.2)}
.verdict .lvl{font-size:12px;text-transform:uppercase;letter-spacing:1.2px;opacity:.9}
.verdict .one{font-size:18px;font-weight:600;margin-top:4px}
.verdict .conf{font-size:12.5px;opacity:.95;margin-top:10px;display:flex;align-items:center;gap:8px}
.confbar{flex:0 0 140px;height:6px;border-radius:4px;background:rgba(255,255,255,.3);overflow:hidden}
.confbar i{display:block;height:100%;background:#fff}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}
.stat{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px 16px;text-align:center}
.stat .num{font-size:28px;font-weight:700;line-height:1}
.stat .lab{font-size:12px;color:var(--muted);margin-top:6px}
.heatmap{margin:6px 0 4px}
.heatmap rect{transition:opacity .15s}.heatmap:hover rect{opacity:.55}.heatmap rect:hover{opacity:1}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;
  padding:18px 20px;margin-bottom:18px}
.card h3{margin:0 0 12px;font-size:13px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
.origin .src{font-weight:600}.origin .hl{margin-top:6px}
.meta{color:var(--muted);font-size:13px}
.timeline{list-style:none;margin:0;padding:0}
.timeline li{display:grid;grid-template-columns:74px 1fr;gap:12px;padding:9px 0;
  border-top:1px solid var(--border)}
.timeline li:first-child{border-top:none}
.delay{color:var(--muted);font-size:12.5px;text-align:right;padding-top:2px}
.tl-src{font-weight:600}.tl-meta{color:var(--muted);font-size:12.5px}
.simbar{height:5px;border-radius:3px;background:var(--grey-sea);margin-top:5px;overflow:hidden}
.simbar i{display:block;height:100%;background:var(--accent)}
.heat{display:flex;flex-wrap:wrap;gap:7px}
.chip{font-size:12.5px;padding:5px 10px;border-radius:7px;border:1px solid var(--border)}
.chip.c{background:var(--green-dim);border-color:var(--green)}
.chip.s{background:var(--grey-sea);color:var(--muted)}
.legend{display:flex;gap:16px;margin:4px 0 12px;font-size:12.5px;color:var(--muted)}
.legend .sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:5px}
.note{color:var(--muted);font-size:13px;margin-top:10px;font-style:italic}
.cites{list-style:none;margin:0;padding:0}
.cites li{padding:7px 0;border-top:1px solid var(--border);font-size:13.5px}
.cites li:first-child{border-top:none}
.cites .sph{color:var(--muted);font-size:12px}
.foot{color:var(--muted);font-size:12.5px;text-align:center;margin-top:34px;
  padding-top:18px;border-top:1px solid var(--border)}
.empty{color:var(--muted);text-align:center;padding:40px 0}
"""

_THEME_JS = """
(function(){
  var k='echolot-theme';
  function set(t){document.documentElement.setAttribute('data-theme',t);
    try{localStorage.setItem(k,t)}catch(e){}
    var b=document.getElementById('tt');if(b)b.textContent=t==='day'?'\\u263e Night':'\\u2600 Day';}
  var saved;try{saved=localStorage.getItem(k)}catch(e){}
  set(saved||'night');
  document.addEventListener('click',function(e){if(e.target&&e.target.id==='tt'){
    set(document.documentElement.getAttribute('data-theme')==='day'?'night':'day');}});
})();
"""


def _bar(frac: float) -> str:
    pct = max(0, min(100, round(frac * 100)))
    return f'<div class="simbar"><i style="width:{pct}%"></i></div>'


def _render_verdict(v: dict) -> str:
    level = (v or {}).get("corroboration_level", "not_found")
    color, label = _LEVEL_STYLE.get(level, _LEVEL_STYLE["not_found"])
    conf = (v or {}).get("confidence")
    conf_html = ""
    if isinstance(conf, (int, float)) and conf:
        pct = round(conf * 100)
        conf_html = (
            '<div class="conf">confidence '
            f'<b>{pct}%</b>'
            f'<span class="confbar"><i style="width:{pct}%"></i></span></div>'
        )
    return (f'<div class="verdict" style="background:{color}">'
            f'<div class="lvl">{_esc(label)}</div>'
            f'<div class="one">{_esc((v or {}).get("one_line",""))}</div>'
            f'{conf_html}</div>')


def _render_stat_strip(passport: dict) -> str:
    cm = passport.get("corroboration_matrix") or {}
    cs = passport.get("coverage_stats") or {}
    confirms = cm.get("confirms", [])
    silent = cm.get("silent", [])
    n_articles = cs.get("articles_analyzed", 0)
    n_live = cs.get("spheres_monitored_live", 0)
    tiles = [
        (str(n_articles), "articles", "var(--accent)"),
        (str(len(confirms)), "spheres covering", "var(--green)"),
        (str(len(silent)), "live but silent", "var(--muted)"),
        (str(n_live), "live spheres", "var(--text)"),
    ]
    cells = "".join(
        f'<div class="stat"><div class="num" style="color:{c}">{_esc(n)}</div>'
        f'<div class="lab">{_esc(l)}</div></div>'
        for n, l, c in tiles
    )
    return f'<div class="stats">{cells}</div>'


def _render_origin(o: dict | None) -> str:
    if not o:
        return ""
    sphere = o.get("sphere") or "—"
    return (
        '<div class="card origin"><h3>Origin — first seen</h3>'
        f'<div class="src">{_esc(o.get("source") or "—")} '
        f'<span class="meta">· {_esc(sphere)} · {_esc(o.get("first_seen_utc") or "")}</span></div>'
        f'<div class="hl">{_esc(o.get("headline_original") or "")}</div>'
        + (f'<div><a href="{_esc(o.get("article_url") or "#")}" target="_blank" rel="noopener">read source ↗</a></div>'
           if o.get("article_url") else "")
        + '</div>'
    )


def _render_timeline(prop: list[dict]) -> str:
    if not prop:
        return ""
    rows = []
    for p in prop[:25]:
        dmin = p.get("delay_minutes") or 0
        delay = f"+{dmin}m" if dmin < 120 else f"+{round(dmin/60)}h"
        sim = p.get("similarity_to_origin") or 0.0
        diff = p.get("headline_diff_note")
        diff_html = f'<div class="tl-meta">⟲ {_esc(diff)}</div>' if diff else ""
        rows.append(
            f'<li><div class="delay">{_esc(delay)}</div>'
            f'<div><div class="tl-src">{_esc(p.get("source") or "—")} '
            f'<span class="tl-meta">· {_esc(p.get("sphere") or "—")}</span></div>'
            f'{_bar(sim)}{diff_html}</div></li>'
        )
    return ('<div class="card"><h3>Propagation timeline</h3>'
            f'<ul class="timeline">{"".join(rows)}</ul></div>')


def _heatmap_svg(confirms: list[str], silent: list[str]) -> str:
    """The 'grey sea of silence' as an inline SVG grid — one cell per live sphere.

    Green = covers the story, grey = live but silent. Cells inherit theme CSS
    variables (works in day & night). Hover shows the sphere name."""
    cells = [("c", s) for s in confirms] + [("s", s) for s in silent]
    if not cells:
        return '<div class="meta">No live spheres to map.</div>'
    COLS, CELL, GAP = 18, 22, 6
    n = len(cells)
    rows = math.ceil(n / COLS)
    cols = min(COLS, n)
    W = cols * (CELL + GAP) - GAP
    H = rows * (CELL + GAP) - GAP
    rects = []
    for i, (kind, name) in enumerate(cells):
        r, c = divmod(i, COLS)
        x, y = c * (CELL + GAP), r * (CELL + GAP)
        fill = "var(--green)" if kind == "c" else "var(--grey-sea)"
        label = f'{name} — {"covers" if kind == "c" else "silent"}'
        rects.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="4" '
            f'fill="{fill}" stroke="var(--border)" stroke-width="1">'
            f'<title>{_esc(label)}</title></rect>'
        )
    return (
        f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px;height:auto" '
        f'role="img" aria-label="sphere coverage heatmap">{"".join(rects)}</svg>'
    )


def _render_heatmap(cm: dict) -> str:
    confirms = cm.get("confirms", [])
    silent = cm.get("silent", [])
    note = cm.get("silence_note") or ""
    total = len(confirms) + len(silent)
    caption = (f'<b style="color:var(--green)">{len(confirms)}</b> of {total} live spheres '
               f'carry this story — the rest is the grey sea of silence.') if total else ""
    return (
        '<div class="card"><h3>Corroboration — covers vs. silent</h3>'
        '<div class="legend">'
        '<span><span class="sw" style="background:var(--green)"></span>covers this story</span>'
        '<span><span class="sw" style="background:var(--grey-sea)"></span>live but silent</span>'
        '</div>'
        f'<div class="heatmap">{_heatmap_svg(confirms, silent)}</div>'
        f'<div class="note">{caption}</div>'
        f'<div class="note">{_esc(note)}</div></div>'
    )


def _render_citations(cites: list[dict]) -> str:
    if not cites:
        return ""
    rows = []
    for c in cites[:10]:
        rows.append(
            f'<li><a href="{_esc(c.get("url") or "#")}" target="_blank" rel="noopener">'
            f'{_esc(c.get("source") or c.get("url") or "source")}</a> '
            f'<span class="sph">{_esc(c.get("sphere") or "")} · {_esc(c.get("published_utc") or "")}</span></li>'
        )
    return ('<div class="card"><h3>Citations</h3>'
            f'<ul class="cites">{"".join(rows)}</ul></div>')


def _form(claim: str, days: int, detail: str) -> str:
    def opt(val, cur, label):
        sel = " selected" if str(val) == str(cur) else ""
        return f'<option value="{val}"{sel}>{label}</option>'
    return (
        '<form class="q" method="get" action="/passport">'
        f'<input type="text" name="claim" value="{_esc(claim)}" '
        'placeholder="A specific claim or an article URL — e.g. \'Germany blocked the EU sanctions package\'">'
        f'<select name="days">{opt(7,days,"7 days")}{opt(14,days,"14 days")}{opt(30,days,"30 days")}{opt(90,days,"90 days")}</select>'
        f'<select name="detail">{opt("summary",detail,"summary")}{opt("full",detail,"full")}</select>'
        '<button type="submit">Trace</button>'
        '</form>'
    )


def render_passport_page(passport: dict | None, *, claim: str = "",
                         days: int = 14, detail: str = "summary") -> str:
    """Full HTML page. passport=None => just the form (empty state)."""
    if passport is None:
        body = ('<div class="empty">Enter a specific news claim (any language) or an '
                'article URL above, and Echolot will trace where it first appeared, '
                'which of the monitored spheres carry it, and which stay silent.</div>')
    else:
        body = (
            _render_verdict(passport.get("verdict") or {})
            + _render_stat_strip(passport)
            + _render_origin(passport.get("origin"))
            + _render_timeline(passport.get("propagation") or [])
            + _render_heatmap(passport.get("corroboration_matrix") or {})
            + _render_citations(passport.get("citations") or [])
        )
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{_esc(claim) + ' — ' if claim else ''}Echolot Narrative Passport</title>"
        f"<style>{_PAGE_CSS}</style></head><body><div class=wrap>"
        '<div class="topbar"><div class="brand">Echolot '
        '<small>narrative passport</small></div>'
        '<button id="tt" class="theme-toggle">☀ Day</button></div>'
        + _form(claim, days, detail)
        + ('<div class="hint">Tip: input a checkable statement, not a broad topic. '
           'Stance (confirm vs. refute) is coming with the classifier layer; '
           'this view shows who covers the story and who stays silent.</div>'
           if passport is None else "")
        + body
        + ('<div class="foot">Generated by Echolot — ask your AI to verify any news. '
           'One call returns the provenance, corroboration map, and spread pattern of any claim.</div>')
        + f"<script>{_THEME_JS}</script></div></body></html>"
    )
