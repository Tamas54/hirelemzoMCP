"""
Ranking sources — all free + commercial-friendly.

Architecture: each source has a `load()` method that downloads the daily list
into a local dict {domain -> rank}, and a `lookup(domain)` method for O(1)
lookups. The DailyRankingDB orchestrates all sources.

Licenses:
  - Tranco: research-open, free for commercial use
            (the code is MIT; the list itself is freely distributable)
  - Cisco Umbrella Top 1M: publicly downloadable CSV, free commercial use
  - Majestic Million: CC BY 3.0 (commercial OK with attribution)
  - OpenPageRank: free tier 1000 req/day, commercial OK
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

from domain_intel.models import CountryRank, RankSource

# ccTLD -> country mapping (subset, mirrors geography.py CCTLD_MAP)
CCTLD_TO_COUNTRY: dict[str, str] = {
    "hu": "HU", "ru": "RU", "ua": "UA", "by": "BY", "pl": "PL", "cz": "CZ",
    "sk": "SK", "ro": "RO", "bg": "BG", "rs": "RS", "hr": "HR", "si": "SI",
    "de": "DE", "at": "AT", "ch": "CH", "fr": "FR", "be": "BE", "nl": "NL",
    "uk": "GB", "ie": "IE", "es": "ES", "pt": "PT", "it": "IT", "gr": "GR",
    "se": "SE", "no": "NO", "dk": "DK", "fi": "FI", "il": "IL", "ir": "IR",
    "tr": "TR", "sa": "SA", "ae": "AE", "eg": "EG", "cn": "CN", "jp": "JP",
    "kr": "KR", "in": "IN", "us": "US", "ca": "CA", "br": "BR", "ar": "AR",
    "au": "AU", "nz": "NZ", "za": "ZA", "mx": "MX",
}

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Base class
# -----------------------------------------------------------------------------
class RankingSource:
    """Base class for a ranking source."""

    name: str = "base"
    license: str = "unknown"

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir / self.name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ranks: dict[str, int] = {}
        self._loaded_date: Optional[date] = None

    def _csv_path(self, d: date) -> Path:
        return self.data_dir / f"{d.isoformat()}.csv"

    async def download_daily(self, target_date: Optional[date] = None) -> Path:
        """Download today's list (or for a given date). Must be implemented per source."""
        raise NotImplementedError

    def load_from_disk(self, target_date: Optional[date] = None) -> bool:
        """Load the most recent available list from disk into memory."""
        target = target_date or date.today()
        # Find the most recent file at or before target_date (look back up to 7 days)
        for delta in range(8):
            candidate = self._csv_path(target - timedelta(days=delta))
            if candidate.exists():
                self._ranks = self._parse_csv(candidate)
                self._loaded_date = target - timedelta(days=delta)
                logger.info(f"{self.name}: loaded {len(self._ranks):,} domains from {candidate.name}")
                return True
        logger.warning(f"{self.name}: no list found on disk, falling back")
        return False

    def _parse_csv(self, path: Path) -> dict[str, int]:
        """Parse a 'rank,domain' CSV into {domain: rank}. Override if format differs."""
        ranks: dict[str, int] = {}
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2:
                    continue
                try:
                    rank = int(row[0])
                    domain = row[1].strip().lower().lstrip("www.")
                    if domain:
                        ranks[domain] = rank
                except (ValueError, IndexError):
                    continue
        return ranks

    def lookup(self, domain: str) -> RankSource:
        """O(1) lookup of a domain's rank."""
        normalized = domain.lower().strip().lstrip("www.")
        rank = self._ranks.get(normalized)

        # Try without "www." and with "www." just in case
        if rank is None and normalized.startswith("www."):
            rank = self._ranks.get(normalized[4:])
        if rank is None:
            # Try with parent domain (e.g. "blog.example.com" → "example.com")
            parts = normalized.split(".")
            if len(parts) > 2:
                rank = self._ranks.get(".".join(parts[-2:]))

        return RankSource(
            source=self.name,
            rank=rank,
            license=self.license,
            fetched_at=datetime.utcnow(),
        )

    @property
    def is_loaded(self) -> bool:
        return len(self._ranks) > 0


# -----------------------------------------------------------------------------
# Tranco (research-grade, daily updated, manipulation-resistant)
# -----------------------------------------------------------------------------
class TrancoSource(RankingSource):
    name = "tranco"
    license = "Research-open (KU Leuven); free for commercial use"

    DAILY_URL = "https://tranco-list.eu/top-1m.csv.zip"

    async def download_daily(self, target_date: Optional[date] = None) -> Path:
        target = target_date or date.today()
        out_path = self._csv_path(target)

        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            logger.info(f"Tranco: downloading {self.DAILY_URL}")
            resp = await client.get(self.DAILY_URL)
            resp.raise_for_status()

            # ZIP contains 'top-1m.csv' with 'rank,domain' format
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                csv_name = next(n for n in z.namelist() if n.endswith(".csv"))
                with z.open(csv_name) as src, out_path.open("wb") as dst:
                    dst.write(src.read())

        logger.info(f"Tranco: saved {out_path.stat().st_size:,} bytes to {out_path}")
        return out_path


