"""
Correlation Service - Unified from POC scripts
Includes: correlateA.py, correlateB.py, wide_correlate.py, google_correlate.py, find_weird_correlations.py

Features:
- Pearson correlation
- Cosine similarity (NearestNeighbors)
- Detrend + Deseasonalization
- Wide category search
- Surprising correlation detection

Optimized with parallel pageview fetching via central http_client.
All Wikipedia API calls use connection pooling and HTTP/2 multiplexing.
"""
import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from scipy import signal
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics.pairwise import cosine_similarity
from statsmodels.tsa.stattools import grangercausalitytests
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
import warnings
warnings.filterwarnings('ignore')

from wikicorrelate.services.wikipedia import wikipedia_service
from wikicorrelate.config import MIN_CORRELATION_THRESHOLD, MAX_RESULTS


# =============================================================================
# WIDE CATEGORIES - From wide_correlate.py
# These provide broad coverage for finding non-obvious correlations
# =============================================================================

WIDE_CATEGORIES = {
    'economics': [
        'Inflation', 'Deflation', 'Recession', 'Economic_bubble',
        'Financial_crisis', 'Great_Recession', 'Hyperinflation',
        'Monetary_policy', 'Fiscal_policy', 'Quantitative_easing',
        'Interest_rate', 'Federal_funds_rate', 'Money_supply',
        'Economic_growth', 'Gross_domestic_product', 'Unemployment',
        'Consumer_price_index', 'Economic_indicator', 'Trade_war',
        'Tariff', 'Stagflation', 'Austerity'
    ],
    'finance': [
        'Stock_market', 'Stock_market_crash', 'Bond_(finance)',
        'Federal_Reserve', 'Central_bank', 'Bank', 'Investment_banking',
        'Venture_capital', 'Private_equity', 'Hedge_fund',
        'S&P_500', 'Dow_Jones_Industrial_Average', 'NASDAQ',
        'Wall_Street', 'New_York_Stock_Exchange',
        'Market_liquidity', 'Volatility_(finance)', 'Risk_management',
        'Derivatives_market', 'Short_selling', 'Margin_trading'
    ],
    'currency': [
        'Currency', 'Fiat_money', 'Foreign_exchange_market',
        'United_States_dollar', 'Euro', 'Japanese_yen', 'British_pound',
        'Swiss_franc', 'Chinese_yuan', 'Currency_crisis', 'Exchange_rate',
        'Monetary_system', 'Gold_standard', 'Bretton_Woods_system',
        'International_Monetary_Fund', 'World_Bank', 'Currency_war'
    ],
    'commodities': [
        'Gold', 'Silver', 'Petroleum', 'Natural_gas', 'Copper',
        'Commodity_market', 'Gold_as_an_investment', 'Platinum',
        'Price_of_oil', 'Energy_crisis', 'OPEC', 'Crude_oil',
        'Brent_Crude', 'West_Texas_Intermediate', 'Oil_reserves'
    ],
    'crypto': [
        'Bitcoin', 'Cryptocurrency', 'Blockchain', 'Ethereum',
        'Tether_(cryptocurrency)', 'Binance', 'Coinbase', 'Crypto_exchange',
        'Smart_contract', 'Decentralized_finance', 'NFT', 'Web3',
        'Satoshi_Nakamoto', 'Cryptography', 'Digital_currency',
        'Dogecoin', 'Litecoin', 'Ripple_(payment_protocol)',
        'Mining_(cryptocurrency)', 'Cryptocurrency_wallet'
    ],
    'technology': [
        'Artificial_intelligence', 'Machine_learning', 'ChatGPT', 'OpenAI',
        'Google', 'Microsoft', 'Apple_Inc.', 'Meta_Platforms', 'Nvidia',
        'Tesla,_Inc.', 'Cloud_computing', 'Quantum_computing', '5G',
        'Smartphone', 'Social_media', 'Cybersecurity', 'Data_science',
        'Deep_learning', 'Neural_network', 'GPT-4', 'Large_language_model',
        'Amazon_(company)', 'Intel', 'AMD', 'Twitter', 'TikTok',
        'Information_technology', 'Internet', 'World_Wide_Web',
        'Dot-com_bubble', 'Silicon_Valley', 'Startup_company',
        'Initial_public_offering', 'Big_data'
    ],
    'events': [
        '2008_financial_crisis', '2020_stock_market_crash',
        'COVID-19_pandemic', 'September_11_attacks',
        'Bankruptcy_of_Lehman_Brothers', 'Black_Monday_(1987)',
        'Asian_financial_crisis', 'European_debt_crisis',
        'Subprime_mortgage_crisis', 'GameStop_short_squeeze',
        'Brexit', 'Russian_invasion_of_Ukraine', 'FTX_collapse'
    ],
    'regulation': [
        'Financial_regulation', 'Securities_and_Exchange_Commission',
        'Bank_regulation', 'Anti-money_laundering',
        'Know_your_customer', 'Financial_Action_Task_Force',
        'Basel_III', 'Dodd–Frank_Wall_Street_Reform',
        'Sarbanes–Oxley_Act', 'Glass–Steagall_legislation'
    ],
    'geopolitics': [
        'Donald_Trump', 'Joe_Biden', 'Vladimir_Putin', 'Xi_Jinping',
        'United_States', 'China', 'Russia', 'European_Union',
        'NATO', 'G7', 'G20', 'United_Nations', 'Trade_war',
        'Sanctions', 'Geopolitics', 'Cold_War', 'Nuclear_proliferation'
    ],
    'energy': [
        'Petroleum', 'Natural_gas', 'OPEC', 'Solar_energy',
        'Wind_power', 'Nuclear_power', 'Electric_vehicle',
        'Renewable_energy', 'Climate_change', 'Carbon_dioxide',
        'Electricity', 'Coal', 'Gasoline', 'Oil_refinery',
        'Energy_transition', 'Green_energy', 'Fracking'
    ],
    'history': [
        'World_War_I', 'World_War_II', 'Cold_War', 'Roman_Empire',
        'Byzantine_Empire', 'Ottoman_Empire', 'British_Empire', 'Mongol_Empire',
        'Crusades', 'Renaissance', 'Industrial_Revolution', 'French_Revolution',
        'American_Revolution', 'Napoleon', 'Julius_Caesar', 'Alexander_the_Great',
        'Ancient_Egypt', 'Ancient_Greece', 'Ancient_Rome', 'Middle_Ages',
        'Medieval', 'Knight', 'Feudalism', 'Castle', 'Teutonic_Order',
        'Knights_Templar', 'Holy_Roman_Empire', 'Prussia', 'Vikings'
    ],
    'military': [
        'Teutonic_Order', 'Knights_Templar', 'Crusades', 'Prussia',
        'Holy_Roman_Empire', 'Sword', 'Shield', 'Cavalry', 'Infantry',
        'Battle', 'War', 'Army', 'Navy', 'Military_history',
        'Siege', 'Fortification', 'Medieval_warfare', 'Nuclear_weapon',
        'Tank', 'Aircraft_carrier', 'Fighter_aircraft', 'Missile',
        'Special_forces', 'Guerrilla_warfare', 'Submarine'
    ],
    'geography': [
        'Europe', 'Asia', 'Africa', 'North_America', 'South_America',
        'Germany', 'France', 'United_Kingdom', 'Russia', 'China',
        'Japan', 'India', 'Brazil', 'Australia', 'Canada',
        'Poland', 'Baltic_states', 'Scandinavia', 'Mediterranean_Sea',
        'Middle_East', 'Southeast_Asia', 'Latin_America'
    ],
    'entertainment': [
        'Netflix', 'Disney+', 'Spotify', 'YouTube', 'TikTok',
        'Video_game', 'Streaming_media', 'Film_industry',
        'Television', 'Music_industry', 'Hollywood', 'Gaming_industry',
        'Esports', 'Box_office', 'Movie_theater'
    ],
    'health': [
        'COVID-19', 'Vaccine', 'Mental_health', 'Depression_(mood)',
        'Obesity', 'Diabetes', 'Cancer', 'Heart_disease',
        'Exercise', 'Diet_(nutrition)', 'Sleep', 'Anxiety',
        'Pandemic', 'World_Health_Organization', 'Pharmaceutical_industry'
    ],
    'sports': [
        'NFL', 'NBA', 'FIFA_World_Cup', 'Olympic_Games',
        'Super_Bowl', 'Football', 'Basketball', 'Soccer',
        'Tennis', 'Golf', 'Formula_One', 'MLB', 'NHL',
        'UEFA_Champions_League', 'Premier_League'
    ],
    'science': [
        'Climate_change', 'Evolution', 'Black_hole', 'Mars',
        'NASA', 'SpaceX', 'Genetics', 'Quantum_mechanics',
        'Archaeology', 'Dinosaur', 'Earthquake', 'Hurricane',
        'Astronomy', 'Physics', 'Chemistry', 'Biology'
    ],
    'food': [
        'Coffee', 'Beer', 'Wine', 'Chocolate', 'Pizza',
        'Vegetarianism', 'Organic_food', 'Fast_food',
        'Restaurant', 'Cooking', 'Diet_(nutrition)',
        'Sugar', 'Wheat', 'Corn', 'Soybean'
    ],
    'culture': [
        'Religion', 'Christianity', 'Islam', 'Buddhism',
        'Atheism', 'Marriage', 'Divorce', 'Fashion',
        'Art', 'Music', 'Literature', 'Philosophy',
        'Social_movement', 'Feminism', 'Environmentalism'
    ]
}

