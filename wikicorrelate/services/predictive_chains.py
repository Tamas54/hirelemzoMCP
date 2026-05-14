"""
Predictive Chains Service
Find frequent event chains with predictive power for price movements.

Based on find_frequent_chains.py POC - integrated with Wikipedia pageviews API
and yfinance for price data.
"""

import asyncio
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    yf = None

from wikicorrelate.services.wikipedia import wikipedia_service
from wikicorrelate.services.correlate import WIDE_CATEGORIES


@dataclass
class ChainResult:
    """Result of a predictive chain test."""
    trigger: str
    intermediate: str
    lag1: int
    lag2: int
    total_events: int
    successful: int
    success_rate: float
    avg_change: float


class PredictiveChainFinder:
    """
    Find frequent event chains with predictive power.

    Tests patterns like:
    - Direct: Wikipedia topic spike → Asset price movement
    - 2-stage: Topic A spike → Topic B spike → Asset price movement
    """

    def __init__(self):
        self.price_cache: Dict[str, pd.DataFrame] = {}
        self.pageview_cache: Dict[str, List[Dict]] = {}

        # Default trigger topics to test
        self.default_triggers = [
            'Economic_bubble',
            'Inflation',
            'Fiat_money',
            'Monetary_policy',
            'Dot-com_bubble',
            'Silver',
            'Copper',
            'Risk_management',
            'Natural_gas',
            'Gold',
            'Federal_Reserve',
            'Interest_rate',
            'Stock_market_crash',
            'Recession',
            'Quantitative_easing'
        ]

        # Default intermediate topics
        self.default_intermediates = [
            'Fiat_money',
            'Cryptocurrency',
            'Investment',
            'Stock_market'
        ]

    def _fetch_price_data(
        self,
        ticker: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        Fetch price data from Yahoo Finance.

        Args:
            ticker: Yahoo Finance ticker (e.g., 'BTC-USD', 'GC=F' for gold)
            start_date: Start date YYYY-MM-DD
            end_date: End date YYYY-MM-DD

        Returns:
            DataFrame with date and price columns
        """
        if not YFINANCE_AVAILABLE:
            return pd.DataFrame()

        cache_key = f"{ticker}_{start_date}_{end_date}"
        if cache_key in self.price_cache:
            return self.price_cache[cache_key]

        try:
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if data.empty:
                return pd.DataFrame()

            df = data.reset_index()
            # Handle both single and multi-level column names
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

            df = df[['Date', 'Close']].copy()
            df.columns = ['date', 'price']
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

            self.price_cache[cache_key] = df
            return df
        except Exception as e:
            print(f"Error fetching price data for {ticker}: {e}")
            return pd.DataFrame()

    async def _get_pageviews(
        self,
        topic: str,
        days: int
    ) -> List[Dict]:
        """Get Wikipedia pageviews for a topic."""
        cache_key = f"{topic}_{days}"
        if cache_key in self.pageview_cache:
            return self.pageview_cache[cache_key]

        start_date, end_date = wikipedia_service.get_date_range(days)
        data = await wikipedia_service.get_pageviews(topic, start_date, end_date)

        if data:
            self.pageview_cache[cache_key] = data

        return data or []

    async def test_direct_chain(
        self,
        trigger_topic: str,
        ticker: str = 'BTC-USD',
        days: int = 3650,
        lag: int = 7,
        trigger_threshold: float = 0.0,
        price_threshold: float = 3.0
    ) -> Optional[Dict]:
        """
        Test direct chain: Wikipedia topic spike → Asset price movement.

        Args:
            trigger_topic: Wikipedia article to monitor
            ticker: Yahoo Finance ticker for price data
            days: Days of history to analyze
            lag: Days between topic spike and price movement
            trigger_threshold: Minimum % change in pageviews to count as trigger
            price_threshold: Minimum % price change to count as success

        Returns:
            Dict with chain statistics or None if not enough data
        """
        if not YFINANCE_AVAILABLE:
            return {"error": "yfinance not installed"}

        # Calculate date range
        end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Fetch data
        pageviews = await self._get_pageviews(trigger_topic, days)
        if not pageviews or len(pageviews) < 30:
            return None

        price_df = self._fetch_price_data(ticker, start_date, end_date)
        if price_df.empty:
            return None

        # Convert pageviews to DataFrame
        pv_df = pd.DataFrame(pageviews)
        pv_df['date'] = pd.to_datetime(pv_df['date']).dt.strftime('%Y-%m-%d')
        pv_df = pv_df.rename(columns={'views': 'trigger_views'})

        # Merge with price data
        df = price_df.merge(pv_df[['date', 'trigger_views']], on='date', how='inner')
        df = df.sort_values('date').reset_index(drop=True)

        if len(df) < 30:
            return None

        # Calculate 7-day % change in pageviews
        df['trigger_pct_change'] = (
            (df['trigger_views'] - df['trigger_views'].shift(7)) /
            df['trigger_views'].shift(7) * 100
        )

        # Detect events
        events = []
        for i in range(len(df) - lag):
            if pd.isna(df.iloc[i]['trigger_pct_change']):
                continue
            if df.iloc[i]['trigger_pct_change'] < trigger_threshold:
                continue

            idx_price = i + lag
            if idx_price >= len(df):
                continue

            price_change_pct = (
                (df.iloc[idx_price]['price'] - df.iloc[i]['price']) /
                df.iloc[i]['price'] * 100
            )

            success = abs(price_change_pct) >= price_threshold

            events.append({
                'date': str(df.iloc[i]['date']),
                'trigger_change': float(df.iloc[i]['trigger_pct_change']),
                'price_change': float(price_change_pct),
                'success': bool(success)
            })

        if not events:
            return None

        events_df = pd.DataFrame(events)
        total = len(events_df)
        successful = int(events_df['success'].sum())
        success_rate = (successful / total * 100) if total > 0 else 0
        avg_change = float(events_df['price_change'].mean())

        return {
            'chain_type': 'direct',
            'trigger': trigger_topic.replace('_', ' '),
            'intermediate': None,
            'target_ticker': ticker,
            'lag_days': lag,
            'total_events': total,
            'successful_events': successful,
            'success_rate': round(success_rate, 2),
            'avg_price_change': round(avg_change, 2),
            'trigger_threshold': trigger_threshold,
            'price_threshold': price_threshold,
            'days_analyzed': days,
            'sample_events': events[-5:] if len(events) >= 5 else events
        }

    async def test_2stage_chain(
        self,
        trigger_topic: str,
        intermediate_topic: str,
        ticker: str = 'BTC-USD',
        days: int = 3650,
        lag1: int = 7,
        lag2: int = 1,
        trigger_threshold: float = 0.0,
        intermediate_threshold: float = 0.0,
        price_threshold: float = 3.0
    ) -> Optional[Dict]:
        """
        Test 2-stage chain: Topic A spike → Topic B spike → Price movement.

        Args:
            trigger_topic: First Wikipedia article (trigger)
            intermediate_topic: Second Wikipedia article (intermediate)
            ticker: Yahoo Finance ticker
            days: Days of history
            lag1: Days between trigger and intermediate
            lag2: Days between intermediate and price movement
            trigger_threshold: Min % change for trigger
            intermediate_threshold: Min % change for intermediate
            price_threshold: Min % price change for success

        Returns:
            Dict with chain statistics
        """
        if not YFINANCE_AVAILABLE:
            return {"error": "yfinance not installed"}

        if trigger_topic == intermediate_topic:
            return None

        # Calculate date range
        end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Fetch data in parallel
        trigger_pv, intermediate_pv = await asyncio.gather(
            self._get_pageviews(trigger_topic, days),
            self._get_pageviews(intermediate_topic, days)
        )

        if not trigger_pv or not intermediate_pv:
            return None

        price_df = self._fetch_price_data(ticker, start_date, end_date)
        if price_df.empty:
            return None

        # Convert to DataFrames
        trigger_df = pd.DataFrame(trigger_pv)
        trigger_df['date'] = pd.to_datetime(trigger_df['date']).dt.strftime('%Y-%m-%d')
        trigger_df = trigger_df.rename(columns={'views': 'trigger_views'})

        inter_df = pd.DataFrame(intermediate_pv)
        inter_df['date'] = pd.to_datetime(inter_df['date']).dt.strftime('%Y-%m-%d')
        inter_df = inter_df.rename(columns={'views': 'intermediate_views'})

        # Merge all data
        df = price_df.merge(trigger_df[['date', 'trigger_views']], on='date', how='inner')
        df = df.merge(inter_df[['date', 'intermediate_views']], on='date', how='inner')
        df = df.sort_values('date').reset_index(drop=True)

        if len(df) < 30:
            return None

        # Calculate % changes
        df['trigger_pct_change'] = (
            (df['trigger_views'] - df['trigger_views'].shift(7)) /
            df['trigger_views'].shift(7) * 100
        )
        df['intermediate_pct_change'] = (
            (df['intermediate_views'] - df['intermediate_views'].shift(7)) /
            df['intermediate_views'].shift(7) * 100
        )

        # Detect 2-stage chains
        events = []
        for i in range(len(df) - lag1 - lag2):
            # Stage 1: Check trigger
            if pd.isna(df.iloc[i]['trigger_pct_change']):
                continue
            if df.iloc[i]['trigger_pct_change'] < trigger_threshold:
                continue

            # Stage 2: Check intermediate (lag1 days later)
            idx_inter = i + lag1
            if idx_inter >= len(df):
                continue
            if pd.isna(df.iloc[idx_inter]['intermediate_pct_change']):
                continue
            if df.iloc[idx_inter]['intermediate_pct_change'] < intermediate_threshold:
                continue

            # Stage 3: Check price (lag2 days after intermediate)
            idx_price = idx_inter + lag2
            if idx_price >= len(df):
                continue

            price_change_pct = (
                (df.iloc[idx_price]['price'] - df.iloc[i]['price']) /
                df.iloc[i]['price'] * 100
            )

            success = abs(price_change_pct) >= price_threshold

            events.append({
                'trigger_date': str(df.iloc[i]['date']),
                'intermediate_date': str(df.iloc[idx_inter]['date']),
                'trigger_change': float(df.iloc[i]['trigger_pct_change']),
                'intermediate_change': float(df.iloc[idx_inter]['intermediate_pct_change']),
                'price_change': float(price_change_pct),
                'success': bool(success)
            })

        if not events:
            return None

        events_df = pd.DataFrame(events)
        total = len(events_df)
        successful = int(events_df['success'].sum())
        success_rate = (successful / total * 100) if total > 0 else 0
        avg_change = float(events_df['price_change'].mean())

        return {
            'chain_type': '2-stage',
            'trigger': trigger_topic.replace('_', ' '),
            'intermediate': intermediate_topic.replace('_', ' '),
            'target_ticker': ticker,
            'lag1_days': lag1,
            'lag2_days': lag2,
            'total_lag_days': lag1 + lag2,
            'total_events': total,
            'successful_events': successful,
            'success_rate': round(success_rate, 2),
            'avg_price_change': round(avg_change, 2),
            'trigger_threshold': trigger_threshold,
            'intermediate_threshold': intermediate_threshold,
            'price_threshold': price_threshold,
            'days_analyzed': days,
            'sample_events': events[-3:] if len(events) >= 3 else events
        }

    async def find_best_chains(
        self,
        ticker: str = 'BTC-USD',
        days: int = 1825,
        min_events: int = 50,
        min_success_rate: float = 25.0,
        lags: List[int] = None,
        max_results: int = 20
    ) -> Dict:
        """
        Find the best predictive chains for an asset.

        Tests multiple trigger topics and configurations to find
        chains with high frequency AND good predictive power.

        Args:
            ticker: Yahoo Finance ticker
            days: Days of history
            min_events: Minimum events required
            min_success_rate: Minimum success rate %
            lags: Lags to test (default: [1, 3, 7, 14])
            max_results: Maximum results to return

        Returns:
            Dict with best direct and 2-stage chains
        """
        if not YFINANCE_AVAILABLE:
            return {"error": "yfinance not installed. Run: pip install yfinance"}

        if lags is None:
            lags = [1, 3, 7, 14]

        direct_results = []
        twostage_results = []

        # Test direct chains
        for trigger in self.default_triggers:
            for lag in lags:
                result = await self.test_direct_chain(
                    trigger_topic=trigger,
                    ticker=ticker,
                    days=days,
                    lag=lag,
                    trigger_threshold=5.0,
                    price_threshold=3.0
                )

                if result and result.get('total_events', 0) >= min_events:
                    if result.get('success_rate', 0) >= min_success_rate:
                        direct_results.append(result)

        # Test 2-stage chains
        for trigger in self.default_triggers:
            for intermediate in self.default_intermediates:
                if trigger == intermediate:
                    continue

                for lag1 in [3, 7, 14]:
                    result = await self.test_2stage_chain(
                        trigger_topic=trigger,
                        intermediate_topic=intermediate,
                        ticker=ticker,
                        days=days,
                        lag1=lag1,
                        lag2=1,
                        trigger_threshold=5.0,
                        intermediate_threshold=5.0,
                        price_threshold=3.0
                    )

                    if result and result.get('total_events', 0) >= min_events:
                        if result.get('success_rate', 0) >= min_success_rate:
                            twostage_results.append(result)

        # Sort by success rate
        direct_sorted = sorted(
            direct_results,
            key=lambda x: (x['success_rate'], x['total_events']),
            reverse=True
        )[:max_results]

        twostage_sorted = sorted(
            twostage_results,
            key=lambda x: (x['success_rate'], x['total_events']),
            reverse=True
        )[:max_results]

        # Remove sample_events for summary
        for r in direct_sorted:
            r.pop('sample_events', None)
        for r in twostage_sorted:
            r.pop('sample_events', None)

        return {
            'ticker': ticker,
            'days_analyzed': days,
            'min_events_required': min_events,
            'min_success_rate_required': min_success_rate,
            'direct_chains': direct_sorted,
            'twostage_chains': twostage_sorted,
            'total_direct_found': len(direct_results),
            'total_twostage_found': len(twostage_results),
            'calculated_at': datetime.now().isoformat()
        }

    async def get_active_signals(
        self,
        ticker: str = 'BTC-USD',
        lookback_days: int = 7
    ) -> Dict:
        """
        Check for currently active predictive signals.

        Looks at recent Wikipedia pageview spikes that historically
        predict price movements.

        Args:
            ticker: Target asset ticker
            lookback_days: Days to look back for recent spikes

        Returns:
            Dict with active signals
        """
        if not YFINANCE_AVAILABLE:
            return {"error": "yfinance not installed"}

        active_signals = []

        # Check each trigger topic for recent spikes
        for trigger in self.default_triggers:
            pageviews = await self._get_pageviews(trigger, 30)
            if not pageviews or len(pageviews) < 14:
                continue

            pv_df = pd.DataFrame(pageviews)
            pv_df['views'] = pd.to_numeric(pv_df['views'])

            # Calculate recent % change
            recent_views = pv_df.tail(lookback_days)['views'].mean()
            baseline_views = pv_df.head(7)['views'].mean()

            if baseline_views > 0:
                pct_change = ((recent_views - baseline_views) / baseline_views) * 100

                if pct_change >= 10.0:  # 10% spike threshold
                    active_signals.append({
                        'topic': trigger.replace('_', ' '),
                        'recent_avg_views': int(recent_views),
                        'baseline_avg_views': int(baseline_views),
                        'pct_change': round(pct_change, 2),
                        'signal_type': 'spike_detected',
                        'potential_impact': 'bullish' if pct_change > 0 else 'bearish'
                    })

        # Sort by magnitude of change
        active_signals.sort(key=lambda x: abs(x['pct_change']), reverse=True)

        return {
            'ticker': ticker,
            'lookback_days': lookback_days,
            'active_signals': active_signals[:10],
            'total_signals': len(active_signals),
            'checked_at': datetime.now().isoformat()
        }


# Singleton instance
predictive_chain_finder = PredictiveChainFinder()


async def test_direct_chain(
    trigger: str,
    ticker: str = 'BTC-USD',
    days: int = 1825,
    lag: int = 7
) -> Optional[Dict]:
    """Test a direct predictive chain."""
    return await predictive_chain_finder.test_direct_chain(
        trigger_topic=trigger,
        ticker=ticker,
        days=days,
        lag=lag
    )


async def test_2stage_chain(
    trigger: str,
    intermediate: str,
    ticker: str = 'BTC-USD',
    days: int = 1825,
    lag1: int = 7,
    lag2: int = 1
) -> Optional[Dict]:
    """Test a 2-stage predictive chain."""
    return await predictive_chain_finder.test_2stage_chain(
        trigger_topic=trigger,
        intermediate_topic=intermediate,
        ticker=ticker,
        days=days,
        lag1=lag1,
        lag2=lag2
    )


async def find_best_chains(
    ticker: str = 'BTC-USD',
    days: int = 1825,
    min_events: int = 50
) -> Dict:
    """Find the best predictive chains for an asset."""
    return await predictive_chain_finder.find_best_chains(
        ticker=ticker,
        days=days,
        min_events=min_events
    )


async def get_active_signals(ticker: str = 'BTC-USD') -> Dict:
    """Get currently active predictive signals."""
    return await predictive_chain_finder.get_active_signals(ticker=ticker)
