"""
User Models
Basic user account structure for future features.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class UserTier(str, Enum):
    """User subscription tiers"""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UserBase(BaseModel):
    """Base user properties"""
    email: str  # Use str instead of EmailStr to avoid email-validator dependency
    name: Optional[str] = None


class UserCreate(UserBase):
    """Properties for user creation"""
    password: str = Field(..., min_length=8)


class UserLogin(BaseModel):
    """Login credentials"""
    email: str
    password: str


class User(UserBase):
    """Full user model (from database)"""
    id: int
    tier: UserTier = UserTier.FREE
    created_at: datetime
    last_login: Optional[datetime] = None
    api_key: Optional[str] = None
    daily_queries_used: int = 0
    daily_query_limit: int = 10  # Default for free tier
    is_active: bool = True

    class Config:
        from_attributes = True


class UserProfile(BaseModel):
    """Public user profile"""
    id: int
    name: Optional[str]
    tier: UserTier
    created_at: datetime


# ===== SAVED SEARCHES / WATCHLIST =====

class SavedSearch(BaseModel):
    """A saved search query"""
    id: int
    user_id: int
    query: str
    mode: str = "normal"  # "normal" or "surprising"
    days: int = 365
    created_at: datetime
    last_run: Optional[datetime] = None
    notify_on_change: bool = False  # For future alert feature


class SavedSearchCreate(BaseModel):
    """Properties for creating a saved search"""
    query: str
    mode: str = "normal"
    days: int = 365
    notify_on_change: bool = False


# ===== ALERTS / REPORTS =====

class AlertType(str, Enum):
    """Types of alerts"""
    CORRELATION_CHANGE = "correlation_change"  # When a correlation significantly changes
    NEW_PREDICTOR = "new_predictor"  # When a new predictive signal is detected
    SPIKE_DETECTED = "spike_detected"  # When a topic spikes


class Alert(BaseModel):
    """User alert configuration"""
    id: int
    user_id: int
    alert_type: AlertType
    topic: str
    threshold: float = 0.1  # Change threshold to trigger
    is_active: bool = True
    created_at: datetime
    last_triggered: Optional[datetime] = None


class AlertCreate(BaseModel):
    """Properties for creating an alert"""
    alert_type: AlertType
    topic: str
    threshold: float = 0.1


# ===== REPORT SCHEDULE =====

class ReportFrequency(str, Enum):
    """Report delivery frequency"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReportConfig(BaseModel):
    """User report configuration"""
    id: int
    user_id: int
    frequency: ReportFrequency
    topics: List[str]  # Topics to include in report
    include_predictive: bool = True
    include_surprising: bool = True
    email_delivery: bool = True
    is_active: bool = True
    created_at: datetime
    last_sent: Optional[datetime] = None


class ReportConfigCreate(BaseModel):
    """Properties for creating a report config"""
    frequency: ReportFrequency
    topics: List[str]
    include_predictive: bool = True
    include_surprising: bool = True
    email_delivery: bool = True


# ===== EMBED WIDGETS =====

class EmbedWidget(BaseModel):
    """Embeddable widget for external sites"""
    id: int
    user_id: int
    widget_key: str  # Unique key for embed URL
    topic: str
    widget_type: str = "chart"  # "chart", "correlations", "predictive"
    theme: str = "dark"  # "dark" or "light"
    width: int = 600
    height: int = 400
    created_at: datetime
    view_count: int = 0


class EmbedWidgetCreate(BaseModel):
    """Properties for creating an embed widget"""
    topic: str
    widget_type: str = "chart"
    theme: str = "dark"
    width: int = 600
    height: int = 400


# ===== API USAGE =====

class APIUsage(BaseModel):
    """API usage tracking"""
    user_id: int
    date: str
    queries: int
    predictive_queries: int
    surprising_queries: int
    embed_views: int


# ===== TIER LIMITS =====

TIER_LIMITS = {
    UserTier.FREE: {
        "daily_queries": 10,
        "saved_searches": 3,
        "alerts": 1,
        "reports": False,
        "embeds": 1,
        "history_days": 365,
    },
    UserTier.PRO: {
        "daily_queries": 100,
        "saved_searches": 20,
        "alerts": 10,
        "reports": True,
        "embeds": 10,
        "history_days": 3650,  # 10 years
    },
    UserTier.ENTERPRISE: {
        "daily_queries": -1,  # Unlimited
        "saved_searches": -1,
        "alerts": -1,
        "reports": True,
        "embeds": -1,
        "history_days": 3650,
    }
}