# Alias for backwards compatibility
CATEGORY_ARTICLES = WIDE_CATEGORIES


def calculate_trend(timeseries: List[Dict]) -> str:
    """
    Calculate trend direction from timeseries data

    Args:
        timeseries: List of dicts with 'views' key

    Returns:
        "up", "down", or "stable"
    """
    if len(timeseries) < 14:
        return "stable"

    # Compare last 7 days average to previous 7 days
    recent = [p['views'] for p in timeseries[-7:]]
    previous = [p['views'] for p in timeseries[-14:-7]]

    recent_avg = np.mean(recent)
    previous_avg = np.mean(previous)

    if recent_avg > previous_avg * 1.1:  # 10% increase
        return "up"
    elif recent_avg < previous_avg * 0.9:  # 10% decrease
        return "down"
    else:
        return "stable"


def detrend_series(series: np.ndarray) -> np.ndarray:
    """
    Remove linear trend from time series

    Args:
        series: NumPy array of values

    Returns:
        Detrended array
    """
    try:
        detrended = signal.detrend(series, type='linear')
        return detrended
    except Exception:
        return series


def detrend_and_deseasonalize(series: np.ndarray, window: int = 7) -> np.ndarray:
    """
    Remove both trend AND seasonality from time series.
    From google_correlate.py - more robust for correlation calculation.

    Args:
        series: NumPy array of values
        window: Moving average window (default 7 days for weekly seasonality)

    Returns:
        Detrended and deseasonalized array
    """
    try:
        # Step 1: Remove linear trend
        detrended = signal.detrend(series, type='linear')

        # Step 2: Remove seasonality using moving average
        series_pd = pd.Series(detrended)
        moving_avg = series_pd.rolling(window=window, center=True).mean()

        # Fill NaN at edges
        moving_avg = moving_avg.bfill().ffill()

        # Subtract seasonal component
        deseasonalized = detrended - moving_avg.values

        return deseasonalized
    except Exception:
        return series


def calculate_cosine_similarity(series_a: np.ndarray, series_b: np.ndarray) -> float:
    """
    Calculate cosine similarity between two time series.
    From correlateB.py - alternative to Pearson correlation.

    Args:
        series_a: First time series
        series_b: Second time series

    Returns:
        Cosine similarity score (-1 to 1)
    """
    try:
        if len(series_a) != len(series_b):
            return 0.0

        # Reshape for sklearn
        a = series_a.reshape(1, -1)
        b = series_b.reshape(1, -1)

        similarity = cosine_similarity(a, b)[0][0]
        return float(similarity)
    except Exception:
        return 0.0


