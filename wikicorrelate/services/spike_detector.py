"""
Spike Detection Service
Detects unusual spikes in time series data and finds lag correlations.
"""
import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import correlate
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass


@dataclass
class Spike:
    """Represents a detected spike in a time series"""
    date: str
    value: int
    z_score: float
    magnitude: float  # How many times above normal


@dataclass
class LagCorrelation:
    """Represents a lag correlation between two series"""
    lag_days: int  # Negative = predictor leads, Positive = predictor follows
    correlation: float
    p_value: float
    direction: str  # "predictor_leads" or "predictor_follows"


@dataclass
class PredictivePattern:
    """A validated predictive pattern"""
    predictor: str
    target: str
    lag_days: int
    correlation: float
    confidence: float
    occurrences: int
    direction: str
    description: str
    spike_pairs: List[Dict]  # Historical spike pairs that match


class SpikeDetector:
    """
    Detects spikes in time series using multiple methods.
    """

    def __init__(
        self,
        z_threshold: float = 2.0,
        window_size: int = 30,
        min_spike_ratio: float = 1.5
    ):
        """
        Args:
            z_threshold: Z-score threshold for spike detection (default 2.0 = 2 std devs)
            window_size: Rolling window for baseline calculation
            min_spike_ratio: Minimum ratio above moving average to count as spike
        """
        self.z_threshold = z_threshold
        self.window_size = window_size
        self.min_spike_ratio = min_spike_ratio

    def detect_spikes_zscore(self, values: np.ndarray, dates: List[str]) -> List[Spike]:
        """
        Detect spikes using Z-score method.

        A spike is when the value is more than z_threshold standard deviations
        above the mean.
        """
        if len(values) < 10:
            return []

        mean = np.mean(values)
        std = np.std(values)

        if std == 0:
            return []

        z_scores = (values - mean) / std
        spikes = []

        for i, (z, val, date) in enumerate(zip(z_scores, values, dates)):
            if z > self.z_threshold:
                spikes.append(Spike(
                    date=date,
                    value=int(val),
                    z_score=round(float(z), 2),
                    magnitude=round(float(val / mean), 2)
                ))

        return spikes

    def detect_spikes_rolling(self, values: np.ndarray, dates: List[str]) -> List[Spike]:
        """
        Detect spikes using rolling average method.

        A spike is when the value is significantly above the rolling average.
        More robust to trends than global Z-score.
        """
        if len(values) < self.window_size * 2:
            return []

        series = pd.Series(values)
        rolling_mean = series.rolling(window=self.window_size, center=True).mean()
        rolling_std = series.rolling(window=self.window_size, center=True).std()

        # Fill NaN values at edges
        rolling_mean = rolling_mean.bfill().ffill()
        rolling_std = rolling_std.bfill().ffill()

        spikes = []

        for i in range(len(values)):
            if rolling_std.iloc[i] == 0:
                continue

            local_z = (values[i] - rolling_mean.iloc[i]) / rolling_std.iloc[i]
            ratio = values[i] / rolling_mean.iloc[i] if rolling_mean.iloc[i] > 0 else 1

            if local_z > self.z_threshold and ratio > self.min_spike_ratio:
                spikes.append(Spike(
                    date=dates[i],
                    value=int(values[i]),
                    z_score=round(float(local_z), 2),
                    magnitude=round(float(ratio), 2)
                ))

        return spikes

    def detect_spikes(
        self,
        timeseries: List[Dict],
        method: str = "rolling"
    ) -> List[Spike]:
        """
        Main spike detection method.

        Args:
            timeseries: List of {"date": "YYYY-MM-DD", "views": int}
            method: "zscore" or "rolling"

        Returns:
            List of detected spikes
        """
        if not timeseries:
            return []

        dates = [p['date'] for p in timeseries]
        values = np.array([p['views'] for p in timeseries], dtype=float)

        if method == "zscore":
            return self.detect_spikes_zscore(values, dates)
        else:
            return self.detect_spikes_rolling(values, dates)


