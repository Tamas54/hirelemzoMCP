"""echolot_compare_page — megosztható /compare?q=… weboldal a regional_framing-hez.

A `regional_framing` eddig MCP-only volt (csak agent-hívásból). Ez a lap a
HONLAPRA hozza: egy téma per-régiós keretezését (domináns keret, frame-eloszlás,
átlag-hangulat, szalagcímek) egymás mellett, szerver-renderelve — így a link
chatbotba/emailbe dobva tiszta, idézhető, gazdag preview-vel jelenik meg.

Adat-only: a `regional_framing()` előszámolt klasszifikátor-oszlopokból dolgozik,
NINCS szerver-LLM-hívás. A lap a fő oldalak téma- és SEO-rendszerét használja.
"""
from __future__ import annotations

from html import escape as _esc
from echolot_theme import (theme_html_attr, theme_toggle_html,
                           THEME_TOGGLE_CSS, THEME_TOGGLE_JS)
from echolot_analysis_page import _FRAME_COLOR, _FRAME_LABEL

_L = {
    "title":      {"hu": "Régiós keretezés", "en": "Regional framing"},
    "subtitle":   {"hu": "ki hogyan keretezi ugyanazt a témát",
                   "en": "how each region frames the same topic"},
    "placeholder": {"hu": "téma vagy entitás (pl. Iran, Gaza, Ukrajna)…",
                    "en": "topic or entity (e.g. Iran, Gaza, Ukraine)…"},
    "analyze":    {"hu": "Összevetés", "en": "Compare"},
    "days":       {"hu": "nap", "en": "days"},
    "articles":   {"hu": "cikk", "en": "articles"},
    "dom_frame":  {"hu": "domináns keret", "en": "dominant frame"},
    "sentiment":  {"hu": "hangulat", "en": "sentiment"},
    "regions":    {"hu": "régió", "en": "regions"},
    "empty":      {"hu": "Adj meg egy témát vagy entitást, és az Echolot megmutatja, "
                         "hogyan keretezi ugyanazt a hírt a világ különböző régiói — "
                         "domináns keret, hangulat és szalagcímek egymás mellett.",
                   "en": "Enter a topic or entity, and Echolot shows how the world's "
                         "regions frame the same story — dominant frame, sentiment and "
                         "headlines side by side."},
    "no_results": {"hu": "Nincs találat erre a témára a megadott időszakban.",
                   "en": "No coverage for this topic in the selected window."},
    "back":       {"hu": "Főoldal", "en": "Home"},
}


def _t(key: str, lang: str) -> str:
    d = _L.get(key, {})
    return d.get(lang, d.get("en", key))


def _frame_label(frame: str, lang: str) -> str:
    fl = _FRAME_LABEL.get(lang, _FRAME_LABEL["en"])
    return fl.get(frame, _FRAME_LABEL["en"].get(frame, frame))


def _sentiment_chip(val) -> str:
    """Színes hangulat-chip (-1..+1)."""
    if val is None:
        return '<span class="sent sent-na">—</span>'
    try:
        v = float(val)
    except (TypeError, ValueError):
        return '<span class="sent sent-na">—</span>'
    if v > 0.15:
        cls, sign = "sent-pos", "+"
    elif v < -0.15:
        cls, sign = "sent-neg", ""
    else:
        cls, sign = "sent-neu", ""
    return f'<span class="sent {cls}">{sign}{v:.2f}</span>'


def _frame_bar(dist: dict, lang: str) -> str:
    """Mini frame-eloszlás sáv a régió-kártyán."""
    if not dist:
        return ""
    total = sum(int(v or 0) for v in dist.values()) or 1
    segs = []
    for fr, cnt in sorted(dist.items(), key=lambda kv: -int(kv[1] or 0)):
        n = int(cnt or 0)
        if not n:
            continue
        pct = n * 100 / total
        color = _FRAME_COLOR.get(fr, "#8b949e")
        segs.append(
            f'<span class="fseg" style="flex:{n};background:{color}" '
            f'title="{_esc(_frame_label(fr, lang))}: {n}"></span>'
        )
    return f'<div class="fbar">{"".join(segs)}</div>' if segs else ""


def _region_card(key: str, reg: dict, lang: str) -> str:
    label = _esc(reg.get("label") or key)
    n_art = int(reg.get("articles") or 0)
    dom = reg.get("dominant_frame")
    avg_sent = reg.get("avg_sentiment")
    dist = reg.get("frame_distribution") or {}
    headlines = reg.get("headlines") or []

    dom_html = ""
    if dom:
        color = _FRAME_COLOR.get(dom, "#8b949e")
        dom_html = (f'<span class="frame-badge" style="background:{color}22;'
                    f'color:{color};border-color:{color}55">'
                    f'{_esc(_frame_label(dom, lang))}</span>')

    hl_html = "".join(
        f'<li><a href="{_esc(h.get("url") or "#")}" target="_blank" rel="noopener">'
        f'{_esc(h.get("title") or "")}</a>'
        f'<span class="hsrc">{_esc(h.get("source") or "")}'
        f'<span class="hlang">{_esc(h.get("language") or "")}</span></span></li>'
        for h in headlines[:4]
    )

    return (
        '<div class="region-card">'
        '<div class="rc-head">'
        f'<h3>{label}</h3>'
        f'<span class="rc-n">{n_art} {_esc(_t("articles", lang))}</span>'
        '</div>'
        f'<div class="rc-meta">{dom_html}{_sentiment_chip(avg_sent)}</div>'
        f'{_frame_bar(dist, lang)}'
        f'<ul class="rc-headlines">{hl_html}</ul>'
        '</div>'
    )