def calculate_correlation(
    base_values: np.ndarray,
    candidate_values: np.ndarray,
    detrend: bool = False,
    deseasonalize: bool = False,
    method: str = 'pearson'
) -> tuple:
    """
    Calculate correlation between two time series.

    Args:
        base_values: NumPy array of base article pageviews
        candidate_values: NumPy array of candidate article pageviews
        detrend: Whether to detrend before calculating correlation
        deseasonalize: Whether to remove seasonality (implies detrend)
        method: 'pearson' or 'cosine'

    Returns:
        Tuple of (correlation, p_value) - p_value is None for cosine
    """
    from scipy.stats import spearmanr

    if len(base_values) != len(candidate_values):
        return (0.0, 1.0)

    if len(base_values) < 7:
        return (0.0, 1.0)

    try:
        # Preprocessing
        if deseasonalize:
            base_values = detrend_and_deseasonalize(base_values)
            candidate_values = detrend_and_deseasonalize(candidate_values)
        elif detrend:
            base_values = detrend_series(base_values)
            candidate_values = detrend_series(candidate_values)

        # Check variance - use Spearman for low variance data
        base_std = np.std(base_values)
        cand_std = np.std(candidate_values)
        use_spearman = base_std < 1.0 or cand_std < 1.0

        # Calculate based on method
        if method == 'cosine':
            similarity = calculate_cosine_similarity(base_values, candidate_values)
            return (float(similarity), None)
        elif use_spearman:
            # Spearman is more robust for low-variance/ordinal data
            corr, p_value = spearmanr(base_values, candidate_values)
            if np.isnan(corr):
                return (0.0, 1.0)
            return (float(corr), float(p_value))
        else:  # pearson (default)
            corr, p_value = pearsonr(base_values, candidate_values)
            if np.isnan(corr):
                return (0.0, 1.0)
            return (float(corr), float(p_value))
    except Exception as e:
        print(f"Correlation error: {e}")
        return (0.0, 1.0)


async def find_correlations(
    base_article: str,
    candidate_articles: List[str],
    days: int = 365,
    threshold: float = MIN_CORRELATION_THRESHOLD,
    max_results: int = MAX_RESULTS,
    detrend: bool = False,
    deseasonalize: bool = False,
    method: str = 'pearson'
) -> Dict:
    """
    Find correlations between a base article and candidate articles.

    Args:
        base_article: The article to correlate against
        candidate_articles: List of articles to test
        days: Number of days to look back
        threshold: Minimum correlation score (absolute value)
        max_results: Maximum number of results to return
        detrend: Whether to detrend before calculating
        deseasonalize: Whether to remove seasonality (implies detrend)
        method: 'pearson' or 'cosine'

    Returns:
        Dict with query info and correlations list
    """
    start_date, end_date = wikipedia_service.get_date_range(days)

    # Fetch base article pageviews
    base_views = await wikipedia_service.get_pageviews(base_article, start_date, end_date)

    if not base_views:
        return {
            "query": base_article,
            "query_timeseries": [],
            "correlations": [],
            "cached": False,
            "calculated_at": datetime.now().isoformat()
        }

    base_values = np.array([p['views'] for p in base_views])

    # Fetch candidate articles in parallel
    all_candidates = await wikipedia_service.get_pageviews_batch(
        candidate_articles,
        start_date,
        end_date
    )

    correlations = []

    for article, views in all_candidates.items():
        if len(views) != len(base_views):
            continue

        candidate_values = np.array([p['views'] for p in views])
        corr, p_value = calculate_correlation(
            base_values,
            candidate_values,
            detrend=detrend,
            deseasonalize=deseasonalize,
            method=method
        )

        if abs(corr) >= threshold:
            avg_views = float(np.mean(candidate_values))
            trend = calculate_trend(views)
            category = get_article_category(article)

            correlations.append({
                "title": article.replace("_", " "),
                "score": round(corr, 4),
                "p_value": round(p_value, 6) if p_value is not None else None,
                "avg_daily_views": round(avg_views, 0),
                "trend": trend,
                "category": category,
                "method": method,
                "description": None,
                "timeseries": views
            })

    # Sort by absolute correlation score
    correlations.sort(key=lambda x: abs(x['score']), reverse=True)

    return {
        "query": base_article.replace("_", " "),
        "query_timeseries": base_views,
        "correlations": correlations[:max_results],
        "method": method,
        "detrend": detrend,
        "deseasonalize": deseasonalize,
        "cached": False,
        "calculated_at": datetime.now().isoformat()
    }


async def search_and_correlate(
    query: str,
    days: int = 365,
    max_candidates: int = 1000,  # Increased for broader search with cache
    threshold: float = 0.1,  # Lower default for more results
    max_results: int = 50,
    use_expander: bool = True,
    detrend: bool = False,
    deseasonalize: bool = False,
    method: str = 'pearson',
    categories: List[str] = None
) -> Dict:
    """
    Full search and correlation workflow.
    Unified from google_correlate.py and wide_correlate.py.

    1. Find Wikipedia article matching query
    2. Get candidates from Wikipedia + Wide Categories + Search Engine
    3. Calculate correlations (Pearson or Cosine)
    4. Return results

    Args:
        query: User search query
        days: Days to look back
        max_candidates: Max candidate articles to test
        threshold: Min correlation threshold
        max_results: Max results to return
        use_expander: Use search engine to find more candidates
        detrend: Remove linear trend before correlation
        deseasonalize: Remove trend AND seasonality
        method: 'pearson' or 'cosine'
        categories: Specific categories to search (None = all)

    Returns:
        Full correlation results dict
    """
    # Step 1: Find the Wikipedia article
    search_results = await wikipedia_service.search_articles(query, limit=1)

    if not search_results:
        return {
            "query": query,
            "query_timeseries": [],
            "correlations": [],
            "cached": False,
            "calculated_at": datetime.now().isoformat(),
            "error": "No Wikipedia article found for this query"
        }

    base_article = search_results[0]

    # Step 2: Collect candidates from multiple sources
    candidates = set()

    # 2a. Wikipedia related articles
    related = await wikipedia_service.get_related_articles(
        base_article,
        limit=50
    )
    candidates.update(related)

    # 2b. Add category articles (all or specified)
    categories_to_use = categories if categories else list(WIDE_CATEGORIES.keys())
    for category in categories_to_use:
        if category in WIDE_CATEGORIES:
            candidates.update(WIDE_CATEGORIES[category])

    # 2c. Add cached top articles for broader coverage
    try:
        from wikicorrelate.services.article_cache import article_cache
        top_articles = await article_cache.get_top_articles(limit=1000)
        candidates.update(top_articles)
        print(f"[search_and_correlate] Added {len(top_articles)} from cache")
    except Exception as e:
        print(f"Cache load error: {e}")

    # 2d. Use search engine expansion for even more candidates
    if use_expander:
        try:
            from wikicorrelate.services.topic_expander import topic_expander
            expanded = await topic_expander.expand_topic(query, expansion_depth=2)
            candidates.update(expanded[:50])
        except Exception as e:
            print(f"Topic expansion error: {e}")

    # 2d. Fallback Wikipedia searches
    fallback_searches = [
        f"{query} related",
        f"{query} history",
        f"{query} effect",
        f"{query} similar",
        f"{query} comparison"
    ]
    for fallback_query in fallback_searches:
        try:
            fallback_results = await wikipedia_service.search_articles(fallback_query, limit=10)
            candidates.update(fallback_results)
        except Exception:
            pass

    # Remove the base article itself
    candidates.discard(base_article)
    candidates.discard(query)
    candidates.discard(query.replace(" ", "_"))

    # Limit candidates
    candidates_list = list(candidates)[:max_candidates]

    print(f"[search_and_correlate] Testing {len(candidates_list)} candidates for '{query}'")

    # Step 3: Calculate correlations
    results = await find_correlations(
        base_article=base_article,
        candidate_articles=candidates_list,
        days=days,
        threshold=threshold,
        max_results=max_results,
        detrend=detrend,
        deseasonalize=deseasonalize,
        method=method
    )

    results['candidates_tested'] = len(candidates_list)
    results['categories_searched'] = categories_to_use

    return results