# -----------------------------------------------------------------------------
# Cisco Umbrella Top 1M (DNS-based, daily)
# -----------------------------------------------------------------------------
class UmbrellaSource(RankingSource):
    name = "umbrella"
    license = "Public dataset (Cisco), free commercial use"

    DAILY_URL = "https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip"

    async def download_daily(self, target_date: Optional[date] = None) -> Path:
        target = target_date or date.today()
        out_path = self._csv_path(target)

        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            logger.info(f"Umbrella: downloading {self.DAILY_URL}")
            resp = await client.get(self.DAILY_URL)
            resp.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                csv_name = next(n for n in z.namelist() if n.endswith(".csv"))
                with z.open(csv_name) as src, out_path.open("wb") as dst:
                    dst.write(src.read())

        logger.info(f"Umbrella: saved to {out_path}")
        return out_path


# -----------------------------------------------------------------------------
# Majestic Million (backlink-based, CC BY 3.0 — REQUIRES ATTRIBUTION!)
# -----------------------------------------------------------------------------
class MajesticSource(RankingSource):
    name = "majestic"
    license = "CC BY 3.0 - commercial OK with attribution to Majestic"

    DAILY_URL = "https://downloads.majestic.com/majestic_million.csv"

    async def download_daily(self, target_date: Optional[date] = None) -> Path:
        target = target_date or date.today()
        out_path = self._csv_path(target)

        async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
            logger.info(f"Majestic: downloading {self.DAILY_URL}")
            async with client.stream("GET", self.DAILY_URL) as resp:
                resp.raise_for_status()
                with out_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

        logger.info(f"Majestic: saved to {out_path}")
        return out_path

    def _parse_csv(self, path: Path) -> dict[str, int]:
        """
        Majestic format: GlobalRank,TldRank,Domain,TLD,RefSubNets,RefIPs,...
        with a header row.
        """
        ranks: dict[str, int] = {}
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rank = int(row.get("GlobalRank", 0))
                    domain = row.get("Domain", "").strip().lower().lstrip("www.")
                    if rank > 0 and domain:
                        ranks[domain] = rank
                except (ValueError, KeyError):
                    continue
        return ranks


# -----------------------------------------------------------------------------
# OpenPageRank API client (live lookup, no bulk download)
# -----------------------------------------------------------------------------
class OpenPageRankSource:
    """
    On-demand API lookup. Free tier: 1000 req/day.
    Register at https://www.domcop.com/openpagerank/
    """

    name = "openpagerank"
    license = "Free tier, commercial OK (DomCop ToS)"

    API_URL = "https://openpagerank.com/api/v1.0/getPageRank"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def lookup(self, domain: str) -> RankSource:
        """OpenPageRank returns a 0-10 score, not a rank. We map it heuristically."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    self.API_URL,
                    params={"domains[]": domain},
                    headers={"API-OPR": self.api_key},
                )
                resp.raise_for_status()
                data = resp.json()
                # response: {response: [{domain, page_rank_integer, rank, ...}]}
                if data.get("response"):
                    entry = data["response"][0]
                    rank = entry.get("rank")
                    if rank and rank != "None":
                        rank = int(rank)
                    else:
                        rank = None
                    return RankSource(
                        source=self.name, rank=rank, license=self.license,
                        fetched_at=datetime.utcnow(),
                    )
        except Exception as e:
            logger.warning(f"OpenPageRank lookup failed for {domain}: {e}")

        return RankSource(
            source=self.name, rank=None, license=self.license,
            fetched_at=datetime.utcnow(),
        )


# -----------------------------------------------------------------------------
# Historical Tranco (for trend analysis)
# -----------------------------------------------------------------------------
class TrancoHistorical:
    """
    Fetches Tranco list for a specific historical date.
    Used for trend / 30d / 90d change analysis.

    Tranco provides permanent URLs for past lists:
      https://tranco-list.eu/daily-list?date=YYYY-MM-DD
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir / "tranco_historical"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._loaded: dict[str, dict[str, int]] = {}  # {date_str: {domain: rank}}

    async def get_rank_at_date(self, domain: str, target_date: date) -> Optional[int]:
        date_str = target_date.isoformat()
        if date_str not in self._loaded:
            await self._load_date(target_date)
        ranks = self._loaded.get(date_str, {})
        normalized = domain.lower().strip().lstrip("www.")
        return ranks.get(normalized)

    async def _load_date(self, target_date: date) -> None:
        date_str = target_date.isoformat()
        csv_path = self.data_dir / f"{date_str}.csv"

        if not csv_path.exists():
            # Tranco daily lists are accessible via permanent URLs
            url = f"https://tranco-list.eu/download/daily/{date_str}"
            try:
                async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        try:
                            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                                csv_name = next(n for n in z.namelist() if n.endswith(".csv"))
                                with z.open(csv_name) as src, csv_path.open("wb") as dst:
                                    dst.write(src.read())
                        except zipfile.BadZipFile:
                            # might be raw CSV
                            csv_path.write_bytes(resp.content)
                    else:
                        logger.warning(f"Tranco historical {date_str}: HTTP {resp.status_code}")
                        self._loaded[date_str] = {}
                        return
            except Exception as e:
                logger.warning(f"Tranco historical {date_str} failed: {e}")
                self._loaded[date_str] = {}
                return

        # Parse
        ranks: dict[str, int] = {}
        try:
            with csv_path.open("r", encoding="utf-8", errors="ignore") as f:
                for row in csv.reader(f):
                    if len(row) >= 2:
                        try:
                            ranks[row[1].strip().lower().lstrip("www.")] = int(row[0])
                        except ValueError:
                            continue
        except Exception as e:
            logger.warning(f"parse failed for {csv_path}: {e}")

        self._loaded[date_str] = ranks


