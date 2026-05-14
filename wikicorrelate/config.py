"""
Correlate-App Configuration
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Paths
# When integrated into Echolot, env vars override the default so the
# wikicorrelate state doesn't collide with Echolot's own data/ folder.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("WIKICORRELATE_DATA_DIR", str(BASE_DIR / "wikicorrelate" / "data")))
DATABASE_PATH = Path(os.getenv("WIKICORRELATE_DB_PATH", str(DATA_DIR / "correlations.db")))

# Create data directory if it doesn't exist
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Wikipedia API
WIKIPEDIA_BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/all-agents"
WIKIPEDIA_USER_AGENT = "CorrelateApp/1.0 (Educational/Research)"
WIKIPEDIA_RATE_LIMIT_DELAY = 0.1  # 100ms between requests

# Correlation settings
DEFAULT_DAYS_LOOKBACK = 365
MAX_DAYS_LOOKBACK = 3650  # ~10 years (Wikipedia API available from July 2015)
MIN_CORRELATION_THRESHOLD = 0.3
MAX_RESULTS = 20

# Cache settings
CACHE_TTL_SECONDS = 3600  # 1 hour for search results
TIMESERIES_CACHE_TTL = 86400  # 24 hours for timeseries

# Rate limiting (free tier)
FREE_TIER_QUERIES_PER_DAY = 20
FREE_TIER_10Y_QUERIES_PER_DAY = 5

# ===== EXTERNAL API KEYS =====

# YouTube Data API v3
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_RATE_LIMIT_DELAY = 0.1  # 100ms between requests

# GitHub API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_RATE_LIMIT_DELAY = 0.1

# Hacker News (no key needed, but rate limit)
HACKERNEWS_RATE_LIMIT_DELAY = 0.2  # Be nice to Firebase

# Arxiv API
ARXIV_RATE_LIMIT_DELAY = 3.0  # 3 seconds as per their guidelines

# Stripe (for payments)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
