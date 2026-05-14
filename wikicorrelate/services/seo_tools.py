"""
SEO Tools Service
Content strategy tools for search optimization.

Includes:
- Gap Analysis: Find counter-cyclical topics
- Seasonal Calendar: Best times to publish
- CSV Export utilities
"""
import numpy as np
import pandas as pd
from io import StringIO
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date, timedelta
from collections import defaultdict
from scipy.stats import pearsonr
from scipy import signal

from wikicorrelate.services.wikipedia import wikipedia_service
from wikicorrelate.services.correlate import (
    WIDE_CATEGORIES,
    CATEGORY_ARTICLES,
    get_all_wide_candidates,
    calculate_correlation,
    detrend_and_deseasonalize,
    get_article_category
)


class SEOToolsService:
    """
    SEO and content strategy tools.
    """

    # ==========================================================================
    # GAP ANALYSIS - Find counter-cyclical content opportunities
    # ==========================================================================

    async def gap_analysis(
        self,
        query: str,
        days: int = 365,
        min_inverse_correlation: float = -0.5,
        max_results: int = 20
    ) -> Dict:
        """
        Keyword Gap Analysis - Find topics that trend UP when your topic trends DOWN.

        Use case: Diversify content to stabilize traffic.
        When "Bitcoin" interest drops, what topics pick up?

        Args:
            query: Main topic to analyze
            days: Days of history
            min_inverse_correlation: Threshold (e.g., -0.5 means r < -0.5)
            max_results: Maximum results

        Returns:
            Dict with gap opportunities and strategy recommendations
        """
        from wikicorrelate.services.article_cache import article_cache

        # Normalize query
        query_article = query.replace(" ", "_")

        # Get date range
        start_date, end_date = wikipedia_service.get_date_range(days)

        # Fetch query pageviews
        query_views = await wikipedia_service.get_pageviews(query_article, start_date, end_date)

        if not query_views:
            return {
                "query": query,
                "error": "Could not fetch pageview data for query",
                "gaps": []
            }

        query_values = np.array([p['views'] for p in query_views])

        # Get candidates from both WIDE_CATEGORIES and cached top articles
        all_candidates = set(get_all_wide_candidates())

        # Add top cached articles for broader coverage
        try:
            top_articles = await article_cache.get_top_articles(limit=2000)
            all_candidates.update(top_articles)
        except Exception as e:
            print(f"Could not load cached articles: {e}")

        all_candidates = [a for a in all_candidates if a.lower() != query_article.lower()]
        print(f"[gap_analysis] Testing {len(all_candidates)} candidates for '{query}'")

        # Fetch candidate data in batch
        all_data = await wikipedia_service.get_pageviews_batch(
            all_candidates, start_date, end_date
        )

        # Find negative correlations
        gaps = []

        for article in all_candidates:
            if article not in all_data or not all_data[article]:
                continue

            candidate_values = np.array([p['views'] for p in all_data[article]])

            if len(candidate_values) != len(query_values):
                continue

            try:
                corr, p_value = pearsonr(query_values, candidate_values)

                if corr <= min_inverse_correlation and p_value < 0.05:
                    # Calculate when this topic peaks vs query
                    peak_offset = self._calculate_peak_offset(query_values, candidate_values)

                    # Calculate traffic potential
                    avg_views = int(np.mean(candidate_values))

                    gaps.append({
                        "topic": article.replace("_", " "),
                        "slug": article,
                        "inverse_correlation": round(corr, 4),
                        "p_value": round(p_value, 6),
                        "avg_daily_views": avg_views,
                        "peak_offset_days": peak_offset,
                        "category": get_article_category(article),
                        "strategy": self._generate_gap_strategy(corr, peak_offset, avg_views)
                    })
            except Exception:
                continue

        # Sort by strength of inverse correlation
        gaps.sort(key=lambda x: x['inverse_correlation'])

        # Trim to max results
        gaps = gaps[:max_results]

        # Generate overall recommendations
        recommendations = self._generate_gap_recommendations(query, gaps)

        return {
            "query": query,
            "query_slug": query_article,
            "days_analyzed": days,
            "threshold": min_inverse_correlation,
            "gaps_found": len(gaps),
            "gaps": gaps,
            "recommendations": recommendations,
            "calculated_at": datetime.now().isoformat()
        }

    def _calculate_peak_offset(self, series_a: np.ndarray, series_b: np.ndarray) -> int:
        """
        Calculate how many days series_b peaks after series_a troughs.
        Useful for timing content publication.
        """
        try:
            # Find correlation at different lags
            max_lag = min(30, len(series_a) // 4)
            best_lag = 0
            best_corr = -1

            for lag in range(-max_lag, max_lag + 1):
                if lag < 0:
                    a = series_a[-lag:]
                    b = series_b[:lag]
                elif lag > 0:
                    a = series_a[:-lag]
                    b = series_b[lag:]
                else:
                    a, b = series_a, series_b

                if len(a) < 10:
                    continue

                corr = np.corrcoef(a, b)[0, 1]
                # For inverse correlation, we want most negative
                if corr < best_corr:
                    best_corr = corr
                    best_lag = lag

            return best_lag
        except Exception:
            return 0

    def _generate_gap_strategy(self, corr: float, offset: int, views: int) -> str:
        """Generate actionable strategy for a gap topic."""
        strength = "strong" if corr < -0.7 else "moderate"

        if offset > 7:
            timing = f"Publish {offset} days after your main topic dips"
        elif offset < -7:
            timing = f"Publish {abs(offset)} days before your main topic dips"
        else:
            timing = "Publish when your main topic starts declining"

        if views > 10000:
            traffic = "High traffic potential"
        elif views > 1000:
            traffic = "Moderate traffic potential"
        else:
            traffic = "Niche topic"

        return f"{strength.title()} inverse correlation. {timing}. {traffic}."

    def _generate_gap_recommendations(self, query: str, gaps: List[Dict]) -> List[str]:
        """Generate overall content strategy recommendations."""
        recommendations = []

        if not gaps:
            recommendations.append(
                f"No strong inverse correlations found for '{query}'. "
                "Consider analyzing with a lower threshold."
            )
            return recommendations

        # Group by category
        categories = defaultdict(list)
        for gap in gaps:
            cat = gap.get('category', 'other')
            categories[cat].append(gap['topic'])

        # Top category recommendation
        top_cat = max(categories.items(), key=lambda x: len(x[1]))
        recommendations.append(
            f"Focus on {top_cat[0]} topics - {len(top_cat[1])} counter-cyclical opportunities found."
        )

        # Strongest inverse
        strongest = gaps[0]
        recommendations.append(
            f"Strongest hedge: '{strongest['topic']}' (r={strongest['inverse_correlation']:.2f}). "
            f"{strongest['strategy']}"
        )

        # Traffic diversification
        high_traffic = [g for g in gaps if g['avg_daily_views'] > 5000]
        if high_traffic:
            recommendations.append(
                f"{len(high_traffic)} high-traffic counter-cyclical topics available for diversification."
            )

        return recommendations

    # ==========================================================================
    # SEASONAL CALENDAR - Best times to publish
    # ==========================================================================

    async def seasonal_calendar(
        self,
        query: str,
        forecast_months: int = 12
    ) -> Dict:
        """
        Generate a content calendar based on historical seasonality.

        Analyzes when interest peaks/troughs and recommends publication timing.

        Args:
            query: Topic to analyze
            forecast_months: Months to forecast ahead

        Returns:
            Dict with monthly/weekly recommendations
        """
        query_article = query.replace(" ", "_")

        # Get 2 years of data for seasonality
        start_date, end_date = wikipedia_service.get_date_range(730)
        pageviews = await wikipedia_service.get_pageviews(query_article, start_date, end_date)

        if not pageviews or len(pageviews) < 60:
            return {
                "query": query,
                "error": "Insufficient data for seasonal analysis",
                "calendar": []
            }

        # Convert to DataFrame
        df = pd.DataFrame(pageviews)
        df['date'] = pd.to_datetime(df['date'])
        df['views'] = pd.to_numeric(df['views'])
        df['month'] = df['date'].dt.month
        df['week'] = df['date'].dt.isocalendar().week
        df['day_of_week'] = df['date'].dt.dayofweek

        # Monthly seasonality
        monthly_avg = df.groupby('month')['views'].mean()
        monthly_std = df.groupby('month')['views'].std()

        # Weekly pattern (day of week)
        dow_avg = df.groupby('day_of_week')['views'].mean()

        # Find peak and trough months
        peak_month = int(monthly_avg.idxmax())
        trough_month = int(monthly_avg.idxmin())

        # Generate calendar
        today = date.today()
        calendar = []

        for i in range(forecast_months):
            forecast_date = today + timedelta(days=30 * i)
            month = forecast_date.month
            month_name = forecast_date.strftime("%B %Y")

            avg_views = float(monthly_avg.get(month, monthly_avg.mean()))
            overall_avg = float(monthly_avg.mean())

            # Calculate opportunity score
            if avg_views > overall_avg * 1.2:
                opportunity = "high"
                action = "Publish cornerstone content"
            elif avg_views > overall_avg * 0.9:
                opportunity = "medium"
                action = "Maintain regular publishing"
            else:
                opportunity = "low"
                action = "Focus on evergreen content or other topics"

            # Best day of week
            best_dow = int(dow_avg.idxmax())
            dow_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

            calendar.append({
                "month": month_name,
                "month_number": month,
                "expected_interest": round(avg_views, 0),
                "vs_average": round((avg_views / overall_avg - 1) * 100, 1),
                "opportunity": opportunity,
                "recommended_action": action,
                "best_publish_day": dow_names[best_dow]
            })

        # Summary insights
        insights = [
            f"Peak interest month: {datetime(2000, peak_month, 1).strftime('%B')} ({(float(monthly_avg[peak_month]) / float(monthly_avg.mean()) - 1) * 100:.0f}% above average)",
            f"Lowest interest month: {datetime(2000, trough_month, 1).strftime('%B')} ({(float(monthly_avg[trough_month]) / float(monthly_avg.mean()) - 1) * 100:.0f}% vs average)",
            f"Best day to publish: {dow_names[int(dow_avg.idxmax())]}",
            f"Worst day to publish: {dow_names[int(dow_avg.idxmin())]}"
        ]

        return {
            "query": query,
            "query_slug": query_article,
            "forecast_months": forecast_months,
            "calendar": calendar,
            "insights": insights,
            "peak_month": peak_month,
            "trough_month": trough_month,
            "calculated_at": datetime.now().isoformat()
        }

    # ==========================================================================
    # CSV EXPORT - Data export utilities
    # ==========================================================================

    def correlations_to_csv(self, data: Dict) -> str:
        """
        Convert correlation results to CSV format.

        Args:
            data: Result from search_and_correlate or similar

        Returns:
            CSV string
        """
        correlations = data.get('correlations', [])

        if not correlations:
            return "No data to export"

        rows = []
        for c in correlations:
            rows.append({
                'title': c.get('title', ''),
                'correlation': c.get('score', 0),
                'p_value': c.get('p_value', ''),
                'avg_daily_views': c.get('avg_daily_views', 0),
                'category': c.get('category', ''),
                'trend': c.get('trend', '')
            })

        df = pd.DataFrame(rows)
        return df.to_csv(index=False)

    def clusters_to_csv(self, data: Dict) -> str:
        """
        Convert cluster results to CSV format.

        Args:
            data: Result from cluster_topics

        Returns:
            CSV string
        """
        clusters = data.get('clusters', [])

        if not clusters:
            return "No data to export"

        rows = []
        for cluster in clusters:
            cluster_name = cluster.get('name', '')
            for topic in cluster.get('topics', []):
                rows.append({
                    'cluster_id': cluster.get('id', 0),
                    'cluster_name': cluster_name,
                    'topic': topic.get('title', ''),
                    'correlation': topic.get('correlation', 0),
                    'category': topic.get('category', '')
                })

        df = pd.DataFrame(rows)
        return df.to_csv(index=False)

    def gaps_to_csv(self, data: Dict) -> str:
        """
        Convert gap analysis results to CSV format.

        Args:
            data: Result from gap_analysis

        Returns:
            CSV string
        """
        gaps = data.get('gaps', [])

        if not gaps:
            return "No data to export"

        rows = []
        for gap in gaps:
            rows.append({
                'topic': gap.get('topic', ''),
                'inverse_correlation': gap.get('inverse_correlation', 0),
                'p_value': gap.get('p_value', ''),
                'avg_daily_views': gap.get('avg_daily_views', 0),
                'peak_offset_days': gap.get('peak_offset_days', 0),
                'category': gap.get('category', ''),
                'strategy': gap.get('strategy', '')
            })

        df = pd.DataFrame(rows)
        return df.to_csv(index=False)

    def calendar_to_csv(self, data: Dict) -> str:
        """
        Convert calendar results to CSV format.

        Args:
            data: Result from seasonal_calendar

        Returns:
            CSV string
        """
        calendar = data.get('calendar', [])

        if not calendar:
            return "No data to export"

        df = pd.DataFrame(calendar)
        return df.to_csv(index=False)

    def timeseries_to_csv(self, data: Dict) -> str:
        """
        Export timeseries data to CSV.

        Args:
            data: Result containing query_timeseries

        Returns:
            CSV string
        """
        timeseries = data.get('query_timeseries', [])

        if not timeseries:
            return "No timeseries data"

        df = pd.DataFrame(timeseries)
        return df.to_csv(index=False)


# Singleton instance
seo_tools = SEOToolsService()


# Convenience functions
async def gap_analysis(query: str, days: int = 365, threshold: float = -0.5) -> Dict:
    """Find counter-cyclical content opportunities."""
    return await seo_tools.gap_analysis(query, days=days, min_inverse_correlation=threshold)


async def seasonal_calendar(query: str, months: int = 12) -> Dict:
    """Generate content calendar based on seasonality."""
    return await seo_tools.seasonal_calendar(query, forecast_months=months)
