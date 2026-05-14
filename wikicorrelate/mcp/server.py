"""
Correlate MCP Server
Model Context Protocol server for Claude integration.
Exposes correlation analysis tools to Claude.
"""
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional
from datetime import datetime

# MCP Protocol imports
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool,
        TextContent,
        CallToolResult,
    )
except ImportError:
    print("MCP package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Import our services
sys.path.insert(0, str(__file__).rsplit("/", 3)[0])
from wikicorrelate.services.correlate import (
    search_and_correlate,
    find_surprising_correlations,
    find_negative_correlations,
    expanded_search,
    expanded_search_fast,
    expanded_search_deep,
    calculate_cosine_similarity,
    analyze_granger_causality,
)
from wikicorrelate.services.markov_discovery import discover_hidden_connections
from wikicorrelate.services.arxiv_source import arxiv_source
from wikicorrelate.services.youtube_source import youtube_source
from wikicorrelate.services.hackernews_source import hackernews_source
from wikicorrelate.services.github_source import github_source
from wikicorrelate.services.cascade_tracker import cascade_tracker
from wikicorrelate.services.predictive_chains import predictive_chain_finder
from wikicorrelate.services.seo_tools import gap_analysis, seasonal_calendar


# Create MCP server
server = Server("correlate")


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="correlate",
            description="Find Wikipedia topics that correlate with a given topic based on pageview patterns. Returns correlation coefficients and statistical significance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The Wikipedia article/topic to find correlations for (e.g., 'Bitcoin', 'Climate_change')"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to analyze (default: 365, max: 3650)",
                        "default": 365
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10)",
                        "default": 10
                    },
                    "method": {
                        "type": "string",
                        "enum": ["pearson", "cosine"],
                        "description": "Correlation method: 'pearson' (default) or 'cosine'",
                        "default": "pearson"
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="surprising_correlations",
            description="Find unexpected/surprising correlations - topics that correlate but seem unrelated. Great for discovering hidden connections.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The Wikipedia topic to find surprising correlations for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to analyze (default: 365)",
                        "default": 365
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="negative_correlations",
            description="Find topics that move OPPOSITE to the query topic. Useful for finding inverse relationships.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The Wikipedia topic to find negative correlations for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to analyze (default: 365)",
                        "default": 365
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="discover_connections",
            description="Use Markov chain random walk to discover hidden connections between topics. Finds topics reachable through indirect paths with low direct correlation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The starting topic to explore from"
                    },
                    "max_steps": {
                        "type": "integer",
                        "description": "Maximum path length to consider (default: 4)",
                        "default": 4
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="granger_causality",
            description="Test if one Wikipedia topic Granger-causes another. Useful for finding predictive relationships.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_a": {
                        "type": "string",
                        "description": "First topic (potential cause)"
                    },
                    "topic_b": {
                        "type": "string",
                        "description": "Second topic (potential effect)"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days to analyze (default: 365)",
                        "default": 365
                    },
                    "max_lag": {
                        "type": "integer",
                        "description": "Maximum lag to test in days (default: 14)",
                        "default": 14
                    }
                },
                "required": ["topic_a", "topic_b"]
            }
        ),
        Tool(
            name="arxiv_papers",
            description="Search for academic papers on Arxiv and get publication trends. Great for research topics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Research topic to search for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to look back (default: 365)",
                        "default": 365
                    },
                    "category": {
                        "type": "string",
                        "description": "Arxiv category filter (e.g., 'cs.AI', 'cs.LG', 'physics')",
                        "default": None
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum papers to return (default: 20)",
                        "default": 20
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="arxiv_stats",
            description="Get aggregate statistics for a research topic on Arxiv including top categories and prolific authors.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Research topic to analyze"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to look back (default: 365)",
                        "default": 365
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="youtube_trends",
            description="Get YouTube video upload trends and view statistics for a topic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic to search YouTube for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to look back (default: 30)",
                        "default": 30
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum videos to sample (default: 20)",
                        "default": 20
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="hackernews_buzz",
            description="Get Hacker News story trends for a topic. Tracks tech community interest.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic to search Hacker News for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to look back (default: 30)",
                        "default": 30
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum stories to return (default: 20)",
                        "default": 20
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="github_activity",
            description="Get GitHub repository activity for a topic. Tracks developer interest.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic to search GitHub for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to look back (default: 30)",
                        "default": 30
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum repos to return (default: 20)",
                        "default": 20
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="cascade_analysis",
            description="Track how attention spreads across platforms (Wikipedia -> HackerNews -> YouTube -> GitHub). Shows the cascade pattern of a topic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic to track across platforms"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to look back (default: 30)",
                        "default": 30
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="predictive_chain",
            description="Test if Wikipedia interest predicts price movements. Uses yfinance for price data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "description": "Wikipedia topic that might predict prices"
                    },
                    "ticker": {
                        "type": "string",
                        "description": "Financial ticker symbol (e.g., 'BTC-USD', 'ETH-USD', '^GSPC')",
                        "default": "BTC-USD"
                    },
                    "lag_days": {
                        "type": "integer",
                        "description": "Days to look ahead for prediction (default: 7)",
                        "default": 7
                    },
                    "days": {
                        "type": "integer",
                        "description": "Historical days to analyze (default: 365)",
                        "default": 365
                    }
                },
                "required": ["trigger"]
            }
        ),
        Tool(
            name="find_signals",
            description="Find active predictive signals - Wikipedia topics currently spiking that historically predict price movements.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Financial ticker to find signals for (default: 'BTC-USD')",
                        "default": "BTC-USD"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="expanded_search",
            description="Search across 10,000+ Wikipedia articles for correlations. Much wider than basic search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic to find correlations for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to analyze (default: 365)",
                        "default": 365
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["fast", "normal", "deep"],
                        "description": "Search depth: 'fast' (cache only), 'normal', or 'deep' (full expansion)",
                        "default": "normal"
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="cluster_topics",
            description="Cluster correlated topics into semantic groups for content strategy. Perfect for pillar page creation and topic cluster SEO.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic to find and cluster correlations for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days to analyze (default: 365)",
                        "default": 365
                    },
                    "n_clusters": {
                        "type": "integer",
                        "description": "Number of clusters (auto-detect if not specified)",
                        "default": None
                    },
                    "min_correlation": {
                        "type": "number",
                        "description": "Minimum correlation to include (default: 0.3)",
                        "default": 0.3
                    },
                    "method": {
                        "type": "string",
                        "enum": ["kmeans", "hierarchical"],
                        "description": "Clustering method (default: kmeans)",
                        "default": "kmeans"
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="gap_analysis",
            description="Find counter-cyclical content opportunities. Identifies topics that trend UP when your topic trends DOWN - perfect for diversifying traffic and stabilizing content performance.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic to find counter-cyclical opportunities for"
                    },
                    "days": {
                        "type": "integer",
                        "description": "Days of history to analyze (default: 365)",
                        "default": 365
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Minimum inverse correlation threshold, e.g., -0.3 means r < -0.3 (default: -0.5)",
                        "default": -0.5
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default: 20)",
                        "default": 20
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="seasonal_calendar",
            description="Generate a content calendar based on historical seasonality. Analyzes when interest peaks/troughs and recommends optimal publication timing for each month.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic to analyze seasonality for"
                    },
                    "forecast_months": {
                        "type": "integer",
                        "description": "Number of months to forecast ahead (default: 12)",
                        "default": 12
                    }
                },
                "required": ["topic"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
    """Handle tool calls."""
    try:
        if name == "correlate":
            topic = arguments["topic"].replace(" ", "_")
            days = arguments.get("days", 365)
            limit = arguments.get("limit", 10)
            method = arguments.get("method", "pearson")

            if method == "cosine":
                results = await calculate_cosine_similarity(topic, days=days, limit=limit)
            else:
                results = await search_and_correlate(topic, days=days, max_results=limit, method=method)

            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(results, indent=2))]
            )

        elif name == "surprising_correlations":
            topic = arguments["topic"].replace(" ", "_")
            days = arguments.get("days", 365)
            limit = arguments.get("limit", 10)

            results = await find_surprising_correlations(topic, days=days, max_results=limit)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(results, indent=2))]
            )

        elif name == "negative_correlations":
            topic = arguments["topic"].replace(" ", "_")
            days = arguments.get("days", 365)
            limit = arguments.get("limit", 10)

            results = await find_negative_correlations(topic, days=days, max_results=limit)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(results, indent=2))]
            )

        elif name == "discover_connections":
            topic = arguments["topic"]
            max_steps = arguments.get("max_steps", 4)
            limit = arguments.get("limit", 10)

            results = await discover_hidden_connections(topic, max_steps=max_steps, limit=limit)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(results, indent=2))]
            )

        elif name == "granger_causality":
            topic_a = arguments["topic_a"].replace(" ", "_")
            topic_b = arguments["topic_b"].replace(" ", "_")
            days = arguments.get("days", 365)
            max_lag = arguments.get("max_lag", 14)

            results = await analyze_granger_causality(topic_a, topic_b, days=days, max_lag=max_lag)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(results, indent=2))]
            )

        elif name == "arxiv_papers":
            topic = arguments["topic"]
            days = arguments.get("days", 365)
            category = arguments.get("category")
            limit = arguments.get("limit", 20)

            papers = await arxiv_source.get_recent_papers(topic, limit=limit)

            # Format for readability
            result = {
                "topic": topic,
                "paper_count": len(papers),
                "papers": papers[:limit]
            }
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        elif name == "arxiv_stats":
            topic = arguments["topic"]
            days = arguments.get("days", 365)

            stats = await arxiv_source.get_topic_stats(topic, days=days)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(stats, indent=2))]
            )

        elif name == "youtube_trends":
            from datetime import date, timedelta
            topic = arguments["topic"]
            days = arguments.get("days", 30)
            limit = arguments.get("limit", 20)

            end_date = date.today()
            start_date = end_date - timedelta(days=days)

            videos = await youtube_source.search_videos_by_topic(
                topic,
                published_after=start_date,
                published_before=end_date,
                max_results=limit
            )

            # Calculate basic stats from videos
            total_views = sum(v.get('view_count', 0) for v in videos)
            total_likes = sum(v.get('like_count', 0) for v in videos)

            result = {
                "topic": topic,
                "days": days,
                "stats": {
                    "videos_found": len(videos),
                    "total_views": total_views,
                    "total_likes": total_likes,
                    "avg_views": total_views // len(videos) if videos else 0
                },
                "sample_videos": videos[:10]
            }
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        elif name == "hackernews_buzz":
            from datetime import date, timedelta
            topic = arguments["topic"]
            days = arguments.get("days", 30)
            limit = arguments.get("limit", 20)

            end_date = date.today()
            start_date = end_date - timedelta(days=days)

            stories = await hackernews_source.search_stories_by_topic(
                topic,
                from_date=start_date,
                to_date=end_date,
                max_results=limit
            )

            # Calculate stats from stories
            total_points = sum(s.get('score', 0) for s in stories)
            total_comments = sum(s.get('descendants', 0) for s in stories)

            result = {
                "topic": topic,
                "days": days,
                "stats": {
                    "stories_found": len(stories),
                    "total_points": total_points,
                    "total_comments": total_comments,
                    "avg_points": total_points // len(stories) if stories else 0
                },
                "top_stories": stories[:10]
            }
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        elif name == "github_activity":
            topic = arguments["topic"]
            days = arguments.get("days", 30)
            limit = arguments.get("limit", 20)

            repos = await github_source.search_repos_by_topic(topic, max_results=limit)
            stats = await github_source.get_topic_stats(topic, days=days)

            result = {
                "topic": topic,
                "stats": stats,
                "repositories": repos[:limit]
            }
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        elif name == "cascade_analysis":
            topic = arguments["topic"]
            days = arguments.get("days", 30)

            cascade = await cascade_tracker.track_cascade(topic, days=days)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(cascade, indent=2))]
            )

        elif name == "predictive_chain":
            trigger = arguments["trigger"].replace(" ", "_")
            ticker = arguments.get("ticker", "BTC-USD")
            lag_days = arguments.get("lag_days", 7)
            days = arguments.get("days", 365)

            result = await predictive_chain_finder.test_direct_chain(
                trigger_topic=trigger,
                ticker=ticker,
                lag=lag_days,
                days=days
            )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        elif name == "find_signals":
            ticker = arguments.get("ticker", "BTC-USD")

            signals = await predictive_chain_finder.get_active_signals(ticker=ticker)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(signals, indent=2))]
            )

        elif name == "expanded_search":
            topic = arguments["topic"].replace(" ", "_")
            days = arguments.get("days", 365)
            limit = arguments.get("limit", 20)
            mode = arguments.get("mode", "normal")

            if mode == "fast":
                from wikicorrelate.services.correlate import expanded_search_fast
                results = await expanded_search_fast(topic, days=days, limit=limit)
            elif mode == "deep":
                from wikicorrelate.services.correlate import expanded_search_deep
                results = await expanded_search_deep(topic, days=days, limit=limit)
            else:
                results = await expanded_search(topic, days=days, limit=limit)

            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(results, indent=2))]
            )

        elif name == "cluster_topics":
            from wikicorrelate.services.clustering import cluster_correlated_topics

            topic = arguments["topic"]
            days = arguments.get("days", 365)
            n_clusters = arguments.get("n_clusters")
            min_correlation = arguments.get("min_correlation", 0.3)
            method = arguments.get("method", "kmeans")

            result = await cluster_correlated_topics(
                query=topic,
                days=days,
                n_clusters=n_clusters,
                min_correlation=min_correlation,
                method=method
            )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        elif name == "gap_analysis":
            topic = arguments["topic"]
            days = arguments.get("days", 365)
            threshold = arguments.get("threshold", -0.5)
            max_results = arguments.get("max_results", 20)

            result = await gap_analysis(topic, days=days, threshold=threshold)
            # Limit results if needed
            if result.get("gaps") and len(result["gaps"]) > max_results:
                result["gaps"] = result["gaps"][:max_results]
                result["gaps_found"] = max_results

            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        elif name == "seasonal_calendar":
            topic = arguments["topic"]
            forecast_months = arguments.get("forecast_months", 12)

            result = await seasonal_calendar(topic, months=forecast_months)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))]
            )

        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")]
            )

    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")]
        )


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