async def wide_search_correlations(
    query: str,
    days: int = 365,
    categories: List[str] = None,
    max_per_category: int = None,
    detrend: bool = True,
    deseasonalize: bool = False,
    threshold: float = 0.1,
    max_results: int = 50,
    method: str = 'pearson'
) -> Dict:
    """
    WIDE CORRELATION SEARCH - From wide_correlate.py

    Searches across all predefined categories for non-obvious correlations.
    Uses detrend by default for more robust results.

    Args:
        query: Search query
        days: Days of history
        categories: Which categories to search (None = all)
        max_per_category: Limit articles per category
        detrend: Remove linear trend (default True)
        deseasonalize: Remove seasonality too
        threshold: Min correlation (default 0.15 for wide search)
        max_results: Max results
        method: 'pearson' or 'cosine'

    Returns:
        Dict with correlations grouped by category
    """
    # Find Wikipedia article
    search_results = await wikipedia_service.search_articles(query, limit=1)

    if not search_results:
        return {
            "query": query,
            "correlations": [],
            "error": "No Wikipedia article found"
        }

    base_article = search_results[0]

    # Get candidates from wide categories
    candidates = set()
    categories_to_use = categories if categories else list(WIDE_CATEGORIES.keys())

    for category in categories_to_use:
        if category in WIDE_CATEGORIES:
            articles = WIDE_CATEGORIES[category]
            if max_per_category:
                articles = articles[:max_per_category]
            candidates.update(articles)

    # Add cached top articles for broader coverage
    try:
        from wikicorrelate.services.article_cache import article_cache
        top_articles = await article_cache.get_top_articles(limit=1000)
        candidates.update(top_articles)
        print(f"[wide_search] Added {len(top_articles)} from cache")
    except Exception as e:
        print(f"Cache load error: {e}")

    # Remove self
    base_normalized = base_article.lower().replace(" ", "_")
    candidates = [c for c in candidates if c.lower() != base_normalized]

    print(f"[wide_search] {len(candidates)} total candidates")

    # Calculate correlations
    results = await find_correlations(
        base_article=base_article,
        candidate_articles=candidates,
        days=days,
        threshold=threshold,
        max_results=max_results,
        detrend=detrend,
        deseasonalize=deseasonalize,
        method=method
    )

    # Group results by category
    by_category = {}
    for corr in results.get('correlations', []):
        cat = corr.get('category') or 'other'
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(corr)

    results['by_category'] = by_category
    results['categories_searched'] = categories_to_use
    results['mode'] = 'wide'

    return results


# Articles that are obviously related (to filter for surprising correlations)
OBVIOUS_PAIRS = {
    'Bitcoin': {'Cryptocurrency', 'Blockchain', 'Ethereum', 'Digital_currency'},
    'Tesla,_Inc.': {'Electric_vehicle', 'Elon_Musk', 'SpaceX'},
    'Climate_change': {'Global_warming', 'Carbon_dioxide', 'Renewable_energy'},
    'COVID-19': {'Vaccine', 'Pandemic', 'Coronavirus'},
    'Stock_market': {'S&P_500', 'NASDAQ', 'Dow_Jones'},
}


async def get_category_correlations(
    base_article: str,
    category: str,
    days: int = 365,
    threshold: float = 0.3,
    detrend: bool = False,
    deseasonalize: bool = False,
    method: str = 'pearson'
) -> Dict:
    """
    Get correlations with a predefined category of articles

    Args:
        base_article: Article to correlate
        category: One of the WIDE_CATEGORIES keys
        days: Days to look back
        threshold: Min correlation
        detrend: Remove linear trend
        deseasonalize: Remove seasonality
        method: 'pearson' or 'cosine'

    Returns:
        Correlation results
    """
    candidates = WIDE_CATEGORIES.get(category, WIDE_CATEGORIES['technology'])

    return await find_correlations(
        base_article=base_article,
        candidate_articles=candidates,
        days=days,
        threshold=threshold,
        detrend=detrend,
        deseasonalize=deseasonalize,
        method=method
    )


def get_article_category(article: str) -> Optional[str]:
    """Find which category an article belongs to"""
    article_lower = article.lower().replace("_", " ").replace("-", " ")
    for category, articles in WIDE_CATEGORIES.items():
        for a in articles:
            if a.lower().replace("_", " ").replace("-", " ") == article_lower:
                return category
    return None


def get_all_wide_candidates() -> List[str]:
    """Get all articles from all wide categories (deduplicated)"""
    all_articles = []
    for articles in WIDE_CATEGORIES.values():
        all_articles.extend(articles)
    return list(set(all_articles))


def is_obvious_pair(article_a: str, article_b: str) -> bool:
    """Check if two articles are obviously related"""
    a_lower = article_a.lower().replace(" ", "_")
    b_lower = article_b.lower().replace(" ", "_")

    # Check direct obvious pairs
    for key, related in OBVIOUS_PAIRS.items():
        key_lower = key.lower()
        related_lower = {r.lower() for r in related}
        if a_lower == key_lower and b_lower in related_lower:
            return True
        if b_lower == key_lower and a_lower in related_lower:
            return True

    # Check if in same category
    cat_a = get_article_category(article_a)
    cat_b = get_article_category(article_b)
    if cat_a and cat_b and cat_a == cat_b:
        return True

    return False


