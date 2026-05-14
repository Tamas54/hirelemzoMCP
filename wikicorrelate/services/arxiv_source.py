"""
Arxiv Data Source
Fetches academic paper publication trends from Arxiv API.
"""
import asyncio
import httpx
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from collections import defaultdict
from urllib.parse import quote

from wikicorrelate.config import ARXIV_RATE_LIMIT_DELAY


class ArxivDataSource:
    """
    Arxiv API integration for academic research trend analysis.

    Rate limit: Be nice - 3 second delay between requests.

    Provides:
    - Paper publication frequency over time
    - Category trends
    - Citation-related metrics (where available)
    """

    def __init__(self):
        self.base_url = "https://export.arxiv.org/api/query"
        self.user_agent = "CorrelateApp/1.0 (Educational/Research)"

        # Arxiv categories
        self.categories = {
            "cs.AI": "Artificial Intelligence",
            "cs.LG": "Machine Learning",
            "cs.CL": "Computation and Language",
            "cs.CV": "Computer Vision",
            "cs.NE": "Neural and Evolutionary Computing",
            "stat.ML": "Machine Learning (Statistics)",
            "physics": "Physics",
            "math": "Mathematics",
            "q-bio": "Quantitative Biology",
            "q-fin": "Quantitative Finance",
            "econ": "Economics"
        }

    async def search_papers_by_topic(
        self,
        topic: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        category: Optional[str] = None,
        max_results: int = 100
    ) -> List[Dict]:
        """
        Search for papers matching a topic.

        Args:
            topic: Search query
            from_date: Start date (paper submission date)
            to_date: End date
            category: Arxiv category (e.g., "cs.AI")
            max_results: Maximum papers to return

        Returns:
            List of paper metadata dicts
        """
        papers = []

        # Build query
        query_parts = [f"all:{quote(topic)}"]
        if category:
            query_parts.append(f"cat:{category}")

        query = "+AND+".join(query_parts)

        async with httpx.AsyncClient(timeout=60.0) as client:
            start = 0
            batch_size = min(100, max_results)

            while len(papers) < max_results:
                params = {
                    "search_query": query,
                    "start": start,
                    "max_results": batch_size,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending"
                }

                try:
                    response = await client.get(
                        self.base_url,
                        params=params,
                        headers={"User-Agent": self.user_agent}
                    )

                    if response.status_code != 200:
                        print(f"Arxiv API error: {response.status_code}")
                        break

                    # Parse XML response
                    root = ET.fromstring(response.text)
                    ns = {"atom": "http://www.w3.org/2005/Atom"}

                    entries = root.findall("atom:entry", ns)

                    if not entries:
                        break

                    for entry in entries:
                        # Parse paper data
                        paper_id = entry.find("atom:id", ns).text.split("/")[-1]
                        title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
                        summary = entry.find("atom:summary", ns).text.strip()[:300]
                        published = entry.find("atom:published", ns).text[:10]  # YYYY-MM-DD

                        # Get authors
                        authors = []
                        for author in entry.findall("atom:author", ns):
                            name = author.find("atom:name", ns)
                            if name is not None:
                                authors.append(name.text)

                        # Get categories
                        categories = []
                        for cat in entry.findall("atom:category", ns):
                            categories.append(cat.get("term"))

                        # Filter by date if specified
                        pub_date = datetime.strptime(published, "%Y-%m-%d").date()
                        if from_date and pub_date < from_date:
                            continue
                        if to_date and pub_date > to_date:
                            continue

                        papers.append({
                            "paper_id": paper_id,
                            "title": title,
                            "authors": authors[:5],  # Limit authors
                            "summary": summary,
                            "categories": categories,
                            "primary_category": categories[0] if categories else None,
                            "published_at": published,
                            "url": f"https://arxiv.org/abs/{paper_id}"
                        })

                        if len(papers) >= max_results:
                            break

                    start += batch_size

                    if len(entries) < batch_size:
                        break

                    # Rate limiting - Arxiv asks for 3 second delay
                    await asyncio.sleep(ARXIV_RATE_LIMIT_DELAY)

                except Exception as e:
                    print(f"Arxiv API error: {e}")
                    break

        return papers

    async def get_topic_publication_frequency(
        self,
        topic: str,
        days: int = 365,
        category: Optional[str] = None,
        granularity: str = "weekly"
    ) -> List[Dict]:
        """
        Get paper publication frequency for a topic over time.

        Creates a timeseries of "how many papers published per week"
        which can be correlated with other metrics.

        Args:
            topic: Topic to search for
            days: Number of days to look back
            category: Optional Arxiv category filter
            granularity: "daily" or "weekly"

        Returns:
            List of {"date": "YYYY-MM-DD", "papers": int}
        """
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        # Fetch papers
        papers = await self.search_papers_by_topic(
            topic=topic,
            from_date=start_date,
            to_date=end_date,
            category=category,
            max_results=1000
        )

        # Count per day
        daily_counts = defaultdict(int)

        for paper in papers:
            pub_date = paper["published_at"]
            daily_counts[pub_date] += 1

        # Build timeseries
        timeseries = []
        current = start_date

        while current <= end_date:
            date_str = current.isoformat()

            if granularity == "weekly":
                if current.weekday() != 0:  # Start from Monday
                    current += timedelta(days=1)
                    continue

                # Sum the week
                week_count = sum(
                    daily_counts[(current + timedelta(days=d)).isoformat()]
                    for d in range(7)
                    if (current + timedelta(days=d)) <= end_date
                )
                timeseries.append({
                    "date": date_str,
                    "papers": week_count
                })
                current += timedelta(days=7)
            else:
                timeseries.append({
                    "date": date_str,
                    "papers": daily_counts.get(date_str, 0)
                })
                current += timedelta(days=1)

        return timeseries

    async def get_category_trends(
        self,
        days: int = 30,
        categories: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Get publication trends across Arxiv categories.

        Args:
            days: Days to look back
            categories: Categories to analyze (or use defaults)

        Returns:
            List of category trend data
        """
        if categories is None:
            categories = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]

        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        trends = []

        for cat in categories:
            papers = await self.search_papers_by_topic(
                topic="",
                from_date=start_date,
                to_date=end_date,
                category=cat,
                max_results=200
            )

            trends.append({
                "category": cat,
                "category_name": self.categories.get(cat, cat),
                "paper_count": len(papers),
                "papers_per_day": round(len(papers) / days, 2),
                "sample_titles": [p["title"][:80] for p in papers[:3]]
            })

            await asyncio.sleep(ARXIV_RATE_LIMIT_DELAY)

        # Sort by paper count
        trends.sort(key=lambda x: x["paper_count"], reverse=True)

        return trends

    async def get_recent_papers(
        self,
        topic: str,
        limit: int = 20
    ) -> List[Dict]:
        """
        Get most recent papers for a topic.

        Args:
            topic: Topic to search for
            limit: Maximum papers to return

        Returns:
            List of recent papers
        """
        papers = await self.search_papers_by_topic(
            topic=topic,
            max_results=limit
        )

        return papers

    async def get_topic_stats(
        self,
        topic: str,
        days: int = 365
    ) -> Dict:
        """
        Get aggregate statistics for a research topic.

        Args:
            topic: Topic to analyze
            days: Days to look back

        Returns:
            Dict with topic statistics
        """
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        papers = await self.search_papers_by_topic(
            topic=topic,
            from_date=start_date,
            to_date=end_date,
            max_results=500
        )

        if not papers:
            return {
                "topic": topic,
                "error": "No papers found",
                "paper_count": 0
            }

        # Category distribution
        categories = defaultdict(int)
        for p in papers:
            for cat in p.get("categories", []):
                categories[cat] += 1

        top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]

        # Author frequency
        authors = defaultdict(int)
        for p in papers:
            for author in p.get("authors", []):
                authors[author] += 1

        top_authors = sorted(authors.items(), key=lambda x: x[1], reverse=True)[:5]

        # Publication rate
        papers_per_month = len(papers) / (days / 30)

        return {
            "topic": topic,
            "period_days": days,
            "paper_count": len(papers),
            "papers_per_month": round(papers_per_month, 1),
            "top_categories": dict(top_categories),
            "top_authors": dict(top_authors),
            "recent_papers": papers[:5]
        }


# Singleton instance
arxiv_source = ArxivDataSource()
