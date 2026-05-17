"""
Trend analysis: how has the domain's rank evolved?

Uses Tranco's historical daily lists (permanent URLs for past dates).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from domain_intel.models import TrendInfo
from domain_intel.ranking import TrancoHistorical

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    def __init__(self, historical: TrancoHistorical):
        self.historical = historical

    async def analyze(self, domain: str, current_rank: Optional[int]) -> TrendInfo:
        today = date.today()
        rank_30d = await self.historical.get_rank_at_date(domain, today - timedelta(days=30))
        rank_90d = await self.historical.get_rank_at_date(domain, today - timedelta(days=90))

        change_30d = None
        change_90d = None
        if current_rank and rank_30d:
            # Positive = improved (rank number decreased, i.e. moved up the list)
            change_30d = rank_30d - current_rank
        if current_rank and rank_90d:
            change_90d = rank_90d - current_rank

        # Direction based on 30d change
        direction = "unknown"
        if change_30d is not None:
            # Threshold: 5% of current rank is "noise" — anything bigger is a real move
            threshold = max(50, int((current_rank or 1000) * 0.05))
            if change_30d > threshold:
                direction = "rising"
            elif change_30d < -threshold:
                direction = "falling"
            else:
                direction = "stable"

        return TrendInfo(
            rank_30d_ago=rank_30d,
            rank_90d_ago=rank_90d,
            change_30d=change_30d,
            change_90d=change_90d,
            direction=direction,
        )