def calculate_surprise_score(article_a: str, article_b: str, correlation: float) -> float:
    """
    Calculate how surprising a correlation is.
    Higher score = more surprising.

    Factors:
    - Different categories = more surprising
    - Not in obvious pairs = more surprising
    - High correlation for unrelated topics = more surprising
    """
    base_score = abs(correlation)

    # Penalty for obvious pairs
    if is_obvious_pair(article_a, article_b):
        return base_score * 0.1  # Heavy penalty

    # Bonus for different categories
    cat_a = get_article_category(article_a)
    cat_b = get_article_category(article_b)

    if cat_a and cat_b and cat_a != cat_b:
        base_score *= 1.5  # Bonus for cross-category

    return min(base_score, 1.0)


async def find_surprising_correlations(
    base_article: str,
    days: int = 365,
    threshold: float = 0.4,
    max_results: int = 20,
    detrend: bool = True,
    deseasonalize: bool = False,
    method: str = 'pearson'
) -> Dict:
    """
    Find surprising/unexpected correlations.
    From find_weird_correlations.py - searches for non-obvious correlations.

    Searches across ALL categories and ranks by surprise score.
    """
    # Get all articles from all categories (excluding the base article's category)
    base_category = get_article_category(base_article)

    all_candidates = []
    for category, articles in WIDE_CATEGORIES.items():
        if category != base_category:  # Skip same category
            all_candidates.extend(articles)

    # Remove duplicates and the base article itself
    all_candidates = list(set(all_candidates))
    base_normalized = base_article.lower().replace(" ", "_")
    all_candidates = [a for a in all_candidates if a.lower() != base_normalized]

    print(f"[find_surprising] Testing {len(all_candidates)} candidates for '{base_article}'")

    # Get correlations
    results = await find_correlations(
        base_article=base_article,
        candidate_articles=all_candidates,
        days=days,
        threshold=threshold,
        max_results=100,  # Get more, then filter by surprise
        detrend=detrend,
        deseasonalize=deseasonalize,
        method=method
    )

    # Calculate surprise scores and filter
    surprising = []
    for corr in results.get('correlations', []):
        if not is_obvious_pair(base_article, corr['title']):
            surprise = calculate_surprise_score(
                base_article,
                corr['title'],
                corr['score']
            )
            corr['surprise_score'] = round(surprise, 3)
            surprising.append(corr)

    # Sort by surprise score
    surprising.sort(key=lambda x: x['surprise_score'], reverse=True)

    results['correlations'] = surprising[:max_results]
    results['mode'] = 'surprising'

    return results


async def find_negative_correlations(
    base_article: str,
    days: int = 365,
    threshold: float = -0.3,
    max_results: int = 20,
    detrend: bool = False,
    deseasonalize: bool = False
) -> Dict:
    """
    Find topics that NEGATIVELY correlate with the base article.
    When base goes UP, these go DOWN (and vice versa).

    Args:
        base_article: Article to find inverse correlations for
        days: Days of history to analyze
        threshold: Maximum correlation (must be negative, e.g., -0.3)
        max_results: Maximum results to return
        detrend: Remove linear trend
        deseasonalize: Remove seasonality

    Returns:
        Dict with query info and negative correlations
    """
    # Get all articles from all wide categories
    all_candidates = get_all_wide_candidates()

    # Remove the base article
    base_normalized = base_article.lower().replace(" ", "_")
    all_candidates = [a for a in all_candidates if a.lower() != base_normalized]

    start_date, end_date = wikipedia_service.get_date_range(days)

    # Fetch base article pageviews
    base_views = await wikipedia_service.get_pageviews(base_article, start_date, end_date)

    if not base_views:
        return {
            "query": base_article,
            "query_timeseries": [],
            "negative_correlations": [],
            "cached": False,
            "calculated_at": datetime.now().isoformat()
        }

    base_values = np.array([p['views'] for p in base_views])

    # Fetch candidates in parallel
    all_data = await wikipedia_service.get_pageviews_batch(
        all_candidates, start_date, end_date
    )

    negative_correlations = []

    for article, views in all_data.items():
        if len(views) != len(base_views):
            continue

        candidate_values = np.array([p['views'] for p in views])
        corr, p_value = calculate_correlation(
            base_values,
            candidate_values,
            detrend=detrend,
            deseasonalize=deseasonalize
        )

        # Only include negative correlations below threshold
        if corr <= threshold:
            avg_views = float(np.mean(candidate_values))
            trend = calculate_trend(views)
            category = get_article_category(article)

            negative_correlations.append({
                "title": article.replace("_", " "),
                "score": round(corr, 4),
                "p_value": round(p_value, 6) if p_value is not None else None,
                "avg_daily_views": round(avg_views, 0),
                "trend": trend,
                "category": category,
                "relationship": "inverse",
                "description": f"When {base_article.replace('_', ' ')} goes UP, {article.replace('_', ' ')} tends to go DOWN",
                "timeseries": views
            })

    # Sort by correlation (most negative first)
    negative_correlations.sort(key=lambda x: x['score'])

    return {
        "query": base_article.replace("_", " "),
        "query_timeseries": base_views,
        "correlations": negative_correlations[:max_results],  # Use "correlations" for frontend compatibility
        "negative_correlations": negative_correlations[:max_results],  # Keep for backward compatibility
        "mode": "negative",
        "threshold": threshold,
        "total_candidates": len(all_candidates),
        "cached": False,
        "calculated_at": datetime.now().isoformat()
    }


