"""
Markov Chain Discovery Service
Finds hidden connections between topics using random walk on correlation graph.
Based on PageRank principles - discovers indirect relationships.

Optimized with parallel pageview fetching via central http_client.
"""
import numpy as np
from scipy.sparse import lil_matrix, csr_matrix
from scipy.sparse.linalg import eigs
from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime
import heapq
from collections import defaultdict
import asyncio

from wikicorrelate.services.wikipedia import wikipedia_service
from wikicorrelate.services.correlate import calculate_correlation, CATEGORY_ARTICLES
from wikicorrelate.services.http_client import fetch_all_parallel


class MarkovTopicDiscovery:
    """
    PageRank-inspired discovery of hidden topic connections.

    Uses correlation-weighted random walks to find:
    - Topics reachable through indirect paths
    - Bridge topics connecting distant domains
    - Surprising connections (high indirect, low direct correlation)
    """

    def __init__(
        self,
        damping: float = 0.85,
        correlation_threshold: float = 0.15,
        max_topics: int = 200
    ):
        """
        Args:
            damping: Random walk damping factor (0.85 = PageRank standard)
                     85% follows edges, 15% teleports randomly
            correlation_threshold: Minimum correlation to create an edge
            max_topics: Maximum topics to include in graph
        """
        self.damping = damping
        self.threshold = correlation_threshold
        self.max_topics = max_topics

        # Graph state
        self.transition_matrix: Optional[csr_matrix] = None
        self.topic_to_idx: Dict[str, int] = {}
        self.idx_to_topic: Dict[int, str] = {}
        self.correlation_matrix: Optional[np.ndarray] = None
        self.topics: List[str] = []

    async def build_graph(self, days: int = 365, seed_topic: str = None) -> int:
        """
        Build the topic correlation graph from all category articles.

        Args:
            days: Days of history to use for correlations
            seed_topic: Ensure this topic is included in the graph

        Returns:
            Number of topics in graph
        """
        # Collect all unique topics
        all_topics: Set[str] = set()
        for articles in CATEGORY_ARTICLES.values():
            all_topics.update(articles)

        # Convert to sorted list for consistency
        topics_list = sorted(list(all_topics))

        # Ensure seed topic is included (even if not in predefined categories)
        if seed_topic:
            # Normalize seed topic name
            seed_normalized = seed_topic.replace(" ", "_")

            if seed_normalized in all_topics:
                # Already in categories - put it first
                topics_list.remove(seed_normalized)
                topics_list = [seed_normalized] + topics_list[:self.max_topics - 1]
            else:
                # Not in categories - add it anyway
                topics_list = [seed_normalized] + topics_list[:self.max_topics - 1]
        else:
            topics_list = topics_list[:self.max_topics]

        self.topics = topics_list
        n = len(self.topics)

        # Build index mappings
        self.topic_to_idx = {t: i for i, t in enumerate(self.topics)}
        self.idx_to_topic = {i: t for i, t in enumerate(self.topics)}

        # Fetch all timeseries
        start_date, end_date = wikipedia_service.get_date_range(days)
        all_data = await wikipedia_service.get_pageviews_batch(
            self.topics, start_date, end_date
        )

        # Build correlation matrix
        self.correlation_matrix = np.zeros((n, n))

        topic_values = {}
        for topic in self.topics:
            if topic in all_data and all_data[topic]:
                topic_values[topic] = np.array([p['views'] for p in all_data[topic]])

        # Calculate pairwise correlations
        for i, topic_a in enumerate(self.topics):
            if topic_a not in topic_values:
                continue
            for j, topic_b in enumerate(self.topics):
                if i >= j or topic_b not in topic_values:
                    continue
                if len(topic_values[topic_a]) != len(topic_values[topic_b]):
                    continue

                corr, _ = calculate_correlation(
                    topic_values[topic_a],
                    topic_values[topic_b]
                )
                self.correlation_matrix[i, j] = corr
                self.correlation_matrix[j, i] = corr

        # Build transition matrix from correlations
        self._build_transition_matrix()

        return n

    def _build_transition_matrix(self) -> None:
        """
        Build transition matrix from correlations.

        Edge weight = max(0, correlation - threshold)
        Rows normalized to sum to 1.
        Damping factor applied.
        """
        n = len(self.topics)
        trans = lil_matrix((n, n))

        for i in range(n):
            row_sum = 0.0
            for j in range(n):
                if i != j:
                    # Only positive correlations above threshold become edges
                    weight = max(0, self.correlation_matrix[i, j] - self.threshold)
                    if weight > 0:
                        trans[i, j] = weight
                        row_sum += weight

            # Normalize row
            if row_sum > 0:
                for j in range(n):
                    if trans[i, j] > 0:
                        trans[i, j] /= row_sum
            else:
                # Dead end - uniform distribution
                for j in range(n):
                    if i != j:
                        trans[i, j] = 1.0 / (n - 1)

        # Apply damping
        uniform = np.ones((n, n)) / n
        trans_dense = trans.toarray()
        trans_damped = self.damping * trans_dense + (1 - self.damping) * uniform

        self.transition_matrix = csr_matrix(trans_damped)

    def random_walk_probability(
        self,
        start_topic: str,
        end_topic: str,
        steps: int = 3
    ) -> float:
        """
        Calculate probability of reaching end_topic from start_topic in N steps.

        Uses matrix exponentiation: M^n[i,j]

        Args:
            start_topic: Starting topic
            end_topic: Destination topic
            steps: Number of random walk steps

        Returns:
            Probability (0-1)
        """
        if self.transition_matrix is None:
            return 0.0

        start_idx = self.topic_to_idx.get(start_topic)
        end_idx = self.topic_to_idx.get(end_topic)

        if start_idx is None or end_idx is None:
            return 0.0

        # Matrix power for random walk
        result = self.transition_matrix.toarray()
        for _ in range(steps - 1):
            result = result @ self.transition_matrix.toarray()

        return float(result[start_idx, end_idx])

    def get_direct_correlation(self, topic_a: str, topic_b: str) -> float:
        """Get direct correlation between two topics."""
        if self.correlation_matrix is None:
            return 0.0

        idx_a = self.topic_to_idx.get(topic_a)
        idx_b = self.topic_to_idx.get(topic_b)

        if idx_a is None or idx_b is None:
            return 0.0

        return float(self.correlation_matrix[idx_a, idx_b])

    async def find_surprising_connections(
        self,
        start_topic: str,
        max_steps: int = 5,
        min_indirect_prob: float = 0.005,
        max_direct_correlation: float = 0.35,
        limit: int = 20
    ) -> List[Dict]:
        """
        Find topics that are:
        - Reachable via random walk (indirect connection)
        - But have low direct correlation (surprising)

        Args:
            start_topic: Topic to find connections from
            max_steps: Maximum path length to consider
            min_indirect_prob: Minimum walk probability
            max_direct_correlation: Maximum direct correlation (lower = more surprising)
            limit: Max results

        Returns:
            List of surprising connections with paths
        """
        if self.transition_matrix is None:
            await self.build_graph()

        start_idx = self.topic_to_idx.get(start_topic)
        if start_idx is None:
            # Topic not in graph, try to find similar
            return []

        surprising = []

        for steps in range(2, max_steps + 1):
            # Get walk probabilities at this step count
            result = self.transition_matrix.toarray()
            for _ in range(steps - 1):
                result = result @ self.transition_matrix.toarray()

            probs = result[start_idx]

            for end_idx, prob in enumerate(probs):
                if end_idx == start_idx:
                    continue
                if prob < min_indirect_prob:
                    continue

                end_topic = self.idx_to_topic[end_idx]
                direct_corr = abs(self.get_direct_correlation(start_topic, end_topic))

                if direct_corr <= max_direct_correlation:
                    # This is surprising! High indirect, low direct
                    surprise_score = prob / (direct_corr + 0.001)

                    # Find the path
                    path = self._find_path(start_idx, end_idx, steps)

                    surprising.append({
                        "topic": end_topic.replace("_", " "),
                        "slug": end_topic,
                        "steps": steps,
                        "path": [self.idx_to_topic[p].replace("_", " ") for p in path],
                        "path_slugs": [self.idx_to_topic[p] for p in path],
                        "indirect_probability": round(prob, 4),
                        "direct_correlation": round(direct_corr, 4),
                        "surprise_score": round(surprise_score, 2)
                    })

        # Sort by surprise score
        surprising.sort(key=lambda x: x['surprise_score'], reverse=True)

        # Deduplicate (keep shortest path to each topic)
        seen = set()
        unique = []
        for s in surprising:
            if s['slug'] not in seen:
                seen.add(s['slug'])
                unique.append(s)

        return unique[:limit]

    def _find_path(self, start_idx: int, end_idx: int, max_steps: int) -> List[int]:
        """
        Find highest-probability path from start to end.
        Uses greedy approach based on transition probabilities.
        """
        path = [start_idx]
        current = start_idx
        trans = self.transition_matrix.toarray()

        for _ in range(max_steps - 1):
            if current == end_idx:
                break

            # Get transition probabilities from current
            probs = trans[current].copy()

            # Avoid going back
            for visited in path:
                probs[visited] = 0

            # Boost probability toward target
            if probs[end_idx] > 0:
                next_idx = end_idx
            else:
                # Pick highest probability neighbor
                next_idx = int(np.argmax(probs))
                if probs[next_idx] == 0:
                    break

            path.append(next_idx)
            current = next_idx

        if path[-1] != end_idx:
            path.append(end_idx)

        return path

    def find_bridge_topics(
        self,
        topic_a: str,
        topic_b: str,
        max_bridges: int = 3
    ) -> List[Dict]:
        """
        Find topics that bridge two distant topics.

        A good bridge has high correlation with both endpoints.
        Uses modified Dijkstra where cost = 1 - correlation.

        Args:
            topic_a: First topic
            topic_b: Second topic
            max_bridges: Maximum bridge topics to return

        Returns:
            List of bridge topics with their bridging strength
        """
        if self.correlation_matrix is None:
            return []

        idx_a = self.topic_to_idx.get(topic_a)
        idx_b = self.topic_to_idx.get(topic_b)

        if idx_a is None or idx_b is None:
            return []

        # Find topics that correlate with both
        bridges = []

        for i, topic in enumerate(self.topics):
            if i == idx_a or i == idx_b:
                continue

            corr_with_a = self.correlation_matrix[idx_a, i]
            corr_with_b = self.correlation_matrix[idx_b, i]

            # Bridge strength = geometric mean of correlations
            if corr_with_a > 0.1 and corr_with_b > 0.1:
                bridge_strength = np.sqrt(corr_with_a * corr_with_b)

                bridges.append({
                    "topic": topic.replace("_", " "),
                    "slug": topic,
                    "correlation_with_a": round(corr_with_a, 4),
                    "correlation_with_b": round(corr_with_b, 4),
                    "bridge_strength": round(bridge_strength, 4)
                })

        # Sort by bridge strength
        bridges.sort(key=lambda x: x['bridge_strength'], reverse=True)

        return bridges[:max_bridges]

    def shortest_path(
        self,
        topic_a: str,
        topic_b: str
    ) -> Tuple[List[str], float]:
        """
        Find shortest path between two topics using Dijkstra.
        Cost = 1 - abs(correlation)

        Returns:
            Tuple of (path as topic names, total cost)
        """
        if self.correlation_matrix is None:
            return [], float('inf')

        idx_a = self.topic_to_idx.get(topic_a)
        idx_b = self.topic_to_idx.get(topic_b)

        if idx_a is None or idx_b is None:
            return [], float('inf')

        n = len(self.topics)

        # Dijkstra
        dist = [float('inf')] * n
        prev = [-1] * n
        dist[idx_a] = 0

        pq = [(0, idx_a)]
        visited = set()

        while pq:
            d, u = heapq.heappop(pq)

            if u in visited:
                continue
            visited.add(u)

            if u == idx_b:
                break

            for v in range(n):
                if v == u or v in visited:
                    continue

                corr = abs(self.correlation_matrix[u, v])
                if corr < 0.1:  # Skip very weak connections
                    continue

                cost = 1 - corr
                new_dist = dist[u] + cost

                if new_dist < dist[v]:
                    dist[v] = new_dist
                    prev[v] = u
                    heapq.heappush(pq, (new_dist, v))

        # Reconstruct path
        if dist[idx_b] == float('inf'):
            return [], float('inf')

        path = []
        current = idx_b
        while current != -1:
            path.append(self.idx_to_topic[current].replace("_", " "))
            current = prev[current]

        path.reverse()
        return path, dist[idx_b]

    async def personalized_pagerank(
        self,
        seed_topics: List[str],
        iterations: int = 20,
        limit: int = 30
    ) -> List[Dict]:
        """
        Run personalized PageRank from seed topics.

        Like Google's "related searches" - starts from seeds and
        finds where random walk converges.

        Args:
            seed_topics: Topics to start from (teleport targets)
            iterations: Number of power iterations
            limit: Max results to return

        Returns:
            List of related topics with scores
        """
        if self.transition_matrix is None:
            await self.build_graph()

        n = len(self.topics)

        # Build personalization vector (uniform over seeds)
        personalization = np.zeros(n)
        for seed in seed_topics:
            idx = self.topic_to_idx.get(seed)
            if idx is not None:
                personalization[idx] = 1.0

        if personalization.sum() == 0:
            return []

        personalization /= personalization.sum()

        # Power iteration
        scores = personalization.copy()
        trans = self.transition_matrix.toarray().T  # Transpose for left eigenvector

        for _ in range(iterations):
            scores = self.damping * (trans @ scores) + (1 - self.damping) * personalization

        # Build results
        results = []
        seed_set = set(seed_topics)

        for i, score in enumerate(scores):
            topic = self.idx_to_topic[i]
            if topic in seed_set:
                continue  # Skip seeds

            results.append({
                "topic": topic.replace("_", " "),
                "slug": topic,
                "pagerank_score": round(float(score), 6),
                "relevance": round(float(score) * 1000, 2)  # Easier to read
            })

        results.sort(key=lambda x: x['pagerank_score'], reverse=True)

        return results[:limit]