_CSS = """
:root{--bg:#0a0d12;--panel:#11161e;--fg:#edf0f4;--fg2:#949eaa;--accent:#14b8a6;--border:#1f2730;}
[data-theme=day]{--bg:#f7f4ed;--panel:#fffdf8;--fg:#1a1f26;--fg2:#5a6470;--accent:#0f766e;--border:#e3ddd0;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,ui-sans-serif,system-ui,sans-serif;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:20px 18px 60px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.brand a{color:var(--fg);text-decoration:none;font-weight:800;font-size:20px}
.brand small{color:var(--fg2);font-weight:500;font-size:13px;margin-left:6px}
.back{color:var(--fg2);text-decoration:none;font-size:14px}
h1.page-h{font-size:26px;margin:6px 0 2px}
.sub{color:var(--fg2);margin:0 0 18px;font-size:15px}
form.q{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
form.q input[type=text]{flex:1;min-width:240px;padding:11px 14px;border-radius:10px;border:1px solid var(--border);background:var(--panel);color:var(--fg);font-size:15px}
form.q select,form.q button{padding:11px 14px;border-radius:10px;border:1px solid var(--border);background:var(--panel);color:var(--fg);font-size:15px;cursor:pointer}
form.q button{background:var(--accent);color:#04110e;border-color:var(--accent);font-weight:700}
.cov{color:var(--fg2);font-size:13px;margin-bottom:16px}
.regions-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.region-card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px}
.rc-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.rc-head h3{margin:0;font-size:17px}
.rc-n{color:var(--fg2);font-size:13px;white-space:nowrap}
.rc-meta{display:flex;gap:8px;align-items:center;margin:8px 0}
.frame-badge{font-size:12px;font-weight:600;padding:2px 9px;border-radius:20px;border:1px solid}
.sent{font-size:12px;font-weight:600;padding:2px 8px;border-radius:20px;font-variant-numeric:tabular-nums}
.sent-pos{background:#2ea04322;color:#3fb950}.sent-neg{background:#f8514922;color:#f85149}
.sent-neu{background:#8b949e22;color:var(--fg2)}.sent-na{color:var(--fg2);opacity:.6}
.fbar{display:flex;height:7px;border-radius:4px;overflow:hidden;margin:10px 0;gap:1px}
.fseg{min-width:2px}
.rc-headlines{list-style:none;margin:6px 0 0;padding:0}
.rc-headlines li{padding:7px 0;border-top:1px solid var(--border)}
.rc-headlines a{color:var(--fg);text-decoration:none;font-size:14px;display:block}
.rc-headlines a:hover{color:var(--accent)}
.hsrc{display:block;color:var(--fg2);font-size:12px;margin-top:2px}
.hlang{margin-left:6px;opacity:.7;text-transform:uppercase;font-size:10px}
.empty{color:var(--fg2);background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:30px;text-align:center;font-size:15px}
"""


def render_compare_page(data: dict | None, *, query: str = "", days: int = 14,
                        lang: str = "hu", request=None, head_extra: str = "") -> str:
    """Teljes HTML-lap. data=None / üres query → űrlap (empty state)."""
    title = f"{_esc(query) + ' — ' if query else ''}{_t('title', lang)} · Echolot"
    opts = "".join(
        f'<option value="{d}"{" selected" if d == days else ""}>{d} {_esc(_t("days", lang))}</option>'
        for d in (7, 14, 30))

    if not query or not data:
        body = f'<div class="empty">{_esc(_t("empty", lang))}</div>'
        cov = ""
    else:
        by_region = data.get("by_region") or {}
        regions = sorted(by_region.items(),
                         key=lambda kv: -int((kv[1] or {}).get("articles") or 0))
        if not regions:
            body = f'<div class="empty">{_esc(_t("no_results", lang))}</div>'
        else:
            cards = "".join(_region_card(k, r, lang) for k, r in regions)
            body = f'<div class="regions-grid">{cards}</div>'
        c = data.get("classification_coverage") or {}
        cov = (f'<div class="cov">{data.get("regions_found", 0)} {_esc(_t("regions", lang))} · '
               f'{c.get("articles_classified", 0)}/{c.get("articles_total", 0)} '
               f'({c.get("percent", 0)}%) {_esc(c.get("note", ""))}</div>')

    return (
        f'<!doctype html><html lang="{lang}"{theme_html_attr(request)}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title>'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
        f'<style>{_CSS}{THEME_TOGGLE_CSS}</style>{head_extra}</head><body>'
        '<div class="wrap">'
        '<div class="topbar"><div class="brand">'
        f'<a href="/?lang={lang}">Echolot</a> <small>{_esc(_t("subtitle", lang))}</small></div>'
        + theme_toggle_html(lang) + '</div>'
        f'<a class="back" href="/?lang={lang}">← {_esc(_t("back", lang))}</a>'
        f'<h1 class="page-h">{_esc(_t("title", lang))}</h1>'
        f'<p class="sub">{_esc(_t("subtitle", lang))}</p>'
        f'<form class="q" method="get" action="/compare">'
        f'<input type="hidden" name="lang" value="{lang}">'
        f'<input type="text" name="q" value="{_esc(query)}" placeholder="{_esc(_t("placeholder", lang))}" autofocus>'
        f'<select name="days">{opts}</select>'
        f'<button type="submit">{_esc(_t("analyze", lang))}</button></form>'
        + cov + body
        + THEME_TOGGLE_JS + '</div></body></html>'
    )
