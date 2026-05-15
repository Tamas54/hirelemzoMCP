"""HTTP content negotiation for AI agents.

Lets agents that don't want to parse HTML send `Accept: text/markdown`
or `Accept: application/json` on the dashboard pages and receive
structured responses instead.

Precedence rules (q-value parsing kept simple):
  1. text/markdown explicitly listed → markdown
  2. application/json explicitly listed AND text/html NOT listed → json
  3. anything else (or text/html, or browser default */*) → html
"""
from __future__ import annotations


def prefers_format(request, default: str = "html") -> str:
    """Return one of "html", "markdown", "json" based on Accept header.

    Browsers always send Accept: text/html (or */*), so they get HTML.
    Curl with no headers gets HTML too. Agents that explicitly opt in
    via Accept: text/markdown or application/json get the structured
    response.

    Override: ?format=md|json|html in the query string forces a format
    (useful for sharing markdown links).
    """
    qfmt = (getattr(request, "query_params", None) or {}).get("format", "").strip().lower()
    if qfmt in ("md", "markdown"):
        return "markdown"
    if qfmt == "json":
        return "json"
    if qfmt == "html":
        return "html"

    accept = ""
    try:
        accept = (request.headers.get("accept") or "").lower()
    except Exception:
        return default

    has_html = "text/html" in accept
    has_md   = "text/markdown" in accept
    has_json = "application/json" in accept or "application/ld+json" in accept

    if has_md:
        return "markdown"
    if has_json and not has_html:
        return "json"
    return default


def render_sphere_detail_markdown(
    origin: str,
    sphere_name: str,
    articles: list,
    sources: list,
    page: int,
    total_pages: int,
    total_articles: int,
) -> str:
    """Render a sphere-detail page as Markdown — for AI agents that
    sent Accept: text/markdown. Same data as the HTML page, structured
    for direct LLM consumption."""
    lines: list[str] = [
        f"# Echolot · `{sphere_name}`",
        "",
        f"> News-feed page for the **{sphere_name}** information sphere — "
        f"part of the Echolot multi-perspective news intelligence corpus. "
        f"For ongoing agent work, prefer the MCP server at `{origin}/mcp` "
        f"(call `get_news(sphere=\"{sphere_name}\")` or "
        f"`narrative_divergence(query=…)`).",
        "",
        f"**Stats**: {total_articles} articles indexed · {len(sources)} sources",
        f"**This page**: page {page} of {total_pages} (30 articles per page)",
        "",
        "## Related URLs",
        "",
        f"- JSON: `{origin}/api/news?spheres={sphere_name}&limit=80`",
        f"- HTML: `{origin}/dashboard/sphere/{sphere_name}`",
        f"- MCP endpoint: `{origin}/mcp`",
        f"- All spheres: `{origin}/dashboard/spheres`",
        "",
        "## Recent articles",
        "",
    ]
    if not articles:
        lines.append("_No articles in this sphere yet._")
    else:
        for a in articles:
            d = dict(a)
            title = (d.get("title") or "").replace("|", "\\|").replace("\n", " ").strip()
            url = d.get("url") or ""
            src = d.get("source_name") or ""
            lang = d.get("language") or ""
            published = (d.get("published_at") or "")[:16].replace("T", " ")
            trust = d.get("trust_tier") or 2
            lean = d.get("lean") or "unknown"
            lines.append(
                f"- [{title}]({url}) · _{src}_ · `{lang}` · "
                f"trust:T{trust} · lean:{lean} · {published}"
            )
    if total_pages > 1:
        lines.append("")
        lines.append("## Pagination")
        lines.append("")
        if page > 1:
            prev_q = "" if page == 2 else f"?page={page-1}"
            lines.append(f"- Previous: `{origin}/dashboard/sphere/{sphere_name}{prev_q}`")
        if page < total_pages:
            lines.append(f"- Next: `{origin}/dashboard/sphere/{sphere_name}?page={page+1}`")
    lines.append("")
    lines.append("## Sources in this sphere")
    lines.append("")
    if not sources:
        lines.append("_No sources mapped to this sphere._")
    else:
        for s in sources:
            d = dict(s)
            sname = d.get("name") or ""
            slean = d.get("lean") or "unknown"
            strust = d.get("trust_tier") or 2
            slang = d.get("language") or ""
            sn = d.get("n") or 0
            lines.append(f"- **{sname}** · trust:T{strust} · lean:{slean} · `{slang}` · {sn} articles")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_spheres_listing_markdown(
    origin: str,
    spheres_with_counts: list,
) -> str:
    """Render the spheres-listing page as Markdown."""
    lines: list[str] = [
        "# Echolot — Information Spheres",
        "",
        "> Every news source in Echolot belongs to one or more "
        "*information spheres* — groupings by editorial perspective, "
        "regional alignment, or regime affiliation. Click a sphere "
        "to see its article feed.",
        "",
        f"**Total spheres**: {len(spheres_with_counts)}",
        "",
        f"For programmatic access, prefer the MCP server at `{origin}/mcp` "
        f"(`get_spheres()` or `narrative_divergence(query=…)`) "
        f"— or the REST endpoint at `{origin}/api/spheres`.",
        "",
        "## All spheres",
        "",
        "| Sphere | Articles | Sources | Latest |",
        "| --- | ---: | ---: | --- |",
    ]
    for r in spheres_with_counts:
        d = dict(r)
        sphere = d.get("sphere") or ""
        n_art = d.get("article_count") or 0
        n_src = d.get("source_count") or 0
        latest = (d.get("latest_at") or "")[:16].replace("T", " ")
        lines.append(
            f"| [`{sphere}`]({origin}/dashboard/sphere/{sphere}) "
            f"| {n_art} | {n_src} | {latest} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"
