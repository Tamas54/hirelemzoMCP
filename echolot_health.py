"""Echolot sphere health monitor.

One job: tell which spheres are alive (green), slowing (yellow), or dead (red).

Status thresholds (configurable):
  green:  latest article < 2h
  yellow: 2h <= latest < 24h
  red:    latest >= 24h, or no articles at all

Pure stdlib. Reads only — never writes the DB.

Usage from Python:
    from echolot_health import compute_health
    report = compute_health("/path/to/echolot.db")

Usage as CLI (quick diag):
    python3 echolot_health.py /path/to/echolot.db
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

GREEN_MAX_MINUTES = 120         # < 2h
YELLOW_MAX_MINUTES = 24 * 60    # < 24h


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_iso_utc(s: str | None) -> datetime | None:
    """Parse any ISO-8601 timestamp into naive UTC datetime.

    Timestamps from RSS feeds carry mixed offsets (+02:00, +10:00, Z). We
    convert everything to UTC so age computation matches reality. A naive
    timestamp (no offset) is assumed to already be UTC.
    """
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _age_minutes(latest: str | None, now_utc: datetime) -> int | None:
    dt = _parse_iso_utc(latest)
    if dt is None:
        return None
    delta = now_utc - dt
    return max(0, int(delta.total_seconds() // 60))


def _age_human(minutes: int | None) -> str:
    if minutes is None:
        return "no articles"
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 24 * 60:
        return f"{minutes // 60}h {minutes % 60}m ago"
    days = minutes // (24 * 60)
    hours = (minutes % (24 * 60)) // 60
    return f"{days}d {hours}h ago"


def _status(minutes: int | None,
            green_max: int = GREEN_MAX_MINUTES,
            yellow_max: int = YELLOW_MAX_MINUTES) -> str:
    if minutes is None:
        return "red"
    if minutes < green_max:
        return "green"
    if minutes < yellow_max:
        return "yellow"
    return "red"


def compute_health(db_path: str | Path,
                   green_max_minutes: int = GREEN_MAX_MINUTES,
                   yellow_max_minutes: int = YELLOW_MAX_MINUTES,
                   top_n: int = 10) -> dict:
    """Compute sphere-by-sphere health report.

    Returns a dict ready to JSON-serialize. Designed to be readable for any
    LLM agent: flat fields, plain strings, no nested magic.
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    conn = _connect(db_path)
    try:
        sphere_sources = conn.execute("""
            SELECT je.value AS sphere, COUNT(*) AS source_count
            FROM sources s, json_each(s.spheres_json) je
            GROUP BY je.value
        """).fetchall()

        # datetime(a.published_at) normalizes mixed-tz ISO strings to UTC so
        # MAX/comparisons are correct regardless of feed origin timezone.
        sphere_articles = conn.execute("""
            SELECT je.value AS sphere,
                   SUM(CASE WHEN datetime(a.published_at) >= datetime('now', '-7 days')
                            THEN 1 ELSE 0 END) AS article_count_7d,
                   SUM(CASE WHEN datetime(a.published_at) >= datetime('now', '-24 hours')
                            THEN 1 ELSE 0 END) AS article_count_24h,
                   MAX(datetime(a.published_at)) AS latest_at
            FROM articles a, json_each(a.spheres_json) je
            GROUP BY je.value
        """).fetchall()

        top_active = conn.execute("""
            SELECT source_id, source_name, COUNT(*) AS articles_24h
            FROM articles
            WHERE datetime(published_at) >= datetime('now', '-24 hours')
            GROUP BY source_id, source_name
            ORDER BY articles_24h DESC
            LIMIT ?
        """, (top_n,)).fetchall()

        slowest = conn.execute("""
            SELECT s.id AS source_id, s.name AS source_name,
                   MAX(datetime(a.published_at)) AS latest_at,
                   COUNT(a.article_id) AS lifetime_count
            FROM sources s
            LEFT JOIN articles a ON a.source_id = s.id
            GROUP BY s.id, s.name
            ORDER BY (latest_at IS NULL) DESC, latest_at ASC
            LIMIT ?
        """, (top_n,)).fetchall()
    finally:
        conn.close()

    sphere_meta: dict[str, dict] = {}
    for row in sphere_sources:
        sphere_meta.setdefault(row["sphere"], {})["source_count"] = row["source_count"]
    for row in sphere_articles:
        m = sphere_meta.setdefault(row["sphere"], {})
        m["article_count_7d"] = row["article_count_7d"]
        m["article_count_24h"] = row["article_count_24h"]
        m["latest_at"] = row["latest_at"]

    spheres_out = []
    summary = {"green": 0, "yellow": 0, "red": 0}
    for sphere, m in sorted(sphere_meta.items()):
        latest_at = m.get("latest_at")
        age = _age_minutes(latest_at, now_utc)
        status = _status(age, green_max_minutes, yellow_max_minutes)
        summary[status] += 1
        spheres_out.append({
            "sphere": sphere,
            "status": status,
            "source_count": m.get("source_count", 0),
            "article_count_24h": m.get("article_count_24h", 0) or 0,
            "article_count_7d": m.get("article_count_7d", 0) or 0,
            "latest_article_at": latest_at,
            "latest_article_age_minutes": age,
            "latest_article_age_human": _age_human(age),
        })
    summary["total"] = len(spheres_out)

    spheres_out.sort(key=lambda r: (
        {"red": 0, "yellow": 1, "green": 2}[r["status"]],
        -(r["latest_article_age_minutes"] or 10**9),
    ))

    top_active_out = [{
        "source_id": r["source_id"],
        "source_name": r["source_name"],
        "articles_24h": r["articles_24h"],
    } for r in top_active]

    slowest_out = []
    for r in slowest:
        age = _age_minutes(r["latest_at"], now_utc)
        slowest_out.append({
            "source_id": r["source_id"],
            "source_name": r["source_name"],
            "latest_article_at": r["latest_at"],
            "latest_article_age_human": _age_human(age),
            "lifetime_article_count": r["lifetime_count"],
        })

    return {
        "checked_at": now_utc.isoformat(timespec="seconds") + "Z",
        "thresholds_minutes": {
            "green_below": green_max_minutes,
            "yellow_below": yellow_max_minutes,
        },
        "summary": summary,
        "spheres": spheres_out,
        "top_active_sources_24h": top_active_out,
        "slowest_sources": slowest_out,
    }


def main(argv: list[str]) -> int:
    db = argv[1] if len(argv) > 1 else "echolot.db"
    if not Path(db).exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 2
    report = compute_health(db)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
