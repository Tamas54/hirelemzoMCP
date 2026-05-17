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


def __getattr__(name):
    """Lazy import for the heavy DomainAnalyzer (pulls bs4, diskcache,
    geoip2, whois, dns). The embedded Echolot adapter never needs it
    and avoiding the eager import keeps production deps minimal."""
    if name == "DomainAnalyzer":
        from domain_intel.analyzer import DomainAnalyzer as _D
        return _D
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
