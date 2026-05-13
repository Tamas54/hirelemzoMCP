"""Echolot diversity weighting.

Problem: a "fresh last 24h, limit 15" query returned 14 Australian articles
because Sydney Morning Herald was actively pushing. Recency-only mode lets
the most prolific feeds drown out everyone else.

Solution: round-robin selection across (source, sphere), then by recency.

Pure stdlib. No DB access — operates on already-fetched dict lists.

Usage:
    from echolot_diversity import diversify
    rows = [...]  # list of article dicts with 'source_name', 'spheres', 'published_at'
    balanced = diversify(rows, limit=30, max_per_source=3, max_per_sphere=5)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _primary_sphere(article: dict[str, Any]) -> str:
    """Pick a stable single sphere for round-robin bucketing.

    An article can belong to multiple spheres (e.g. ["hu_economy", "global_economy"]).
    For round-robin we need one sphere per article, so we pick the first — the
    list order in spheres_json reflects the source's primary classification.
    """
    spheres = article.get("spheres") or []
    return spheres[0] if spheres else "unknown"


def diversify(
    articles: list[dict[str, Any]],
    limit: int = 30,
    max_per_source: int = 3,
    max_per_sphere: int = 5,
    enabled: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Round-robin selection across source and sphere.

    Args:
        articles: pre-fetched article dicts, already sorted by recency (newest first).
        limit: how many to return.
        max_per_source: hard cap on articles from any single source.
        max_per_sphere: hard cap on articles from any single primary sphere.
        enabled: if False, just slice to `limit` (raw recency).

    Returns:
        (selected_articles, stats_dict)
        stats_dict has: {diversified, pool_size, returned, distinct_sources, distinct_spheres}
    """
    if not enabled or not articles:
        out = articles[:limit]
        return out, {
            "diversified": False,
            "pool_size": len(articles),
            "returned": len(out),
            "distinct_sources": len({a.get("source_name", "") for a in out}),
            "distinct_spheres": len({_primary_sphere(a) for a in out}),
        }

    selected: list[dict[str, Any]] = []
    per_source: dict[str, int] = defaultdict(int)
    per_sphere: dict[str, int] = defaultdict(int)
    last_source: str | None = None

    # Round-robin pass: prefer articles whose source differs from the previous pick.
    remaining = list(articles)
    while remaining and len(selected) < limit:
        picked_idx = None
        # First try: a fresh source that has not hit caps.
        for i, a in enumerate(remaining):
            src = a.get("source_name") or ""
            sph = _primary_sphere(a)
            if src == last_source:
                continue
            if per_source[src] >= max_per_source:
                continue
            if per_sphere[sph] >= max_per_sphere:
                continue
            picked_idx = i
            break
        # Fallback: any article that hasn't hit caps (even if same source as last).
        if picked_idx is None:
            for i, a in enumerate(remaining):
                src = a.get("source_name") or ""
                sph = _primary_sphere(a)
                if per_source[src] >= max_per_source:
                    continue
                if per_sphere[sph] >= max_per_sphere:
                    continue
                picked_idx = i
                break
        # No article passes the caps any more — we're done.
        if picked_idx is None:
            break
        a = remaining.pop(picked_idx)
        selected.append(a)
        src = a.get("source_name") or ""
        sph = _primary_sphere(a)
        per_source[src] += 1
        per_sphere[sph] += 1
        last_source = src

    return selected, {
        "diversified": True,
        "pool_size": len(articles),
        "returned": len(selected),
        "distinct_sources": len({a.get("source_name", "") for a in selected}),
        "distinct_spheres": len({_primary_sphere(a) for a in selected}),
        "max_per_source": max_per_source,
        "max_per_sphere": max_per_sphere,
    }
