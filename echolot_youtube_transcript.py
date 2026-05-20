"""Echolot YouTube transcript fetcher — youtube-transcript-api wrapper.

Visszaad egy egységesített transcript-payload-ot egy YouTube `video_id`-ra.
A `youtube-transcript-api` (1.2.x) timedtext-endpointot hív, no API-key
kell, de Cloud-flare / consent-fal blokkolhatja proxy nélkül EU-s IP-ről —
ezekre fallback None.

Architektúra
------------
- ``fetch_transcript(video_id, lang_preference)`` → dict vagy None
- In-memory cache 24h TTL-lel (transcript ritkán változik)
- ``select_language()`` segéd — kézzel-készített > auto-generated, preferált
  nyelv prioritás, fallback bármilyen elérhetőre.

Payload-shape
-------------
    {
        "video_id": "abc123XYZ_",
        "language_code": "hu",
        "language": "Hungarian",
        "is_generated": False,
        "segments": [
            {"start": 1.13, "duration": 2.75, "text": "..."},
            ...
        ],
        "plain_text": "összevont szöveg sortörés-szeparátorral"
    }
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

log = logging.getLogger("echolot.youtube_transcript")

CACHE_TTL_SEC = 24 * 60 * 60   # 24 óra — transcript ritkán változik
_cache: dict[tuple[str, Optional[str]], tuple[float, Optional[dict]]] = {}

# Worldmonitor-style proxy env-var. Format: "http://user:pass@host:port" vagy
# "http://host:port". Ha nincs beállítva, közvetlen request megy a YouTube
# timedtext-szerveréhez — DC-IP-ket (Railway, Fly, Vercel egyaránt) ez sok
# esetben blokkolja vagy üresíti, ezért production-on proxy kell.
YOUTUBE_PROXY_URL: Optional[str] = os.environ.get("YOUTUBE_PROXY_URL") or None


def _select_transcript(transcript_list, lang_preference: Optional[str]):
    """Válassz a TranscriptList-ből: preferált nyelv > kézzel készített > auto.

    Returns a Transcript object (vagy raise).
    """
    candidates = list(transcript_list)
    if not candidates:
        raise RuntimeError("no transcripts available")

    def score(tr) -> tuple:
        # Magasabb pontszám = jobb
        lang_match = (
            2 if (lang_preference and tr.language_code == lang_preference) else
            1 if (lang_preference and tr.language_code.startswith(lang_preference[:2])) else
            0
        )
        manual_bonus = 0 if tr.is_generated else 1
        return (lang_match, manual_bonus)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def fetch_transcript(
    video_id: str,
    lang_preference: Optional[str] = None,
    *,
    translate_to: Optional[str] = None,
) -> Optional[dict]:
    """Fetch + cache a YouTube transcript.

    Args:
        video_id: YouTube video ID (11 char).
        lang_preference: preferált nyelvkód (pl. "hu", "en"). Ha nincs ilyen
            nyelvű transcript, fallback bármi elérhetőre.
        translate_to: ha megadva, a kiválasztott transcript-et lefordítja
            erre a nyelvre (ha `is_translatable`).

    Returns:
        Dict payload (lásd modul-docstring), vagy None ha hiba / nincs
        elérhető transcript.
    """
    if not video_id or len(video_id) != 11:
        return None

    cache_key = (video_id, lang_preference or "")
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and (now - hit[0]) < CACHE_TTL_SEC:
        return hit[1]

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        chosen = _select_transcript(transcript_list, lang_preference)

        if translate_to and translate_to != chosen.language_code and chosen.is_translatable:
            try:
                chosen = chosen.translate(translate_to)
            except Exception as exc:
                log.info("transcript translate to %s failed: %s", translate_to, exc)

        fetched = chosen.fetch()
        segments = []
        for snip in fetched:
            segments.append({
                "start": float(getattr(snip, "start", 0.0) or 0.0),
                "duration": float(getattr(snip, "duration", 0.0) or 0.0),
                "text": (getattr(snip, "text", "") or "").strip(),
            })
        plain_text = "\n".join(s["text"] for s in segments if s["text"])
        payload = {
            "video_id": video_id,
            "language_code": getattr(chosen, "language_code", "?"),
            "language": getattr(chosen, "language", "?"),
            "is_generated": bool(getattr(chosen, "is_generated", False)),
            "segments": segments,
            "plain_text": plain_text,
        }
        _cache[cache_key] = (now, payload)
        return payload

    except ImportError:
        log.warning("youtube-transcript-api nincs telepítve")
        _cache[cache_key] = (now, None)
        return None
    except Exception as exc:
        # Tipikus okok: transcripts disabled, video private/removed,
        # consent-wall, network error. Mind None-t adunk vissza, a hibát
        # logoljuk.
        log.info("transcript fetch failed for %s: %s — %s",
                 video_id, type(exc).__name__, str(exc)[:140])
        _cache[cache_key] = (now, None)
        return None


def format_timestamp(seconds: float) -> str:
    """`12.34` → `00:12` ; `124.56` → `02:04` ; `4824.5` → `1:20:24`."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def clear_cache() -> None:
    _cache.clear()
