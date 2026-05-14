"""
Predictive Analysis Service
Finds predictive patterns between topics using spike detection and lag correlation.
"""
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime
import asyncio

from wikicorrelate.services.wikipedia import wikipedia_service
from wikicorrelate.services.spike_detector import (
    spike_detector, lag_correlator, pattern_validator,
    Spike, LagCorrelation, PredictivePattern
)
from wikicorrelate.services.correlate import CATEGORY_ARTICLES


async def find_predictive_signals(
    target_topic: str,
    candidate_topics: List[str],
    days: int = 730,
    min_correlation: float = 0.4,
    min_occurrences: int = 3,
    max_results: int = 20
) -> Dict:
    """
    Find topics that predict the target topic.

    Args:
        target_topic: The topic we want to predict
        candidate_topics: List of potential predictor topics
        days: Days of history to analyze
        min_correlation: Minimum correlation to consider
        min_occurrences: Minimum pattern occurrences for validation
        max_results: Maximum predictive signals to return

    Returns:
        Dict with target info and predictive signals
    """
    start_date, end_date = wikipedia_service.get_date_range(days)

    # Fetch target timeseries
    target_data = await wikipedia_service.get_pageviews(
        target_topic, start_date, end_date
    )

    if not target_data:
        return {
            "query": target_topic,
            "predictive_signals": [],
            "error": "Could not fetch target topic data"
        }

    target_values = np.array([p['views'] for p in target_data])

    # Detect spikes in target
    target_spikes = spike_detector.detect_spikes(target_data)

    # Fetch all candidate timeseries in parallel
    all_candidates = await wikipedia_service.get_pageviews_batch(
        candidate_topics, start_date, end_date
    )

    predictive_signals = []

    for candidate, cand_data in all_candidates.items():
        if len(cand_data) != len(target_data):
            continue

        cand_values = np.array([p['views'] for p in cand_data])

        # Find best lag correlation
        best_lag = lag_correlator.find_best_lag(
            cand_values, target_values, min_correlation
        )

        if not best_lag:
            continue

        # Only interested in predictive lags (candidate leads target)
        if best_lag.lag_days >= 0:
            continue  # Skip if candidate doesn't lead

        # Validate the pattern with historical spike analysis
        occurrences, confidence, spike_pairs = pattern_validator.validate_pattern(
            cand_data, target_data, best_lag.lag_days
        )

        if occurrences >= min_occurrences:
            # Generate human-readable description
            lag_abs = abs(best_lag.lag_days)
            description = (
                f"{candidate.replace('_', ' ')} spikes predict "
                f"{target_topic.replace('_', ' ')} spikes by {lag_abs} days"
            )

            predictive_signals.append({
                "predictor": candidate.replace("_", " "),
                "predictor_slug": candidate,
                "lag_days": best_lag.lag_days,
                "correlation": best_lag.correlation,
                "confidence": confidence,
                "occurrences": occurrences,
                "direction": best_lag.direction,
                "description": description,
                "p_value": best_lag.p_value,
                "spike_pairs": spike_pairs[:5]  # Limit to 5 examples
            })

    # Sort by confidence * correlation
    predictive_signals.sort(
        key=lambda x: x['confidence'] * abs(x['correlation']),
        reverse=True
    )

    return {
        "query": target_topic.replace("_", " "),
        "query_slug": target_topic,
        "days_analyzed": days,
        "target_spikes_found": len(target_spikes),
        "predictive_signals": predictive_signals[:max_results],
        "calculated_at": datetime.now().isoformat()
    }


async def find_predictive_signals_expanded(
    target_topic: str,
    days: int = 730,
    min_correlation: float = 0.4,
    min_occurrences: int = 3,
    max_results: int = 20
) -> Dict:
    """
    Find predictive signals using expanded candidate list from all categories.
    """
    # Get all articles from all categories
    all_candidates = []
    for category, articles in CATEGORY_ARTICLES.items():
        all_candidates.extend(articles)

    # Remove duplicates and the target itself
    all_candidates = list(set(all_candidates))
    target_normalized = target_topic.lower().replace(" ", "_")
    all_candidates = [a for a in all_candidates if a.lower() != target_normalized]

    return await find_predictive_signals(
        target_topic=target_topic,
        candidate_topics=all_candidates,
        days=days,
        min_correlation=min_correlation,
        min_occurrences=min_occurrences,
        max_results=max_results
    )


