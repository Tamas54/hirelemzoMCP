"""
Pydantic schemas for Correlate-App API
"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime

class TimeseriesPoint(BaseModel):
    """Single data point in a timeseries"""
    date: str
    views: int

class CorrelationResult(BaseModel):
    """Single correlation result"""
    title: str
    score: float
    p_value: Optional[float] = None
    avg_daily_views: float
    trend: str  # "up", "down", "stable"
    description: Optional[str] = None
    timeseries: List[TimeseriesPoint]

class SearchResponse(BaseModel):
    """Response for /api/search endpoint"""
    query: str
    query_timeseries: List[TimeseriesPoint]
    correlations: List[CorrelationResult]
    cached: bool = False
    calculated_at: str

class TimeseriesRequest(BaseModel):
    """Request for multiple timeseries"""
    topics: List[str]
    days: int = 365

class TopicTimeseries(BaseModel):
    """Timeseries for a single topic"""
    title: str
    timeseries: List[TimeseriesPoint]
    avg_daily_views: float

class TimeseriesResponse(BaseModel):
    """Response for /api/timeseries endpoint"""
    topics: List[TopicTimeseries]
    start_date: str
    end_date: str

class TopMover(BaseModel):
    """Single top mover correlation"""
    article_a: str
    article_b: str
    correlation: float
    change_24h: float
    direction: str  # "strengthening", "weakening"

class TopMoversResponse(BaseModel):
    """Response for /api/top-movers endpoint"""
    top_movers: List[TopMover]
    updated_at: str

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    database: str
    timestamp: str
