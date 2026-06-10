"""Human-facing /analysis page — the F1 framing/emotion/sentiment view.

Hirspektrum-style analytical dashboard rendered from the classifier columns:
frame-distribution donut (Semetko–Valkenburg 9 frames), emotion bars (Plutchik),
sentiment gauge, and a per-source breakdown. Pure inline SVG, themed via CSS
vars (day/night), no JS beyond the theme toggle. Data comes from
echolot_analytics.overview().
"""
from __future__ import annotations

import math
from html import escape as _esc

_FRAME_COLOR = {
    "conflict": "#f85149", "human_interest": "#58a6ff", "economic": "#3fb950",
    "morality": "#bc8cff", "vulnerability": "#d29922", "responsibility": "#ff7b72",
    "security_threat": "#db61a2", "progress": "#2ea043", "other": "#8b949e",
}
_FRAME_LABEL = {
    "conflict": "Conflict", "human_interest": "Human interest", "economic": "Economic",
    "morality": "Morality", "vulnerability": "Vulnerability", "responsibility": "Responsibility",
    "security_threat": "Security threat", "progress": "Progress", "other": "Other",
}
_EMO_COLOR = {
    "anger": "#f85149", "fear": "#8957e5", "joy": "#e3b341", "surprise": "#39c5cf",
    "sadness": "#1f6feb", "trust": "#3fb950", "disgust": "#db61a2", "other": "#8b949e",
}

_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c232d;--border:#2d333b;--text:#e6edf3;
  --muted:#8b949e;--accent:#58a6ff;--grey:#21262d}
