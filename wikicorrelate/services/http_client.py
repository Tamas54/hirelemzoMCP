"""
Központi async HTTP client connection pool-lal.
MINDEN service ezt használja Wikipedia API hívásokhoz.

Ez a modul biztosítja:
- Singleton HTTP client a teljes alkalmazáshoz
- Connection pooling (max 100 kapcsolat)
- HTTP/2 multiplexing
- Párhuzamos fetch segédfüggvények
"""
import httpx
import asyncio
from typing import Optional, Dict, Any, List


class AsyncHttpClient:
    """
    Singleton HTTP client connection pool-lal.

    Usage:
        client = await http_client.get_client()
        response = await client.get(url)
    """
    _instance: Optional["AsyncHttpClient"] = None
    _client: Optional[httpx.AsyncClient] = None
    _lock: asyncio.Lock = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._lock = asyncio.Lock()
        return cls._instance

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the shared HTTP client."""
        if self._client is None or self._client.is_closed:
            async with self._lock:
                # Double-check after lock
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(30.0, connect=5.0),
                        limits=httpx.Limits(
                            max_connections=100,
                            max_keepalive_connections=50,
                            keepalive_expiry=30.0
                        ),
                        http2=True,  # HTTP/2 multiplexing!
                        headers={
                            'User-Agent': 'WikiCorrelate/2.0 (https://github.com/wikicorrelate; contact@wikicorrelate.com)'
                        }
                    )
        return self._client

    async def close(self):
        """Close the shared HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# Singleton instance
http_client = AsyncHttpClient()


async def fetch_one(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore
) -> tuple[str, Any]:
    """
    Fetch single URL with semaphore rate limiting.

    Returns:
        Tuple of (url, response_json or None)
    """
    async with semaphore:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return url, response.json()
            return url, None
        except Exception:
            return url, None


async def fetch_all_parallel(
    urls: List[str],
    max_concurrent: int = 50
) -> Dict[str, Any]:
    """
    Párhuzamos URL lekérés semaphore-ral.

    Ez a FŐ FÜGGVÉNY amit minden service-nek használnia kell
    tömeges Wikipedia API lekérésekhez!

    Args:
        urls: Lista az URL-ekből
        max_concurrent: Max párhuzamos kérések száma (default: 50)

    Returns:
        Dict: {url: response_json} - csak sikeres válaszok

    Example:
        urls = [
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/...",
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/...",
        ]
        results = await fetch_all_parallel(urls, max_concurrent=50)
    """
    if not urls:
        return {}

    client = await http_client.get_client()
    semaphore = asyncio.Semaphore(max_concurrent)

    tasks = [fetch_one(client, url, semaphore) for url in urls]
    results = await asyncio.gather(*tasks)

    return {url: data for url, data in results if data is not None}


async def fetch_with_keys(
    url_key_pairs: Dict[str, str],
    max_concurrent: int = 50
) -> Dict[str, Any]:
    """
    Párhuzamos URL lekérés, eredményeket kulcsokhoz rendelve.

    Args:
        url_key_pairs: Dict ahol key=url, value=eredmény kulcs
        max_concurrent: Max párhuzamos kérések

    Returns:
        Dict: {result_key: response_json}

    Example:
        url_key_pairs = {
            "https://api.../Bitcoin/...": "Bitcoin",
            "https://api.../Ethereum/...": "Ethereum",
        }
        results = await fetch_with_keys(url_key_pairs)
        # Returns: {"Bitcoin": {...}, "Ethereum": {...}}
    """
    if not url_key_pairs:
        return {}

    client = await http_client.get_client()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_mapped(url: str, key: str) -> tuple[str, Any]:
        async with semaphore:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return key, response.json()
                return key, None
            except Exception:
                return key, None

    tasks = [fetch_mapped(url, key) for url, key in url_key_pairs.items()]
    results = await asyncio.gather(*tasks)

    return {key: data for key, data in results if data is not None}