async def find_cross_domain_correlations(
    days: int = 365,
    limit: int = 20,
    detrend: bool = True
) -> list:
    """
    Find the most surprising correlations across all domains.
    Used for the "Top Surprising" section on homepage.
    """
    import random

    surprising_pairs = []

    # Sample some base articles from each category
    categories = list(WIDE_CATEGORIES.keys())

    for category in random.sample(categories, min(5, len(categories))):
        articles = WIDE_CATEGORIES[category]
        base = random.choice(articles)

        # Find surprising correlations for this article
        results = await find_surprising_correlations(
            base_article=base,
            days=days,
            threshold=0.4,
            max_results=5,
            detrend=detrend
        )

        for corr in results.get('correlations', []):
            surprising_pairs.append({
                'article_a': base.replace('_', ' '),
                'article_b': corr['title'],
                'correlation': corr['score'],
                'surprise_score': corr.get('surprise_score', 0),
                'category_a': category,
                'category_b': get_article_category(corr['title'].replace(' ', '_'))
            })

    # Sort by surprise score
    surprising_pairs.sort(key=lambda x: x['surprise_score'], reverse=True)

    return surprising_pairs[:limit]


# =============================================================================
# COSINE SIMILARITY BATCH - From correlateB.py
# =============================================================================

async def find_similar_by_cosine(
    query: str,
    days: int = 180,
    n_results: int = 20,
    categories: List[str] = None
) -> Dict:
    """
    Find similar topics using Cosine Similarity (from correlateB.py).
    Uses NearestNeighbors for efficient similarity search.

    Args:
        query: Topic to find similarities for
        days: Days of history
        n_results: Number of similar topics to return
        categories: Categories to search (None = all)

    Returns:
        Dict with similar topics ranked by cosine similarity
    """
    # Find Wikipedia article
    search_results = await wikipedia_service.search_articles(query, limit=1)

    if not search_results:
        return {
            "query": query,
            "similar": [],
            "error": "No Wikipedia article found"
        }

    base_article = search_results[0]

    # Get candidates
    categories_to_use = categories if categories else list(WIDE_CATEGORIES.keys())
    candidates = []
    for cat in categories_to_use:
        if cat in WIDE_CATEGORIES:
            candidates.extend(WIDE_CATEGORIES[cat])

    candidates = list(set(candidates))
    candidates = [c for c in candidates if c.lower() != base_article.lower()]

    # Include base article in the matrix
    all_articles = [base_article] + candidates

    start_date, end_date = wikipedia_service.get_date_range(days)

    # Fetch all pageviews
    all_data = await wikipedia_service.get_pageviews_batch(
        all_articles, start_date, end_date
    )

    # Build matrix (articles x days)
    valid_articles = []
    matrix_data = []

    # Get base article data first
    if base_article not in all_data or len(all_data.get(base_article, [])) == 0:
        return {
            "query": query,
            "similar": [],
            "error": "Could not fetch base article data"
        }

    base_views = all_data[base_article]
    expected_len = len(base_views)

    for article, views in all_data.items():
        if len(views) == expected_len:
            valid_articles.append(article)
            matrix_data.append([v['views'] for v in views])

    if len(valid_articles) < 2:
        return {
            "query": query,
            "similar": [],
            "error": "Not enough data for similarity calculation"
        }

    # Build numpy matrix
    data_matrix = np.array(matrix_data)

    # Find base article index
    try:
        base_idx = valid_articles.index(base_article)
    except ValueError:
        return {
            "query": query,
            "similar": [],
            "error": "Base article not in valid set"
        }

    # Use NearestNeighbors with cosine distance
    n_neighbors = min(n_results + 1, len(valid_articles))
    nn = NearestNeighbors(
        n_neighbors=n_neighbors,
        algorithm='auto',
        metric='cosine'
    )
    nn.fit(data_matrix)

    query_vector = data_matrix[base_idx:base_idx+1]
    distances, indices = nn.kneighbors(query_vector, n_neighbors=n_neighbors)

    # Build results (skip first as it's the query itself)
    similar = []
    for i, (dist, idx) in enumerate(zip(distances[0][1:], indices[0][1:])):
        similarity = 1 - dist  # cosine distance -> similarity
        article = valid_articles[idx]
        category = get_article_category(article)

        similar.append({
            "title": article.replace("_", " "),
            "similarity": round(similarity, 4),
            "rank": i + 1,
            "category": category,
            "method": "cosine"
        })

    return {
        "query": base_article.replace("_", " "),
        "similar": similar,
        "method": "cosine_nearest_neighbors",
        "articles_analyzed": len(valid_articles),
        "days": days,
        "calculated_at": datetime.now().isoformat()
    }


# =============================================================================
# GRANGER CAUSALITY - From granger_causality.py
# Tests if one series helps predict another (beyond just correlation)
# =============================================================================

def granger_test(
    series1: np.ndarray,
    series2: np.ndarray,
    max_lag: int = 14
) -> Optional[Dict]:
    """
    Granger causality test between two time series.
    Tests BOTH directions.

    Args:
        series1: First time series (e.g., Bitcoin pageviews)
        series2: Second time series (e.g., Natural gas pageviews)
        max_lag: Maximum lag in days to test

    Returns:
        Dict with causality results for both directions
    """
    # Prepare data
    df = pd.DataFrame({
        'series1': series1,
        'series2': series2
    })

    # Remove NaN
    df = df.dropna()

    if len(df) < max_lag * 3:
        return None

    try:
        # Test: Does series1 Granger-cause series2?
        result_1_to_2 = grangercausalitytests(
            df[['series2', 'series1']],
            maxlag=max_lag,
            verbose=False
        )

        # Test: Does series2 Granger-cause series1?
        result_2_to_1 = grangercausalitytests(
            df[['series1', 'series2']],
            maxlag=max_lag,
            verbose=False
        )

        # Extract p-values (using F-test)
        pvalues_1_to_2 = {
            lag: result_1_to_2[lag][0]['ssr_ftest'][1]
            for lag in range(1, max_lag + 1)
        }

        pvalues_2_to_1 = {
            lag: result_2_to_1[lag][0]['ssr_ftest'][1]
            for lag in range(1, max_lag + 1)
        }

        # Best lags (lowest p-value)
        best_lag_1_to_2 = min(pvalues_1_to_2, key=pvalues_1_to_2.get)
        best_pval_1_to_2 = pvalues_1_to_2[best_lag_1_to_2]

        best_lag_2_to_1 = min(pvalues_2_to_1, key=pvalues_2_to_1.get)
        best_pval_2_to_1 = pvalues_2_to_1[best_lag_2_to_1]

        return {
            'series1_causes_series2': {
                'pvalues': pvalues_1_to_2,
                'best_lag': best_lag_1_to_2,
                'best_pvalue': best_pval_1_to_2,
                'significant': best_pval_1_to_2 < 0.05
            },
            'series2_causes_series1': {
                'pvalues': pvalues_2_to_1,
                'best_lag': best_lag_2_to_1,
                'best_pvalue': best_pval_2_to_1,
                'significant': best_pval_2_to_1 < 0.05
            }
        }

    except Exception as e:
        print(f"Granger test error: {e}")
        return None


