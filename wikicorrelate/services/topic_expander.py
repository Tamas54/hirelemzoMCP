"""
Topic Expander Service
Uses search engines to find semantically distant but potentially correlated topics.
"""
import asyncio
import httpx
import re
from typing import List, Dict, Set, Optional
from urllib.parse import quote_plus
import random


class TopicExpander:
    """
    Expands a topic into a list of semantically distant but potentially related topics.
    Uses DuckDuckGo for broader topic discovery.
    """

    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        self.ddg_url = "https://html.duckduckgo.com/html/"
        self._client: httpx.AsyncClient = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create a shared HTTP client"""
        if self._client is None or self._client.is_closed:
            async with self._client_lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        timeout=15.0,
                        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                        headers={"User-Agent": self.user_agent}
                    )
        return self._client

    async def close(self):
        """Close the shared HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def search_ddg(self, query: str, max_results: int = 30) -> List[str]:
        """
        Search DuckDuckGo and extract Wikipedia article titles from results.
        """
        results = []

        try:
            client = await self._get_client()
            response = await client.post(
                self.ddg_url,
                data={"q": query, "b": ""}
            )

            if response.status_code != 200:
                return results

            html = response.text

            # Extract Wikipedia URLs from results
            wiki_pattern = r'https?://en\.wikipedia\.org/wiki/([^"&\s]+)'
            matches = re.findall(wiki_pattern, html)

            for match in matches:
                # Clean up the title
                title = match.split('#')[0].split('?')[0]
                title = title.replace('%20', '_')

                # Skip special pages
                if any(skip in title for skip in [
                    'Wikipedia:', 'Help:', 'Template:', 'Category:',
                    'Special:', 'File:', 'Portal:', 'Talk:'
                ]):
                    continue

                if title and title not in results:
                    results.append(title)

                if len(results) >= max_results:
                    break

        except Exception as e:
            print(f"DuckDuckGo search error: {e}")

        return results

    async def expand_topic(
        self,
        topic: str,
        expansion_depth: int = 3,
        max_per_query: int = 15
    ) -> List[str]:
        """
        Expand a topic using multiple search strategies.

        Strategies:
        1. Direct related searches
        2. Effect/cause searches
        3. Industry/market searches
        4. Unexpected connection searches

        Args:
            topic: Base topic to expand
            expansion_depth: How many query variations to use
            max_per_query: Max results per query

        Returns:
            List of Wikipedia article titles
        """
        all_topics: Set[str] = set()

        # Define search query templates for finding distant connections
        query_templates = [
            # Direct but broad
            f"{topic} affects",
            f"{topic} caused by",
            f"{topic} impact on",

            # Economic/market connections
            f"{topic} market correlation",
            f"{topic} economic indicator",
            f"{topic} price relationship",

            # Unexpected domains
            f"{topic} surprising connection",
            f"{topic} unexpected link",
            f"{topic} hidden relationship",

            # Supply chain / industry
            f"{topic} supply chain",
            f"{topic} industry impact",
            f"{topic} production factors",

            # Geographic / demographic
            f"{topic} regional patterns",
            f"{topic} demographic trends",

            # Behavioral / social
            f"{topic} consumer behavior",
            f"{topic} social trends",
            f"{topic} cultural impact",

            # Technology / innovation
            f"{topic} technology disruption",
            f"{topic} innovation effect",

            # Environmental
            f"{topic} environmental factors",
            f"{topic} weather correlation",
            f"{topic} seasonal patterns",
        ]

        # Shuffle and limit based on expansion depth
        random.shuffle(query_templates)
        queries_to_run = query_templates[:expansion_depth * 3]

        # Run searches with rate limiting
        for query in queries_to_run:
            results = await self.search_ddg(f"{query} site:en.wikipedia.org", max_per_query)
            all_topics.update(results)
            await asyncio.sleep(0.5)  # Rate limiting

        # Remove the original topic and obvious variations
        topic_normalized = topic.lower().replace(" ", "_")
        filtered = [
            t for t in all_topics
            if t.lower() != topic_normalized
            and not t.lower().startswith(topic_normalized)
            and not topic_normalized.startswith(t.lower())
        ]

        return filtered

    async def find_distant_topics(
        self,
        topic: str,
        exclude_categories: Optional[List[str]] = None,
        max_results: int = 50
    ) -> List[Dict]:
        """
        Find semantically distant topics that might have surprising correlations.

        Args:
            topic: Base topic
            exclude_categories: Categories to exclude (e.g., if topic is "Bitcoin",
                               exclude "cryptocurrency")
            max_results: Maximum topics to return

        Returns:
            List of dicts with topic info and estimated semantic distance
        """
        # Expand the topic
        expanded = await self.expand_topic(topic, expansion_depth=3)

        # Calculate rough semantic distance based on how "unexpected" the topic is
        results = []

        for exp_topic in expanded[:max_results]:
            # Simple heuristic: longer search path = more distant
            # Topics found via "surprising connection" queries score higher
            distance_score = 0.5  # Base score

            # Boost topics that don't share words with original
            topic_words = set(topic.lower().replace("_", " ").split())
            exp_words = set(exp_topic.lower().replace("_", " ").split())
            common_words = topic_words & exp_words

            if not common_words:
                distance_score += 0.3  # No common words = more distant

            results.append({
                "topic": exp_topic.replace("_", " "),
                "slug": exp_topic,
                "semantic_distance": round(distance_score, 2)
            })

        # Sort by semantic distance (higher = more surprising potential)
        results.sort(key=lambda x: x['semantic_distance'], reverse=True)

        return results


