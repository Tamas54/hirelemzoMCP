"""
echolot_theme.py
================
Day/night theming for the public pages.

The canonical Echolot look is the dark "intelligence-terminal / editorial"
night mode. Day mode is its editorial-paper counterpart: a warm off-white
("newsprint") background, ink-black text, a deep teal accent, NO glowing orbs,
and depth carried by soft shadows + hairline borders instead of glassmorphism.

Behaviour (Kommandant decision 2026-06-09):
  - Manual toggle only (no prefers-color-scheme auto-detection).
  - Default = night. The toggle flips to day and persists in a cookie.
  - The cookie is read server-side and emitted as data-theme on <html>, so the
    correct theme is present in the first paint (no flash).

Wiring per page:
  <html lang="{lang}"{theme_html_attr(request)}>
  <style>... existing ... {DAY_THEME_CSS}{THEME_TOGGLE_CSS}</style>
  ... place {theme_toggle_html(lang)} in the top action bar ...
  ... {THEME_TOGGLE_JS} before </body> ...
"""
from __future__ import annotations

COOKIE_NAME = "echolot_theme"


def theme_html_attr(request) -> str:
    """Return ' data-theme="day"' by DEFAULT; '' (night) only when the cookie
    explicitly selects night (Kommandant 2026-06-18: nappali az alapértelmezett).

    Defensive: any failure (no request, no cookies) falls back to day.
    """
    try:
        if request is not None and request.cookies.get(COOKIE_NAME) == "night":
            return ""  # explicit night
    except Exception:
        pass
    return ' data-theme="day"'  # default: nappali


# ── Day-mode token overrides (editorial paper) ───────────────────────────
# Both token systems are overridden: the dashboard :root tokens and the
# landing-v2 tokens scoped under .landing-v2-shell / .rovat-shell / story shell.
DAY_THEME_CSS = """
/* ============ DAY MODE — editorial paper ============ */
:root[data-theme="day"]{
  --primary:#0f766e; --primary-dim:rgba(15,118,110,.10);
  --accent-amber:#b45309; --accent-rose:#be123c; --accent-blue:#1d4ed8;
  --bg:#f7f4ed; --bg-card:#ffffff;
  --text:#1a1814; --text-dim:#6b6459;
  --border:rgba(26,24,20,.12);
}
[data-theme="day"] .landing-v2-shell,
[data-theme="day"] .lt-shell,
[data-theme="day"] .yt-shell,
[data-theme="day"] .rovat-shell,
[data-theme="day"] .story-detail-shell{
  --bg-0:#f7f4ed; --bg-1:#ffffff; --bg-2:#ffffff; --bg-3:#f1ede3;
  --line:rgba(26,24,20,.12); --line-soft:rgba(26,24,20,.07);
  --line-strong:rgba(26,24,20,.20);
  --fg-0:#1a1814; --fg-1:#33302a; --fg-2:#6b6459; --fg-3:#8c8576;
  --pol-l:#be123c; --pol-c:#6b6459; --pol-r:#1d4ed8;
  --accent:#0f766e; --muted:#8c8576;
  --sphere-hu-pol:#c0392b; --sphere-hu-econ:#0f766e; --sphere-hu-soc:#b45309;
  --sphere-world-pol:#92633a; --sphere-world-econ:#1d4ed8; --sphere-tech:#6d28d9;
  --sphere-ru:#be123c; --sphere-us:#15803d;
}
/* glowing orbs look muddy on paper — remove them */
[data-theme="day"] .ambient,
[data-theme="day"] .orb{display:none!important;}
/* flat warm-paper background instead of the dark radial atmosphere */
[data-theme="day"] body{background:#f7f4ed;}
[data-theme="day"] .landing-v2-shell{background:#f7f4ed;}
/* glassy dark header → translucent paper */
[data-theme="day"] .header-bar{background:rgba(247,244,237,.85)!important;}
/* solid card surfaces; depth via soft shadow + hairline (not glass) */
[data-theme="day"] .src-card,
[data-theme="day"] .persp-col,
[data-theme="day"] .echolot-faq-item,
[data-theme="day"] .story-detail-header{
  background:#ffffff;
  box-shadow:0 1px 2px rgba(26,24,20,.05),0 10px 28px -18px rgba(26,24,20,.18);
}
[data-theme="day"] .src-card:hover{background:#fffdf8;}
/* deepen the gradient wordmark so it reads on light */
[data-theme="day"] .echolot-title{
  background:linear-gradient(135deg,#0f766e,#0e7490,#1d4ed8);
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
[data-theme="day"] .echolot-logo{color:#0f766e;}
/* nav active pill border on light */
[data-theme="day"] .nav-tab.active{border-color:rgba(15,118,110,.35);}
[data-theme="day"] .nav-tab:hover{background:rgba(26,24,20,.04);}
/* fulltext quote rule */
[data-theme="day"] .src-card-fulltext-body{border-left-color:rgba(26,24,20,.16);}
/* dashboard: a few hardcoded Tailwind dark utilities */
[data-theme="day"] .border-gray-800{border-color:rgba(26,24,20,.12)!important;}
[data-theme="day"] .bg-gray-800{background:#efe9df!important;color:#1a1814!important;}
/* weather embed iframe has an inline dark background — flip it for day */
[data-theme="day"] #weather-embed{background:#ffffff!important;}
/* search box (augment strip) — hardcoded dark, used on both landings */
[data-theme="day"] .echolot-search-input,
[data-theme="day"] .echolot-search-days{
  background:#ffffff!important;color:#1a1814;border-color:rgba(26,24,20,.18);
}
[data-theme="day"] .echolot-search-input::placeholder{color:#8c8576;}
"""


