"""
Database module for Correlate-App
SQLite with async support via aiosqlite
"""
import aiosqlite
from datetime import datetime
from pathlib import Path
from wikicorrelate.config import DATABASE_PATH

async def get_db():
    """Get async database connection"""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db

async def init_db():
    """Initialize database tables"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Articles table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                description TEXT,
                avg_daily_views REAL,
                last_updated DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Timeseries table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS timeseries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                date DATE NOT NULL,
                views INTEGER NOT NULL,
                FOREIGN KEY (article_id) REFERENCES articles(id),
                UNIQUE(article_id, date)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_timeseries_article_date ON timeseries(article_id, date)")

        # Correlations table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS correlations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_a_id INTEGER NOT NULL,
                article_b_id INTEGER NOT NULL,
                correlation_score REAL NOT NULL,
                p_value REAL,
                calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (article_a_id) REFERENCES articles(id),
                FOREIGN KEY (article_b_id) REFERENCES articles(id),
                UNIQUE(article_a_id, article_b_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_correlations_article_a ON correlations(article_a_id, correlation_score DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_correlations_score ON correlations(correlation_score DESC)")

        # Search cache table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                results_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_search_cache_query ON search_cache(query)")

        # Trending table (for top movers)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trending (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_a_id INTEGER NOT NULL,
                article_b_id INTEGER NOT NULL,
                article_a_title TEXT,
                article_b_title TEXT,
                correlation_score REAL,
                correlation_change REAL,
                date DATE NOT NULL,
                FOREIGN KEY (article_a_id) REFERENCES articles(id),
                FOREIGN KEY (article_b_id) REFERENCES articles(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_trending_date ON trending(date DESC, correlation_change DESC)")

        # ===== USER TABLES =====

        # Users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                password_hash TEXT NOT NULL,
                tier TEXT DEFAULT 'free',
                api_key TEXT UNIQUE,
                daily_queries_used INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login DATETIME
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key)")

        # Saved searches table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                mode TEXT DEFAULT 'normal',
                days INTEGER DEFAULT 365,
                notify_on_change BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_run DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_saved_searches_user ON saved_searches(user_id)")

        # Alerts table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                alert_type TEXT NOT NULL,
                topic TEXT NOT NULL,
                threshold REAL DEFAULT 0.1,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_triggered DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id)")

        # Report configurations table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS report_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                frequency TEXT DEFAULT 'weekly',
                topics_json TEXT,
                include_predictive BOOLEAN DEFAULT 1,
                include_surprising BOOLEAN DEFAULT 1,
                email_delivery BOOLEAN DEFAULT 1,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_sent DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_report_configs_user ON report_configs(user_id)")

        # Embed widgets table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS embed_widgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                widget_key TEXT UNIQUE NOT NULL,
                topic TEXT NOT NULL,
                widget_type TEXT DEFAULT 'chart',
                theme TEXT DEFAULT 'dark',
                width INTEGER DEFAULT 600,
                height INTEGER DEFAULT 400,
                view_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_embed_widgets_key ON embed_widgets(widget_key)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_embed_widgets_user ON embed_widgets(user_id)")

        # API usage tracking table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date DATE NOT NULL,
                queries INTEGER DEFAULT 0,
                predictive_queries INTEGER DEFAULT 0,
                surprising_queries INTEGER DEFAULT 0,
                embed_views INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, date)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_user_date ON api_usage(user_id, date)")

        await db.commit()
        print("Database initialized successfully")

# Helper functions for common operations
async def get_article_by_title(title: str):
    """Get article by title"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM articles WHERE title = ?", (title,)
        )
        return await cursor.fetchone()

async def insert_article(title: str, description: str = None, avg_daily_views: float = None):
    """Insert or update article"""
    slug = title.lower().replace(" ", "_").replace("(", "").replace(")", "")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO articles (title, slug, description, avg_daily_views, last_updated)
            VALUES (?, ?, ?, ?, ?)
        """, (title, slug, description, avg_daily_views, datetime.now()))
        await db.commit()

async def get_cached_search(query: str, max_age_seconds: int = 3600):
    """Get cached search results if fresh enough"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT results_json, created_at FROM search_cache
            WHERE query = ? AND datetime(created_at) > datetime('now', ?)
            ORDER BY created_at DESC LIMIT 1
        """, (query.lower(), f'-{max_age_seconds} seconds'))
        return await cursor.fetchone()

async def cache_search_results(query: str, results_json: str):
    """Cache search results"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO search_cache (query, results_json) VALUES (?, ?)
        """, (query.lower(), results_json))
        await db.commit()

async def get_top_movers(limit: int = 10):
    """Get top correlation movers for today"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM trending
            WHERE date = date('now')
            ORDER BY ABS(correlation_change) DESC
            LIMIT ?
        """, (limit,))
        return await cursor.fetchall()
