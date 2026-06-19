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


def render_story_detail_markdown(
    origin: str,
    cluster: dict,
    lang: str = "hu",
) -> str:
    """Render a top-story cluster as Markdown — for chatbots / AI agents that
    sent `Accept: text/markdown` (or `?format=md`). A megosztott link így
    tisztán, idézhetően landol egy chatben: cím + régiós/keret-tálalás +
    idézhető mondat + forráslista. Ugyanaz az adat, mint a HTML-oldalon."""
    def esc(s: str) -> str:
        return (s or "").replace("|", "\\|").replace("\n", " ").strip()

    title = esc(cluster.get("title") or cluster.get("lead_title") or "—")
    lead = esc(cluster.get("lead_summary") or "")
    bias = cluster.get("bias_dist") or {}
    L, C, R = (int(bias.get("L", 0) or 0), int(bias.get("C", 0) or 0),
               int(bias.get("R", 0) or 0))
    n_sources = int(cluster.get("source_count") or 0)
    spheres = cluster.get("sphere_set") or []
    sphere = spheres[0] if spheres else ""
    cid = cluster.get("cluster_id") or ""
    languages = cluster.get("languages") or []
    dominant_frame = esc(cluster.get("dominant_frame") or "")
    frame_dist = cluster.get("frame_dist") or {}
    first_pub = (cluster.get("first_published") or "")[:16].replace("T", " ")
    latest_pub = (cluster.get("latest_published") or "")[:16].replace("T", " ")
    articles = cluster.get("articles") or []

    # Idézhető mondat (citable) — egyetlen, önmagában megálló állítás, amit egy
    # AI/ember szó szerint beidézhet. NEM LLM-ből: a precomputed adatból.
    pol_parts = [s for s in (f"{L}% bal" if L else "",
                             f"{C}% közép" if C else "",
                             f"{R}% jobb" if R else "") if s]
    pol_phrase = ", ".join(pol_parts) if pol_parts else "nincs osztályozott megoszlás"
    citable = (
        f"Az Echolot szerint a(z) „{title}” témát {n_sources} forrás "
        f"dolgozta fel {len(languages) or 1} nyelven; a politikai-spektrum "
        f"megoszlás: {pol_phrase}."
    )

    lines: list[str] = [
        f"# {title}",
        "",
        f"> {citable}",
        "",
    ]
    if lead:
        lines += [lead, ""]

    lines += [
        "## Tálalás (Echolot)",
        "",
        f"- **Források**: {n_sources}",
        f"- **Politikai spektrum**: L {L}% · C {C}% · R {R}%",
    ]
    if dominant_frame:
        lines.append(f"- **Domináns keret**: {dominant_frame}")
    if sphere:
        lines.append(f"- **Hírrégió**: `{sphere}`")
    if languages:
        lines.append(f"- **Nyelvek**: {', '.join(esc(x) for x in languages)}")
    if first_pub:
        span = f"{first_pub}" + (f" → {latest_pub}" if latest_pub and latest_pub != first_pub else "")
        lines.append(f"- **Időszak**: {span}")
    lines.append("")

    if frame_dist:
        lines += ["## Keret-eloszlás", ""]
        for fr, cnt in sorted(frame_dist.items(), key=lambda kv: -int(kv[1] or 0)):
            lines.append(f"- {esc(str(fr))}: {int(cnt or 0)}")
        lines.append("")

    lines += ["## Források", ""]
    if not articles:
        lines.append("_Nincs forrás._")
    else:
        for a in articles:
            d = dict(a)
            at = esc(d.get("title") or "")
            url = d.get("url") or ""
            src = esc(d.get("source_name") or "")
            alang = d.get("language") or ""
            lean = d.get("source_lean") or "unknown"
            pub = (d.get("published_at") or "")[:16].replace("T", " ")
            lines.append(
                f"- [{at}]({url}) · _{src}_ · `{alang}` · lean:{lean} · {pub}"
            )
    lines += [
        "",
        "---",
        "",
        f"HTML: `{origin}/story/{cid}?lang={lang}` · "
        f"OG-kép: `{origin}/og/story/{cid}.png` · "
        f"MCP: `{origin}/mcp` (`narrative_divergence`, `narrative_passport`)",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_analysis_markdown(
    origin: str,
    data: dict,
    query: str = "",
    days: int = 30,
    scope: str = "global",
    lang: str = "hu",
) -> str:
    """Render the /analysis framing+sentiment dashboard as Markdown — for
    chatbots/agents (Accept: text/markdown or ?format=md). Same precomputed
    classifier data as the HTML page, structured for direct LLM consumption."""
    def esc(s) -> str:
        return str(s or "").replace("|", "\\|").replace("\n", " ").strip()

    cov = data.get("classification_coverage") or {}
    frames = data.get("frame_distribution") or {}
    emotions = data.get("emotion_distribution") or {}
    sent = data.get("sentiment") or {}
    sources = data.get("top_sources") or []

    title = f"Echolot — Framing & Sentiment Analysis"
    subj = f"query `{esc(query)}`" if query else f"the {scope} corpus"
    lines: list[str] = [
        f"# {title}",
        "",
        f"> Cross-source framing, emotion and sentiment breakdown for {subj} "
        f"over the last {days} days, computed from the Echolot classifier. "
        f"For programmatic access prefer the MCP server at `{origin}/mcp` "
        f"(`frame_divergence`, `narrative_divergence`).",
        "",
        f"**Classified**: {cov.get('articles_classified', 0)} / "
        f"{cov.get('articles_total', 0)} matched articles "
        f"({cov.get('percent', 0)}%). {esc(cov.get('note', ''))}",
        "",
        "## Sentiment",
        "",
        f"- avg: {sent.get('avg', 0)} · min: {sent.get('min', 0)} · "
        f"max: {sent.get('max', 0)} · n: {sent.get('n', 0)}",
        "",
    ]

    if frames:
        lines += ["## Frame distribution", "", "| Frame | Count |", "| --- | ---: |"]
        for fr, cnt in sorted(frames.items(), key=lambda kv: -int(kv[1] or 0)):
            lines.append(f"| {esc(fr)} | {int(cnt or 0)} |")
        lines.append("")

    if emotions:
        lines += ["## Emotion distribution", "", "| Emotion | Count |", "| --- | ---: |"]
        for em, cnt in sorted(emotions.items(), key=lambda kv: -int(kv[1] or 0)):
            lines.append(f"| {esc(em)} | {int(cnt or 0)} |")
        lines.append("")

    if sources:
        lines += [
            "## Top sources", "",
            "| Source | Lean | Articles | Dominant frame | Avg sentiment |",
            "| --- | --- | ---: | --- | ---: |",
        ]
        for s in sources:
            d = dict(s)
            lines.append(
                f"| {esc(d.get('source'))} | {esc(d.get('lean') or 'unknown')} "
                f"| {int(d.get('articles') or 0)} | {esc(d.get('dominant_frame') or '—')} "
                f"| {d.get('avg_sentiment', 0)} |"
            )
        lines.append("")

    q = f"?query={query}&days={days}" if query else f"?days={days}"
    lines += [
        "---", "",
        f"HTML: `{origin}/analysis{q}` · MCP: `{origin}/mcp`", "",
    ]
    return "\n".join(lines) + "\n"


def render_passport_markdown(
    origin: str,
    passport: dict,
    claim: str = "",
    days: int = 14,
) -> str:
    """Render a narrative_passport as Markdown — for chatbots/agents
    (Accept: text/markdown or ?format=md). Same data as the /passport HTML
    page and the MCP narrative_passport tool, structured for direct quoting."""
    def esc(s) -> str:
        return str(s or "").replace("|", "\\|").replace("\n", " ").strip()

    verdict = passport.get("verdict") or {}
    origin_b = passport.get("origin") or {}
    cov = passport.get("coverage_stats") or {}
    vel = passport.get("velocity") or {}
    matrix = passport.get("corroboration_matrix") or {}
    citations = passport.get("citations") or []
    nclaim = esc(passport.get("normalized_claim") or claim or "—")

    lines: list[str] = [
        f"# Narrative Passport — {nclaim}",
        "",
        f"> {esc(verdict.get('one_line') or '')}",
        "",
        f"**Verdict**: {esc(verdict.get('corroboration_level') or 'unknown')} "
        f"· confidence {verdict.get('confidence', 0)}",
        "",
        "## Coverage",
        "",
        f"- **Articles analyzed**: {cov.get('articles_analyzed', 0)}",
        f"- **Spheres with coverage**: {cov.get('spheres_with_coverage', 0)} "
        f"of {cov.get('spheres_monitored_live', 0)} monitored",
        f"- **Languages**: {', '.join(esc(x) for x in (cov.get('languages') or [])) or '—'}",
        f"- **Window**: {cov.get('time_window_days', days)} days "
        f"(`{esc(cov.get('fts_query') or '')}`)",
        "",
    ]

    if origin_b:
        lines += [
            "## Origin (first seen)", "",
            f"- **When**: {esc(origin_b.get('first_seen_utc'))}",
            f"- **Source**: {esc(origin_b.get('source'))} "
            f"· sphere `{esc(origin_b.get('sphere'))}`",
        ]
        hl = origin_b.get("headline_original") or ""
        url = origin_b.get("article_url") or ""
        if hl:
            lines.append(f"- **Headline**: [{esc(hl)}]({url})" if url else f"- **Headline**: {esc(hl)}")
        lines.append("")

    if vel:
        lines += [
            "## Velocity", "",
            f"- **Pattern**: {esc(vel.get('pattern') or '—')} "
            f"(×{vel.get('current_multiplier', 0)})",
            f"- {esc(vel.get('pattern_evidence') or '')}",
            "",
        ]

    confirms = matrix.get("confirms") or []
    contradicts = matrix.get("contradicts") or []
    silent = matrix.get("silent") or []
    if confirms or contradicts or silent:
        lines += ["## Corroboration matrix", ""]
        if confirms:
            lines.append(f"- **Confirms** ({len(confirms)}): {', '.join(f'`{esc(x)}`' for x in confirms)}")
        if contradicts:
            lines.append(f"- **Contradicts** ({len(contradicts)}): {', '.join(f'`{esc(x)}`' for x in contradicts)}")
        if silent:
            lines.append(f"- **Silent** ({len(silent)}): {', '.join(f'`{esc(x)}`' for x in silent)}")
        if matrix.get("silence_note"):
            lines.append(f"- _{esc(matrix.get('silence_note'))}_")
        lines.append("")

    if citations:
        lines += ["## Citations", ""]
        for c in citations:
            d = dict(c)
            src = esc(d.get("source"))
            url = d.get("url") or ""
            pub = (d.get("published_utc") or "")[:16].replace("T", " ")
            sph = esc(d.get("sphere"))
            lines.append(f"- [{src}]({url}) · `{sph}` · {pub}" if url
                         else f"- {src} · `{sph}` · {pub}")
        lines.append("")

    _q = f"?claim={claim}&days={days}" if claim else ""
    lines += [
        "---", "",
        f"HTML: `{origin}/passport{_q}` · "
        f"MCP: `{origin}/mcp` (`narrative_passport`)", "",
    ]
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
