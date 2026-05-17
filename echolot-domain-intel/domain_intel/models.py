"""Pydantic models for domain intelligence reports."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ConfidenceLevel(str, Enum):
    """How much can we trust this signal?"""

    HIGH = "high"        # Multiple independent sources agree
    MEDIUM = "medium"    # Single source or partial agreement
    LOW = "low"          # Heuristic / inferred
    UNKNOWN = "unknown"  # No data


class RankSource(BaseModel):
    """Rank from a single source."""

    source: str = Field(..., description="Source name (tranco, majestic, umbrella, ...)")
    rank: Optional[int] = Field(None, description="Global rank (1=top); None if not ranked")
    license: str = Field(..., description="Data license")
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class RankInfo(BaseModel):
    """Aggregated ranking information from multiple sources."""

    consensus_rank: Optional[int] = Field(
        None, description="Median rank across available sources (lower=more popular)"
    )
    rank_bucket: Optional[str] = Field(
        None,
        description="Bucket label: 'top_100', 'top_1k', 'top_10k', 'top_100k', 'top_1m', 'unranked'",
    )
    sources: list[RankSource] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class CountrySignal(BaseModel):
    """A single geographic signal."""

    method: str = Field(..., description="whois | dns_ip_geo | html_lang | tld | content | echolot_corpus")
    country_code: str = Field(..., description="ISO 3166-1 alpha-2")
    weight: float = Field(1.0, description="Signal strength 0-1")
    detail: Optional[str] = None


class CountryRank(BaseModel):
    """Rank within a single country."""

    country_code: str = Field(..., description="ISO 3166-1 alpha-2")
    rank: int = Field(..., description="Position within country's domains (1=top)")
    percentile: Optional[float] = Field(
        None, description="0-100 percentile within country (100 = top of the country)"
    )
    source: str = Field(
        "tranco_cctld",
        description="cf_radar | tranco_cctld | umbrella_cctld | majestic_cctld",
    )


class GeographyInfo(BaseModel):
    """Aggregated geographic audience signals."""

    top_countries: list[dict] = Field(
        default_factory=list,
        description="List of {country_code, score, methods} sorted by score desc",
    )
    primary_country: Optional[str] = Field(None, description="ISO code of top country")
    country_ranks: list[CountryRank] = Field(
        default_factory=list,
        description="Per-country ranks (only for countries where we have a per-country index)",
    )
    signals: list[CountrySignal] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class CategoryInfo(BaseModel):
    """Domain category / classification."""

    primary_category: Optional[str] = Field(
        None,
        description="e.g. 'news_media', 'tech', 'finance', 'government', ...",
    )
    sub_categories: list[str] = Field(default_factory=list)
    echolot_sphere: Optional[str] = Field(
        None,
        description="If domain is in Echolot's corpus, the sphere it belongs to",
    )
    classification_method: str = Field(
        "unknown", description="echolot_corpus | ai_classifier | keyword_fallback | unknown"
    )
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class CountryAudience(BaseModel):
    """Estimated audience inside a single country."""

    country_code: str = Field(..., description="ISO 3166-1 alpha-2")
    monthly_uniques: int = Field(..., description="Estimated monthly unique visitors in this country")
    pct_of_internet_users: float = Field(
        ..., description="Estimated % of country's internet users reached monthly (0-100)"
    )


class AudienceInfo(BaseModel):
    """
    Estimated audience size for a domain.

    All values are rough order-of-magnitude estimates derived from
    ranking-list positions + calibration anchors. Treat the upper/lower
    band as the true uncertainty range; the point estimate is just the
    geometric mean of the band.
    """

    monthly_uniques_global: Optional[int] = Field(
        None, description="Estimated global monthly unique visitors"
    )
    monthly_uniques_band: Optional[tuple[int, int]] = Field(
        None, description="(lower, upper) ~80% interval"
    )
    by_country: list[CountryAudience] = Field(
        default_factory=list,
        description="Country-level breakdown — only populated for countries with audience signal",
    )
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    method: str = Field(
        "global_powerlaw",
        description="global_powerlaw | country_powerlaw | corpus_anchor | unknown",
    )


class TrendInfo(BaseModel):
    """Rank evolution over time."""

    rank_30d_ago: Optional[int] = None
    rank_90d_ago: Optional[int] = None
    change_30d: Optional[int] = Field(
        None, description="Positive = rank improved (lower number); negative = rank declined"
    )
    change_90d: Optional[int] = None
    direction: str = Field("unknown", description="rising | falling | stable | unknown")


class DomainReport(BaseModel):
    """Complete domain intelligence report."""

    domain: str
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)

    rank: RankInfo
    geography: GeographyInfo
    category: CategoryInfo
    audience: AudienceInfo
    trend: TrendInfo

    # Metadata
    is_reachable: Optional[bool] = None
    server_ip: Optional[str] = None
    detected_language: Optional[str] = None
    whois_registrar: Optional[str] = None
    whois_created: Optional[datetime] = None

    # Sources / attribution (for license compliance!)
    data_sources: list[str] = Field(default_factory=list)
    licenses: dict[str, str] = Field(default_factory=dict)

    cache_hit: bool = False
