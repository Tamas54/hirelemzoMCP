"""Echolot sphere velocity — what's spiking right now?

For each sphere, compare article volume in a recent window (e.g. last 6h)
to a baseline window (e.g. 24-48h ago = same hour-of-day yesterday).
A velocity_ratio above 1.3 means "rising", above 2.0 means "spike".

Pure stdlib SQL. Designed to be cheap (one GROUP BY query, no scans).

Status thresholds (configurable):
    spike   : ratio >= 2.0          - "this sphere is really hot right now"
    rising  : 1.3 <= ratio < 2.0    - "noticeably more than usual"
    normal  : 0.7 <= ratio < 1.3    - "same as usual"
    quiet   : ratio < 0.7           - "slower than usual"

CLI:
    python3 echolot_velocity.py [echolot.db] [window_hours] [baseline_offset_hours]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _status(ratio: float | None,
            spike_min: float = 2.0,
            rising_min: float = 1.3,
            quiet_max: float = 0.7) -> str:
    if ratio is None:
        return "no_baseline"
    if ratio >= spike_min:
        return "spike"
    if ratio >= rising_min:
        return "rising"
    if ratio < quiet_max:
        return "quiet"
    return "normal"


def compute_sphere_velocity(
    db_path: str | Path,
    window_hours: int = 6,
    baseline_offset_hours: int = 48,
    baseline_window_hours: int = 24,
    min_baseline: int = 2,
    limit: int = 30,
) -> dict:
    """Per-sphere recent-window vs baseline-window article rate.

    Args:
        window_hours: how recent to count (default 6h)
        baseline_offset_hours: where the baseline window starts (default 48h ago)
        baseline_window_hours: how wide the baseline window is (default 24h, so
            baseline = [48h..72h ago] by default — a full day for stable rate)
        min_baseline: skip spheres with fewer than this many baseline articles
            (avoids "1 / 0.5 = 2x" noise on tiny spheres)
        limit: how many spheres to return (sorted by velocity_ratio desc)

    Note: ratio compares per-hour rates, not raw counts, so current and
    baseline windows can have different widths.
    """
    baseline_end = baseline_offset_hours
    baseline_start = baseline_offset_hours + baseline_window_hours

    conn = _connect(db_path)
    try:
        # We bucket on PUBLISHED_AT (article release time), not fetched_at
        # (scraper ingest time). Reason: on Railway dev-mode the DB has no
        # persistent volume — every deploy starts with an empty file. With
        # fetched_at the baseline window [24h..192h ago] would be empty for
        # 24h+ after each deploy. published_at carries the source's real
        # release timestamp (often hours-to-days old when first scraped),
        # so the baseline window is meaningful immediately after deploy.
        #
        # Timezone handling: published_at values come in mixed offsets
        # (+02:00, +10:00, Z, etc.). SQLite 3.46's julianday() normalizes
        # all of them to UTC, so `(julianday('now') - julianday(p)) * 24`
        # gives a clean hours-difference number we can threshold.
        #
        # json_each unpacks the spheres_json list so each article counts
        # in every sphere it belongs to.
        rows = conn.execute(f"""
            SELECT je.value AS sphere,
                   SUM(CASE WHEN (julianday('now') - julianday(a.published_at)) * 24 <= {window_hours}
                              AND (julianday('now') - julianday(a.published_at)) * 24 >= 0
                            THEN 1 ELSE 0 END) AS current_count,
                   SUM(CASE WHEN (julianday('now') - julianday(a.published_at)) * 24 >  {baseline_end}
                              AND (julianday('now') - julianday(a.published_at)) * 24 <= {baseline_start}
                            THEN 1 ELSE 0 END) AS baseline_count
            FROM articles a, json_each(a.spheres_json) je
            WHERE a.published_at IS NOT NULL
              AND (julianday('now') - julianday(a.published_at)) * 24 <= {baseline_start + 1}
              AND (julianday('now') - julianday(a.published_at)) * 24 >= 0
            GROUP BY je.value
        """).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        current = r["current_count"] or 0
        baseline = r["baseline_count"] or 0
        if baseline < min_baseline and current < min_baseline:
            # Skip dead spheres entirely.
            continue
        # Per-hour normalize so current vs baseline windows of different
        # widths compare as rates, not raw counts.
        current_rate = current / window_hours if window_hours > 0 else 0.0
        baseline_rate = baseline / baseline_window_hours if baseline_window_hours > 0 else 0.0
        if baseline_rate > 0:
            ratio = round(current_rate / baseline_rate, 2)
        else:
            ratio = None
        out.append({
            "sphere": r["sphere"],
            "current_count": current,
            "baseline_count": baseline,
            "velocity_ratio": ratio,
            "status": _status(ratio),
        })

    # Sort: spikes first, then by ratio desc. Items with no baseline (ratio=None)
    # but high current go near the top with status="no_baseline".
    def sort_key(item):
        if item["velocity_ratio"] is None:
            return (-item["current_count"], 0)
        return (0, -item["velocity_ratio"])
    out.sort(key=sort_key)

    return {
        "window_hours": window_hours,
        "baseline_window": f"{baseline_end}-{baseline_start}h ago, {baseline_window_hours}h wide",
        "baseline_window_hours": baseline_window_hours,
        "min_baseline": min_baseline,
        "metric": "published_at (source release time, julianday-normalized)",
        "note": "compares source-side publication rate; works on fresh DBs since articles carry historical published_at",
        "spheres_evaluated": len(out),
        "spheres": out[:limit],
    }


def main(argv: list[str]) -> int:
    db = argv[1] if len(argv) > 1 else "echolot.db"
    window = int(argv[2]) if len(argv) > 2 else 6
    baseline_off = int(argv[3]) if len(argv) > 3 else 48
    baseline_win = int(argv[4]) if len(argv) > 4 else 24
    if not Path(db).exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 2
    r = compute_sphere_velocity(
        db,
        window_hours=window,
        baseline_offset_hours=baseline_off,
        baseline_window_hours=baseline_win,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
