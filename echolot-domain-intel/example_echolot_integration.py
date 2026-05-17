"""
Example: how to integrate domain_intel into the Echolot codebase.

Two integration patterns:
  A. Direct Python import (Echolot Python process embeds the analyzer)
  B. HTTP microservice (Echolot calls the FastAPI server)

The patterns can coexist — use HTTP for cross-language clients (Rust scrapers,
Bridge MCPs) and direct import for the Python-heavy core.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

# =============================================================================
# Pattern A: Direct Python import
# =============================================================================

from domain_intel import DomainAnalyzer


# -----------------------------------------------------------------------------
# A.1. Hook Echolot's own sphere database for geography signals
# -----------------------------------------------------------------------------
def echolot_geo_lookup(domain: str) -> str | None:
    """
    Plug your existing Echolot sphere/source DB here.
    Returns ISO 3166-1 alpha-2 country code if known, else None.

    Pseudo-code — adapt to your actual DB layer:
    """
    # Example (replace with your real query):
    # row = db.execute(
    #     "SELECT country_code FROM echolot_sources WHERE domain = %s",
    #     (domain,)
    # ).fetchone()
    # return row["country_code"] if row else None
    mock_db = {
        "telex.hu": "HU",
        "iz.ru": "RU",
        "haaretz.com": "IL",
        "tasnimnews.com": "IR",
    }
    return mock_db.get(domain)


def echolot_category_lookup(domain: str) -> dict | None:
    """
    Returns Echolot's category + sphere data if the domain is in your corpus.
    """
    mock_db = {
        "telex.hu": {
            "sphere": "hungarian_independent_media",
            "category": "news_media",
            "sub_categories": ["politics", "investigation"],
        },
        "iz.ru": {
            "sphere": "russian_pro_kremlin",
            "category": "news_media",
            "sub_categories": ["politics", "state_media"],
        },
        "haaretz.com": {
            "sphere": "israeli_liberal",
            "category": "news_media",
            "sub_categories": ["politics", "investigation"],
        },
    }
    return mock_db.get(domain)


# -----------------------------------------------------------------------------
# A.2. Use the analyzer inside Echolot
# -----------------------------------------------------------------------------
async def echolot_analyze_news_portal(domain: str):
    """How Echolot would use the analyzer."""

    analyzer = DomainAnalyzer.from_env(
        echolot_corpus_lookup_geo=echolot_geo_lookup,
        echolot_corpus_lookup_category=echolot_category_lookup,
    )
    await analyzer.initialize()

    report = await analyzer.analyze(domain)

    # Now combine with Echolot's narrative analytics:
    print(f"\n=== {domain} ===")
    print(f"Rank: #{report.rank.consensus_rank:,}" if report.rank.consensus_rank else "Unranked")
    print(f"Bucket: {report.rank.rank_bucket}")
    print(f"Primary country: {report.geography.primary_country}")
    print(f"Sphere: {report.category.echolot_sphere}")
    print(f"Trend: {report.trend.direction}")

    # Example: build the Echolot intelligence narrative
    if report.category.echolot_sphere and report.rank.consensus_rank:
        narrative = (
            f"`{domain}` (rank #{report.rank.consensus_rank:,}, "
            f"{report.geography.primary_country}-focused) "
            f"belongs to the {report.category.echolot_sphere} sphere. "
            f"Trend: {report.trend.direction}."
        )
        print(f"\nIntelligence narrative:\n{narrative}")

    return report


# =============================================================================
# Pattern B: HTTP microservice
# =============================================================================

import httpx


async def echolot_via_http(domain: str, api_url: str = "http://domain-intel:8080"):
    """Call the analyzer from any service (Rust, Go, another Python app)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{api_url}/domain/{domain}")
        resp.raise_for_status()
        return resp.json()


# =============================================================================
# Bulk analysis: process Echolot's whole source list
# =============================================================================

async def enrich_echolot_sources():
    """
    Pattern: enrich every known news portal in your Echolot DB
    with rank + geography + trend data.
    """
    sources = [
        "telex.hu", "index.hu", "444.hu", "hvg.hu",
        "iz.ru", "tass.com", "ria.ru",
        "haaretz.com", "jpost.com",
        "tasnimnews.com", "presstv.ir",
        "nytimes.com", "wsj.com",
    ]

    analyzer = DomainAnalyzer.from_env(
        echolot_corpus_lookup_geo=echolot_geo_lookup,
        echolot_corpus_lookup_category=echolot_category_lookup,
    )
    await analyzer.initialize()

    results = await asyncio.gather(
        *[analyzer.analyze(d, fetch_page=False) for d in sources],
        return_exceptions=True,
    )

    for domain, report in zip(sources, results):
        if isinstance(report, Exception):
            print(f"❌ {domain}: {report}")
            continue
        print(
            f"✅ {domain:25s} "
            f"rank={report.rank.consensus_rank or 'n/a':<10} "
            f"country={report.geography.primary_country or '?':3s} "
            f"sphere={report.category.echolot_sphere or 'unknown'}"
        )


# =============================================================================
# Main demo
# =============================================================================
if __name__ == "__main__":
    asyncio.run(echolot_analyze_news_portal("telex.hu"))
    print("\n" + "=" * 60)
    asyncio.run(enrich_echolot_sources())
