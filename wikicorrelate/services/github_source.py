"""
GitHub Data Source
Fetches repository creation, stars, and activity trends from GitHub API.
"""
import asyncio
import httpx
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

from wikicorrelate.config import GITHUB_TOKEN, GITHUB_RATE_LIMIT_DELAY


class GitHubDataSource:
    """
    GitHub API integration for open source trend analysis.

    Rate limit: 5,000 requests/hour (authenticated)

    Provides:
    - Repository creation frequency over time
    - Star count trends
    - Fork and issue activity
    """

    def __init__(self):
        self.token = GITHUB_TOKEN
        self.base_url = "https://api.github.com"
        self.user_agent = "CorrelateApp/1.0"

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with optional auth."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/vnd.github.v3+json"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    async def search_repos_by_topic(
        self,
        topic: str,
        created_after: Optional[date] = None,
        created_before: Optional[date] = None,
        sort: str = "stars",
        max_results: int = 100
    ) -> List[Dict]:
        """
        Search for repositories matching a topic.

        Args:
            topic: Search query (topic, language, etc)
            created_after: Only repos created after this date
            created_before: Only repos created before this date
            sort: "stars", "forks", "updated", or "help-wanted-issues"
            max_results: Maximum repos to return

        Returns:
            List of repository metadata dicts
        """
        repos = []

        # Build query
        query_parts = [topic]
        if created_after:
            query_parts.append(f"created:>{created_after.isoformat()}")
        if created_before:
            query_parts.append(f"created:<{created_before.isoformat()}")

        query = " ".join(query_parts)

        async with httpx.AsyncClient(timeout=30.0) as client:
            page = 1
            while len(repos) < max_results:
                params = {
                    "q": query,
                    "sort": sort,
                    "order": "desc",
                    "per_page": min(100, max_results - len(repos)),
                    "page": page
                }

                try:
                    response = await client.get(
                        f"{self.base_url}/search/repositories",
                        params=params,
                        headers=self._get_headers()
                    )

                    if response.status_code == 403:
                        print("GitHub rate limit reached")
                        break

                    if response.status_code != 200:
                        print(f"GitHub API error: {response.status_code}")
                        break

                    data = response.json()
                    items = data.get("items", [])

                    if not items:
                        break

                    for item in items:
                        repos.append({
                            "repo_id": item["id"],
                            "name": item["name"],
                            "full_name": item["full_name"],
                            "owner": item["owner"]["login"],
                            "description": (item.get("description") or "")[:200],
                            "stars": item["stargazers_count"],
                            "forks": item["forks_count"],
                            "open_issues": item["open_issues_count"],
                            "language": item.get("language"),
                            "created_at": item["created_at"],
                            "updated_at": item["updated_at"],
                            "url": item["html_url"]
                        })

                    page += 1

                    # Check if more pages
                    if len(items) < params["per_page"]:
                        break

                    await asyncio.sleep(GITHUB_RATE_LIMIT_DELAY)

                except Exception as e:
                    print(f"GitHub API error: {e}")
                    break

        return repos

    async def get_repo_details(self, owner: str, repo: str) -> Optional[Dict]:
        """
        Get detailed information about a repository.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Repository details or None
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}",
                    headers=self._get_headers()
                )

                if response.status_code != 200:
                    return None

                item = response.json()

                return {
                    "repo_id": item["id"],
                    "name": item["name"],
                    "full_name": item["full_name"],
                    "owner": item["owner"]["login"],
                    "description": item.get("description", ""),
                    "stars": item["stargazers_count"],
                    "forks": item["forks_count"],
                    "watchers": item["watchers_count"],
                    "open_issues": item["open_issues_count"],
                    "language": item.get("language"),
                    "topics": item.get("topics", []),
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                    "pushed_at": item["pushed_at"],
                    "size": item["size"],
                    "default_branch": item["default_branch"],
                    "license": item.get("license", {}).get("name") if item.get("license") else None,
                    "url": item["html_url"]
                }

            except Exception as e:
                print(f"GitHub repo error: {e}")
                return None

    async def get_topic_repo_creation_frequency(
        self,
        topic: str,
        days: int = 365,
        granularity: str = "weekly"
    ) -> List[Dict]:
        """
        Get repository creation frequency for a topic over time.

        Creates a timeseries of "how many repos created per week"
        which can be correlated with other metrics.

        Args:
            topic: Topic to search for
            days: Number of days to look back
            granularity: "daily" or "weekly" (weekly recommended for GitHub)

        Returns:
            List of {"date": "YYYY-MM-DD", "repos_created": int, "total_stars": int}
        """
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        # Fetch repos created in the period
        repos = await self.search_repos_by_topic(
            topic=topic,
            created_after=start_date,
            created_before=end_date,
            sort="updated",
            max_results=500
        )

        # Count per day
        daily_counts = defaultdict(lambda: {"repos": 0, "stars": 0, "forks": 0})

        for repo in repos:
            created = repo["created_at"][:10]  # YYYY-MM-DD
            daily_counts[created]["repos"] += 1
            daily_counts[created]["stars"] += repo.get("stars", 0)
            daily_counts[created]["forks"] += repo.get("forks", 0)

        # Build timeseries
        timeseries = []
        current = start_date

        while current <= end_date:
            date_str = current.isoformat()

            # For GitHub, weekly granularity makes more sense
            if granularity == "daily":
                day_data = daily_counts.get(date_str, {"repos": 0, "stars": 0, "forks": 0})
                timeseries.append({
                    "date": date_str,
                    "repos_created": day_data["repos"],
                    "total_stars": day_data["stars"],
                    "total_forks": day_data["forks"]
                })
                current += timedelta(days=1)
            else:
                # Weekly - sum 7 days
                if current.weekday() != 0:  # Start from Monday
                    current += timedelta(days=1)
                    continue

                week_data = {"repos": 0, "stars": 0, "forks": 0}
                for d in range(7):
                    day = (current + timedelta(days=d)).isoformat()
                    if day in daily_counts:
                        week_data["repos"] += daily_counts[day]["repos"]
                        week_data["stars"] += daily_counts[day]["stars"]
                        week_data["forks"] += daily_counts[day]["forks"]

                timeseries.append({
                    "date": date_str,
                    "repos_created": week_data["repos"],
                    "total_stars": week_data["stars"],
                    "total_forks": week_data["forks"]
                })
                current += timedelta(days=7)

        return timeseries

    async def get_trending_repos(
        self,
        language: Optional[str] = None,
        since: str = "daily"
    ) -> List[Dict]:
        """
        Get trending repositories.

        Note: Uses search API with recent creation + high stars.

        Args:
            language: Filter by programming language
            since: "daily", "weekly", or "monthly"

        Returns:
            List of trending repos
        """
        # Calculate date range
        if since == "daily":
            created_after = date.today() - timedelta(days=1)
        elif since == "weekly":
            created_after = date.today() - timedelta(days=7)
        else:
            created_after = date.today() - timedelta(days=30)

        query = f"created:>{created_after.isoformat()}"
        if language:
            query += f" language:{language}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": 25
            }

            try:
                response = await client.get(
                    f"{self.base_url}/search/repositories",
                    params=params,
                    headers=self._get_headers()
                )

                if response.status_code != 200:
                    return []

                data = response.json()
                repos = []

                for item in data.get("items", []):
                    repos.append({
                        "name": item["name"],
                        "full_name": item["full_name"],
                        "description": (item.get("description") or "")[:150],
                        "stars": item["stargazers_count"],
                        "forks": item["forks_count"],
                        "language": item.get("language"),
                        "created_at": item["created_at"],
                        "url": item["html_url"]
                    })

                return repos

            except Exception as e:
                print(f"GitHub trending error: {e}")
                return []

    async def get_topic_stats(
        self,
        topic: str,
        days: int = 90
    ) -> Dict:
        """
        Get aggregate statistics for a topic/technology.

        Args:
            topic: Topic to analyze
            days: Days to look back

        Returns:
            Dict with topic statistics
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        repos = await self.search_repos_by_topic(
            topic=topic,
            created_after=start_date,
            created_before=end_date,
            sort="stars",
            max_results=200
        )

        if not repos:
            return {
                "topic": topic,
                "error": "No repositories found",
                "repo_count": 0
            }

        total_stars = sum(r.get("stars", 0) for r in repos)
        total_forks = sum(r.get("forks", 0) for r in repos)
        avg_stars = total_stars / len(repos)

        # Language distribution
        languages = defaultdict(int)
        for r in repos:
            lang = r.get("language")
            if lang:
                languages[lang] += 1

        top_languages = sorted(languages.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "topic": topic,
            "period_days": days,
            "repo_count": len(repos),
            "total_stars": total_stars,
            "total_forks": total_forks,
            "avg_stars_per_repo": round(avg_stars, 1),
            "top_languages": dict(top_languages),
            "top_repos": sorted(repos, key=lambda x: x.get("stars", 0), reverse=True)[:5]
        }


# Singleton instance
github_source = GitHubDataSource()