# Additional helper functions for integration

async def get_expanded_candidates(
    topic: str,
    include_categories: bool = True,
    max_total: int = 100
) -> List[str]:
    """
    Get expanded candidate list for correlation analysis.

    Combines:
    1. Search engine expanded topics
    2. Predefined category topics (optionally)

    Returns list of Wikipedia article slugs.
    """
    from wikicorrelate.services.correlate import CATEGORY_ARTICLES

    expander = TopicExpander()
    candidates: Set[str] = set()

    # Get search-expanded topics
    expanded = await expander.expand_topic(topic, expansion_depth=2)
    candidates.update(expanded)

    # Add topics from all categories for broader coverage
    if include_categories:
        for category, articles in CATEGORY_ARTICLES.items():
            candidates.update(articles)

    # Remove the original topic
    topic_slug = topic.replace(" ", "_")
    candidates.discard(topic_slug)
    candidates.discard(topic)

    return list(candidates)[:max_total]


def calculate_semantic_distance(topic_a: str, topic_b: str) -> float:
    """
    Estimate semantic distance between two topics.

    Simple heuristic based on word overlap.
    For production, would use embeddings (e.g., sentence-transformers).

    Returns:
        Float 0-1 where 1 = completely unrelated, 0 = identical
    """
    # Tokenize
    words_a = set(topic_a.lower().replace("_", " ").replace("-", " ").split())
    words_b = set(topic_b.lower().replace("_", " ").replace("-", " ").split())

    # Remove common stopwords
    stopwords = {'the', 'a', 'an', 'of', 'in', 'on', 'and', 'or', 'for', 'to'}
    words_a -= stopwords
    words_b -= stopwords

    if not words_a or not words_b:
        return 0.5

    # Jaccard distance
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)

    if union == 0:
        return 0.5

    similarity = intersection / union
    distance = 1 - similarity

    return round(distance, 3)


def calculate_surprise_score(
    correlation: float,
    semantic_distance: float,
    is_same_category: bool = False
) -> float:
    """
    Calculate how surprising a correlation is.

    surprise = correlation_strength * semantic_distance

    A high correlation between semantically distant topics is very surprising.

    Args:
        correlation: Correlation coefficient (-1 to 1)
        semantic_distance: Semantic distance (0-1)
        is_same_category: Penalty if topics are in the same category

    Returns:
        Surprise score (0-1)
    """
    base_score = abs(correlation) * semantic_distance

    # Penalty for same category (less surprising)
    if is_same_category:
        base_score *= 0.5

    return round(min(base_score, 1.0), 3)


# Singleton instance
topic_expander = TopicExpander()
