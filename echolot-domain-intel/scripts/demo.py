"""
CLI demo - try the analyzer from the command line.

Usage:
    python scripts/demo.py telex.hu
    python scripts/demo.py telex.hu haaretz.com iz.ru --json
    python scripts/demo.py --refresh  # download today's ranking lists
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from domain_intel import DomainAnalyzer

app = typer.Typer(help="Echolot Domain Intelligence CLI")
console = Console()
logging.basicConfig(level=logging.WARNING)


@app.command()
def analyze(
    domains: list[str] = typer.Argument(..., help="Domains to analyze"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Skip cache, force fresh analysis"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="Don't fetch homepages (faster, offline)"),
    refresh: bool = typer.Option(False, "--refresh", help="Refresh ranking lists first"),
):
    """Analyze one or more domains."""
    asyncio.run(_run(domains, json_output, no_cache, no_fetch, refresh))


async def _run(domains, json_output, no_cache, no_fetch, refresh):
    analyzer = DomainAnalyzer.from_env()

    with console.status("[bold cyan]Loading ranking databases..."):
        results = await analyzer.initialize(download_if_missing=True)

    console.print(f"[dim]Loaded sources:[/dim] {results}")

    if refresh:
        with console.status("[bold yellow]Refreshing ranking lists..."):
            r = await analyzer.refresh_rankings()
        console.print(f"[green]Refresh:[/green] {r}")

    for domain in domains:
        with console.status(f"[bold cyan]Analyzing {domain}..."):
            report = await analyzer.analyze(
                domain,
                use_cache=not no_cache,
                fetch_page=not no_fetch,
            )

        if json_output:
            console.print_json(data=report.model_dump(mode="json"))
        else:
            _print_pretty(report)


def _print_pretty(report):
    tree = Tree(f"[bold cyan]📊 {report.domain}[/bold cyan]" + (" [yellow](cached)[/yellow]" if report.cache_hit else ""))

    # Rank
    rank_branch = tree.add(f"[bold]🏆 Rank[/bold] · confidence: {report.rank.confidence.value}")
    if report.rank.consensus_rank:
        rank_branch.add(f"Consensus: [green]#{report.rank.consensus_rank:,}[/green] ({report.rank.rank_bucket})")
    else:
        rank_branch.add("[red]unranked[/red] (not in any top-1M list)")
    for src in report.rank.sources:
        if src.rank:
            rank_branch.add(f"{src.source}: #{src.rank:,}")
        else:
            rank_branch.add(f"{src.source}: [dim]not ranked[/dim]")

    # Geography
    geo_branch = tree.add(f"[bold]🌍 Geography[/bold] · confidence: {report.geography.confidence.value}")
    if report.geography.primary_country:
        geo_branch.add(f"Primary: [green]{report.geography.primary_country}[/green]")
    for tc in report.geography.top_countries[:5]:
        methods = ", ".join(tc["methods"][:3])
        geo_branch.add(f"{tc['country_code']}: score {tc['score']} ({methods})")

    # Category
    cat_branch = tree.add(f"[bold]🏷️  Category[/bold] · confidence: {report.category.confidence.value}")
    cat_branch.add(f"Primary: [green]{report.category.primary_category or 'unknown'}[/green]")
    if report.category.sub_categories:
        cat_branch.add(f"Subs: {', '.join(report.category.sub_categories)}")
    if report.category.echolot_sphere:
        cat_branch.add(f"Echolot sphere: [magenta]{report.category.echolot_sphere}[/magenta]")
    cat_branch.add(f"Method: [dim]{report.category.classification_method}[/dim]")

    # Country ranks
    if report.geography.country_ranks:
        cr_branch = tree.add("[bold]📍 Country rank[/bold]")
        for cr in report.geography.country_ranks[:5]:
            pct = f" · top {100 - cr.percentile:.2f}%" if cr.percentile is not None else ""
            cr_branch.add(f"{cr.country_code}: #{cr.rank:,}{pct} [dim]({cr.source})[/dim]")

    # Audience
    aud_branch = tree.add(f"[bold]👥 Audience[/bold] · confidence: {report.audience.confidence.value}")
    if report.audience.monthly_uniques_global:
        global_str = f"[green]~{report.audience.monthly_uniques_global:,}[/green] monthly uniques globally"
        if report.audience.monthly_uniques_band:
            lo, hi = report.audience.monthly_uniques_band
            global_str += f" [dim](band: {lo:,}–{hi:,})[/dim]"
        aud_branch.add(global_str)
    else:
        aud_branch.add("[red]No estimate (domain not ranked)[/red]")
    for ca in report.audience.by_country[:5]:
        aud_branch.add(
            f"{ca.country_code}: [cyan]{ca.monthly_uniques:,}[/cyan] uniques "
            f"({ca.pct_of_internet_users:.1f}% of country internet users)"
        )
    aud_branch.add(f"Method: [dim]{report.audience.method}[/dim]")

    # Trend
    trend_branch = tree.add(f"[bold]📈 Trend[/bold] · direction: {report.trend.direction}")
    if report.trend.rank_30d_ago:
        trend_branch.add(f"30d ago: #{report.trend.rank_30d_ago:,}  Δ {report.trend.change_30d:+,}")
    if report.trend.rank_90d_ago:
        trend_branch.add(f"90d ago: #{report.trend.rank_90d_ago:,}  Δ {report.trend.change_90d:+,}")

    # Metadata
    meta = tree.add("[bold]ℹ️  Metadata[/bold]")
    meta.add(f"Reachable: {report.is_reachable}")
    meta.add(f"IP: {report.server_ip or 'n/a'}")
    meta.add(f"Language: {report.detected_language or 'n/a'}")
    meta.add(f"Registrar: {report.whois_registrar or 'n/a'}")
    if report.whois_created:
        meta.add(f"Created: {report.whois_created.date()}")

    console.print(tree)
    console.print(f"[dim]Sources: {', '.join(report.data_sources)}[/dim]")
    console.print()


@app.command()
def refresh():
    """Download today's ranking lists for all sources."""
    asyncio.run(_refresh())


async def _refresh():
    analyzer = DomainAnalyzer.from_env()
    with console.status("[bold yellow]Downloading ranking lists..."):
        results = await analyzer.refresh_rankings()
    table = Table(title="Refresh results")
    table.add_column("Source")
    table.add_column("Status")
    for k, v in results.items():
        table.add_row(k, "[green]ok[/green]" if v else "[red]failed[/red]")
    console.print(table)


@app.command()
def health():
    """Print current status of all loaded sources."""
    asyncio.run(_health())


async def _health():
    analyzer = DomainAnalyzer.from_env()
    await analyzer.initialize(download_if_missing=False)
    table = Table(title="Ranking sources")
    table.add_column("Source")
    table.add_column("Loaded")
    table.add_column("Domains")
    for src in analyzer.ranking_db.sources:
        table.add_row(
            src.name,
            "[green]yes[/green]" if src.is_loaded else "[red]no[/red]",
            f"{len(src._ranks):,}" if src.is_loaded else "-",
        )
    console.print(table)
    console.print(f"\nCache: {analyzer.cache.stats()}")


if __name__ == "__main__":
    app()
