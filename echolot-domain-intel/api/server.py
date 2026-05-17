"""
FastAPI server for the Echolot Domain Intelligence service.

Run:
    uvicorn api.server:app --host 0.0.0.0 --port 8080

Or via Docker (see docker-compose.yml).

Endpoints:
    GET  /health                       - health check
    GET  /domain/{domain}              - full analysis
    GET  /domain/{domain}/rank         - rank info only (faster)
    POST /domain/batch                 - analyze multiple at once
    POST /admin/refresh                - force refresh ranking lists (cron target)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from domain_intel import DomainAnalyzer, DomainReport, StoryReachAggregator, StoryReachReport
from domain_intel.models import RankInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("echolot.domain_intel.api")


# -----------------------------------------------------------------------------
# App lifecycle
# -----------------------------------------------------------------------------
analyzer: Optional[DomainAnalyzer] = None
story_reach: Optional[StoryReachAggregator] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global analyzer, story_reach
    logger.info("Initializing DomainAnalyzer...")
    analyzer = DomainAnalyzer.from_env()
    load_results = await analyzer.initialize(download_if_missing=True)
    logger.info(f"Ranking sources loaded: {load_results}")
    logger.info(
        f"Country indices: {len(analyzer.ranking_db.country_index.loaded_countries)} countries"
    )
    story_reach = StoryReachAggregator()
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Echolot Domain Intelligence",
    description=(
        "Free + commercial-safe domain analysis. Replaces Cloudflare Radar / "
        "Similarweb for the Echolot platform."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# -----------------------------------------------------------------------------
# Auth middleware (optional)
# -----------------------------------------------------------------------------
def check_auth(x_api_key: Optional[str] = Header(None)):
    expected = os.getenv("API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class BatchRequest(BaseModel):
    domains: list[str] = Field(..., min_length=1, max_length=50)
    fetch_page: bool = True
    use_cache: bool = True


class BatchResponse(BaseModel):
    reports: list[DomainReport]
    errors: dict[str, str] = Field(default_factory=dict)


class StoryReachRequest(BaseModel):
    """Sources publishing the same story; we compute total estimated reach."""

    sources: list[str] = Field(
        ..., min_length=1, max_length=200,
        description="Domain names that published the story",
    )
    fetch_page: bool = False
    use_cache: bool = True
    story_visibility: float | None = Field(
        None, ge=0.0, le=1.0,
        description="Override the per-source story visibility fraction (0-1). "
                    "Default: use rank-bucket-based defaults from calibration_data.py.",
    )


class HealthResponse(BaseModel):
    status: str
    ranking_sources: dict
    cache_stats: dict


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    if not analyzer:
        raise HTTPException(status_code=503, detail="Not initialized")
    return HealthResponse(
        status="ok",
        ranking_sources={
            src.name: {
                "loaded": src.is_loaded,
                "size": len(src._ranks) if src.is_loaded else 0,
            }
            for src in analyzer.ranking_db.sources
        },
        cache_stats=analyzer.cache.stats(),
    )


@app.get("/domain/{domain}", response_model=DomainReport)
async def analyze_domain(
    domain: str,
    fetch_page: bool = Query(True, description="Fetch homepage for content signals"),
    use_cache: bool = Query(True, description="Use cached results if available"),
    x_api_key: Optional[str] = Header(None),
):
    """Full domain analysis."""
    check_auth(x_api_key)
    if not analyzer:
        raise HTTPException(status_code=503, detail="Not initialized")
    try:
        return await analyzer.analyze(domain, use_cache=use_cache, fetch_page=fetch_page)
    except Exception as e:
        logger.exception(f"Analysis failed for {domain}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/domain/{domain}/rank", response_model=RankInfo)
async def get_rank_only(
    domain: str,
    x_api_key: Optional[str] = Header(None),
):
    """Fast endpoint: rank only, no page fetch, no WHOIS."""
    check_auth(x_api_key)
    if not analyzer:
        raise HTTPException(status_code=503, detail="Not initialized")
    normalized = analyzer._normalize(domain)
    sources = await analyzer.ranking_db.lookup(normalized)
    return analyzer._aggregate_ranks(sources)


@app.post("/domain/batch", response_model=BatchResponse)
async def batch_analyze(
    req: BatchRequest,
    x_api_key: Optional[str] = Header(None),
):
    """Batch analyze up to 50 domains. Errors are reported per-domain."""
    check_auth(x_api_key)
    if not analyzer:
        raise HTTPException(status_code=503, detail="Not initialized")

    import asyncio
    async def safe_analyze(d: str):
        try:
            return d, await analyzer.analyze(d, use_cache=req.use_cache, fetch_page=req.fetch_page), None
        except Exception as e:
            return d, None, str(e)

    results = await asyncio.gather(*[safe_analyze(d) for d in req.domains])

    reports = []
    errors = {}
    for domain, report, err in results:
        if report:
            reports.append(report)
        else:
            errors[domain] = err or "unknown error"

    return BatchResponse(reports=reports, errors=errors)


@app.post("/story/reach", response_model=StoryReachReport)
async def estimate_story_reach(
    req: StoryReachRequest,
    x_api_key: Optional[str] = Header(None),
):
    """
    Estimate total reach of a story across multiple sources.

    Internally:
      1. Fetch a DomainReport for each source (cached when possible).
      2. Aggregate audience.by_country across sources with overlap discount
         (1 - product of non-reach probabilities).
      3. Return per-country reach + grand total.
    """
    check_auth(x_api_key)
    if not analyzer or not story_reach:
        raise HTTPException(status_code=503, detail="Not initialized")

    import asyncio
    async def safe_analyze(d: str):
        try:
            return await analyzer.analyze(d, use_cache=req.use_cache, fetch_page=req.fetch_page)
        except Exception as e:
            logger.warning(f"reach: analyze failed for {d}: {e}")
            return None

    reports = await asyncio.gather(*[safe_analyze(d) for d in req.sources])
    reports = [r for r in reports if r is not None]
    return story_reach.aggregate(reports, story_visibility_override=req.story_visibility)


@app.post("/admin/refresh")
async def refresh_rankings(x_api_key: Optional[str] = Header(None)):
    """Force a refresh of all ranking lists. Call this from a daily cron."""
    check_auth(x_api_key)
    if not analyzer:
        raise HTTPException(status_code=503, detail="Not initialized")
    return await analyzer.refresh_rankings()


@app.delete("/admin/cache")
async def clear_cache(x_api_key: Optional[str] = Header(None)):
    check_auth(x_api_key)
    if not analyzer:
        raise HTTPException(status_code=503, detail="Not initialized")
    analyzer.cache.clear()
    return {"cleared": True}
