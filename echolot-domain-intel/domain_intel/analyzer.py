"""
Main orchestrator: ties together ranking, geography, classification, trend.

Usage:
    from domain_intel import DomainAnalyzer
    analyzer = DomainAnalyzer.from_env()  # reads from environment vars
    await analyzer.initialize()           # loads ranking lists
    report = await analyzer.analyze("telex.hu")
    print(report.model_dump_json(indent=2))
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from domain_intel.audience import AudienceEstimator
from domain_intel.cache import DomainCache
from domain_intel.classification import CategoryClassifier
from domain_intel.geography import GeographyDetector
from domain_intel.models import (
    ConfidenceLevel,
    DomainReport,
    RankInfo,
)
from domain_intel.ranking import DailyRankingDB
from domain_intel.trend import TrendAnalyzer

logger = logging.getLogger(__name__)


class DomainAnalyzer:
    """
    The main entry point.

    Can be used as a Python library (import directly into your Echolot code)
    OR as a microservice (see api/server.py for the FastAPI wrapper).
    """

    def __init__(
        self,
        data_dir: Path = Path("./data"),
        cache_ttl_hours: int = 168,
        enable_tranco: bool = True,
        enable_umbrella: bool = True,
        enable_majestic: bool = True,
        openpagerank_api_key: Optional[str] = None,
        geoip_db_path: Optional[Path] = None,
        ai_api_base: Optional[str] = None,
        ai_api_key: Optional[str] = None,
        ai_model: str = "moonshotai/Kimi-K2-Instruct",
        echolot_corpus_lookup_geo=None,      # callable: (domain) -> Optional[country_code]
        echolot_corpus_lookup_category=None, # callable: (domain) -> Optional[{sphere, category, ...}]
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.cache = DomainCache(self.data_dir / "cache", ttl_hours=cache_ttl_hours)

        self.ranking_db = DailyRankingDB(
            data_dir=self.data_dir,
            enable_tranco=enable_tranco,
            enable_umbrella=enable_umbrella,
            enable_majestic=enable_majestic,
            openpagerank_api_key=openpagerank_api_key,
        )

        self.geography = GeographyDetector(
            geoip_db_path=geoip_db_path,
            echolot_corpus_lookup=echolot_corpus_lookup_geo,
        )

        self.classifier = CategoryClassifier(
            echolot_corpus_lookup=echolot_corpus_lookup_category,
            ai_api_base=ai_api_base,
            ai_api_key=ai_api_key,
            ai_model=ai_model,
        )

        self.trend = TrendAnalyzer(self.ranking_db.historical)
        self.audience = AudienceEstimator()
        self._initialized = False

    @classmethod
    def from_env(cls, **overrides) -> "DomainAnalyzer":
        """Build analyzer from environment variables (see .env.example)."""
        def get_bool(key: str, default: bool = False) -> bool:
            return os.getenv(key, str(default)).lower() in ("true", "1", "yes")

        kwargs = {
            "data_dir": Path(os.getenv("DATA_DIR", "./data")),
            "cache_ttl_hours": int(os.getenv("CACHE_TTL_HOURS", "168")),
            "enable_tranco": get_bool("TRANCO_ENABLED", True),
            "enable_umbrella": get_bool("UMBRELLA_ENABLED", True),
            "enable_majestic": get_bool("MAJESTIC_ENABLED", True),
            "openpagerank_api_key": os.getenv("OPENPAGERANK_API_KEY") or None,
            "geoip_db_path": Path(os.getenv("GEOIP_DB_PATH", "")) if os.getenv("GEOIP_DB_PATH") else None,
            "ai_api_base": os.getenv("AI_API_BASE") or None,
            "ai_api_key": os.getenv("AI_API_KEY") or None,
            "ai_model": os.getenv("AI_MODEL", "moonshotai/Kimi-K2-Instruct"),
        }
        kwargs.update(overrides)
        # Only include geoip if the file actually exists
        if kwargs["geoip_db_path"] and not kwargs["geoip_db_path"].exists():
            kwargs["geoip_db_path"] = None

        return cls(**kwargs)

    async def initialize(self, download_if_missing: bool = True) -> dict:
        """
        Load ranking lists from disk. If missing and `download_if_missing`,
        download today's lists from each enabled source.
        """
        load_results = self.ranking_db.load_all()
        missing = [name for name, ok in load_results.items() if not ok]

        if missing and download_if_missing:
            logger.info(f"Downloading missing lists: {missing}")
            await self.ranking_db.refresh_all()
            load_results = self.ranking_db.load_all()

        self._initialized = True
        return load_results

    async def analyze(
        self,
        domain: str,
        use_cache: bool = True,
        fetch_page: bool = True,
    ) -> DomainReport:
        """
        Full analysis pipeline.

        Args:
            domain: e.g. "telex.hu"
            use_cache: read from / write to disk cache
            fetch_page: fetch the homepage for content-based signals
                       (set False for offline-only analysis)
        """
        if not self._initialized:
            await self.initialize()

        normalized = self._normalize(domain)

        # ----- Cache check -----
        if use_cache:
            cached = self.cache.get(normalized, suffix="report")
            if cached:
                try:
                    report = DomainReport.model_validate(cached)
                    report.cache_hit = True
                    return report
                except Exception:
                    pass

        # ----- Fetch page content (used by geography + classification) -----
        page_text: Optional[str] = None
        page_title: Optional[str] = None
        is_reachable: Optional[bool] = None
        detected_language: Optional[str] = None
        server_ip: Optional[str] = None

        if fetch_page:
            page_data = await self._fetch_page(normalized)
            page_text = page_data.get("text")
            page_title = page_data.get("title")
            is_reachable = page_data.get("reachable")
            detected_language = page_data.get("language")

        # Resolve IP (for the metadata field)
        try:
            server_ip = await asyncio.to_thread(socket.gethostbyname, normalized)
        except Exception:
            pass

        # ----- Run all analyzers in parallel -----
        rank_sources_task = self.ranking_db.lookup(normalized)
        geography_task = self.geography.analyze(normalized, page_text=page_text)
        category_task = self.classifier.classify(normalized, page_text=page_text, page_title=page_title)

        rank_sources, geography_info, category_info = await asyncio.gather(
            rank_sources_task, geography_task, category_task,
        )

        # Aggregate ranks
        rank_info = self._aggregate_ranks(rank_sources)

        # Per-country ranks (cheap, in-memory)
        target_countries = []
        if geography_info.primary_country:
            target_countries.append(geography_info.primary_country)
        for tc in geography_info.top_countries[:3]:
            cc = tc["country_code"]
            if cc not in target_countries:
                target_countries.append(cc)
        geography_info.country_ranks = self.ranking_db.country_index.lookup(
            normalized, target_countries=target_countries,
        )

        # Audience estimation
        audience_info = self.audience.estimate(rank_info, geography_info, domain=normalized)

        # Trend (depends on rank info)
        trend_info = await self.trend.analyze(normalized, rank_info.consensus_rank)

        # WHOIS metadata
        whois_registrar = None
        whois_created = None
        try:
            import whois
            w = await asyncio.to_thread(whois.whois, normalized)
            whois_registrar = getattr(w, "registrar", None)
            if isinstance(whois_registrar, list):
                whois_registrar = whois_registrar[0] if whois_registrar else None
            wc = getattr(w, "creation_date", None)
            if isinstance(wc, list):
                wc = wc[0] if wc else None
            if isinstance(wc, datetime):
                whois_created = wc
        except Exception as e:
            logger.debug(f"whois metadata failed for {normalized}: {e}")

        # ----- Compose report -----
        data_sources = list({rs.source for rs in rank_sources if rs.rank is not None})
        licenses = {rs.source: rs.license for rs in rank_sources}

        if rank_info.consensus_rank:
            data_sources.append("local")

        report = DomainReport(
            domain=normalized,
            rank=rank_info,
            geography=geography_info,
            category=category_info,
            audience=audience_info,
            trend=trend_info,
            is_reachable=is_reachable,
            server_ip=server_ip,
            detected_language=detected_language,
            whois_registrar=whois_registrar,
            whois_created=whois_created,
            data_sources=sorted(set(data_sources)),
            licenses=licenses,
            cache_hit=False,
        )

        # Save to cache
        if use_cache:
            self.cache.set(normalized, report.model_dump(mode="json"), suffix="report")

        return report

    # ----- Helpers -----

    def _normalize(self, domain: str) -> str:
        d = domain.lower().strip()
        # Strip protocol if present
        d = d.replace("https://", "").replace("http://", "")
        # Strip path
        d = d.split("/")[0]
        # Strip port
        d = d.split(":")[0]
        # Strip www.
        if d.startswith("www."):
            d = d[4:]
        return d

    async def _fetch_page(self, domain: str) -> dict:
        """Fetch homepage for content analysis."""
        url = f"https://{domain}"
        result = {"reachable": False, "text": None, "title": None, "language": None}

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; EcholotDomainIntel/1.0)",
                },
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and "html" in resp.headers.get("content-type", "").lower():
                    result["reachable"] = True
                    html = resp.text[:200000]  # Cap to first 200KB
                    soup = BeautifulSoup(html, "lxml")

                    # Title
                    title_tag = soup.find("title")
                    if title_tag:
                        result["title"] = title_tag.get_text(strip=True)[:200]

                    # Body text (rough)
                    for tag in soup(["script", "style", "noscript"]):
                        tag.decompose()
                    text = soup.get_text(separator=" ", strip=True)
                    result["text"] = text[:10000]

                    # Language detection
                    try:
                        from langdetect import detect
                        result["language"] = detect(text[:3000])
                    except Exception:
                        pass
                else:
                    result["reachable"] = resp.status_code == 200
        except Exception as e:
            logger.debug(f"page fetch failed for {url}: {e}")

        return result

    # Source weights for weighted-geomean consensus.
    # Tranco/Majestic carry full weight. Umbrella reflects Cisco enterprise
    # DNS resolvers and is heavily B2B/IT-biased — it consistently ranks
    # consumer news sites 50-200K when Tranco/Majestic agree on 5-30K. Drop
    # its weight to 0.15 so it's a tie-breaker, not a vote.
    _SOURCE_WEIGHTS = {"tranco": 1.0, "majestic": 1.0, "umbrella": 0.15}

    def _aggregate_ranks(self, sources: list) -> RankInfo:
        """Compute consensus rank and bucket from individual sources.

        Uses weighted geometric mean in log-space. Geomean is preferred over
        arithmetic mean for rank data (rank distribution is log-scaled);
        weighting downscales Umbrella's enterprise-DNS bias for news domains.
        """
        weighted = [
            (s.rank, self._SOURCE_WEIGHTS.get(s.source, 1.0))
            for s in sources
            if s.rank is not None
        ]

        if not weighted:
            return RankInfo(
                consensus_rank=None,
                rank_bucket="unranked",
                sources=sources,
                confidence=ConfidenceLevel.UNKNOWN,
            )

        if len(weighted) == 1:
            consensus = weighted[0][0]
        else:
            log_sum = sum(math.log(r) * w for r, w in weighted)
            total_w = sum(w for _, w in weighted)
            consensus = int(math.exp(log_sum / total_w))

        valid_ranks = [r for r, _ in weighted]

        # Bucket
        if consensus <= 100:
            bucket = "top_100"
        elif consensus <= 1_000:
            bucket = "top_1k"
        elif consensus <= 10_000:
            bucket = "top_10k"
        elif consensus <= 100_000:
            bucket = "top_100k"
        elif consensus <= 1_000_000:
            bucket = "top_1m"
        else:
            bucket = "beyond_1m"

        # Confidence
        if len(valid_ranks) >= 3:
            # Multiple sources agree → high confidence
            confidence = ConfidenceLevel.HIGH
        elif len(valid_ranks) == 2:
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW

        return RankInfo(
            consensus_rank=consensus,
            rank_bucket=bucket,
            sources=sources,
            confidence=confidence,
        )

    async def refresh_rankings(self) -> dict:
        """Manually trigger download of today's ranking lists."""
        results = await self.ranking_db.refresh_all()
        self.ranking_db.load_all()
        return results