async def analyze_granger_causality(
    article1: str,
    article2: str,
    days: int = 365,
    max_lag: int = 14,
    detrend: bool = True,
    deseasonalize: bool = False
) -> Dict:
    """
    Full Granger causality analysis between two Wikipedia articles.
    Tests if one article's pageviews help predict the other's.

    Args:
        article1: First Wikipedia article
        article2: Second Wikipedia article
        days: Days of history to analyze
        max_lag: Maximum lag to test
        detrend: Remove linear trend
        deseasonalize: Remove seasonality

    Returns:
        Dict with causality analysis results
    """
    start_date, end_date = wikipedia_service.get_date_range(days)

    # Fetch both articles
    data1 = await wikipedia_service.get_pageviews(article1, start_date, end_date)
    data2 = await wikipedia_service.get_pageviews(article2, start_date, end_date)

    if not data1 or not data2:
        return {
            "article1": article1,
            "article2": article2,
            "error": "Could not fetch data for one or both articles",
            "calculated_at": datetime.now().isoformat()
        }

    # Align lengths
    min_len = min(len(data1), len(data2))
    data1 = data1[:min_len]
    data2 = data2[:min_len]

    # Extract values
    series1 = np.array([p['views'] for p in data1])
    series2 = np.array([p['views'] for p in data2])

    # Preprocessing
    if deseasonalize:
        series1 = detrend_and_deseasonalize(series1)
        series2 = detrend_and_deseasonalize(series2)
    elif detrend:
        series1 = detrend_series(series1)
        series2 = detrend_series(series2)

    # Run Granger test
    result = granger_test(series1, series2, max_lag=max_lag)

    if result is None:
        return {
            "article1": article1.replace("_", " "),
            "article2": article2.replace("_", " "),
            "error": "Not enough data for Granger test",
            "calculated_at": datetime.now().isoformat()
        }

    # Interpret results
    r1 = result['series1_causes_series2']
    r2 = result['series2_causes_series1']

    both_significant = r1['significant'] and r2['significant']
    one_way_1to2 = r1['significant'] and not r2['significant']
    one_way_2to1 = r2['significant'] and not r1['significant']

    if both_significant:
        relationship = "bidirectional"
        description = f"Bidirectional causality: {article1.replace('_', ' ')} ⇄ {article2.replace('_', ' ')}"
    elif one_way_1to2:
        relationship = "unidirectional_1to2"
        description = f"{article1.replace('_', ' ')} → {article2.replace('_', ' ')} (lag {r1['best_lag']} days)"
    elif one_way_2to1:
        relationship = "unidirectional_2to1"
        description = f"{article2.replace('_', ' ')} → {article1.replace('_', ' ')} (lag {r2['best_lag']} days)"
    else:
        relationship = "none"
        description = "No significant Granger causality in either direction"

    return {
        "article1": article1.replace("_", " "),
        "article2": article2.replace("_", " "),
        "days_analyzed": int(min_len),
        "max_lag_tested": int(max_lag),
        "detrend": bool(detrend),
        "deseasonalize": bool(deseasonalize),
        "direction1": {
            "from": article1.replace("_", " "),
            "to": article2.replace("_", " "),
            "best_lag": int(r1['best_lag']),
            "best_pvalue": float(round(r1['best_pvalue'], 8)),
            "significant": bool(r1['significant']),
            "confidence": float(round((1 - r1['best_pvalue']) * 100, 2)) if r1['best_pvalue'] < 1 else 0.0
        },
        "direction2": {
            "from": article2.replace("_", " "),
            "to": article1.replace("_", " "),
            "best_lag": int(r2['best_lag']),
            "best_pvalue": float(round(r2['best_pvalue'], 8)),
            "significant": bool(r2['significant']),
            "confidence": float(round((1 - r2['best_pvalue']) * 100, 2)) if r2['best_pvalue'] < 1 else 0.0
        },
        "relationship": relationship,
        "description": description,
        "calculated_at": datetime.now().isoformat()
    }


async def find_granger_causes(
    base_article: str,
    days: int = 365,
    max_lag: int = 14,
    detrend: bool = True,
    max_results: int = 20,
    categories: List[str] = None
) -> Dict:
    """
    Find all topics that Granger-cause the base article.
    Searches through all categories and returns significant causes.

    Args:
        base_article: The article to find causes for
        days: Days of history
        max_lag: Maximum lag to test
        detrend: Remove trend
        max_results: Maximum results
        categories: Categories to search (None = all)

    Returns:
        Dict with topics that Granger-cause the base article
    """
    categories_to_use = categories if categories else list(WIDE_CATEGORIES.keys())

    candidates = []
    for cat in categories_to_use:
        if cat in WIDE_CATEGORIES:
            candidates.extend(WIDE_CATEGORIES[cat])

    candidates = list(set(candidates))
    candidates = [c for c in candidates if c.lower() != base_article.lower()]

    start_date, end_date = wikipedia_service.get_date_range(days)

    # Fetch base article
    base_views = await wikipedia_service.get_pageviews(base_article, start_date, end_date)

    if not base_views:
        return {
            "query": base_article,
            "causes": [],
            "error": "Could not fetch base article"
        }

    base_values = np.array([p['views'] for p in base_views])
    if detrend:
        base_values = detrend_and_deseasonalize(base_values)

    # Fetch all candidates
    all_data = await wikipedia_service.get_pageviews_batch(
        candidates, start_date, end_date
    )

    causes = []
    for article, views in all_data.items():
        if len(views) != len(base_views):
            continue

        candidate_values = np.array([p['views'] for p in views])
        if detrend:
            candidate_values = detrend_and_deseasonalize(candidate_values)

        # Test if candidate Granger-causes base
        result = granger_test(candidate_values, base_values, max_lag=max_lag)

        if result and result['series1_causes_series2']['significant']:
            r = result['series1_causes_series2']
            causes.append({
                "title": article.replace("_", " "),
                "best_lag": r['best_lag'],
                "pvalue": round(r['best_pvalue'], 8),
                "confidence": round((1 - r['best_pvalue']) * 100, 2),
                "category": get_article_category(article),
                "description": f"{article.replace('_', ' ')} helps predict {base_article.replace('_', ' ')} (lag {r['best_lag']} days)"
            })

    # Sort by confidence (highest first)
    causes.sort(key=lambda x: x['confidence'], reverse=True)

    return {
        "query": base_article.replace("_", " "),
        "mode": "granger_causes",
        "causes": causes[:max_results],
        "total_found": len(causes),
        "candidates_tested": len(all_data),
        "max_lag": max_lag,
        "calculated_at": datetime.now().isoformat()
    }


