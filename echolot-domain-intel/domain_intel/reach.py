"""
Story-level reach aggregation.

Use case
--------
You have a news story published on N domains. How many people *actually
saw it*? Naive answer: sum of monthly_uniques across all sources. That
massively overcounts because (a) most users overlap between sources in
the same country, and (b) only a fraction of a site's monthly visitors
see any given story.

Model
-----
For each country c we compute the reach probability across all sources:

    p_total(c) = 1 - Π_i (1 - p_i(c))

where:

    p_i(c) = (daily_uniques_i(c) / internet_users(c)) * story_visibility_i

Then the country's story reach is:

    reach(c) = p_total(c) * internet_users(c)

Final total = sum of reach(c) over all countries.

Conversions
-----------
  daily_uniques     ≈ monthly_uniques * DAILY_TO_MONTHLY_RATIO  (default 1/8)
  story_visibility  ≈ STORY_VISIBILITY_BUCKETS[rank_bucket]     (default 0.12)

These are calibration constants -- see calibration_data.py.
"""

from __future__ import annotations

import logging
from typing import Iterable

from pydantic import BaseModel, Field

from domain_intel.calibration_data import (
    COUNTRY_DATA,
    DAILY_TO_MONTHLY_RATIO,
    STORY_VISIBILITY_BUCKETS,
    STORY_VISIBILITY_DEFAULT,
)
from domain_intel.models import DomainReport

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Response schemas
# -----------------------------------------------------------------------------
class CountryReach(BaseModel):
    country_code: str
    estimated_readers: int = Field(..., description="Unique people in this country who likely saw the story")
    pct_of_population: float = Field(..., description="0-100, share of total population")
    pct_of_internet_users: float = Field(..., description="0-100, share of internet users")
    contributing_sources: int


class StoryReachReport(BaseModel):
    sources: list[str]
    skipped_sources: list[str] = Field(default_factory=list)
    total_estimated_readers: int
    by_country: list[CountryReach]
    method: str = "overlap_adjusted_country_reach"
    notes: list[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Aggregator
# -----------------------------------------------------------------------------
class StoryReachAggregator:
    """Stateless story-level reach aggregator."""

    def __init__(
        self,
        country_data: dict = COUNTRY_DATA,
        daily_to_monthly: float = DAILY_TO_MONTHLY_RATIO,
        visibility_buckets: dict[str, float] = STORY_VISIBILITY_BUCKETS,
        default_visibility: float = STORY_VISIBILITY_DEFAULT,
    ):
        self.country_data = country_data
        self.daily_to_monthly = daily_to_monthly
        self.visibility_buckets = visibility_buckets
        self.default_visibility = default_visibility

    def aggregate(
        self,
        reports: Iterable[DomainReport],
        story_visibility_override: float | None = None,
    ) -> StoryReachReport:
        """
        Aggregate per-source reach into a single overlap-adjusted estimate.

        Args:
            reports: DomainReports for each source publishing the story.
            story_visibility_override: if given, use this fraction for all
                sources instead of the per-bucket default.

        Returns:
            StoryReachReport with country breakdown and total reach.
        """
        reports = list(reports)
        sources: list[str] = []
        skipped: list[str] = []

        # For each country, accumulate (1 - p_i) products
        # country_code -> product so far
        non_reach_product: dict[str, float] = {}
        country_source_counts: dict[str, int] = {}

        for report in reports:
            visibility = (
                story_visibility_override
                if story_visibility_override is not None
                else self.visibility_buckets.get(
                    report.rank.rank_bucket or "unranked", self.default_visibility
                )
            )

            # Need audience info to contribute
            if not report.audience or not report.audience.by_country:
                skipped.append(report.domain)
                continue
            sources.append(report.domain)

            for ca in report.audience.by_country:
                cc = ca.country_code
                country_info = self.country_data.get(cc)
                if not country_info:
                    continue
                population, penetration, _ = country_info
                internet_users = int(population * penetration)
                if internet_users <= 0:
                    continue

                daily_uniques = ca.monthly_uniques * self.daily_to_monthly
                p_i = min(1.0, (daily_uniques * visibility) / internet_users)

                # Initialise the "no one reached" product
                product = non_reach_product.get(cc, 1.0)
                non_reach_product[cc] = product * (1.0 - p_i)
                country_source_counts[cc] = country_source_counts.get(cc, 0) + 1

        # Compute reach per country
        by_country: list[CountryReach] = []
        total = 0
        for cc, q in non_reach_product.items():
            country_info = self.country_data[cc]
            population, penetration, _ = country_info
            internet_users = int(population * penetration)
            p_total = 1.0 - q
            readers = int(p_total * internet_users)
            if readers <= 0:
                continue
            by_country.append(CountryReach(
                country_code=cc,
                estimated_readers=readers,
                pct_of_population=round((readers / population) * 100, 2) if population else 0.0,
                pct_of_internet_users=round((readers / internet_users) * 100, 2) if internet_users else 0.0,
                contributing_sources=country_source_counts[cc],
            ))
            total += readers

        # Sort by reach desc
        by_country.sort(key=lambda c: -c.estimated_readers)

        notes: list[str] = []
        if skipped:
            notes.append(
                f"{len(skipped)} source(s) skipped because they lack audience info"
            )
        if not by_country:
            notes.append(
                "No reach could be computed -- check that source reports include audience.by_country"
            )

        return StoryReachReport(
            sources=sources,
            skipped_sources=skipped,
            total_estimated_readers=total,
            by_country=by_country,
            notes=notes,
        )
