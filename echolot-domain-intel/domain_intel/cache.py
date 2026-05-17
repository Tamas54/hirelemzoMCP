"""Simple file-based cache using diskcache."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

import diskcache


class DomainCache:
    """
    File-based cache for domain reports.

    Designed to be replaceable with Redis/ClickHouse in production —
    just match the get/set/delete interface.
    """

    def __init__(self, cache_dir: str | Path, ttl_hours: int = 168):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(str(self.cache_dir))
        self.ttl_seconds = ttl_hours * 3600

    def _key(self, domain: str, suffix: str = "") -> str:
        normalized = domain.lower().strip().lstrip("www.")
        if suffix:
            return f"{normalized}::{suffix}"
        return normalized

    def get(self, domain: str, suffix: str = "") -> Optional[Any]:
        return self._cache.get(self._key(domain, suffix))

    def set(self, domain: str, value: Any, suffix: str = "", ttl: Optional[int] = None) -> None:
        self._cache.set(
            self._key(domain, suffix),
            value,
            expire=ttl or self.ttl_seconds,
        )

    def delete(self, domain: str, suffix: str = "") -> None:
        self._cache.delete(self._key(domain, suffix))

    def clear(self) -> None:
        self._cache.clear()

    def stats(self) -> dict:
        return {
            "size": len(self._cache),
            "volume_bytes": self._cache.volume(),
            "directory": str(self.cache_dir),
        }
