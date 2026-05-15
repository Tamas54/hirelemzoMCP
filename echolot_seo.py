"""SEO helpers for Echolot.

Provides:
  - public_origin(request) — canonical scheme://host (ECHOLOT_PUBLIC_ORIGIN
                              env-var if set, else derived from request)
  - robots_txt(origin)     — robots.txt content (allow all + sitemap link)
  - list_indexable_spheres(db_path) — sphere ids with at least one article
                                       in the last 30d (skip dead spheres)
  - build_sitemap_xml(origin, spheres, langs) — XML string
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape


def public_origin(request) -> str:
    """Resolve the canonical public origin (scheme://host).

    Precedence:
      1. ECHOLOT_PUBLIC_ORIGIN env-var (e.g. "https://echolot.example.com")
      2. X-Forwarded-Proto + Host headers (Railway sets these)
      3. request.url.scheme + request.url.netloc
    """
    env = os.getenv("ECHOLOT_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if env:
        return env
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def robots_txt(origin: str) -> str:
    """robots.txt — allow all crawlers, point to sitemap, disallow /api + /mcp."""
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /api/\n"
        "Disallow: /mcp\n"
        "Disallow: /mcp/\n"
        f"Sitemap: {origin}/sitemap.xml\n"
    )


def list_indexable_spheres(db_path: str) -> list[str]:
    """Return sphere-ids with at least one article in the last 30 days.

    Uses `fetched_at` (UTC ISO, comparable) not `published_at` (mixed-tz,
    SQLite datetime() returns NULL on offset-suffixed values). Comparator
    built with strftime to match the 'T' separator format on both sides.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT spheres_json, COUNT(*) AS n
            FROM articles
            WHERE fetched_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-30 days')
            GROUP BY spheres_json
        """).fetchall()
        conn.close()
    except Exception:
        return []
    import json as _json
    seen: set[str] = set()
    for r in rows:
        try:
            for sph in _json.loads(r["spheres_json"] or "[]"):
                if sph:
                    seen.add(sph)
        except Exception:
            continue
    return sorted(seen)


def build_sitemap_xml(
    origin: str,
    spheres: list[str],
    langs: tuple[str, ...] = ("hu", "en", "de", "es", "zh", "fr"),
    default_lang: str = "hu",
) -> str:
    """Build a sitemap.xml with hreflang alternates on the landing page.

    Includes:
      - Landing (/) with hreflang alternates for all 6 languages
      - /dashboard/trending, /dashboard/spheres, /dashboard/health
      - /dashboard/sphere/{name} for every active sphere
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]

    # Landing — one entry per lang, with full alternates block on each
    alt_block = []
    for lang in langs:
        alt_block.append(
            f'    <xhtml:link rel="alternate" hreflang="{lang}" '
            f'href="{xml_escape(origin)}/?lang={lang}"/>'
        )
    alt_block.append(
        f'    <xhtml:link rel="alternate" hreflang="x-default" '
        f'href="{xml_escape(origin)}/?lang={default_lang}"/>'
    )
    alt_block_s = "\n".join(alt_block)
    for lang in langs:
        lines.extend([
            "  <url>",
            f"    <loc>{xml_escape(origin)}/?lang={lang}</loc>",
            alt_block_s,
            f"    <lastmod>{today}</lastmod>",
            "    <changefreq>hourly</changefreq>",
            "    <priority>1.0</priority>",
            "  </url>",
        ])

    # Dashboard sub-pages (single-lang; the lang-selector switches client-side)
    for path, prio, freq in [
        ("/dashboard/trending", "0.9", "hourly"),
        ("/dashboard/spheres",  "0.8", "daily"),
        ("/dashboard/health",   "0.5", "daily"),
    ]:
        lines.extend([
            "  <url>",
            f"    <loc>{xml_escape(origin)}{path}</loc>",
            f"    <lastmod>{today}</lastmod>",
            f"    <changefreq>{freq}</changefreq>",
            f"    <priority>{prio}</priority>",
            "  </url>",
        ])

    # Per-sphere detail pages
    for sphere in spheres:
        lines.extend([
            "  <url>",
            f"    <loc>{xml_escape(origin)}/dashboard/sphere/{xml_escape(sphere)}</loc>",
            f"    <lastmod>{today}</lastmod>",
            "    <changefreq>hourly</changefreq>",
            "    <priority>0.7</priority>",
            "  </url>",
        ])

    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
