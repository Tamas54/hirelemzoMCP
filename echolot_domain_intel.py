"""Echolot ↔ domain-intel embedded adapter.

Thin wrapper around `echolot-domain-intel/domain_intel/` that exposes a
sync, sqlite-aware API to the main Echolot app (dashboard, story reach,
source-card enrichment).

Public surface:
  - domain_from_url(url) → str | None
  - get_audience_for_domain(domain, country_hint=None) → dict | None
  - get_audience_for_source(db_path, source_id) → dict | None
  - compute_story_reach(db_path, source_ids) → dict | None

Init cost: building AudienceEstimator + COUNTRY_DATA tables is ~5 ms.
Per-call cost after lru_cache warm-up: O(1).
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# sys.path injection so we can `from domain_intel ...`
_BASE_DIR = Path(__file__).resolve().parent
_DI_DIR = _BASE_DIR / "echolot-domain-intel"
if _DI_DIR.is_dir() and str(_DI_DIR) not in sys.path:
    sys.path.insert(0, str(_DI_DIR))

from domain_intel.audience import AudienceEstimator  # noqa: E402
from domain_intel.calibration_data import (  # noqa: E402
    COUNTRY_DATA,
    DAILY_TO_MONTHLY_RATIO,
    STORY_VISIBILITY_BUCKETS,
    STORY_VISIBILITY_DEFAULT,
)
from domain_intel.models import (  # noqa: E402
    ConfidenceLevel,
    GeographyInfo,
    RankInfo,
    RankSource,
)
from domain_intel.ranking import DailyRankingDB  # noqa: E402


# Lazy singletons -------------------------------------------------------------

_audience: Optional[AudienceEstimator] = None
_ranking_db: Optional[DailyRankingDB] = None
_ranking_init_attempted: bool = False


def _get_audience() -> AudienceEstimator:
    global _audience
    if _audience is None:
        _audience = AudienceEstimator()
    return _audience


def _get_ranking_db() -> Optional[DailyRankingDB]:
    """Lazy-load the Tranco/Umbrella/Majestic CSVs from the standalone
    PoC data dir. Returns None if data isn't available (graceful fallback
    to anchor-only mode)."""
    global _ranking_db, _ranking_init_attempted
    if _ranking_db is not None or _ranking_init_attempted:
        return _ranking_db
    _ranking_init_attempted = True
    data_dir = _DI_DIR / "data"
    if not data_dir.is_dir():
        logger.info("ranking data dir not found at %s; anchor-only mode", data_dir)
        return None
    try:
        db = DailyRankingDB(data_dir=data_dir)
        db.load_all()
        loaded = sum(1 for s in db.sources if s.is_loaded)
        if loaded == 0:
            logger.info("ranking DB has no loaded sources; anchor-only mode")
            return None
        logger.info("ranking DB loaded: %d sources", loaded)
        _ranking_db = db
    except Exception as e:
        logger.warning("ranking DB init failed: %s", e)
    return _ranking_db


# Source weights for DNS-rank consensus (same as analyzer.py:_SOURCE_WEIGHTS)
_RANK_SOURCE_WEIGHTS = {"tranco": 1.0, "majestic": 1.0, "umbrella": 0.15}


def _consensus_from_db(domain: str) -> Optional[tuple[int, list[RankSource]]]:
    """Look up domain in the ranking CSVs, compute weighted-geomean consensus."""
    db = _get_ranking_db()
    if not db:
        return None
    import math as _math
    sources_out: list[RankSource] = []
    log_sum = 0.0
    total_w = 0.0
    for src in db.sources:
        if not src.is_loaded:
            continue
        rank = src._ranks.get(domain)
        if rank is None:
            continue
        w = _RANK_SOURCE_WEIGHTS.get(src.name, 1.0)
        log_sum += _math.log(rank) * w
        total_w += w
        sources_out.append(RankSource(
            source=src.name, rank=rank,
            license=getattr(src, "license", "unknown"),
        ))
    if not sources_out or total_w <= 0:
        return None
    consensus = int(_math.exp(log_sum / total_w))
    return consensus, sources_out


# ccTLD → country. Strong signal: a .hu domain is overwhelmingly Hungarian.
_CCTLD_TO_COUNTRY: dict[str, str] = {
    "hu": "HU", "de": "DE", "fr": "FR", "es": "ES", "it": "IT", "pl": "PL",
    "ru": "RU", "ua": "UA", "by": "BY", "il": "IL", "ir": "IR", "tr": "TR",
    "ae": "AE", "sa": "SA", "eg": "EG", "at": "AT", "ch": "CH", "be": "BE",
    "nl": "NL", "pt": "PT", "se": "SE", "no": "NO", "dk": "DK", "fi": "FI",
    "ie": "IE", "gr": "GR", "cz": "CZ", "sk": "SK", "ro": "RO", "bg": "BG",
    "hr": "HR", "si": "SI", "rs": "RS", "cn": "CN", "jp": "JP", "kr": "KR",
    "in": "IN", "id": "ID", "sg": "SG", "ca": "CA", "mx": "MX", "br": "BR",
    "ar": "AR", "au": "AU", "za": "ZA", "uk": "GB", "gb": "GB",
}

# Language → country fallback. ONLY for languages spoken in a clearly
# dominant single country (no English/Arabic/Spanish multi-country mess).
_LANG_TO_COUNTRY_SINGLE: dict[str, str] = {
    "hu": "HU", "ja": "JP", "ko": "KR", "he": "IL", "fa": "IR", "th": "TH",
    "vi": "VN", "pl": "PL", "cs": "CZ", "sk": "SK", "ro": "RO", "el": "GR",
    "bg": "BG", "hr": "HR", "sl": "SI", "be": "BY", "uk": "UA",
}


def _country_for_source(domain: Optional[str], language: Optional[str]) -> Optional[str]:
    """Best-effort country attribution. ccTLD trumps language; ambiguous
    languages (en, es, fr, ar, zh, pt, de) get no fallback — better to
    have no breakdown than to misattribute traffic."""
    if domain:
        tld = domain.rsplit(".", 1)[-1].lower()
        cc = _CCTLD_TO_COUNTRY.get(tld)
        if cc:
            return cc
    if language:
        return _LANG_TO_COUNTRY_SINGLE.get(language.lower())
    return None


# Public helpers --------------------------------------------------------------


def domain_from_url(url: Optional[str]) -> Optional[str]:
    """Extract bare domain (no www., lowercased) from a URL. None on garbage."""
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
        host = host.lower().strip()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def _bucket_for(rank: Optional[int]) -> str:
    if rank is None:
        return "unranked"
    if rank <= 100:
        return "top_100"
    if rank <= 1_000:
        return "top_1k"
    if rank <= 10_000:
        return "top_10k"
    if rank <= 100_000:
        return "top_100k"
    if rank <= 1_000_000:
        return "top_1m"
    return "beyond_1m"


def _candidate_domains(domain: str) -> list[str]:
    """Yield (exact, parent, grandparent) until we hit registrable root.

    `news.yahoo.co.jp` → ["news.yahoo.co.jp", "yahoo.co.jp", "co.jp"] but
    `co.jp` is filtered out as a public-suffix-only entry. We stop at the
    last 2-3 labels heuristically (covers .com, .co.uk, .com.au, etc.).
    """
    if "." not in domain:
        return [domain]
    parts = domain.split(".")
    out = [domain]
    # Strip one label at a time from the left, but stop when only 2 labels
    # remain (root) or only 3 if it looks like a 2-label TLD (.co.uk, .com.au)
    while len(parts) > 2:
        parts = parts[1:]
        out.append(".".join(parts))
        # Stop after 1 fallback if the remaining TLD is a 2-label public suffix
        if len(parts) == 3 and parts[1] in {"co", "com", "or", "net", "org", "gov", "ac", "edu"}:
            break
    return out


@lru_cache(maxsize=4096)
def get_audience_for_domain(
    domain: Optional[str],
    country_hint: Optional[str] = None,
) -> Optional[dict]:
    """Look up audience for a domain via the embedded calibration.

    Tries the exact domain first, then falls back to parent domains
    (e.g. rss.cnn.com → cnn.com). Returns None if no candidate hits the
    anchor tables.
    """
    if not domain:
        return None
    aud = _get_audience()

    # Stub geography from the country hint. Echolot already knows the
    # source's primary country (from sources.language or sources.notes), so
    # we don't have to re-run WHOIS/DNS detection.
    top: list[dict] = []
    if country_hint:
        top.append(
            {"country_code": country_hint, "score": 1.0, "methods": ["echolot_corpus"]}
        )
    geo = GeographyInfo(
        primary_country=country_hint,
        top_countries=top,
        country_ranks=[],
        signals=[],
        confidence=ConfidenceLevel.MEDIUM if country_hint else ConfidenceLevel.LOW,
    )
    info = None
    matched = domain
    matched_rank = RankInfo(
        consensus_rank=None, rank_bucket="unranked",
        sources=[], confidence=ConfidenceLevel.UNKNOWN,
    )
    for candidate in _candidate_domains(domain):
        # 1st priority: anchor hit via known SW rank/visits (HIGH confidence)
        candidate_info = aud.estimate(matched_rank, geo, domain=candidate)
        if candidate_info.monthly_uniques_global is not None:
            info = candidate_info
            matched = candidate
            break
        # 2nd priority: DNS ranking consensus → power-law (MEDIUM/LOW confidence)
        dns = _consensus_from_db(candidate)
        if dns:
            consensus, rank_sources = dns
            bucket = _bucket_for(consensus)
            confidence = (
                ConfidenceLevel.HIGH if len(rank_sources) >= 3
                else ConfidenceLevel.MEDIUM if len(rank_sources) == 2
                else ConfidenceLevel.LOW
            )
            rank_info = RankInfo(
                consensus_rank=consensus, rank_bucket=bucket,
                sources=rank_sources, confidence=confidence,
            )
            candidate_info = aud.estimate(rank_info, geo, domain=candidate)
            if candidate_info.monthly_uniques_global is not None:
                info = candidate_info
                matched = candidate
                matched_rank = rank_info
                break
    if info is None or info.monthly_uniques_global is None:
        return None
    return {
        "domain": matched,
        "visits": info.monthly_uniques_global,
        "visits_band": list(info.monthly_uniques_band) if info.monthly_uniques_band else None,
        "confidence": info.confidence.value,
        "method": info.method,
        "country": country_hint,
        "by_country": [
            (c.country_code, c.monthly_uniques) for c in info.by_country
        ],
        "rank_bucket": _bucket_for_visits(info.monthly_uniques_global),
    }


def _bucket_for_visits(visits: int) -> str:
    """Reverse map visits → tier bucket via the new power-law.

    Used to feed StoryReachAggregator's visibility_buckets — which expects
    rank_bucket strings — without round-tripping through a fake rank.
    """
    if visits >= 250_000_000:
        return "top_100"
    if visits >= 50_000_000:
        return "top_1k"
    if visits >= 5_000_000:
        return "top_10k"
    if visits >= 500_000:
        return "top_100k"
    return "top_1m"


@lru_cache(maxsize=2048)
def get_audience_for_source(db_path: str, source_id: str) -> Optional[dict]:
    """Resolve source_id → url → domain → audience via echolot.db."""
    if not source_id:
        return None
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT url, language FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        logger.debug("get_audience_for_source db lookup failed: %s", e)
        return None
    if not row:
        return None
    url, language = row
    domain = domain_from_url(url)
    if not domain:
        return None
    country = _country_for_source(domain, language)
    aud = get_audience_for_domain(domain, country_hint=country)
    if aud:
        aud = dict(aud)  # shallow copy — lru_cache returns a shared dict
        aud["source_id"] = source_id
    return aud


def compute_story_reach(
    db_path: str,
    source_ids: list[str],
    story_visibility: Optional[float] = None,
) -> Optional[dict]:
    """Overlap-discounted story reach across multiple source-sites.

    Per-country algorithm: `p_total = 1 - Π_i (1 - p_i)` where
    `p_i = (daily_uniques_i / internet_users) * story_visibility`.

    Returns dict with total_readers, by_country breakdown, and notes.
    """
    if not source_ids:
        return None

    non_reach_product: dict[str, float] = {}
    source_counts: dict[str, int] = {}
    contributed: list[str] = []
    skipped: list[str] = []

    # Raw fallback: sum of daily-uniques across all sources, discounted by
    # visibility. Used when overlap-discounted model can't run (typical case:
    # all .com international sources with no country attribution).
    raw_daily_total = 0
    raw_sources = 0

    for sid in source_ids:
        aud = get_audience_for_source(db_path, sid)
        if not aud:
            skipped.append(sid)
            continue

        bucket = aud.get("rank_bucket") or "top_10k"
        visibility = (
            story_visibility
            if story_visibility is not None
            else STORY_VISIBILITY_BUCKETS.get(bucket, STORY_VISIBILITY_DEFAULT)
        )

        # Raw fallback contribution — uses global visits even without country
        global_visits = aud.get("visits", 0)
        if global_visits:
            raw_daily_total += int(global_visits * DAILY_TO_MONTHLY_RATIO * visibility)
            raw_sources += 1

        if not aud.get("by_country"):
            # No country attribution — counted in raw fallback only
            continue

        contributed.append(sid)
        for cc, monthly in aud["by_country"]:
            country = COUNTRY_DATA.get(cc)
            if not country:
                continue
            population, penetration, _ = country
            internet_users = int(population * penetration)
            if internet_users <= 0:
                continue
            daily = monthly * DAILY_TO_MONTHLY_RATIO
            p_i = min(1.0, (daily * visibility) / internet_users)
            cur = non_reach_product.get(cc, 1.0)
            non_reach_product[cc] = cur * (1.0 - p_i)
            source_counts[cc] = source_counts.get(cc, 0) + 1

    by_country: list[dict] = []
    total_with_overlap = 0
    for cc, q in non_reach_product.items():
        country = COUNTRY_DATA[cc]
        population, penetration, _ = country
        internet_users = int(population * penetration)
        p_total = 1.0 - q
        readers = int(p_total * internet_users)
        if readers <= 0:
            continue
        by_country.append({
            "country_code": cc,
            "estimated_readers": readers,
            "pct_of_internet_users": round((readers / internet_users) * 100, 2) if internet_users else 0.0,
            "contributing_sources": source_counts[cc],
        })
        total_with_overlap += readers

    by_country.sort(key=lambda c: -c["estimated_readers"])

    # Prefer overlap-discounted reach when we have country attribution
    # for >=50% of contributing sources. Else fall back to raw-daily * 0.7
    # heuristic factor (the typical overlap reduction across same-language
    # outlets is 20-40%).
    if by_country and len(contributed) >= max(1, raw_sources // 2):
        total = total_with_overlap
        method = "overlap_adjusted_country_reach"
    elif raw_daily_total > 0:
        total = int(raw_daily_total * 0.7)
        method = "raw_discounted_global"
    else:
        return None

    return {
        "total_readers": total,
        "by_country": by_country,
        "contributing_sources": len(contributed) or raw_sources,
        "skipped_sources": len(skipped),
        "method": method,
    }


def format_visits_compact(visits: int) -> str:
    """Human-friendly visits formatting. 72_210_000 → "72M"."""
    if visits >= 1_000_000_000:
        return f"{visits / 1_000_000_000:.1f}B"
    if visits >= 1_000_000:
        return f"{visits / 1_000_000:.0f}M"
    if visits >= 1_000:
        return f"{visits / 1_000:.0f}K"
    return str(visits)


def format_readers_compact(readers: int) -> str:
    """Same as format_visits_compact but tuned for reach numbers."""
    return format_visits_compact(readers)
