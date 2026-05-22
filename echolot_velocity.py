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
    adaptive_note: str | None = None

    conn = _connect(db_path)
    try:
        # Two filtering rules baked in here:
        #   1) We compare on fetched_at, not published_at. published_at carries
        #      mixed source timezones (+10:00, +02:00, Z) that older SQLite
        #      datetime() builds (Railway image) can't normalize. fetched_at
        #      is UTC ISO set by the scraper, and "what's spiking right now"
        #      is more honestly about ingest cadence than about source-side
        #      publication time anyway.
        #   2) Both sides of the comparison are normalized via
        #      strftime('%Y-%m-%dT%H:%M:%S', ...). fetched_at is stored as
        #      "YYYY-MM-DDTHH:MM:SS.ffffff+00:00" — datetime('now') alone would
        #      give "YYYY-MM-DD HH:MM:SS" (space, no T), which loses to the
        #      stored format lexicographically. strftime forces T on both sides.
        #
        # json_each unpacks the spheres_json list so each article counts in
        # every sphere it belongs to.
        def _run_query(b_end: float, b_start: float):
            # b_start = how many hours back the baseline window opens (older)
            # b_end   = how many hours back the baseline window closes (newer)
            return conn.execute(f"""
                SELECT je.value AS sphere,
                       SUM(CASE WHEN strftime('%Y-%m-%dT%H:%M:%S', a.fetched_at)
                                     >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-{window_hours} hours')
                                THEN 1 ELSE 0 END) AS current_count,
                       SUM(CASE WHEN strftime('%Y-%m-%dT%H:%M:%S', a.fetched_at)
                                     >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-{b_start} hours')
                                  AND strftime('%Y-%m-%dT%H:%M:%S', a.fetched_at)
                                     <  strftime('%Y-%m-%dT%H:%M:%S', 'now', '-{b_end} hours')
                                THEN 1 ELSE 0 END) AS baseline_count
                FROM articles a, json_each(a.spheres_json) je
                WHERE strftime('%Y-%m-%dT%H:%M:%S', a.fetched_at)
                      >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-{b_start + 1} hours')
                GROUP BY je.value
            """).fetchall()

        rows = _run_query(baseline_end, baseline_start)

        # Adaptive fallback for fresh databases (Railway dev mode: no
        # persistent volume → every deploy starts from 0). If the requested
        # baseline window pulled in nothing usable, retry with whatever older
        # data we actually have: baseline = [now - window_hours .. DB oldest].
        # This keeps the "rising vs earlier" idea while degrading gracefully
        # when the requested 7-day window is empty.
        if not any((r["baseline_count"] or 0) >= min_baseline for r in rows):
            span_hours = conn.execute(
                "SELECT (julianday('now') - julianday(MIN(fetched_at))) * 24.0 "
                "FROM articles"
            ).fetchone()[0]
            if span_hours and span_hours > window_hours * 2:
                # Need at least 2× current window so baseline has room to differ.
                # Leave a tiny margin off the oldest edge to avoid edge dropoff.
                new_end = float(window_hours)          # baseline closes at end of current window
                new_start = float(span_hours) - 0.1    # baseline opens at oldest available data
                rows = _run_query(new_end, new_start)
                baseline_end = new_end
                baseline_start = new_start
                baseline_window_hours = new_start - new_end
                adaptive_note = (
                    f"adaptive baseline: DB has only ~{span_hours:.1f}h of data "
                    f"(deploy reset?), baseline = oldest..now-{window_hours}h"
                )
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
        "metric": "fetched_at (ingest cadence)",
        "note": "compares scraper ingest rate, not source publication rate",
        "adaptive_note": adaptive_note,
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
