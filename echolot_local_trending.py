"""Lang-aware helyi trending aggregátor a Ground News-szerű főoldalra.

A felhasználó ?lang=X szerint kiválasztja a megfelelő geo-t és vegyíti
a Wikipedia top-pageviews + Google News + sphere-velocity adatokat.

A három forrás párhuzamosan async-ben fut. Hibatűrő: ha egyik forrás
elhasal (timeout, API quota, hiányzó modul), {error, results: []}
struktúrával válaszol és a többi forrás eredménye továbbra is használható.

Egységes API a frontend felé::

    from echolot_local_trending import build_local_trending
    data = await build_local_trending(lang="hu", db_path="echolot.db")

Cache: 5 perces TTL kulcsolva (lang, wiki_limit, gnews_limit, velocity_limit)
szerint.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

log = logging.getLogger("echolot.local_trending")

# ---------------------------------------------------------------------------
# Optional imports — minden forrás védve van, ha valamelyik modul hiányzik
# vagy átalakul, az aggregátor még mindig az elérhető részeket adja vissza.
# ---------------------------------------------------------------------------
try:
    from echolot_wiki_daily_top import top_pageviews as _wiki_top_pageviews
except Exception as _exc:  # pragma: no cover - import-time guard
    log.warning("local_trending: wiki module unavailable: %s", _exc)
    _wiki_top_pageviews = None  # type: ignore[assignment]

try:
    from echolot_gnews_trends import fetch_country_trending as _gnews_fetch
except Exception as _exc:  # pragma: no cover
    log.warning("local_trending: gnews module unavailable: %s", _exc)
    _gnews_fetch = None  # type: ignore[assignment]

# A meglévő modul exportja `compute_sphere_velocity` (NEM `compute_velocity`).
# A task-leírás `compute_velocity`-t említett, de a tényleges signatura
# `compute_sphere_velocity(db_path, window_hours, baseline_offset_hours,
# baseline_window_hours, min_baseline, limit)`. Mindkét nevet megpróbáljuk
# importálni a forward-compat kedvéért.
_velocity_fn = None
try:
    from echolot_velocity import compute_sphere_velocity as _velocity_fn  # type: ignore[assignment]
except Exception:
    try:
        from echolot_velocity import compute_velocity as _velocity_fn  # type: ignore[assignment]
    except Exception as _exc:  # pragma: no cover
        log.warning("local_trending: velocity module unavailable: %s", _exc)
        _velocity_fn = None


# ---------------------------------------------------------------------------
# Lang → geo / sphere-prefix mapping
# ---------------------------------------------------------------------------
# A `sphere_substr` a sphere-nevek-en illeszkedő substring (case-insensitive).
# A velocity-szűrő a globális `global_*` sphere-eket MINDIG visszaadja,
# függetlenül a lang-tól (cross-cultural anchor).
LANG_TO_TRENDING_GEO: dict[str, dict[str, str]] = {
    "hu": {"wiki": "hu", "gnews": "HU", "sphere_substr": "hu_"},
    "en": {"wiki": "en", "gnews": "US", "sphere_substr": "regional_us"},
    "de": {"wiki": "de", "gnews": "DE", "sphere_substr": "regional_german"},
    "es": {"wiki": "es", "gnews": "ES", "sphere_substr": "regional_spanish"},
    "zh": {"wiki": "zh", "gnews": "CN", "sphere_substr": "regional_chinese"},
    "fr": {"wiki": "fr", "gnews": "FR", "sphere_substr": "regional_french"},
    "pl": {"wiki": "pl", "gnews": "PL", "sphere_substr": "regional_polish"},
    "ru": {"wiki": "ru", "gnews": "RU", "sphere_substr": "regional_russian"},
    "uk": {"wiki": "uk", "gnews": "UA", "sphere_substr": "regional_ukrainian"},
    "it": {"wiki": "it", "gnews": "IT", "sphere_substr": "regional_italian"},
}

DEFAULT_LANG = "hu"

# 5 perc cache — kulcsa az összes paraméter, hogy különböző limit-kombinációk
# ne ütközzenek.
CACHE_TTL = 5 * 60
_cache: dict[tuple, tuple[float, dict]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_geo(lang: str) -> tuple[str, dict[str, str]]:
    """Normalize lang → (lang, geo-config). Esik vissza DEFAULT_LANG-ra."""
    norm = (lang or "").lower().strip()
    if norm not in LANG_TO_TRENDING_GEO:
        log.debug("local_trending: unknown lang %r → fallback %s", lang, DEFAULT_LANG)
        norm = DEFAULT_LANG
    return norm, LANG_TO_TRENDING_GEO[norm]


def _build_wiki_url(article: str, wiki_field: str, geo_wiki: str) -> str:
    """https://hu.wikipedia.org/wiki/<article>

    `wiki_field` az upstream által visszaadott `wiki` mező (pl. `"hu.wikipedia"`),
    `geo_wiki` a kért 2-betűs lang. Mindkettőből próbálunk értelmes hostot
    építeni — a `wiki_field` az elsődleges, mert pontosan tükrözi az upstream
    által ténylegesen lekérdezett wiki-t.
    """
    host = (wiki_field or "").strip()
    if not host:
        host = f"{(geo_wiki or 'en').lower()}.wikipedia"
    if not host.endswith(".org"):
        host = f"{host}.org"
    if not host.startswith("http"):
        host = f"https://{host}"
    # Az `article` URL-encoded mezőre nem szabad encode-olni — a Wikipedia
    # az aláhúzásos formát natívan elfogadja, és a benne lévő "%-jelek"
    # eleve URL-safe kódolásban érkeznek.
    return f"{host}/wiki/{article}"


async def _safe_wiki(geo_wiki: str, limit: int) -> dict:
    """Wiki top-pageviews → {results: [...]} vagy {error, results: []}."""
    if _wiki_top_pageviews is None:
        return {"error": "wiki_module_unavailable", "results": []}
    try:
        raw = await _wiki_top_pageviews(geo_wiki=geo_wiki, limit=limit)
    except Exception as exc:
        log.warning("local_trending: wiki fetch failed (%s): %s", geo_wiki, exc)
        return {"error": f"{type(exc).__name__}: {exc}", "results": []}
    enriched: list[dict] = []
    for item in raw or []:
        article = item.get("article", "")
        enriched.append({
            "article": article,
            "title": item.get("title") or article.replace("_", " "),
            "views": item.get("views", 0),
            "rank": item.get("rank"),
            "wiki_url": _build_wiki_url(article, item.get("wiki", ""), geo_wiki),
        })
    return {"results": enriched}


async def _safe_gnews(geo: str, limit: int) -> dict:
    """Google News country trending → {results: [...]} vagy {error, results: []}.

    `fetch_country_trending` szinkron (feedparser blocking I/O), ezért
    `asyncio.to_thread`-ban futtatjuk, hogy ne blokkolja az event loop-ot.
    """
    if _gnews_fetch is None:
        return {"error": "gnews_module_unavailable", "results": []}
    try:
        raw = await asyncio.to_thread(_gnews_fetch, geo, limit)
    except Exception as exc:
        log.warning("local_trending: gnews fetch failed (%s): %s", geo, exc)
        return {"error": f"{type(exc).__name__}: {exc}", "results": []}
    results: list[dict] = []
    for item in raw or []:
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "source": item.get("source", ""),
            "published": item.get("published", ""),
        })
    return {"results": results}


def _is_global_sphere(name: str) -> bool:
    return (name or "").startswith("global_")


def _matches_lang_sphere(name: str, sphere_substr: str) -> bool:
    """Case-insensitive substring match a lang-specifikus sphere-prefixre."""
    if not name or not sphere_substr:
        return False
    return sphere_substr.lower() in name.lower()


async def _safe_velocity(db_path: str, sphere_substr: str, limit: int) -> dict:
    """Sphere velocity → {results: [...]} szűrve a lang-szerinti + global_* sphere-ekre.

    A `compute_sphere_velocity` szinkron (sqlite3), ezért threadben fut.
    A felfelé limit-et nagyobbra állítjuk (limit*5), majd a szűrés UTÁN
    vágjuk a kívánt darabszámra — különben a lang-irreleváns spike-ok
    elnyomhatnák a hu_* sphere-eket.
    """
    if _velocity_fn is None:
        return {"error": "velocity_module_unavailable", "results": []}
    try:
        raw = await asyncio.to_thread(
            _velocity_fn,
            db_path,
            6,    # window_hours
            48,   # baseline_offset_hours
            24,   # baseline_window_hours
            2,    # min_baseline
            max(limit * 5, 50),  # over-fetch then filter
        )
    except TypeError:
        # Eltérő signatura (pl. csak kwargok) — fall back kwarg-only call-ra.
        try:
            raw = await asyncio.to_thread(
                _velocity_fn,
                db_path=db_path,
                window_hours=6,
                limit=max(limit * 5, 50),
            )
        except Exception as exc:
            log.warning("local_trending: velocity (kwargs) failed: %s", exc)
            return {"error": f"{type(exc).__name__}: {exc}", "results": []}
    except Exception as exc:
        log.warning("local_trending: velocity failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}", "results": []}

    spheres = []
    if isinstance(raw, dict):
        spheres = raw.get("spheres", []) or []
    elif isinstance(raw, list):
        # Ha valamiért lista jön vissza, kezeljük le.
        spheres = raw

    filtered: list[dict] = []
    for s in spheres:
        name = s.get("sphere", "")
        if _is_global_sphere(name) or _matches_lang_sphere(name, sphere_substr):
            filtered.append({
                "sphere": name,
                "current_count": s.get("current_count", 0),
                "baseline_count": s.get("baseline_count", 0),
                "velocity_ratio": s.get("velocity_ratio"),
                "status": s.get("status", ""),
            })
        if len(filtered) >= limit:
            break
    return {"results": filtered}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def build_local_trending(
    lang: str,
    db_path: str,
    wiki_limit: int = 10,
    gnews_limit: int = 10,
    velocity_limit: int = 10,
) -> dict:
    """Aggregálja a 3 trending forrást a megadott lang-hoz.

    Args:
        lang: 2-betűs nyelvkód (`SUPPORTED_LANGS` egyike). Ismeretlen lang-ra
            DEFAULT_LANG-ra (hu) esik vissza.
        db_path: SQLite DB útvonal a velocity-számításhoz.
        wiki_limit: max Wikipedia top cikk.
        gnews_limit: max Google News trending headline.
        velocity_limit: max sphere-velocity rekord (lang-szűrés UTÁN).

    Returns:
        {
            "lang": "hu",
            "geo": {"wiki": "hu", "gnews": "HU", "sphere_substr": "hu_"},
            "wiki": {"results": [{article, title, views, rank, wiki_url}, ...],
                     "error"?: str},
            "gnews": {"results": [{title, link, source, published}, ...],
                      "error"?: str},
            "velocity": {"results": [{sphere, current_count, baseline_count,
                         velocity_ratio, status}, ...], "error"?: str},
            "cached": bool,
            "fetched_at": <epoch>,
        }

    Hibatűrő — egy-egy forrás bukása nem dönti az egészet, csak az adott
    forráshoz kerül `error` mező és üres `results` lista.
    """
    norm_lang, geo = _resolve_geo(lang)
    cache_key = (norm_lang, wiki_limit, gnews_limit, velocity_limit, db_path)
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL:
        cached_payload = dict(hit[1])
        cached_payload["cached"] = True
        return cached_payload

    log.info(
        "local_trending: building lang=%s wiki_geo=%s gnews_geo=%s",
        norm_lang, geo["wiki"], geo["gnews"],
    )

    # 3 forrás párhuzamosan. `return_exceptions=True` extra védelem —
    # a _safe_* wrapperek már elnyelik a hibákat, de a gather-szintű guard
    # garantálja, hogy semmilyen kivétel ne propagálódjon ki.
    wiki_task = _safe_wiki(geo["wiki"], wiki_limit)
    gnews_task = _safe_gnews(geo["gnews"], gnews_limit)
    velocity_task = _safe_velocity(db_path, geo["sphere_substr"], velocity_limit)

    results = await asyncio.gather(
        wiki_task, gnews_task, velocity_task, return_exceptions=True,
    )

    def _unwrap(res: Any, name: str) -> dict:
        if isinstance(res, BaseException):
            log.warning("local_trending: %s task raised %s", name, res)
            return {"error": f"{type(res).__name__}: {res}", "results": []}
        if not isinstance(res, dict):
            return {"error": "invalid_result_type", "results": []}
        return res

    payload: dict = {
        "lang": norm_lang,
        "geo": dict(geo),
        "wiki": _unwrap(results[0], "wiki"),
        "gnews": _unwrap(results[1], "gnews"),
        "velocity": _unwrap(results[2], "velocity"),
        "cached": False,
        "fetched_at": now,
    }

    _cache[cache_key] = (now, payload)
    return payload


def clear_cache() -> None:
    """Test/debug helper — törli a teljes cache-t."""
    _cache.clear()


__all__ = [
    "LANG_TO_TRENDING_GEO",
    "DEFAULT_LANG",
    "build_local_trending",
    "clear_cache",
]
