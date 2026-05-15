"""SEO helpers for Echolot.

Provides:
  - public_origin(request) — canonical scheme://host (ECHOLOT_PUBLIC_ORIGIN
                              env-var if set, else derived from request)
  - robots_txt(origin)     — robots.txt content (allow all + sitemap link)
  - list_indexable_spheres(db_path) — sphere ids with at least one article
                                       in the last 30d (skip dead spheres)
  - build_sitemap_xml(origin, spheres, langs) — XML string
  - og_image_svg() — placeholder Echolot OG image as SVG (1200×630)
  - seo_head_html(origin, lang, path, langs, og_title, og_description, og_image_url)
      — full <meta> + <link rel=canonical> + <link rel=alternate hreflang>
        + Open Graph + Twitter Card block to inject into the page <head>
  - schema_org_website_html(origin, lang) — JSON-LD <script> for WebSite
  - schema_org_organization_html(origin) — JSON-LD <script> for Organization
  - schema_org_breadcrumb_html(items) — JSON-LD <script> for BreadcrumbList
"""
from __future__ import annotations

import html as _html
import json
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


# ── Open Graph image (placeholder Echolot SVG, 1200×630) ──────────────
_OG_IMAGE_SVG = """\
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0a0e1a"/>
      <stop offset="60%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#1e1b4b"/>
    </linearGradient>
    <radialGradient id="orb" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0%" stop-color="#22d3ee" stop-opacity="0.5"/>
      <stop offset="100%" stop-color="#22d3ee" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <circle cx="200" cy="150" r="180" fill="url(#orb)"/>
  <circle cx="1000" cy="500" r="220" fill="url(#orb)" opacity="0.6"/>
  <text x="600" y="190" font-family="ui-monospace, 'JetBrains Mono', monospace"
        font-size="32" fill="#22d3ee" text-anchor="middle" letter-spacing="6">
    &#x25B7;  E C H O L O T  &#x25C1;
  </text>
  <text x="600" y="320" font-family="ui-sans-serif, system-ui, sans-serif"
        font-size="76" font-weight="700" fill="#f1f5f9" text-anchor="middle">
    Global narrative map
  </text>
  <text x="600" y="395" font-family="ui-sans-serif, system-ui, sans-serif"
        font-size="36" font-weight="500" fill="#94a3b8" text-anchor="middle">
    Globális narratíva-térkép
  </text>
  <text x="600" y="490" font-family="ui-sans-serif, system-ui, sans-serif"
        font-size="22" fill="#64748b" text-anchor="middle">
    315 sources  &#xB7;  63 information spheres  &#xB7;  8 languages
  </text>
  <text x="600" y="570" font-family="ui-monospace, 'JetBrains Mono', monospace"
        font-size="16" fill="#475569" text-anchor="middle">
    open MCP server  &#xB7;  narrative-divergence platform
  </text>
</svg>
"""


def og_image_svg() -> str:
    """Return the placeholder OG image as an SVG string (1200×630)."""
    return _OG_IMAGE_SVG


# ── SEO <head> block: meta + canonical + hreflang + OG + Twitter ──────

