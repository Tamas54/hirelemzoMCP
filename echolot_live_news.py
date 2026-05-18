"""Live news TV viewer backend — YouTube live-stream scraper + HLS map + cache.

Standalone-ban fut a tv-viewer/ sandboxon belül; integráláskor a fő
echolot_app-be importálódik majd. A logikát a worldmonitor
ais-relay.cjs `handleYouTubeLiveRequest` (~5320-5400. sor) Python-port-ja
adja.

Architektúra
------------
1. ``DIRECT_HLS_MAP`` — csatorna-id → direct CDN m3u8 URL. Ezek NEM
   igényelnek YouTube-scrape-et, csak HLS.js + `<video>`.
2. ``CHANNELS`` — 9 default csatorna konfig (id, name, YT-handle,
   fallback-videoId). Ha van DIRECT_HLS, azt használjuk; egyébként a
   YT live-page-éről scrape-elünk hlsManifestUrl-t és videoId-t.
3. ``fetch_live_info(channel_handle)`` — egy YT-handle (pl. `@CNN`) live
   oldalának HTML letöltése + regex extract: ``"videoId":"..."`` és
   ``"hlsManifestUrl":"..."``. 5min cache.
4. ``resolve_channel(channel_id)`` — magasabb szintű: kombináll
   DIRECT_HLS_MAP-et + fetch_live_info-t. Visszaad
   ``{videoId, hlsUrl, isLive, name, handle, fallbackVideoId}``.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("echolot.live_news")

# ── Configuration ─────────────────────────────────────────────────────

# Egyezzen a böngészők modern UA-jával — különben a YT live-page bizonyos
# botdetect-rendszerei eltérő HTML-t adnak (mobile vagy hibakód).
CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

CACHE_TTL_SEC = 5 * 60  # 5 perc — egyezik a worldmonitor relay-jével

# Worldmonitor ais-relay.cjs ugyanezt használja YOUTUBE_PROXY_URL env-ből.
# Format: "http://user:pass@host:port" vagy "http://host:port".
# Ha nincs beállítva, közvetlen kérés megy — EU-s IP-ről ekkor consent-wall
# blokkolhatja az isLive detektálást (sok csatornánál fallback aktiválódik).
YOUTUBE_PROXY_URL: Optional[str] = os.environ.get("YOUTUBE_PROXY_URL") or None

# Worldmonitor LiveNewsPanel.ts 220-250. sor: a 9 default csatornából
# ezek MŰKÖDNEK direct HLS-szel. Vagyis itt NEM kell YT-scrape; csak
# közvetlen <video> + hls.js.
DIRECT_HLS_MAP: dict[str, str] = {
    "sky": "https://linear901-oo-hls0-prd-gtm.delivery.skycdp.com/17501/sde-fast-skynews/master.m3u8",
    "euronews": "https://dash4.antik.sk/live/test_euronews/playlist.m3u8",
    "dw": "https://dwamdstream103.akamaized.net/hls/live/2015526/dwstream103/master.m3u8",
    "france24": "https://amg00106-france24-france24-samsunguk-qvpp8.amagi.tv/playlist/amg00106-france24-france24-samsunguk/playlist.m3u8",
    "alarabiya": "https://live.alarabiya.net/alarabiapublish/alarabiya.smil/playlist.m3u8",
}


@dataclass
class Channel:
    """A live news channel — either direct HLS or YouTube-scraped."""
    id: str
    name: str
    handle: Optional[str] = None      # YouTube handle, e.g. "@CNN"
    fallback_video_id: Optional[str] = None
    use_fallback_only: bool = False   # Skip YT-scrape, always use fallback


# Worldmonitor FULL_LIVE_CHANNELS — a 9 default. AlJazeera + AlArabiya
# fix fallback-videoId-vel jönnek mert a YT-live detektálás gyakran
# megbukik geo-blokk miatt.
CHANNELS: list[Channel] = [
    Channel("bloomberg", "Bloomberg",  "@markets",           "iEpJwprxDdk"),
    Channel("sky",       "Sky News",   "@SkyNews",           "uvviIF4725I"),
    Channel("euronews",  "Euronews",   "@euronews",          "pykpO5kQJ98"),
    Channel("dw",        "DW",         "@DWNews",            "LuKwFajn37U"),
    Channel("cnbc",      "CNBC",       "@CNBC",              "9NyxcX3rhQs"),
    Channel("cnn",       "CNN",        "@CNN",               "w_Ma8oQLmSM"),
    Channel("france24",  "France 24",  "@FRANCE24",          "u9foWyMSETk"),
    Channel("alarabiya", "Al Arabiya", "@AlArabiya",         "n7eQejkXbnM", use_fallback_only=True),
    Channel("aljazeera", "Al Jazeera", "@AlJazeeraEnglish",  "gCNeDWCI0vo", use_fallback_only=True),
]

_CHANNEL_BY_ID: dict[str, Channel] = {c.id: c for c in CHANNELS}


# ── Cache ─────────────────────────────────────────────────────────────

@dataclass
class CacheEntry:
    video_id: Optional[str]
    hls_url: Optional[str]
    is_live: bool
    ts: float


_cache: dict[str, CacheEntry] = {}


# ── YouTube live scrape ───────────────────────────────────────────────

_RE_VIDEO_ID = re.compile(r'"videoId":"([a-zA-Z0-9_-]{11})"')
_RE_IS_LIVE = re.compile(r'"isLive"\s*:\s*true')
_RE_HLS_MANIFEST = re.compile(r'"hlsManifestUrl"\s*:\s*"([^"]+)"')


def _scrape_yt_live(handle: str, *, timeout: float = 12.0) -> tuple[Optional[str], Optional[str]]:
    """Fetch a YouTube channel's /live page and extract videoId + hlsUrl.

    Returns ``(video_id, hls_url)`` where each may be None if not found.
    Matches the ais-relay.cjs ``handleYouTubeLiveRequest`` logic — looks
    for the ``"videoDetails"`` block (next 5000 chars), then regex.
    """
    handle = handle if handle.startswith("@") else f"@{handle}"
    url = f"https://www.youtube.com/{handle}/live"

    # Worldmonitor-stílusú request: ha van YOUTUBE_PROXY_URL beállítva,
    # azon át megy (deploy non-EU IP-ről). Ha nincs proxy, közvetlen +
    # SOCS/CONSENT cookie a GDPR-fal bypass-olásához. (A worldmonitor
    # node-runtime proxy-val él; mi a cookies-szal pótoljuk dev-időre.)
    client_kwargs: dict = {
        "timeout": timeout,
        "follow_redirects": True,
        "headers": {
            "User-Agent": CHROME_UA,
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "http2": True,
    }
    if YOUTUBE_PROXY_URL:
        client_kwargs["proxy"] = YOUTUBE_PROXY_URL
    else:
        # GDPR consent-wall bypass cookies (NON-EU proxy esetén nem kellenek)
        client_kwargs["cookies"] = {
            "CONSENT": "YES+cb.20240314-07-p0.en+FX+123",
            "SOCS": "CAESEwgDEgk2NjA1OTM5MjEaAmVuIAEaBgiA9NK6Bg",
        }
    try:
        with httpx.Client(**client_kwargs) as client:
            r = client.get(url)
            if r.status_code != 200:
                log.info("yt-scrape %s: HTTP %s", handle, r.status_code)
                return None, None
            html = r.text
            if "consent.youtube.com" in str(r.url) or "ConsentUi" in html[:2000]:
                log.warning("yt-scrape %s: hit consent wall", handle)
                return None, None
    except Exception as exc:
        log.warning("yt-scrape %s: fetch failed: %s", handle, exc)
        return None, None

    # videoDetails block: 5000 chars utáni régió scope-ja (worldmonitor logika)
    video_id: Optional[str] = None
    details_idx = html.find('"videoDetails"')
    if details_idx != -1:
        block = html[details_idx : details_idx + 5000]
        vid_match = _RE_VIDEO_ID.search(block)
        live_match = _RE_IS_LIVE.search(block)
        if vid_match and live_match:
            video_id = vid_match.group(1)

    # HLS-manifest a teljes HTML-en. A JSON-encoded URL `&` jelekkel
    # tartalmazza az ampersandokat — ezeket vissza kell decode-olni `&`-re,
    # különben a HLS.js nem tudja a query-stringet parse-olni.
    hls_url: Optional[str] = None
    if video_id:
        hls_match = _RE_HLS_MANIFEST.search(html)
        if hls_match:
            hls_url = hls_match.group(1).replace(r"&", "&")

    return video_id, hls_url


# ── Public API ────────────────────────────────────────────────────────

def resolve_channel(channel_id: str) -> dict:
    """Return live info for a channel.

    Result shape:
        {
          "channel_id": str,
          "name": str,
          "handle": str | None,
          "video_id": str | None,        # YouTube video id (for iframe embed)
          "hls_url": str | None,         # m3u8 (for hls.js native <video>)
          "is_live": bool,
          "source": "direct" | "yt_live" | "fallback",
        }

    Lookup order:
        1. DIRECT_HLS_MAP — közvetlen CDN m3u8
        2. YT-scrape (ha nem ``use_fallback_only``)
        3. Fallback videoId — statikus YT-embed
    """
    ch = _CHANNEL_BY_ID.get(channel_id)
    if not ch:
        return {
            "channel_id": channel_id, "name": "", "handle": None,
            "video_id": None, "hls_url": None, "is_live": False,
            "source": "unknown",
        }

    # 1) Direct HLS
    direct_hls = DIRECT_HLS_MAP.get(channel_id)
    if direct_hls:
        return {
            "channel_id": ch.id, "name": ch.name, "handle": ch.handle,
            "video_id": None, "hls_url": direct_hls, "is_live": True,
            "source": "direct",
        }

    # 2) YT-scrape (cache-elve)
    if ch.handle and not ch.use_fallback_only:
        cached = _cache.get(ch.id)
        now = time.time()
        if cached and (now - cached.ts) < CACHE_TTL_SEC:
            if cached.is_live:
                return {
                    "channel_id": ch.id, "name": ch.name, "handle": ch.handle,
                    "video_id": cached.video_id, "hls_url": cached.hls_url,
                    "is_live": True, "source": "yt_live",
                }
        else:
            video_id, hls_url = _scrape_yt_live(ch.handle)
            _cache[ch.id] = CacheEntry(
                video_id=video_id, hls_url=hls_url,
                is_live=bool(video_id), ts=now,
            )
            if video_id:
                return {
                    "channel_id": ch.id, "name": ch.name, "handle": ch.handle,
                    "video_id": video_id, "hls_url": hls_url,
                    "is_live": True, "source": "yt_live",
                }

    # 3) Fallback static videoId
    if ch.fallback_video_id:
        return {
            "channel_id": ch.id, "name": ch.name, "handle": ch.handle,
            "video_id": ch.fallback_video_id, "hls_url": None,
            "is_live": False, "source": "fallback",
        }

    return {
        "channel_id": ch.id, "name": ch.name, "handle": ch.handle,
        "video_id": None, "hls_url": None, "is_live": False,
        "source": "none",
    }


def all_channels() -> list[dict]:
    """Return the 9 default channels as serializable dicts (no live-info)."""
    return [
        {"id": c.id, "name": c.name, "handle": c.handle,
         "has_direct_hls": c.id in DIRECT_HLS_MAP}
        for c in CHANNELS
    ]


def clear_cache() -> None:
    _cache.clear()
