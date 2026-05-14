"""
Daily Correlation Service
Generates a fresh "Correlation of the Day" for the landing page.
Social share bait - surprising correlations that make people go "wait, what?"
"""
import random
import json
from datetime import datetime, date
from typing import Dict, List, Optional
import aiosqlite

from wikicorrelate.services.correlate import (
    find_correlations, calculate_surprise_score,
    CATEGORY_ARTICLES, is_obvious_pair
)
from wikicorrelate.services.topic_expander import calculate_semantic_distance
from wikicorrelate.config import DATABASE_PATH


class DailyCorrelation:
    """
    Generates and manages daily surprising correlations.
    """

    def __init__(self):
        self.fun_fact_templates = [
            "When {a} interest rises, {b} attention follows - but why?",
            "{a} and {b} move together more than you'd expect!",
            "Surprising: {a} predicts {b} with {corr}% correlation",
            "The hidden link between {a} and {b}",
            "Did you know? {a} and {b} are more connected than {a} and its 'obvious' relatives",
            "{a} seekers also care about {b} - the data proves it",
        ]

    async def generate_daily(self, force: bool = False) -> Dict:
        """
        Generate today's surprising correlation.

        1. Pick a random trending/popular topic
        2. Find its most surprising correlation
        3. Save to database
        4. Return the correlation

        Args:
            force: Generate even if today's already exists

        Returns:
            Today's correlation dict
        """
        today = date.today().isoformat()

        # Check if already generated today
        if not force:
            existing = await self.get_today()
            if existing:
                return existing

        # Pick a base topic from random categories
        categories = list(CATEGORY_ARTICLES.keys())
        random.shuffle(categories)

        best_correlation = None
        best_surprise = 0

        # Try a few different base topics
        for category in categories[:3]:
            articles = CATEGORY_ARTICLES[category]
            base_topic = random.choice(articles)

            # Find correlations with other categories
            other_articles = []
            for other_cat, other_arts in CATEGORY_ARTICLES.items():
                if other_cat != category:
                    other_articles.extend(other_arts)

            # Get correlations
            try:
                results = await find_correlations(
                    base_article=base_topic,
                    candidate_articles=other_articles,
                    days=365,
                    threshold=0.4,
                    max_results=50
                )

                for corr in results.get('correlations', []):
                    # Skip obvious pairs
                    if is_obvious_pair(base_topic, corr['title'].replace(" ", "_")):
                        continue

                    # Calculate surprise
                    semantic_dist = calculate_semantic_distance(base_topic, corr['title'])
                    surprise = calculate_surprise_score(
                        base_topic, corr['title'], corr['score']
                    )

                    # Boost for high correlation + high distance
                    combined_score = surprise * abs(corr['score']) * semantic_dist

                    if combined_score > best_surprise:
                        best_surprise = combined_score
                        best_correlation = {
                            "topic_a": base_topic.replace("_", " "),
                            "topic_a_slug": base_topic,
                            "topic_b": corr['title'],
                            "topic_b_slug": corr['title'].replace(" ", "_"),
                            "correlation": corr['score'],
                            "surprise_score": round(surprise * 10, 1),  # Scale to 0-10
                            "semantic_distance": round(semantic_dist, 3),
                            "category_a": category,
                        }

            except Exception as e:
                print(f"Error generating for {base_topic}: {e}")
                continue

        if not best_correlation:
            # Fallback to a hardcoded interesting one
            best_correlation = {
                "topic_a": "Bitcoin",
                "topic_a_slug": "Bitcoin",
                "topic_b": "Gold",
                "topic_b_slug": "Gold",
                "correlation": 0.45,
                "surprise_score": 6.5,
                "semantic_distance": 0.7,
                "category_a": "finance",
            }

        # Generate fun fact
        template = random.choice(self.fun_fact_templates)
        fun_fact = template.format(
            a=best_correlation['topic_a'],
            b=best_correlation['topic_b'],
            corr=int(abs(best_correlation['correlation']) * 100)
        )

        best_correlation['fun_fact'] = fun_fact
        best_correlation['date'] = today
        best_correlation['generated_at'] = datetime.now().isoformat()

        # Save to database
        await self._save_daily(today, best_correlation)

        return best_correlation

    async def _save_daily(self, date_str: str, correlation: Dict) -> None:
        """Save daily correlation to database."""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                INSERT OR REPLACE INTO daily_correlations
                (date, topic_a, topic_b, correlation, surprise_score, sources, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str,
                correlation['topic_a_slug'],
                correlation['topic_b_slug'],
                correlation['correlation'],
                correlation['surprise_score'],
                json.dumps(correlation),  # Full data as JSON
                datetime.now().isoformat()
            ))
            await db.commit()

    async def get_today(self) -> Optional[Dict]:
        """Get today's correlation from database."""
        today = date.today().isoformat()

        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT sources FROM daily_correlations
                WHERE date = ?
            """, (today,))
            row = await cursor.fetchone()

            if row:
                try:
                    return json.loads(row['sources'])
                except json.JSONDecodeError:
                    return None

        return None

    async def get_archive(self, limit: int = 30) -> List[Dict]:
        """
        Get archived daily correlations.

        Args:
            limit: Maximum entries to return

        Returns:
            List of past daily correlations
        """
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT date, topic_a, topic_b, correlation, surprise_score, sources
                FROM daily_correlations
                ORDER BY date DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()

            results = []
            for row in rows:
                try:
                    full_data = json.loads(row['sources'])
                    results.append(full_data)
                except json.JSONDecodeError:
                    results.append({
                        "date": row['date'],
                        "topic_a": row['topic_a'].replace("_", " "),
                        "topic_b": row['topic_b'].replace("_", " "),
                        "correlation": row['correlation'],
                        "surprise_score": row['surprise_score']
                    })

            return results

    async def get_stats(self) -> Dict:
        """Get statistics about daily correlations."""
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total,
                    AVG(correlation) as avg_correlation,
                    AVG(surprise_score) as avg_surprise,
                    MIN(date) as first_date,
                    MAX(date) as last_date
                FROM daily_correlations
            """)
            row = await cursor.fetchone()

            if row:
                return {
                    "total_days": row[0],
                    "avg_correlation": round(row[1] or 0, 4),
                    "avg_surprise_score": round(row[2] or 0, 2),
                    "first_date": row[3],
                    "last_date": row[4]
                }

            return {"total_days": 0}


# Ensure table exists
async def init_daily_correlation_table():
    """Create daily_correlations table if not exists."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_correlations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE UNIQUE NOT NULL,
                topic_a VARCHAR(255) NOT NULL,
                topic_b VARCHAR(255) NOT NULL,
                correlation REAL NOT NULL,
                surprise_score REAL,
                sources TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_correlations_date
            ON daily_correlations(date DESC)
        """)
        await db.commit()


# Singleton instance
daily_correlation = DailyCorrelation()
