"""
Audience size estimation: rank -> approximate monthly unique visitors.

Model
-----
For a given rank source we fit a power-law:

    monthly_uniques = A * rank ** (-alpha)

on a small set of (rank, uniques) anchor points. Two flavours:

  * Global power-law:    fit GLOBAL_ANCHORS once
  * Country power-law:   fit COUNTRY_ANCHORS[cc] per country
                         (only countries with local audit data)

For countries without a fitted curve we scale the global estimate by:

    monthly_country = monthly_global *
                      (country_internet_users / WORLD_INTERNET_USERS) *
                      country_share

where country_share is supplied by the geography pipeline (1.0 if the
domain is country-exclusive, lower if multilingual / international).

Confidence
----------
Two anchors per fit -> low confidence band (factor ~3 either way).
Six+ anchors per fit -> medium band (factor ~2).
We never claim "high" confidence on this; it's a heuristic.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from domain_intel.calibration_data import (
    COUNTRY_ANCHORS,
    COUNTRY_DATA,
    GLOBAL_ANCHORS,
    SIMILARWEB_KNOWN_RANKS,
    SIMILARWEB_KNOWN_VISITS,
    WORLD_INTERNET_USERS,
)
from domain_intel.models import (
    AudienceInfo,
    ConfidenceLevel,
    CountryAudience,
    CountryRank,
    GeographyInfo,
    RankInfo,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Power-law fit
# -----------------------------------------------------------------------------
def _fit_powerlaw(anchors: list[tuple[int, int]]) -> tuple[float, float]:
    """
    Least-squares fit in log-log space: log(y) = log(A) - alpha * log(x).

    Returns (A, alpha). Falls back to (anchors[0][1], 0.85) if degenerate.
    """
    valid = [(x, y) for x, y in anchors if x > 0 and y > 0]
    if len(valid) < 2:
        if valid:
            return float(valid[0][1]), 0.85
        return 1.0, 0.85

    xs = [math.log(x) for x, _ in valid]
    ys = [math.log(y) for _, y in valid]
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(xs[i] * ys[i] for i in range(n))

    denom = n * sxx - sx * sx
    if denom == 0:
        return float(valid[0][1]), 0.85

    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    # slope corresponds to (-alpha), so alpha = -slope
    alpha = -slope
    A = math.exp(intercept)
    return A, alpha


def _powerlaw(rank: int, A: float, alpha: float) -> int:
    if rank <= 0:
        return 0
    value = A * (rank ** -alpha)
    return max(0, int(value))


# -----------------------------------------------------------------------------
# Estimator
# -----------------------------------------------------------------------------
class AudienceEstimator:
    """
    Stateless audience size estimator.

    Construct once at startup -- fits the calibration curves up front so
    per-domain queries are O(1).
    """

    def __init__(
        self,
        global_anchors: list[tuple[int, int]] = GLOBAL_ANCHORS,
        country_anchors: dict[str, list[tuple[int, int]]] = COUNTRY_ANCHORS,
        country_data: dict[str, tuple[int, float, str]] = COUNTRY_DATA,
    ):
        self.global_A, self.global_alpha = _fit_powerlaw(global_anchors)
        self.country_params: dict[str, tuple[float, float, int]] = {}
        for cc, anchors in country_anchors.items():
            n = len(anchors)
            A, alpha = _fit_powerlaw(anchors)
            self.country_params[cc] = (A, alpha, n)
        self.country_data = country_data
        logger.info(
            f"AudienceEstimator: global α={self.global_alpha:.3f} A={self.global_A:.2e}, "
            f"{len(self.country_params)} country curves"
        )

    # ----- Public API -----

    def estimate(
        self,
        rank: RankInfo,
        geography: GeographyInfo,
        domain: Optional[str] = None,
    ) -> AudienceInfo:
        """
        Build an AudienceInfo from a rank result + geography result.

        Hybrid lookup:
          1. If domain is in SIMILARWEB_KNOWN_VISITS, use the measured visits
             directly (HIGH confidence, method="similarweb_anchor").
          2. Else if domain is in SIMILARWEB_KNOWN_RANKS, use the known SW
             rank and skip the consensus_rank path (HIGH confidence,
             method="similarweb_rank+powerlaw"). This avoids the DNS/SW
             rank mismatch (which ranges 2-17× depending on language/site).
          3. Else fall back to consensus_rank → power-law (MEDIUM confidence,
             method="global_powerlaw"). Wide error band.
        """
        global_rank = rank.consensus_rank
        domain_key = (domain or "").lower().lstrip("www.") if domain else None
        global_estimate: Optional[int] = None
        global_band: Optional[tuple[int, int]] = None
        anchor_method: Optional[str] = None
        anchor_confidence: Optional[ConfidenceLevel] = None

        # ----- (1) Direct visits anchor -----
        if domain_key and domain_key in SIMILARWEB_KNOWN_VISITS:
            global_estimate = SIMILARWEB_KNOWN_VISITS[domain_key]
            global_band = self._band(global_estimate, factor=1.3)  # tight band
            anchor_method = "similarweb_anchor"
            anchor_confidence = ConfidenceLevel.HIGH

        # ----- (2) Known SW rank + power-law -----
        elif domain_key and domain_key in SIMILARWEB_KNOWN_RANKS:
            sw_rank = SIMILARWEB_KNOWN_RANKS[domain_key]
            global_estimate = _powerlaw(sw_rank, self.global_A, self.global_alpha)
            global_band = self._band(global_estimate, factor=1.5)
            anchor_method = "similarweb_rank+powerlaw"
            anchor_confidence = ConfidenceLevel.HIGH

        # ----- (3) Fallback: consensus rank power-law -----
        elif global_rank:
            global_estimate = _powerlaw(global_rank, self.global_A, self.global_alpha)
            global_band = self._band(global_estimate, factor=2.5)  # wider band; DNS/SW mismatch
            anchor_method = None  # falls through to default below

        if global_estimate is None:
            return AudienceInfo(
                monthly_uniques_global=None,
                monthly_uniques_band=None,
                by_country=[],
                confidence=ConfidenceLevel.UNKNOWN,
                method="unknown",
            )

        # ----- Country breakdown -----
        country_audiences: list[CountryAudience] = []
        method = anchor_method or "global_powerlaw"

        country_shares = self._country_shares(geography)
        country_rank_lookup = {
            cr.country_code: cr for cr in geography.country_ranks
        }

        for cc, share in country_shares.items():
            ca = self._country_audience(
                country_code=cc,
                share_of_global=share,
                global_estimate=global_estimate,
                country_rank=country_rank_lookup.get(cc),
            )
            if ca:
                country_audiences.append(ca)
                if ca.country_code in self.country_params and not anchor_method:
                    method = "country_powerlaw+global"

        # Sort by audience size descending
        country_audiences.sort(key=lambda c: -c.monthly_uniques)

        # Confidence: anchor lookups override the rank/geo-derived confidence
        if anchor_confidence is not None:
            confidence = anchor_confidence
        else:
            confidence = self._confidence(rank.confidence, geography.confidence, len(country_audiences))

        return AudienceInfo(
            monthly_uniques_global=global_estimate,
            monthly_uniques_band=global_band,
            by_country=country_audiences,
            confidence=confidence,
            method=method,
        )

    # ----- Internals -----

    def _country_audience(
        self,
        country_code: str,
        share_of_global: float,
        global_estimate: int,
        country_rank: Optional[CountryRank],
    ) -> Optional[CountryAudience]:
        """
        Compute country-specific monthly uniques.

        Priority:
          1. If we have a per-country power-law AND a per-country rank, use that
          2. Otherwise scale global estimate by share_of_global × (country / world)
        """
        cc = country_code.upper()
        country_info = self.country_data.get(cc)
        if not country_info:
            return None
        population, penetration, _region = country_info
        internet_users = int(population * penetration)

        # Method 1: per-country power-law (best)
        if cc in self.country_params and country_rank:
            A, alpha, _n = self.country_params[cc]
            estimate = _powerlaw(country_rank.rank, A, alpha)
        else:
            # Method 2: scale global estimate by penetration share + country share
            global_country_factor = internet_users / WORLD_INTERNET_USERS
            estimate = int(global_estimate * share_of_global * (0.5 + global_country_factor))
            # The 0.5 + factor is a fudge: even small countries can have
            # >>their internet-share if the domain is country-exclusive

        # Cap at country's internet user count (you can't reach more people than exist)
        estimate = min(estimate, internet_users)
        if estimate <= 0:
            return None

        pct = (estimate / internet_users) * 100 if internet_users else 0.0
        return CountryAudience(
            country_code=cc,
            monthly_uniques=estimate,
            pct_of_internet_users=round(pct, 2),
        )

    def _country_shares(self, geography: GeographyInfo) -> dict[str, float]:
        """
        Convert geography signals into share-of-global-audience per country.

        Approach: normalise the country scores from geography.top_countries
        so they sum to 1.0. If only one signal, that country gets 1.0.
        """
        if not geography.top_countries:
            return {}

        scores = {tc["country_code"]: float(tc["score"]) for tc in geography.top_countries}
        total = sum(scores.values())
        if total <= 0:
            return {}
        return {cc: score / total for cc, score in scores.items()}

    def _band(self, point: int, factor: float = 2.0) -> tuple[int, int]:
        """Symmetric multiplicative band: (point/factor, point*factor)."""
        if point <= 0:
            return (0, 0)
        return (int(point / factor), int(point * factor))

    def _confidence(
        self,
        rank_conf: ConfidenceLevel,
        geo_conf: ConfidenceLevel,
        n_countries: int,
    ) -> ConfidenceLevel:
        """Audience confidence = min(rank, geo) with bonus if multi-country."""
        order = {
            ConfidenceLevel.UNKNOWN: 0,
            ConfidenceLevel.LOW: 1,
            ConfidenceLevel.MEDIUM: 2,
            ConfidenceLevel.HIGH: 3,
        }
        worst = min(order[rank_conf], order[geo_conf])
        # No audience info → unknown
        if n_countries == 0:
            worst = min(worst, 1)
        rev = {v: k for k, v in order.items()}
        return rev[worst]
