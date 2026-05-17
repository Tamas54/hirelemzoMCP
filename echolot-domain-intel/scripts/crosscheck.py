"""
Cross-check the audience estimator against external ground truth
(e.g. Similarweb numbers the user pulls manually).

Edit OBSERVATIONS below with your real-world data and run:

    python scripts/crosscheck.py

Output: side-by-side table of model estimate vs ground truth + ratio.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain_intel.audience import AudienceEstimator
from domain_intel.models import (
    ConfidenceLevel,
    CountryRank,
    GeographyInfo,
    RankInfo,
)


# -----------------------------------------------------------------------------
# Ground-truth observations. Edit me!
# -----------------------------------------------------------------------------
# Each row:
#   domain, global_rank (Similarweb / Tranco), primary_country, country_rank (or None),
#   sw_monthly_visits (total visits, not uniques),
#   sw_monthly_uniques (unique visitors, if available; None if not),
#   primary_country_share (0-1, fraction of traffic from primary_country),
#   notes
OBSERVATIONS: list[dict] = [
    # Example rows — replace with real Similarweb data
    {
        "domain": "telex.hu",
        "global_rank": 18000,           # Similarweb rank
        "primary_country": "HU",
        "country_rank": None,
        "sw_monthly_visits": None,      # fill in
        "sw_monthly_uniques": None,     # fill in
        "primary_country_share": 0.92,
        "notes": "",
    },
    # Add more...
]


# -----------------------------------------------------------------------------
def main():
    est = AudienceEstimator()

    print(f"{'Domain':<25} {'Country':<8} {'Model est':>12} {'SW uniques':>12} {'SW visits':>12} {'Ratio (est/SW)':>16}")
    print("-" * 95)

    for obs in OBSERVATIONS:
        rank_info = RankInfo(
            consensus_rank=obs["global_rank"],
            rank_bucket="top_100k",  # not important for the math
            confidence=ConfidenceLevel.HIGH,
        )
        cc = obs["primary_country"]
        share = obs["primary_country_share"]
        country_ranks = []
        if obs["country_rank"]:
            country_ranks.append(CountryRank(
                country_code=cc, rank=obs["country_rank"],
                percentile=None, source="manual",
            ))
        geo_info = GeographyInfo(
            top_countries=[
                {"country_code": cc, "score": share, "methods": ["manual"]},
            ] + ([{"country_code": "??", "score": 1 - share, "methods": ["manual"]}] if share < 0.99 else []),
            primary_country=cc,
            country_ranks=country_ranks,
            confidence=ConfidenceLevel.HIGH,
        )

        audience = est.estimate(rank_info, geo_info)
        country_est = next(
            (ca.monthly_uniques for ca in audience.by_country if ca.country_code == cc),
            None,
        )
        sw_uniques = obs["sw_monthly_uniques"]
        sw_visits = obs["sw_monthly_visits"]

        # Compare model estimate (uniques) against SW uniques. If only visits
        # available, divide by 8 as a rough visits/uniques ratio for news.
        sw_ref = sw_uniques if sw_uniques else (sw_visits // 8 if sw_visits else None)
        ratio_str = f"{country_est / sw_ref:.2f}×" if (country_est and sw_ref) else "n/a"

        print(
            f"{obs['domain']:<25} {cc:<8} "
            f"{country_est:>12,}" if country_est else f"{obs['domain']:<25} {cc:<8} {'n/a':>12}",
            end="",
        )
        print(
            f" {sw_uniques or 'n/a':>12} {sw_visits or 'n/a':>12} {ratio_str:>16}"
        )


if __name__ == "__main__":
    main()