# -----------------------------------------------------------------------------
# Per-country rank index
# -----------------------------------------------------------------------------
class CountryRankIndex:
    """
    Per-country rankings derived from global lists + optional Cloudflare Radar
    overrides.

    Two-tier strategy:

      1. **ccTLD-derived ranking** (always available after global lists load):
         Filter the Tranco/Umbrella/Majestic union by ccTLD, sort by global
         rank, re-rank 1..N within each country. Works for .hu, .ru, .de etc.
         Misses .com / .org sites even when audience is country-specific.

      2. **Cloudflare Radar** (if data/cf_radar/{CC}.csv is present):
         Authoritative per-country rank from DNS-resolver traffic share.
         CC BY-NC -- internal calibration only. Overrides ccTLD ranking.
    """

    def __init__(self, data_dir: Path):
        self.cf_radar_dir = data_dir / "cf_radar"
        # cc -> {domain: country_rank}
        self._cf_radar: dict[str, dict[str, int]] = {}
        self._cf_radar_sizes: dict[str, int] = {}
        # cc -> {domain: country_rank} from ccTLD-derived sub-indexing
        self._cctld: dict[str, dict[str, int]] = {}
        self._cctld_sizes: dict[str, int] = {}

    # ----- Index builders -----

    def build_cctld(self, sources: list[RankingSource]) -> None:
        """
        Build per-country indices by filtering loaded global lists by ccTLD.
        Call after `DailyRankingDB.load_all()`.
        """
        # Merge ranks across global sources: take the *median* rank per domain
        merged: dict[str, list[int]] = {}
        for src in sources:
            if not src.is_loaded:
                continue
            for domain, rank in src._ranks.items():
                merged.setdefault(domain, []).append(rank)

        # Convert to a single rank per domain
        consensus: dict[str, int] = {}
        for domain, ranks in merged.items():
            ranks.sort()
            consensus[domain] = ranks[len(ranks) // 2]

        # Group by ccTLD
        by_country: dict[str, list[tuple[str, int]]] = {}
        for domain, global_rank in consensus.items():
            tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
            cc = CCTLD_TO_COUNTRY.get(tld)
            if not cc:
                continue
            by_country.setdefault(cc, []).append((domain, global_rank))

        # Sort each country's list by global rank, re-rank 1..N
        for cc, entries in by_country.items():
            entries.sort(key=lambda t: t[1])
            self._cctld[cc] = {domain: i + 1 for i, (domain, _) in enumerate(entries)}
            self._cctld_sizes[cc] = len(entries)
        logger.info(
            f"CountryRankIndex: built ccTLD indices for {len(self._cctld)} countries; "
            f"largest: " + ", ".join(
                f"{cc}={self._cctld_sizes[cc]:,}"
                for cc in sorted(self._cctld_sizes, key=self._cctld_sizes.get, reverse=True)[:5]
            )
        )

    def load_cf_radar(self) -> dict[str, int]:
        """
        Load per-country lists from data/cf_radar/{CC}.csv if they exist.

        Expected CSV format: `rank,domain` (rows; no header required).
        Returns {country_code: num_domains_loaded}.
        """
        results: dict[str, int] = {}
        if not self.cf_radar_dir.exists():
            return results

        for csv_path in sorted(self.cf_radar_dir.glob("*.csv")):
            cc = csv_path.stem.upper()
            if len(cc) != 2:
                continue
            ranks: dict[str, int] = {}
            try:
                with csv_path.open("r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if not row:
                            continue
                        # Allow header rows like 'rank,domain'
                        try:
                            rank = int(row[0])
                        except (ValueError, IndexError):
                            continue
                        if len(row) < 2:
                            continue
                        d = row[1].strip().lower().lstrip("www.")
                        if d:
                            ranks[d] = rank
                self._cf_radar[cc] = ranks
                self._cf_radar_sizes[cc] = len(ranks)
                results[cc] = len(ranks)
            except Exception as e:
                logger.warning(f"CountryRankIndex: failed to load {csv_path}: {e}")
        if results:
            logger.info(
                f"CountryRankIndex: loaded Cloudflare Radar lists for "
                f"{len(results)} countries ({sum(results.values()):,} total entries)"
            )
        return results

    # ----- Lookup -----

    def lookup(self, domain: str, target_countries: Optional[list[str]] = None) -> list[CountryRank]:
        """
        Return CountryRank entries for this domain.

        If `target_countries` is given, only those countries are checked
        (cheaper). Otherwise we scan every loaded country index — fine for
        a small number of countries (<100).
        """
        normalized = domain.lower().strip().lstrip("www.")
        result: list[CountryRank] = []
        seen: set[str] = set()

        # Iterate target countries first, then any others
        candidates = list(target_countries) if target_countries else []
        candidates += [cc for cc in self._cf_radar if cc not in candidates]
        candidates += [cc for cc in self._cctld if cc not in candidates]

        for cc in candidates:
            if cc in seen:
                continue
            seen.add(cc)
            # CF Radar wins if present
            if cc in self._cf_radar:
                rank = self._cf_radar[cc].get(normalized)
                if rank:
                    size = self._cf_radar_sizes[cc]
                    percentile = round(100 * (1 - rank / size), 2) if size else None
                    result.append(CountryRank(
                        country_code=cc, rank=rank,
                        percentile=percentile, source="cf_radar",
                    ))
                    continue
            # Fallback to ccTLD-derived
            if cc in self._cctld:
                rank = self._cctld[cc].get(normalized)
                if rank:
                    size = self._cctld_sizes[cc]
                    percentile = round(100 * (1 - rank / size), 2) if size else None
                    result.append(CountryRank(
                        country_code=cc, rank=rank,
                        percentile=percentile, source="tranco_cctld",
                    ))
        return result

    @property
    def loaded_countries(self) -> list[str]:
        """Union of countries with any per-country index loaded."""
        return sorted(set(self._cf_radar) | set(self._cctld))


# -----------------------------------------------------------------------------
# Orchestrator
# -----------------------------------------------------------------------------
class DailyRankingDB:
    """
    Holds all daily ranking sources in memory for fast O(1) lookups.

    Usage:
        db = DailyRankingDB(data_dir=Path("./data"))
        await db.refresh_all()  # download today's lists if missing
        db.load_all()           # load latest available lists from disk
        sources = db.lookup("telex.hu")
    """

    def __init__(
        self,
        data_dir: Path,
        enable_tranco: bool = True,
        enable_umbrella: bool = True,
        enable_majestic: bool = True,
        openpagerank_api_key: Optional[str] = None,
    ):
        self.data_dir = data_dir
        self.sources: list[RankingSource] = []

        if enable_tranco:
            self.sources.append(TrancoSource(data_dir))
        if enable_umbrella:
            self.sources.append(UmbrellaSource(data_dir))
        if enable_majestic:
            self.sources.append(MajesticSource(data_dir))

        self.opr: Optional[OpenPageRankSource] = (
            OpenPageRankSource(openpagerank_api_key) if openpagerank_api_key else None
        )

        self.historical = TrancoHistorical(data_dir)
        self.country_index = CountryRankIndex(data_dir)

    async def refresh_all(self) -> dict[str, bool]:
        """Download today's lists for all sources."""
        results = {}
        for src in self.sources:
            try:
                await src.download_daily()
                results[src.name] = True
            except Exception as e:
                logger.error(f"refresh failed for {src.name}: {e}")
                results[src.name] = False
        return results

    def load_all(self) -> dict[str, bool]:
        """Load each source's most recent list from disk + build country indices."""
        results = {}
        for src in self.sources:
            results[src.name] = src.load_from_disk()
        # Build country indices off the loaded data
        self.country_index.build_cctld(self.sources)
        self.country_index.load_cf_radar()
        return results

    async def lookup(self, domain: str) -> list[RankSource]:
        """Look up a domain across all sources."""
        results: list[RankSource] = []
        for src in self.sources:
            if src.is_loaded:
                results.append(src.lookup(domain))

        # OpenPageRank is live API, not bulk
        if self.opr:
            results.append(await self.opr.lookup(domain))

        return results
