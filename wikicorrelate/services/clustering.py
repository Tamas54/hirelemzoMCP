"""
Topic Clustering Service
Semantic grouping of correlated topics for content strategy.

Uses K-Means and Hierarchical clustering on pageview vectors
to create "Pillar Page" style topic clusters.

Optimized with parallel pageview fetching via central http_client.
"""
import numpy as np
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from wikicorrelate.services.wikipedia import wikipedia_service
from wikicorrelate.services.correlate import (
    WIDE_CATEGORIES,
    CATEGORY_ARTICLES,
    search_and_correlate,
    get_article_category
)
from wikicorrelate.services.http_client import http_client


class TopicClusteringService:
    """
    Clusters correlated topics into semantic groups.

    Use cases:
    - Content strategy: Group topics for pillar pages
    - SEO: Identify topic clusters for internal linking
    - Research: Find thematic groupings in data
    """

    # Cluster naming heuristics based on category composition
    CLUSTER_LABELS = {
        'economics': 'Economic Trends',
        'finance': 'Financial Markets',
        'crypto': 'Cryptocurrency & Blockchain',
        'technology': 'Technology & Innovation',
        'geopolitics': 'Geopolitics & Policy',
        'energy': 'Energy & Commodities',
        'health': 'Health & Wellness',
        'entertainment': 'Entertainment & Media',
        'science': 'Science & Research',
        'sports': 'Sports & Events',
        'culture': 'Culture & Society',
        'mixed': 'Cross-Domain Topics'
    }

    async def cluster_topics(
        self,
        query: str,
        days: int = 365,
        n_clusters: int = None,
        min_correlation: float = 0.3,
        max_topics: int = 50,
        method: str = 'kmeans'
    ) -> Dict:
        """
        Find correlated topics and cluster them semantically.

        Args:
            query: Base topic to find correlations for
            days: Days of history to analyze
            n_clusters: Number of clusters (auto-detected if None)
            min_correlation: Minimum correlation to include
            max_topics: Maximum topics to cluster
            method: 'kmeans' or 'hierarchical'

        Returns:
            Dict with clusters and metadata
        """
        # Step 1: Get correlated topics
        correlations = await search_and_correlate(
            query=query,
            days=days,
            max_results=max_topics,
            threshold=min_correlation
        )

        if 'error' in correlations or not correlations.get('correlations'):
            return {
                "query": query,
                "clusters": [],
                "error": correlations.get('error', 'No correlated topics found')
            }

        # Normalize the result format
        raw_results = correlations['correlations']
        results = []
        for r in raw_results:
            results.append({
                'article': r.get('title', '').replace(' ', '_'),
                'title': r.get('title', ''),
                'correlation': r.get('score', 0),
                'category': r.get('category', None)
            })

        if len(results) < 3:
            return {
                "query": query,
                "clusters": [{
                    "id": 0,
                    "name": "Related Topics",
                    "topics": results
                }],
                "message": "Too few topics for meaningful clustering"
            }

        # Step 2: Build feature matrix from pageview data
        topics = [r['article'] for r in results]
        feature_matrix, valid_topics, valid_results = await self._build_feature_matrix(
            topics, results, days
        )

        if feature_matrix is None or len(valid_topics) < 3:
            return {
                "query": query,
                "clusters": [{
                    "id": 0,
                    "name": "Related Topics",
                    "topics": results
                }],
                "message": "Insufficient data for clustering"
            }

        # Step 3: Determine optimal cluster count
        if n_clusters is None:
            n_clusters = self._optimal_cluster_count(feature_matrix)

        n_clusters = min(n_clusters, len(valid_topics) // 2, 8)
        n_clusters = max(n_clusters, 2)

        # Step 4: Perform clustering
        if method == 'hierarchical':
            labels = self._hierarchical_clustering(feature_matrix, n_clusters)
        else:
            labels = self._kmeans_clustering(feature_matrix, n_clusters)

        # Step 5: Build cluster output
        clusters = self._build_cluster_output(
            valid_topics, valid_results, labels, n_clusters
        )

        # Step 6: Calculate cluster quality metrics
        if len(set(labels)) > 1:
            silhouette = silhouette_score(feature_matrix, labels)
        else:
            silhouette = 0.0

        return {
            "query": query,
            "query_slug": query.replace(" ", "_"),
            "clusters": clusters,
            "total_topics": len(valid_topics),
            "n_clusters": len(clusters),
            "clustering_method": method,
            "silhouette_score": round(silhouette, 3),
            "days_analyzed": days,
            "min_correlation": min_correlation,
            "calculated_at": datetime.now().isoformat()
        }

    async def _build_feature_matrix(
        self,
        topics: List[str],
        results: List[Dict],
        days: int
    ) -> Tuple[Optional[np.ndarray], List[str], List[Dict]]:
        """
        Build feature matrix from pageview timeseries.

        Returns normalized pageview vectors for clustering.
        """
        start_date, end_date = wikipedia_service.get_date_range(days)

        # Fetch pageviews for all topics
        all_data = await wikipedia_service.get_pageviews_batch(
            topics, start_date, end_date
        )

        # Build matrix
        vectors = []
        valid_topics = []
        valid_results = []
        result_map = {r['article']: r for r in results}

        for topic in topics:
            if topic in all_data and all_data[topic]:
                views = [p['views'] for p in all_data[topic]]
                if len(views) >= 30:  # Minimum data points
                    vectors.append(views)
                    valid_topics.append(topic)
                    if topic in result_map:
                        valid_results.append(result_map[topic])

        if not vectors:
            return None, [], []

        # Pad/truncate to same length
        max_len = max(len(v) for v in vectors)
        padded = []
        for v in vectors:
            if len(v) < max_len:
                v = v + [v[-1]] * (max_len - len(v))
            padded.append(v[:max_len])

        matrix = np.array(padded, dtype=float)

        # Normalize (z-score per topic)
        scaler = StandardScaler()
        normalized = scaler.fit_transform(matrix)

        return normalized, valid_topics, valid_results

    def _optimal_cluster_count(self, data: np.ndarray) -> int:
        """
        Determine optimal number of clusters using silhouette score.
        """
        n_samples = len(data)
        max_clusters = min(n_samples // 2, 8)

        if max_clusters < 2:
            return 2

        best_score = -1
        best_k = 2

        for k in range(2, max_clusters + 1):
            try:
                kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = kmeans.fit_predict(data)
                score = silhouette_score(data, labels)

                if score > best_score:
                    best_score = score
                    best_k = k
            except Exception:
                continue

        return best_k

    def _kmeans_clustering(self, data: np.ndarray, n_clusters: int) -> np.ndarray:
        """Apply K-Means clustering."""
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        return kmeans.fit_predict(data)

    def _hierarchical_clustering(self, data: np.ndarray, n_clusters: int) -> np.ndarray:
        """Apply Agglomerative Hierarchical clustering."""
        clustering = AgglomerativeClustering(
            n_clusters=n_clusters,
            metric='euclidean',
            linkage='ward'
        )
        return clustering.fit_predict(data)

    def _build_cluster_output(
        self,
        topics: List[str],
        results: List[Dict],
        labels: np.ndarray,
        n_clusters: int
    ) -> List[Dict]:
        """
        Build structured cluster output with names and topics.
        """
        # Group topics by cluster
        clusters_dict = defaultdict(list)
        result_map = {r['article']: r for r in results}

        for topic, label in zip(topics, labels):
            topic_data = result_map.get(topic, {
                'article': topic,
                'title': topic.replace('_', ' '),
                'correlation': 0.0
            })
            clusters_dict[int(label)].append(topic_data)

        # Build output with cluster names
        clusters = []
        for cluster_id in sorted(clusters_dict.keys()):
            cluster_topics = clusters_dict[cluster_id]

            # Sort by correlation within cluster
            cluster_topics.sort(
                key=lambda x: abs(x.get('correlation', 0)),
                reverse=True
            )

            # Determine cluster name from dominant category
            cluster_name = self._name_cluster(cluster_topics)

            # Calculate cluster stats
            correlations = [t.get('correlation', 0) for t in cluster_topics]
            avg_correlation = np.mean(correlations) if correlations else 0

            clusters.append({
                "id": cluster_id,
                "name": cluster_name,
                "topic_count": len(cluster_topics),
                "avg_correlation": round(avg_correlation, 3),
                "topics": cluster_topics,
                "top_topic": cluster_topics[0]['title'] if cluster_topics else None
            })

        # Sort clusters by average correlation
        clusters.sort(key=lambda x: abs(x['avg_correlation']), reverse=True)

        return clusters

    def _name_cluster(self, topics: List[Dict]) -> str:
        """
        Generate a name for a cluster based on its topics' categories.
        """
        category_counts = defaultdict(int)

        for topic in topics:
            article = topic.get('article', '')
            category = get_article_category(article)
            if category:
                category_counts[category] += 1

        if not category_counts:
            # Use the first topic as the cluster name
            if topics:
                return f"{topics[0]['title']} Cluster"
            return "Topic Cluster"

        # Get dominant category
        dominant = max(category_counts.items(), key=lambda x: x[1])
        dominant_category = dominant[0]

        # Check if it's truly dominant (>50% of topics)
        total = sum(category_counts.values())
        if dominant[1] / total >= 0.5:
            return self.CLUSTER_LABELS.get(dominant_category, f"{dominant_category.title()} Topics")

        # Mixed cluster - use top 2 categories
        top_2 = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:2]
        names = [self.CLUSTER_LABELS.get(c[0], c[0].title()) for c in top_2]
        return f"{names[0]} & {names[1]}"

    async def get_cluster_details(
        self,
        query: str,
        cluster_id: int,
        days: int = 365
    ) -> Dict:
        """
        Get detailed information about a specific cluster.

        Includes:
        - All topics in the cluster
        - Intra-cluster correlations
        - Suggested content angles
        """
        clusters = await self.cluster_topics(query, days=days)

        if 'error' in clusters:
            return clusters

        for cluster in clusters.get('clusters', []):
            if cluster['id'] == cluster_id:
                # Add content suggestions
                cluster['content_suggestions'] = self._generate_content_suggestions(
                    cluster['topics']
                )
                return cluster

        return {"error": f"Cluster {cluster_id} not found"}

    def _generate_content_suggestions(self, topics: List[Dict]) -> List[str]:
        """
        Generate content strategy suggestions based on cluster topics.
        """
        suggestions = []

        if len(topics) >= 3:
            top_3 = [t['title'] for t in topics[:3]]
            suggestions.append(
                f"Pillar page: 'The Connection Between {top_3[0]}, {top_3[1]}, and {top_3[2]}'"
            )

        if len(topics) >= 5:
            suggestions.append(
                f"Listicle: '{len(topics)} Topics Every {topics[0]['title']} Enthusiast Should Know'"
            )

        # Find highest correlation pair for comparison content
        if len(topics) >= 2:
            suggestions.append(
                f"Comparison: '{topics[0]['title']} vs {topics[1]['title']}'"
            )

        return suggestions


# Singleton instance
clustering_service = TopicClusteringService()


async def cluster_correlated_topics(
    query: str,
    days: int = 365,
    n_clusters: int = None,
    min_correlation: float = 0.3,
    method: str = 'kmeans'
) -> Dict:
    """
    Main entry point for topic clustering.

    Args:
        query: Topic to find and cluster correlations for
        days: Days of history
        n_clusters: Number of clusters (auto if None)
        min_correlation: Minimum correlation threshold
        method: 'kmeans' or 'hierarchical'

    Returns:
        Dict with semantic topic clusters
    """
    return await clustering_service.cluster_topics(
        query=query,
        days=days,
        n_clusters=n_clusters,
        min_correlation=min_correlation,
        method=method
    )
