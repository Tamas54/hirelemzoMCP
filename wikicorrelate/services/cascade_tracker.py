"""
Cross-Platform Attention Cascade Tracker
Tracks how topics spread across platforms: Wikipedia -> HackerNews -> YouTube -> GitHub
"""
import asyncio
import numpy as np
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass

from wikicorrelate.services.wikipedia import wikipedia_service
from wikicorrelate.services.youtube_source import youtube_source
from wikicorrelate.services.hackernews_source import hackernews_source
from wikicorrelate.services.github_source import github_source
from wikicorrelate.services.arxiv_source import arxiv_source
from wikicorrelate.services.spike_detector import spike_detector, Spike
from wikicorrelate.config import YOUTUBE_API_KEY


@dataclass
class PlatformSpike:
    """A spike detected on a specific platform."""
    platform: str
    date: str
    magnitude: float
    z_score: float
    value: int


@dataclass
class CascadeEvent:
    """A cascade of attention across platforms."""
    start_platform: str
    start_date: str
    platforms_reached: List[str]
    platform_lags: Dict[str, int]  # platform -> days after start
    total_duration_days: int


class AttentionCascade:
    """
    Tracks how attention for a topic cascades across platforms.

    Typical patterns:
    - Wikipedia spike -> HackerNews (1-2 days) -> YouTube (3-5 days) -> GitHub (5-7 days)
    - News event creates Wikipedia interest, then tech discussion, then content creation
    """

    def __init__(self):
        self.platforms = ["wikipedia", "hackernews", "youtube", "github", "arxiv"]
        self.platform_sources = {
            "wikipedia": self._get_wikipedia_timeseries,
            "hackernews": self._get_hackernews_timeseries,
            "youtube": self._get_youtube_timeseries,
            "github": self._get_github_timeseries,
            "arxiv": self._get_arxiv_timeseries
        }

    async def _get_wikipedia_timeseries(
        self,
        topic: str,
        days: int
    ) -> List[Dict]:
        """Get Wikipedia pageview timeseries."""
        start_date, end_date = wikipedia_service.get_date_range(days)
        data = await wikipedia_service.get_pageviews(topic, start_date, end_date)
        return data or []

    async def _get_hackernews_timeseries(
        self,
        topic: str,
        days: int
    ) -> List[Dict]:
        """Get HackerNews mention timeseries."""
        data = await hackernews_source.get_topic_mention_frequency(
            topic=topic,
            days=days,
            granularity="daily"
        )
        # Normalize to same format as Wikipedia
        return [{"date": d["date"], "views": d["mentions"]} for d in data]

    async def _get_youtube_timeseries(
        self,
        topic: str,
        days: int
    ) -> List[Dict]:
        """Get YouTube upload frequency timeseries."""
        if not YOUTUBE_API_KEY:
            return []

        data = await youtube_source.get_topic_upload_frequency(
            topic=topic,
            days=days,
            granularity="daily"
        )
        return [{"date": d["date"], "views": d["uploads"]} for d in data]

    async def _get_github_timeseries(
        self,
        topic: str,
        days: int
    ) -> List[Dict]:
        """Get GitHub repo creation timeseries."""
        data = await github_source.get_topic_repo_creation_frequency(
            topic=topic,
            days=days,
            granularity="daily"
        )
        return [{"date": d["date"], "views": d["repos_created"]} for d in data]

    async def _get_arxiv_timeseries(
        self,
        topic: str,
        days: int
    ) -> List[Dict]:
        """Get Arxiv paper publication timeseries."""
        data = await arxiv_source.get_topic_publication_frequency(
            topic=topic,
            days=days,
            granularity="daily"
        )
        return [{"date": d["date"], "views": d["papers"]} for d in data]

    async def track_cascade(
        self,
        topic: str,
        days: int = 365
    ) -> Dict:
        """
        Track attention cascade across all platforms for a topic.

        Args:
            topic: Topic to track
            days: Days of history to analyze

        Returns:
            Dict with cascade timeline and patterns
        """
        # Fetch timeseries from all platforms in parallel
        platform_data = {}
        platform_spikes = {}

        # Use asyncio.gather for parallel fetching
        tasks = []
        for platform in self.platforms:
            tasks.append(self.platform_sources[platform](topic, days))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for platform, result in zip(self.platforms, results):
            if isinstance(result, Exception):
                print(f"Error fetching {platform}: {result}")
                platform_data[platform] = []
            else:
                platform_data[platform] = result

            # Detect spikes
            if platform_data[platform]:
                spikes = spike_detector.detect_spikes(platform_data[platform])
                platform_spikes[platform] = [
                    PlatformSpike(
                        platform=platform,
                        date=s.date,
                        magnitude=s.magnitude,
                        z_score=s.z_score,
                        value=s.value
                    )
                    for s in spikes
                ]
            else:
                platform_spikes[platform] = []

        # Build cascade timeline
        cascade_timeline = self._build_cascade_timeline(platform_spikes)

        # Find cascade patterns
        patterns = self._analyze_cascade_patterns(platform_spikes)

        # Calculate platform correlations
        correlations = await self._calculate_platform_correlations(platform_data)

        return {
            "query": topic.replace("_", " "),
            "days_analyzed": days,
            "platform_spike_counts": {p: len(s) for p, s in platform_spikes.items()},
            "cascade_timeline": cascade_timeline,
            "cascade_patterns": patterns,
            "platform_correlations": correlations,
            "platform_data_available": {p: len(d) > 0 for p, d in platform_data.items()},
            "calculated_at": datetime.now().isoformat()
        }

    def _build_cascade_timeline(
        self,
        platform_spikes: Dict[str, List[PlatformSpike]]
    ) -> List[Dict]:
        """
        Build a unified timeline of spikes across all platforms.
        """
        all_events = []

        for platform, spikes in platform_spikes.items():
            for spike in spikes:
                all_events.append({
                    "date": spike.date,
                    "platform": platform,
                    "magnitude": spike.magnitude,
                    "z_score": spike.z_score
                })

        # Sort by date
        all_events.sort(key=lambda x: x["date"])

        return all_events

    def _analyze_cascade_patterns(
        self,
        platform_spikes: Dict[str, List[PlatformSpike]]
    ) -> Dict:
        """
        Analyze typical cascade patterns.

        Finds the typical order and lag between platform spikes.
        """
        # Find spike clusters (spikes within 14 days of each other)
        all_spikes = []
        for platform, spikes in platform_spikes.items():
            for spike in spikes:
                spike_date = datetime.strptime(spike.date, "%Y-%m-%d")
                all_spikes.append((spike_date, platform, spike.magnitude))

        if not all_spikes:
            return {
                "typical_order": [],
                "typical_lags": {},
                "cascade_events": 0
            }

        # Sort by date
        all_spikes.sort(key=lambda x: x[0])

        # Find cascade events (sequential platform activations)
        cascade_events = []
        platform_order_counts = defaultdict(int)
        platform_lags = defaultdict(list)

        i = 0
        while i < len(all_spikes):
            # Start a new potential cascade
            cascade_start = all_spikes[i][0]
            cascade_platforms = [all_spikes[i][1]]
            last_platform = all_spikes[i][1]

            j = i + 1
            while j < len(all_spikes):
                days_diff = (all_spikes[j][0] - cascade_start).days

                if days_diff > 21:  # Max cascade window
                    break

                new_platform = all_spikes[j][1]
                if new_platform not in cascade_platforms:
                    cascade_platforms.append(new_platform)
                    lag = (all_spikes[j][0] - cascade_start).days
                    platform_lags[f"{cascade_platforms[0]}->{new_platform}"].append(lag)
                    last_platform = new_platform

                j += 1

            if len(cascade_platforms) >= 2:
                # Record the order
                order_key = "->".join(cascade_platforms)
                platform_order_counts[order_key] += 1
                cascade_events.append({
                    "start_date": cascade_start.isoformat(),
                    "platforms": cascade_platforms,
                    "duration_days": (all_spikes[j-1][0] - cascade_start).days if j > i+1 else 0
                })

            i = j if j > i+1 else i+1

        # Calculate average lags
        avg_lags = {}
        for key, lags in platform_lags.items():
            avg_lags[key] = round(sum(lags) / len(lags), 1)

        # Find most common order
        typical_order = []
        if platform_order_counts:
            most_common = max(platform_order_counts.items(), key=lambda x: x[1])
            typical_order = most_common[0].split("->")

        return {
            "typical_order": typical_order,
            "typical_lags": avg_lags,
            "cascade_events": len(cascade_events),
            "order_frequency": dict(platform_order_counts),
            "recent_cascades": cascade_events[-5:] if cascade_events else []
        }

    async def _calculate_platform_correlations(
        self,
        platform_data: Dict[str, List[Dict]]
    ) -> Dict[str, float]:
        """
        Calculate pairwise correlations between platform timeseries.
        """
        from wikicorrelate.services.correlate import calculate_correlation

        correlations = {}

        platforms_with_data = [p for p in self.platforms if platform_data.get(p)]

        for i, p1 in enumerate(platforms_with_data):
            for p2 in platforms_with_data[i+1:]:
                data1 = platform_data[p1]
                data2 = platform_data[p2]

                # Align by date
                dates1 = {d["date"]: d["views"] for d in data1}
                dates2 = {d["date"]: d["views"] for d in data2}

                common_dates = sorted(set(dates1.keys()) & set(dates2.keys()))

                if len(common_dates) < 30:
                    continue

                values1 = np.array([dates1[d] for d in common_dates])
                values2 = np.array([dates2[d] for d in common_dates])

                corr, _ = calculate_correlation(values1, values2)
                correlations[f"{p1}_{p2}"] = round(corr, 4)

        return correlations

    async def find_cascade_pattern(
        self,
        topic: str,
        days: int = 365
    ) -> Dict:
        """
        Find the typical cascade pattern for a topic.

        Returns the typical order of platform activation and lags.
        """
        result = await self.track_cascade(topic, days)

        patterns = result.get("cascade_patterns", {})

        if not patterns.get("typical_order"):
            return {
                "topic": topic.replace("_", " "),
                "pattern_found": False,
                "message": "Not enough cascade events to determine pattern"
            }

        return {
            "topic": topic.replace("_", " "),
            "pattern_found": True,
            "typical_order": patterns["typical_order"],
            "typical_lags": patterns["typical_lags"],
            "cascade_events_analyzed": patterns["cascade_events"],
            "lead_platform": patterns["typical_order"][0] if patterns["typical_order"] else None,
            "description": self._generate_pattern_description(patterns)
        }

    def _generate_pattern_description(self, patterns: Dict) -> str:
        """Generate human-readable description of cascade pattern."""
        order = patterns.get("typical_order", [])
        lags = patterns.get("typical_lags", {})

        if not order:
            return "No clear cascade pattern detected."

        parts = [f"Attention typically starts on {order[0]}"]

        for i in range(1, len(order)):
            prev = order[i-1]
            curr = order[i]
            lag_key = f"{order[0]}->{curr}"
            lag = lags.get(lag_key, "?")
            parts.append(f"spreads to {curr} after ~{lag} days")

        return ", ".join(parts) + "."


# Singleton instance
cascade_tracker = AttentionCascade()


async def track_topic_cascade(topic: str, days: int = 365) -> Dict:
    """
    Main entry point for cascade tracking.

    Args:
        topic: Topic to track
        days: Days of history

    Returns:
        Full cascade analysis
    """
    return await cascade_tracker.track_cascade(topic, days)


async def get_cascade_pattern(topic: str) -> Dict:
    """
    Get the typical cascade pattern for a topic.
    """
    return await cascade_tracker.find_cascade_pattern(topic)
