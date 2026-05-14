"""
Smart Expander Service - Intelligent topic expansion for correlation search.

Layer 3 of Category Expansion:
- Expands topics using Wikipedia links
- Uses Wikidata for related entities
- Combines with existing DuckDuckGo expander
"""
import httpx
import asyncio
from typing import List, Set, Dict, Optional
from datetime import datetime

from wikicorrelate.config import WIKIPEDIA_USER_AGENT


class SmartExpander:
    """
    Intelligent topic expansion using Wikipedia and Wikidata.

    Features:
    - Wikipedia article links extraction
    - Wikipedia "See also" section parsing
    - Wikidata entity relationships
    - Combines multiple expansion strategies
    """

    def __init__(self):
        self.user_agent = WIKIPEDIA_USER_AGENT
        self._cache: Dict[str, List[str]] = {}  # In-memory cache for session
        self._client: httpx.AsyncClient = None  # Shared HTTP client
        self._client_lock = asyncio.Lock()  # Lock for client creation

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create a shared HTTP client with connection pooling"""
        if self._client is None or self._client.is_closed:
            async with self._client_lock:
                # Double-check after acquiring lock
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        timeout=30.0,
                        limits=httpx.Limits(
                            max_connections=50,
                            max_keepalive_connections=25
                        ),
                        headers={'User-Agent': self.user_agent}
                    )
        return self._client

    async def close(self):
        """Close the shared HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_related_articles(
        self,
        article: str,
        max_depth: int = 1,
        max_per_level: int = 50
    ) -> List[str]:
        """
        Get related articles by traversing Wikipedia links.

        Args:
            article: Base article name
            max_depth: How many levels of links to follow (1 = direct links only)
            max_per_level: Max articles to process per level

        Returns:
            List of related article names
        """
        # Check cache
        cache_key = f"{article}:{max_depth}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        related = set()
        to_process = {article}
        processed = set()

        client = await self._get_client()
        for depth in range(max_depth):
            next_level = set()

            for current in list(to_process)[:max_per_level]:
                if current in processed:
                    continue
                processed.add(current)

                # Get links from this article
                links = await self._get_wikipedia_links(client, current)
                related.update(links)

                # Prepare next level (only for deeper searches)
                if depth < max_depth - 1:
                    next_level.update(links[:10])  # Top 10 for next level

            to_process = next_level

        result = list(related - {article})

        # Cache result
        self._cache[cache_key] = result

        return result

    async def _get_wikipedia_links(
        self,
        client: httpx.AsyncClient,
        article: str,
        limit: int = 100
    ) -> List[str]:
        """
        Get outgoing links from a Wikipedia article.

        Args:
            client: HTTP client
            article: Article name
            limit: Maximum links to return

        Returns:
            List of linked article names
        """
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "titles": article.replace("_", " "),
            "prop": "links",
            "pllimit": str(limit),
            "plnamespace": "0",  # Main namespace only
            "format": "json"
        }

        try:
            response = await client.get(
                url,
                params=params,
                headers={'User-Agent': self.user_agent}
            )

            if response.status_code == 200:
                data = response.json()
                pages = data.get("query", {}).get("pages", {})

                links = []
                for page in pages.values():
                    for link in page.get("links", []):
                        title = link.get("title", "")
                        # Skip meta pages
                        if title and ":" not in title:
                            links.append(title.replace(" ", "_"))

                return links

        except Exception as e:
            print(f"Error getting links for {article}: {e}")

        return []

    async def get_see_also(self, article: str) -> List[str]:
        """
        Get articles from the "See also" section.

        These are usually the most relevant related articles.

        Args:
            article: Article name

        Returns:
            List of "See also" article names
        """
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "parse",
            "page": article.replace("_", " "),
            "prop": "sections",
            "format": "json"
        }

        try:
            client = await self._get_client()
            response = await client.get(url, params=params)

            if response.status_code != 200:
                return []

            data = response.json()
            sections = data.get("parse", {}).get("sections", [])

            # Find "See also" section
            see_also_index = None
            for section in sections:
                if section.get("line", "").lower() == "see also":
                    see_also_index = section.get("index")
                    break

            if not see_also_index:
                return []

            # Get section content
            params2 = {
                "action": "parse",
                "page": article.replace("_", " "),
                "prop": "links",
                "section": see_also_index,
                "format": "json"
            }

            response2 = await client.get(url, params=params2)

            if response2.status_code == 200:
                data2 = response2.json()
                links = data2.get("parse", {}).get("links", [])
                return [
                    link.get("*", "").replace(" ", "_")
                    for link in links
                    if link.get("ns") == 0 and link.get("exists")
                ]

        except Exception as e:
            print(f"Error getting See Also for {article}: {e}")

        return []

    async def get_wikidata_related(self, article: str) -> List[str]:
        """
        Get related articles from Wikidata entity relationships.

        Uses properties like:
        - P31: instance of
        - P279: subclass of
        - P361: part of
        - P527: has part
        - P1889: different from
        - P460: said to be same as

        Args:
            article: Wikipedia article name

        Returns:
            List of related Wikipedia article names
        """
        client = await self._get_client()

        # First, get the Wikidata entity ID
        entity_id = await self._get_wikidata_id(client, article)
        if not entity_id:
            return []

        # Get related entities
        related_ids = await self._get_wikidata_relations(client, entity_id)

        # Convert back to Wikipedia article names
        related_articles = []
        for qid in related_ids[:30]:  # Limit to 30
            wiki_title = await self._get_wikipedia_title(client, qid)
            if wiki_title:
                related_articles.append(wiki_title)

        return related_articles

    async def _get_wikidata_id(
        self,
        client: httpx.AsyncClient,
        article: str
    ) -> Optional[str]:
        """Get Wikidata entity ID for a Wikipedia article."""
        url = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "wbgetentities",
            "sites": "enwiki",
            "titles": article.replace("_", " "),
            "props": "info",
            "format": "json"
        }

        try:
            response = await client.get(
                url,
                params=params,
                headers={'User-Agent': self.user_agent}
            )

            if response.status_code == 200:
                data = response.json()
                entities = data.get("entities", {})
                for entity_id in entities:
                    if entity_id != "-1":
                        return entity_id

        except Exception as e:
            print(f"Error getting Wikidata ID for {article}: {e}")

        return None

    async def _get_wikidata_relations(
        self,
        client: httpx.AsyncClient,
        entity_id: str
    ) -> List[str]:
        """Get related entity IDs from Wikidata claims."""
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"

        try:
            response = await client.get(
                url,
                headers={'User-Agent': self.user_agent}
            )

            if response.status_code != 200:
                return []

            data = response.json()
            entity = data.get("entities", {}).get(entity_id, {})
            claims = entity.get("claims", {})

            related = set()

            # Properties that indicate related entities
            relation_props = [
                "P31",   # instance of
                "P279",  # subclass of
                "P361",  # part of
                "P527",  # has part
                "P1889", # different from (related but different)
                "P460",  # said to be same as
                "P1382", # coincides with
                "P1542", # has effect
                "P1536", # immediate cause
                "P737",  # influenced by
            ]

            for prop in relation_props:
                if prop in claims:
                    for claim in claims[prop]:
                        mainsnak = claim.get("mainsnak", {})
                        datavalue = mainsnak.get("datavalue", {})
                        if datavalue.get("type") == "wikibase-entityid":
                            value = datavalue.get("value", {})
                            qid = value.get("id")
                            if qid:
                                related.add(qid)

            return list(related)

        except Exception as e:
            print(f"Error getting Wikidata relations for {entity_id}: {e}")

        return []

    async def _get_wikipedia_title(
        self,
        client: httpx.AsyncClient,
        entity_id: str
    ) -> Optional[str]:
        """Get Wikipedia article title from Wikidata entity ID."""
        url = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "wbgetentities",
            "ids": entity_id,
            "props": "sitelinks",
            "sitefilter": "enwiki",
            "format": "json"
        }

        try:
            response = await client.get(
                url,
                params=params,
                headers={'User-Agent': self.user_agent}
            )

            if response.status_code == 200:
                data = response.json()
                entity = data.get("entities", {}).get(entity_id, {})
                sitelinks = entity.get("sitelinks", {})
                enwiki = sitelinks.get("enwiki", {})
                title = enwiki.get("title")
                if title:
                    return title.replace(" ", "_")

        except Exception as e:
            pass  # Silently fail for individual lookups

        return None

    async def get_categories(self, article: str) -> List[str]:
        """
        Get categories that an article belongs to.

        Args:
            article: Article name

        Returns:
            List of category names (without "Category:" prefix)
        """
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "titles": article.replace("_", " "),
            "prop": "categories",
            "cllimit": "50",
            "clshow": "!hidden",  # Exclude hidden categories
            "format": "json"
        }

        try:
            client = await self._get_client()
            response = await client.get(url, params=params)

            if response.status_code == 200:
                data = response.json()
                pages = data.get("query", {}).get("pages", {})

                categories = []
                for page in pages.values():
                    for cat in page.get("categories", []):
                        title = cat.get("title", "")
                        if title.startswith("Category:"):
                            categories.append(title[9:])  # Remove prefix

                return categories

        except Exception as e:
            print(f"Error getting categories for {article}: {e}")

        return []

    async def get_articles_in_category(
        self,
        category: str,
        limit: int = 100
    ) -> List[str]:
        """
        Get articles in a Wikipedia category.

        Args:
            category: Category name (without "Category:" prefix)
            limit: Maximum articles to return

        Returns:
            List of article names
        """
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmtype": "page",
            "cmlimit": str(limit),
            "format": "json"
        }

        try:
            client = await self._get_client()
            response = await client.get(url, params=params)

            if response.status_code == 200:
                data = response.json()
                members = data.get("query", {}).get("categorymembers", [])
                return [
                    m.get("title", "").replace(" ", "_")
                    for m in members
                    if m.get("ns") == 0  # Main namespace only
                ]

        except Exception as e:
            print(f"Error getting category members for {category}: {e}")

        return []

    async def expand_all(
        self,
        article: str,
        max_results: int = 100
    ) -> Dict[str, List[str]]:
        """
        Expand topic using all available methods.

        Args:
            article: Base article name
            max_results: Maximum total results

        Returns:
            Dict with expansion results by source
        """
        # Run expansions in parallel
        links_task = self.get_related_articles(article, max_depth=1)
        see_also_task = self.get_see_also(article)
        wikidata_task = self.get_wikidata_related(article)

        links, see_also, wikidata = await asyncio.gather(
            links_task, see_also_task, wikidata_task,
            return_exceptions=True
        )

        # Handle exceptions
        if isinstance(links, Exception):
            links = []
        if isinstance(see_also, Exception):
            see_also = []
        if isinstance(wikidata, Exception):
            wikidata = []

        # Combine and dedupe
        all_related = set()
        all_related.update(links[:50])
        all_related.update(see_also)
        all_related.update(wikidata)

        # Remove self
        all_related.discard(article)

        return {
            "wikipedia_links": links[:50],
            "see_also": see_also,
            "wikidata": wikidata,
            "combined": list(all_related)[:max_results],
            "total_unique": len(all_related)
        }

    def clear_cache(self):
        """Clear the in-memory cache."""
        self._cache.clear()


# Singleton instance
smart_expander = SmartExpander()