# =============================================================================
# EXPANDED SEARCH - Category Expansion (353 → 10,000+ articles)
# Uses cached top articles + smart expansion for any-topic search
# =============================================================================

async def expanded_search(
    query: str,
    days: int = 365,
    limit: int = 20,
    use_cache: bool = True,
    expand: bool = True,
    threshold: float = 0.3,
    detrend: bool = False,
    deseasonalize: bool = False,
    method: str = 'pearson'
) -> Dict:
    """
    EXPANDED CORRELATION SEARCH - Like Google Correlate.

    Searches across:
    1. Top 10,000 cached Wikipedia articles (instant)
    2. Smart expansion: Wikipedia links + Wikidata (if expand=True)
    3. Topic expander: DuckDuckGo (if expand=True)

    Args:
        query: Topic to search for
        days: Days of history to analyze
        limit: Maximum results to return
        use_cache: Whether to use cached top articles
        expand: Whether to expand search using Wikipedia/Wikidata
        threshold: Minimum correlation score
        detrend: Remove linear trend
        deseasonalize: Remove seasonality
        method: 'pearson' or 'cosine'

    Returns:
        Dict with correlations and metadata
    """
    from wikicorrelate.services.article_cache import article_cache
    from wikicorrelate.services.smart_expander import smart_expander

    # Find Wikipedia article for query
    search_results = await wikipedia_service.search_articles(query, limit=1)

    if not search_results:
        return {
            "query": query,
            "correlations": [],
            "error": "No Wikipedia article found for this query",
            "calculated_at": datetime.now().isoformat()
        }

    base_article = search_results[0]

    # Collect candidates from multiple sources
    candidates = set()

    # Source 1: Cached top articles (instant, 5000-10000 articles)
    if use_cache:
        top_articles = await article_cache.get_top_articles(limit=5000)
        candidates.update(top_articles)
        print(f"[expanded_search] Added {len(top_articles)} from cache")

    # Source 2: Wide categories (353 curated articles)
    for articles in WIDE_CATEGORIES.values():
        candidates.update(articles)

    # Source 3: Smart expansion (Wikipedia links + Wikidata)
    if expand:
        try:
            expansion = await smart_expander.expand_all(base_article, max_results=100)
            candidates.update(expansion.get("combined", []))
            print(f"[expanded_search] Added {len(expansion.get('combined', []))} from smart expander")
        except Exception as e:
            print(f"Smart expansion error: {e}")

    # Source 4: Topic expander (DuckDuckGo)
    if expand:
        try:
            from wikicorrelate.services.topic_expander import topic_expander
            expanded = await topic_expander.expand_topic(query, expansion_depth=1)
            candidates.update(expanded[:30])
            print(f"[expanded_search] Added {len(expanded[:30])} from topic expander")
        except Exception as e:
            print(f"Topic expander error: {e}")

    # Remove the query itself
    candidates.discard(base_article)
    candidates.discard(query)
    candidates.discard(query.replace(" ", "_"))

    candidates_list = list(candidates)
    print(f"[expanded_search] Total candidates: {len(candidates_list)}")

    # Calculate correlations
    results = await find_correlations(
        base_article=base_article,
        candidate_articles=candidates_list,
        days=days,
        threshold=threshold,
        max_results=limit,
        detrend=detrend,
        deseasonalize=deseasonalize,
        method=method
    )

    # Add metadata
    results['mode'] = 'expanded'
    results['candidates_from_cache'] = len(top_articles) if use_cache else 0
    results['candidates_from_categories'] = sum(len(a) for a in WIDE_CATEGORIES.values())
    results['expansion_enabled'] = expand
    results['total_candidates'] = len(candidates_list)

    return results


async def expanded_search_fast(
    query: str,
    days: int = 365,
    limit: int = 20,
    threshold: float = 0.3
) -> Dict:
    """
    FAST EXPANDED SEARCH - Cache only, no expansion.

    Uses only cached top articles for instant results.
    Best for quick searches on popular topics.

    Args:
        query: Topic to search for
        days: Days of history
        limit: Max results
        threshold: Min correlation

    Returns:
        Correlation results
    """
    return await expanded_search(
        query=query,
        days=days,
        limit=limit,
        use_cache=True,
        expand=False,
        threshold=threshold,
        detrend=False,
        deseasonalize=False,
        method='pearson'
    )


async def expanded_search_deep(
    query: str,
    days: int = 365,
    limit: int = 30,
    threshold: float = 0.25
) -> Dict:
    """
    DEEP EXPANDED SEARCH - Full expansion with all sources.

    Uses cache + smart expansion + topic expander.
    Best for finding non-obvious correlations.

    Args:
        query: Topic to search for
        days: Days of history
        limit: Max results
        threshold: Min correlation

    Returns:
        Correlation results with surprise scores
    """
    results = await expanded_search(
        query=query,
        days=days,
        limit=100,  # Get more, filter by surprise
        use_cache=True,
        expand=True,
        threshold=threshold,
        detrend=True,
        deseasonalize=False,
        method='pearson'
    )

    # Add surprise scores
    base_article = results.get('query', query).replace(' ', '_')

    for corr in results.get('correlations', []):
        if not is_obvious_pair(base_article, corr['title'].replace(' ', '_')):
            surprise = calculate_surprise_score(
                base_article,
                corr['title'].replace(' ', '_'),
                corr['score']
            )
            corr['surprise_score'] = round(surprise, 3)
        else:
            corr['surprise_score'] = 0.1

    # Sort by surprise score
    results['correlations'].sort(key=lambda x: x.get('surprise_score', 0), reverse=True)
    results['correlations'] = results['correlations'][:limit]
    results['mode'] = 'expanded_deep'

    return results