def seo_head_html(
    origin: str,
    lang: str,
    path: str,
    *,
    description: str,
    og_title: str,
    og_description: str | None = None,
    og_image_url: str | None = None,
    page_type: str = "website",
    langs: tuple[str, ...] = ("hu", "en", "de", "es", "zh", "fr"),
    default_lang: str = "hu",
    is_lang_switchable: bool = True,
) -> str:
    """Render the SEO <head> block (meta description, canonical, hreflang
    alternates, Open Graph, Twitter Card).

    Args:
        origin: scheme://host (from public_origin())
        lang: current request language (e.g. "en")
        path: request path WITHOUT query string (e.g. "/" or "/dashboard/sphere/hu_press")
        description: meta description (best <= 160 chars)
        og_title: Open Graph title
        og_description: defaults to `description` if None
        og_image_url: full absolute URL to the OG image
        page_type: og:type (website / article / profile)
        langs: which language alternates to emit
        default_lang: x-default hreflang target
        is_lang_switchable: if True, hreflang alternates are rendered
            (use False for sphere-detail / health pages where lang has
            no separate URL — they're a single canonical version)
    """
    og_description = og_description or description
    og_image_url = og_image_url or f"{origin}/static/og-image.svg"

    # OG locale uses xx_XX style (en→en_US, hu→hu_HU, de→de_DE, etc.)
    locale_map = {"hu": "hu_HU", "en": "en_US", "de": "de_DE",
                  "es": "es_ES", "zh": "zh_CN", "fr": "fr_FR"}
    og_locale = locale_map.get(lang, "hu_HU")
    og_alternates = [v for k, v in locale_map.items() if k != lang and k in langs]

    # Build canonical URL. If lang-switchable, the canonical includes ?lang=
    if is_lang_switchable:
        canonical = f"{origin}{path}?lang={lang}"
    else:
        canonical = f"{origin}{path}"

    # Build hreflang block
    hreflang_lines: list[str] = []
    if is_lang_switchable:
        for code in langs:
            href = f"{origin}{path}?lang={code}"
            hreflang_lines.append(
                f'<link rel="alternate" hreflang="{code}" href="{_html.escape(href, quote=True)}">'
            )
        x_default_href = f"{origin}{path}?lang={default_lang}"
        hreflang_lines.append(
            f'<link rel="alternate" hreflang="x-default" href="{_html.escape(x_default_href, quote=True)}">'
        )

    desc_e = _html.escape(description, quote=True)
    og_title_e = _html.escape(og_title, quote=True)
    og_desc_e = _html.escape(og_description, quote=True)
    canonical_e = _html.escape(canonical, quote=True)
    og_image_e = _html.escape(og_image_url, quote=True)

    parts = [
        f'<meta name="description" content="{desc_e}">',
        f'<link rel="canonical" href="{canonical_e}">',
        *hreflang_lines,
        f'<meta property="og:title" content="{og_title_e}">',
        f'<meta property="og:description" content="{og_desc_e}">',
        f'<meta property="og:url" content="{canonical_e}">',
        f'<meta property="og:type" content="{page_type}">',
        f'<meta property="og:site_name" content="Echolot">',
        f'<meta property="og:locale" content="{og_locale}">',
    ]
    for og_alt in og_alternates:
        parts.append(f'<meta property="og:locale:alternate" content="{og_alt}">')
    parts.extend([
        f'<meta property="og:image" content="{og_image_e}">',
        f'<meta property="og:image:width" content="1200">',
        f'<meta property="og:image:height" content="630">',
        f'<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{og_title_e}">',
        f'<meta name="twitter:description" content="{og_desc_e}">',
        f'<meta name="twitter:image" content="{og_image_e}">',
    ])
    return "\n".join(parts) + "\n"


# ── Schema.org JSON-LD ────────────────────────────────────────────────

def _ld_script(payload: dict) -> str:
    """Wrap a JSON-LD payload in a <script type="application/ld+json"> tag.

    The </ in JSON strings (e.g. "</script>") must be escaped to prevent
    early script-tag termination — </ → \\u003c/.
    """
    body = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{body}</script>'


def schema_org_website_html(origin: str, lang: str = "en") -> str:
    """JSON-LD <script> for the WebSite schema with a SearchAction
    (lets Google show a search box in SERP for the brand)."""
    payload = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "Echolot",
        "alternateName": "Echolot — Global narrative map",
        "url": origin,
        "inLanguage": lang,
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{origin}/dashboard?query={{search_term_string}}&lang={lang}",
            },
            "query-input": "required name=search_term_string",
        },
    }
    return _ld_script(payload)


def schema_org_organization_html(origin: str) -> str:
    """JSON-LD <script> for the Makronóm Intézet Organization schema."""
    payload = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Makronóm Intézet",
        "url": "https://makronom.hu",
        "logo": f"{origin}/static/og-image.svg",
        "sameAs": [
            "https://github.com/Tamas54/hirelemzoMCP",
        ],
    }
    return _ld_script(payload)


def schema_org_breadcrumb_html(items: list[tuple[str, str]]) -> str:
    """JSON-LD <script> for a BreadcrumbList.

    Args:
        items: list of (name, absolute_url) tuples in order, e.g.
               [("Home", "https://…/"), ("Spheres", "https://…/dashboard/spheres"),
                ("hu_press", "https://…/dashboard/sphere/hu_press")]
    """
    payload = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
            for i, (name, url) in enumerate(items)
        ],
    }
    return _ld_script(payload)