# ── Toggle button + behaviour ────────────────────────────────────────────
THEME_TOGGLE_CSS = """
.theme-toggle{
  display:inline-flex;align-items:center;justify-content:center;
  background:rgba(255,255,255,0.04);
  border:1px solid var(--border,rgba(255,255,255,0.12));
  color:var(--text-dim,#8a9499);
  border-radius:8px;width:34px;height:32px;padding:0;cursor:pointer;
  font-size:0.95rem;line-height:1;transition:all .15s;
}
.theme-toggle:hover{color:var(--text,#e8eef0);border-color:var(--primary,#14b8a6);}
.theme-ico-night{display:none;}
[data-theme="day"] .theme-ico-day{display:none;}
[data-theme="day"] .theme-ico-night{display:inline;}
[data-theme="day"] .theme-toggle{
  background:#ffffff;border-color:rgba(26,24,20,0.18);color:#1a1814;
  box-shadow:0 1px 2px rgba(26,24,20,.08);
}
[data-theme="day"] .theme-toggle:hover{border-color:#0f766e;color:#0f766e;}
"""

_TOGGLE_TITLE = {
    "hu": "Nappali / éjszakai mód", "en": "Day / night mode",
    "de": "Tag- / Nachtmodus", "fr": "Mode jour / nuit",
    "ru": "Дневной / ночной режим", "uk": "Денний / нічний режим",
}


def theme_toggle_html(lang: str = "hu") -> str:
    """A sun/moon toggle. Shows ☀ in night (click → day), ☾ in day (click → night)."""
    title = _TOGGLE_TITLE.get(lang, _TOGGLE_TITLE["hu"])
    return (
        f'<button class="theme-toggle" type="button" onclick="echolotToggleTheme()" '
        f'aria-label="{title}" title="{title}">'
        '<span class="theme-ico-day" aria-hidden="true">☀</span>'
        '<span class="theme-ico-night" aria-hidden="true">☾</span>'
        '</button>'
    )


THEME_TOGGLE_JS = """
<script>
function echolotToggleTheme(){
  var d=document.documentElement;
  var isDay=d.getAttribute('data-theme')==='day';
  if(isDay){
    d.removeAttribute('data-theme');
    document.cookie='echolot_theme=night;path=/;max-age=31536000;samesite=lax';
  }else{
    d.setAttribute('data-theme','day');
    document.cookie='echolot_theme=day;path=/;max-age=31536000;samesite=lax';
  }
  // The weather widget is a separate iframe document — reload it with the new
  // theme so a live toggle updates it too (not just the next page load).
  var wf=document.getElementById('weather-embed');
  if(wf){
    var s=(wf.getAttribute('src')||'').replace(/&theme=day/g,'').replace(/\\?theme=day/g,'?');
    if(!isDay){ s += (s.indexOf('?')>=0?'&':'?') + 'theme=day'; }
    wf.src=s;
  }
}
</script>
"""