# Singleton instance
markov_discovery = MarkovTopicDiscovery()


async def discover_hidden_connections(
    topic: str,
    max_steps: int = 4,
    limit: int = 20
) -> Dict:
    """
    Main entry point for discovering hidden connections.

    Args:
        topic: Topic to find hidden connections for
        max_steps: Maximum path length
        limit: Max results

    Returns:
        Dict with surprising connections and bridge topics
    """
    # Normalize topic name
    topic_slug = topic.replace(" ", "_")

    # Always rebuild graph with seed topic to ensure it's included
    # This is needed because the query topic might not be in the first 150
    await markov_discovery.build_graph(seed_topic=topic_slug)

    # Find surprising connections
    surprising = await markov_discovery.find_surprising_connections(
        topic_slug,
        max_steps=max_steps,
        limit=limit
    )

    # Find commonly-accessed bridge topics
    top_bridges = []
    if surprising:
        # Get bridges to the most surprising connection
        top_surprising = surprising[0]['slug']
        bridges = markov_discovery.find_bridge_topics(topic_slug, top_surprising)
        top_bridges = bridges

    # Get personalized PageRank recommendations
    related = await markov_discovery.personalized_pagerank(
        [topic_slug],
        limit=10
    )

    return {
        "query": topic_slug.replace("_", " "),
        "query_slug": topic_slug,
        "surprising_connections": surprising,
        "bridge_topics": top_bridges,
        "related_topics": related,
        "graph_size": len(markov_discovery.topics),
        "calculated_at": datetime.now().isoformat()
    }