[data-theme="day"]{--bg:#f6f8fa;--panel:#fff;--panel2:#f0f3f6;--border:#d0d7de;
  --text:#1f2328;--muted:#656d76;--accent:#0969da;--grey:#eaeef2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
a{color:var(--accent);text-decoration:none}
.wrap{max-width:920px;margin:0 auto;padding:28px 20px 80px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}
.brand{font-weight:700;font-size:20px}.brand small{color:var(--muted);font-weight:400;font-size:13px}
.tt{background:var(--panel);border:1px solid var(--border);color:var(--text);border-radius:8px;
  padding:6px 12px;cursor:pointer;font-size:13px}
form.q{display:flex;gap:10px;flex-wrap:wrap;background:var(--panel);border:1px solid var(--border);
  border-radius:12px;padding:14px;margin-bottom:22px}
form.q input{flex:1;min-width:240px;background:var(--panel2);border:1px solid var(--border);
  color:var(--text);border-radius:8px;padding:10px 12px;font-size:15px}
form.q select,form.q button{background:var(--panel2);border:1px solid var(--border);color:var(--text);
  border-radius:8px;padding:10px 12px;font-size:14px;cursor:pointer}
form.q button{background:var(--accent);color:#fff;border:none;font-weight:600;padding:10px 20px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
@media(max-width:680px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin-bottom:16px}
.card h3{margin:0 0 14px;font-size:13px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
.donut-wrap{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.legend{display:flex;flex-direction:column;gap:6px;font-size:13px;flex:1;min-width:160px}
.legend .row{display:flex;align-items:center;gap:8px}
.legend .sw{width:11px;height:11px;border-radius:3px;flex:0 0 auto}
.legend .pct{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums}
.ebar{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}
.ebar .lab{width:74px;color:var(--muted)}
.ebar .track{flex:1;height:9px;background:var(--grey);border-radius:5px;overflow:hidden}
.ebar .fill{display:block;height:100%;border-radius:5px}
.ebar .n{width:30px;text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.senti{display:flex;align-items:center;gap:12px}
.senti .big{font-size:34px;font-weight:700}
.gauge{flex:1;height:10px;border-radius:6px;background:linear-gradient(90deg,#f85149,#d29922,#3fb950);position:relative}
.gauge .pin{position:absolute;top:-4px;width:4px;height:18px;background:var(--text);border-radius:2px;transform:translateX(-2px)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;
  letter-spacing:.5px;padding:6px 8px;border-bottom:1px solid var(--border)}
td{padding:8px;border-bottom:1px solid var(--border)}
.chip{font-size:11.5px;padding:3px 8px;border-radius:6px;color:#fff;white-space:nowrap}
.sent-cell{font-variant-numeric:tabular-nums}
.cov{color:var(--muted);font-size:12.5px;margin-bottom:18px}
.empty{color:var(--muted);text-align:center;padding:40px 0}
.foot{color:var(--muted);font-size:12.5px;text-align:center;margin-top:30px;padding-top:18px;border-top:1px solid var(--border)}
"""

_THEME_JS = """(function(){var k='echolot-theme';function set(t){
document.documentElement.setAttribute('data-theme',t);try{localStorage.setItem(k,t)}catch(e){}
var b=document.getElementById('tt');if(b)b.textContent=t==='day'?'\\u263e Night':'\\u2600 Day';}
var s;try{s=localStorage.getItem(k)}catch(e){}set(s||'night');
document.addEventListener('click',function(e){if(e.target&&e.target.id==='tt'){
set(document.documentElement.getAttribute('data-theme')==='day'?'night':'day');}});})();"""


def _donut(dist: dict) -> str:
    total = sum(dist.values()) or 1
    R, C = 70, 2 * math.pi * 70
    segs, cum = [], 0.0
    rows = []
    for frame, n in dist.items():
        frac = n / total
        color = _FRAME_COLOR.get(frame, "#8b949e")
        seg = frac * C
        segs.append(
            f'<circle cx="90" cy="90" r="{R}" fill="none" stroke="{color}" '
            f'stroke-width="26" stroke-dasharray="{seg:.2f} {C-seg:.2f}" '
            f'stroke-dashoffset="{-cum*C:.2f}" transform="rotate(-90 90 90)"/>')
        cum += frac
        rows.append(
            f'<div class="row"><span class="sw" style="background:{color}"></span>'
            f'{_esc(_FRAME_LABEL.get(frame, frame))}<span class="pct">{round(frac*100)}%</span></div>')
    svg = (f'<svg width="180" height="180" viewBox="0 0 180 180" role="img" '
           f'aria-label="frame distribution">{"".join(segs)}'
           f'<text x="90" y="86" text-anchor="middle" fill="var(--text)" font-size="22" '
           f'font-weight="700">{total}</text>'
           f'<text x="90" y="104" text-anchor="middle" fill="var(--muted)" font-size="11">articles</text></svg>')
    return f'<div class="donut-wrap">{svg}<div class="legend">{"".join(rows)}</div></div>'


def _emotion_bars(dist: dict) -> str:
    total = sum(dist.values()) or 1
    mx = max(dist.values()) if dist else 1
    rows = []
    for emo, n in dist.items():
        color = _EMO_COLOR.get(emo, "#8b949e")
        w = round(100 * n / mx)
        rows.append(
            f'<div class="ebar"><span class="lab">{_esc(emo)}</span>'
            f'<span class="track"><span class="fill" style="width:{w}%;background:{color}"></span></span>'
            f'<span class="n">{n}</span></div>')
    return "".join(rows) or '<div class="empty">no emotion data yet</div>'


def _sentiment(s: dict) -> str:
    avg = s.get("avg")
    if avg is None:
        return '<div class="empty">no sentiment data yet</div>'
    pos = round((avg + 1) / 2 * 100)  # -1..1 -> 0..100
    color = "#3fb950" if avg > 0.15 else ("#f85149" if avg < -0.15 else "#d29922")
    return (f'<div class="senti"><div class="big" style="color:{color}">{avg:+.2f}</div>'
            f'<div class="gauge"><div class="pin" style="left:{pos}%"></div></div></div>'
            f'<div class="cov" style="margin-top:10px">range {s.get("min")} … {s.get("max")} '
            f'over {s.get("n")} classified articles</div>')


def _sources_table(sources: list[dict]) -> str:
    if not sources:
        return '<div class="empty">no sources yet</div>'
    rows = []
    for s in sources:
        f = s.get("dominant_frame")
        chip = (f'<span class="chip" style="background:{_FRAME_COLOR.get(f,"#8b949e")}">'
                f'{_esc(_FRAME_LABEL.get(f, f))}</span>') if f else '<span class="cov">—</span>'
        sent = s.get("avg_sentiment")
        scol = ("#3fb950" if (sent or 0) > 0.15 else "#f85149" if (sent or 0) < -0.15 else "var(--muted)")
        sval = f'<span style="color:{scol}">{sent:+.2f}</span>' if sent is not None else "—"
        rows.append(
            f'<tr><td>{_esc(s["source"])}</td><td class="cov">{_esc(s.get("lean") or "—")}</td>'
            f'<td>{s["articles"]}</td><td>{chip}</td>'
            f'<td class="sent-cell">{sval}</td></tr>')
    return ('<table><thead><tr><th>Source</th><th>Lean</th><th>Art.</th>'
            '<th>Dominant frame</th><th>Sentiment</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def render_analysis_page(data: dict, *, query: str = "", days: int = 30) -> str:
    cov = data.get("classification_coverage", {})
    note = cov.get("note")
    has_data = sum(data.get("frame_distribution", {}).values()) > 0
    if has_data:
        body = (
            '<div class="grid">'
            f'<div class="card"><h3>Framing — Semetko–Valkenburg</h3>{_donut(data["frame_distribution"])}</div>'
            f'<div class="card"><h3>Emotion — Plutchik</h3>{_emotion_bars(data["emotion_distribution"])}</div>'
            '</div>'
            f'<div class="card"><h3>Overall sentiment</h3>{_sentiment(data.get("sentiment", {}))}</div>'
            f'<div class="card"><h3>Source breakdown</h3>{_sources_table(data.get("top_sources", []))}</div>'
        )
    else:
        body = ('<div class="empty">No classified articles in this window yet.<br>'
                'The F1 classifier fills framing/emotion/sentiment in the background — '
                'this view lights up as it runs.</div>')
    cov_line = f'<div class="cov">{_esc(note)}</div>' if note else ""
    opts = "".join(f'<option value="{d}"{" selected" if d==days else ""}>{d} days</option>'
                   for d in (7, 14, 30, 90))
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{_esc(query)+' — ' if query else ''}Echolot Framing Analysis</title>"
        f"<style>{_CSS}</style></head><body><div class=wrap>"
        '<div class="topbar"><div class="brand"><a href="/" style="color:inherit">Echolot</a> '
        '<small>framing &amp; emotion analysis</small></div>'
        '<button id="tt" class="tt">☀ Day</button></div>'
        '<form class="q" method="get" action="/analysis">'
        f'<input type="text" name="query" value="{_esc(query)}" placeholder="Topic filter (optional) — e.g. \'migration\', \'Magyar Péter\'">'
        f'<select name="days">{opts}</select><button type="submit">Analyze</button></form>'
        + cov_line + body
        + '<div class="foot">Generated by Echolot — framing, emotion &amp; sentiment across 93 media spheres.</div>'
        + f"<script>{_THEME_JS}</script></div></body></html>"
    )
