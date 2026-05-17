"""
Echolot Domain Intelligence
===========================
Free, commercial-safe domain analysis library for the Echolot platform.

Replaces commercial services like Similarweb / Cloudflare Radar (CC BY-NC)
using only permissively-licensed data sources:
  - Tranco list (research-open)
  - Cisco Umbrella Top 1M (public)
  - Majestic Million (CC BY 3.0)
  - OpenPageRank (free tier, commercial OK)
  - MaxMind GeoLite2 (CC BY-SA 4.0)
  - WHOIS / DNS (public protocols)

Usage (Python lib):
    from domain_intel import DomainAnalyzer
    analyzer = DomainAnalyzer()
    report = await analyzer.analyze("telex.hu")
    print(report.json())

Usage (HTTP):
    GET /domain/{domain}      → DomainReport
    GET /domain/{domain}/rank → RankInfo only
"""

from domain_intel.analyzer import DomainAnalyzer
from domain_intel.audience import AudienceEstimator
from domain_intel.models import (
    AudienceInfo,
    CategoryInfo,
    ConfidenceLevel,
    CountryAudience,
    CountryRank,
    DomainReport,
    GeographyInfo,
    RankInfo,
    TrendInfo,
)
from domain_intel.reach import (
    CountryReach,
    StoryReachAggregator,
    StoryReachReport,
)

__version__ = "0.2.0"
__all__ = [
    "DomainAnalyzer",
    "AudienceEstimator",
    "StoryReachAggregator",
    "DomainReport",
    "RankInfo",
    "GeographyInfo",
    "CategoryInfo",
    "AudienceInfo",
    "CountryAudience",
    "CountryRank",
    "TrendInfo",
    "ConfidenceLevel",
    "StoryReachReport",
    "CountryReach",
]