async def analyze_spike_timing(
    topic: str,
    days: int = 730
) -> Dict:
    """
    Analyze spike patterns for a single topic.

    Returns spike detection results and timing patterns.
    """
    start_date, end_date = wikipedia_service.get_date_range(days)
    data = await wikipedia_service.get_pageviews(topic, start_date, end_date)

    if not data:
        return {"error": "Could not fetch topic data"}

    spikes = spike_detector.detect_spikes(data)

    # Calculate spike statistics
    values = [p['views'] for p in data]
    mean_views = np.mean(values)
    std_views = np.std(values)

    # Analyze spike timing patterns
    spike_dates = [s.date for s in spikes]
    intervals = []
    if len(spike_dates) > 1:
        for i in range(1, len(spike_dates)):
            d1 = datetime.strptime(spike_dates[i-1], '%Y-%m-%d')
            d2 = datetime.strptime(spike_dates[i], '%Y-%m-%d')
            intervals.append((d2 - d1).days)

    avg_interval = np.mean(intervals) if intervals else None

    return {
        "topic": topic.replace("_", " "),
        "days_analyzed": days,
        "total_spikes": len(spikes),
        "mean_daily_views": round(mean_views, 0),
        "std_daily_views": round(std_views, 0),
        "spikes": [
            {
                "date": s.date,
                "value": s.value,
                "z_score": s.z_score,
                "magnitude": s.magnitude
            }
            for s in spikes
        ],
        "avg_days_between_spikes": round(avg_interval, 1) if avg_interval else None,
        "calculated_at": datetime.now().isoformat()
    }


async def compare_lag_patterns(
    topic_a: str,
    topic_b: str,
    days: int = 730
) -> Dict:
    """
    Compare two topics and find lead/lag relationships.
    """
    start_date, end_date = wikipedia_service.get_date_range(days)

    # Fetch both timeseries
    data_a = await wikipedia_service.get_pageviews(topic_a, start_date, end_date)
    data_b = await wikipedia_service.get_pageviews(topic_b, start_date, end_date)

    if not data_a or not data_b:
        return {"error": "Could not fetch data for one or both topics"}

    if len(data_a) != len(data_b):
        return {"error": "Timeseries length mismatch"}

    values_a = np.array([p['views'] for p in data_a])
    values_b = np.array([p['views'] for p in data_b])

    # Get all lag correlations
    all_lags = lag_correlator.find_lag_correlation(values_a, values_b)

    # Find best lag in each direction
    best_a_leads = None
    best_b_leads = None

    for lag in all_lags:
        if lag.lag_days < 0:  # A leads B
            if not best_a_leads or abs(lag.correlation) > abs(best_a_leads.correlation):
                best_a_leads = lag
        elif lag.lag_days > 0:  # B leads A
            if not best_b_leads or abs(lag.correlation) > abs(best_b_leads.correlation):
                best_b_leads = lag

    # Validate patterns
    validation_a = None
    validation_b = None

    if best_a_leads and abs(best_a_leads.correlation) >= 0.3:
        occ, conf, pairs = pattern_validator.validate_pattern(
            data_a, data_b, best_a_leads.lag_days
        )
        validation_a = {"occurrences": occ, "confidence": conf}

    if best_b_leads and abs(best_b_leads.correlation) >= 0.3:
        occ, conf, pairs = pattern_validator.validate_pattern(
            data_b, data_a, -best_b_leads.lag_days
        )
        validation_b = {"occurrences": occ, "confidence": conf}

    return {
        "topic_a": topic_a.replace("_", " "),
        "topic_b": topic_b.replace("_", " "),
        "days_analyzed": days,
        "a_leads_b": {
            "best_lag_days": best_a_leads.lag_days if best_a_leads else None,
            "correlation": best_a_leads.correlation if best_a_leads else None,
            "validation": validation_a
        } if best_a_leads else None,
        "b_leads_a": {
            "best_lag_days": best_b_leads.lag_days if best_b_leads else None,
            "correlation": best_b_leads.correlation if best_b_leads else None,
            "validation": validation_b
        } if best_b_leads else None,
        "lag_correlations": [
            {"lag": lc.lag_days, "correlation": lc.correlation}
            for lc in all_lags
        ],
        "calculated_at": datetime.now().isoformat()
    }