class LagCorrelator:
    """
    Finds lag correlations between two time series.
    Determines if one series predicts another with a time delay.
    """

    def __init__(self, max_lag: int = 30):
        """
        Args:
            max_lag: Maximum lag in days to check (both directions)
        """
        self.max_lag = max_lag

    def find_lag_correlation(
        self,
        series_a: np.ndarray,
        series_b: np.ndarray,
        normalize: bool = True
    ) -> List[LagCorrelation]:
        """
        Find correlation at different lags between two series.

        Args:
            series_a: First time series (potential predictor)
            series_b: Second time series (potential target)
            normalize: Whether to normalize the correlation

        Returns:
            List of LagCorrelation for each tested lag
        """
        if len(series_a) != len(series_b):
            return []

        n = len(series_a)
        if n < self.max_lag * 2:
            return []

        results = []

        # Normalize series
        if normalize:
            series_a = (series_a - np.mean(series_a)) / (np.std(series_a) + 1e-10)
            series_b = (series_b - np.mean(series_b)) / (np.std(series_b) + 1e-10)

        # Test different lags
        for lag in range(-self.max_lag, self.max_lag + 1):
            if lag < 0:
                # series_a leads series_b by |lag| days
                a_slice = series_a[:lag]  # Earlier part of A
                b_slice = series_b[-lag:]  # Later part of B
            elif lag > 0:
                # series_b leads series_a by lag days
                a_slice = series_a[lag:]
                b_slice = series_b[:-lag]
            else:
                a_slice = series_a
                b_slice = series_b

            if len(a_slice) < 30:
                continue

            # Calculate Pearson correlation
            try:
                corr, p_value = stats.pearsonr(a_slice, b_slice)

                direction = "predictor_leads" if lag < 0 else (
                    "predictor_follows" if lag > 0 else "simultaneous"
                )

                results.append(LagCorrelation(
                    lag_days=lag,
                    correlation=round(float(corr), 4),
                    p_value=round(float(p_value), 6),
                    direction=direction
                ))
            except Exception:
                continue

        return results

    def find_best_lag(
        self,
        series_a: np.ndarray,
        series_b: np.ndarray,
        min_correlation: float = 0.3
    ) -> Optional[LagCorrelation]:
        """
        Find the lag with the highest correlation.

        Args:
            series_a: Potential predictor series
            series_b: Target series
            min_correlation: Minimum correlation to consider

        Returns:
            Best LagCorrelation or None if none meet threshold
        """
        all_lags = self.find_lag_correlation(series_a, series_b)

        if not all_lags:
            return None

        # Find best by absolute correlation
        best = max(all_lags, key=lambda x: abs(x.correlation))

        if abs(best.correlation) >= min_correlation:
            return best

        return None


class PatternValidator:
    """
    Validates predictive patterns by checking historical occurrences.
    """

    def __init__(
        self,
        spike_detector: SpikeDetector,
        min_occurrences: int = 3,
        lag_tolerance: int = 3
    ):
        """
        Args:
            spike_detector: SpikeDetector instance
            min_occurrences: Minimum times pattern must occur for validation
            lag_tolerance: Days tolerance for matching spike pairs
        """
        self.spike_detector = spike_detector
        self.min_occurrences = min_occurrences
        self.lag_tolerance = lag_tolerance

    def validate_pattern(
        self,
        predictor_timeseries: List[Dict],
        target_timeseries: List[Dict],
        expected_lag: int
    ) -> Tuple[int, float, List[Dict]]:
        """
        Validate a predictive pattern by finding historical spike pairs.

        Args:
            predictor_timeseries: Time series of predictor
            target_timeseries: Time series of target
            expected_lag: Expected lag in days (negative = predictor leads)

        Returns:
            Tuple of (occurrences, confidence, spike_pairs)
        """
        # Detect spikes in both series
        predictor_spikes = self.spike_detector.detect_spikes(predictor_timeseries)
        target_spikes = self.spike_detector.detect_spikes(target_timeseries)

        if not predictor_spikes or not target_spikes:
            return 0, 0.0, []

        # Convert dates to datetime for comparison
        def to_datetime(date_str):
            return datetime.strptime(date_str, '%Y-%m-%d')

        matched_pairs = []

        for p_spike in predictor_spikes:
            p_date = to_datetime(p_spike.date)
            expected_target_date = p_date + timedelta(days=abs(expected_lag))

            # Find matching target spike within tolerance
            for t_spike in target_spikes:
                t_date = to_datetime(t_spike.date)
                day_diff = abs((t_date - expected_target_date).days)

                if day_diff <= self.lag_tolerance:
                    matched_pairs.append({
                        'predictor_date': p_spike.date,
                        'predictor_value': p_spike.value,
                        'predictor_z': p_spike.z_score,
                        'target_date': t_spike.date,
                        'target_value': t_spike.value,
                        'target_z': t_spike.z_score,
                        'actual_lag': (t_date - p_date).days
                    })
                    break  # Only count first match per predictor spike

        occurrences = len(matched_pairs)

        # Calculate confidence based on:
        # - Number of occurrences vs total predictor spikes
        # - Consistency of lag timing
        if occurrences >= self.min_occurrences:
            hit_rate = occurrences / len(predictor_spikes)
            confidence = min(hit_rate * 1.2, 1.0)  # Slight boost, cap at 1.0
        else:
            confidence = occurrences / self.min_occurrences * 0.5  # Low confidence

        return occurrences, round(confidence, 2), matched_pairs


# Singleton instances with default config
spike_detector = SpikeDetector(z_threshold=2.0, window_size=30)
lag_correlator = LagCorrelator(max_lag=30)
pattern_validator = PatternValidator(spike_detector, min_occurrences=3)
