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
    baseline_offset_hours: int = 24,
    min_baseline: int = 2,
    limit: int = 30,
) -> dict:
    """Per-sphere recent-window vs baseline-window article count.

    Args:
        window_hours: how recent to count (default 6h)
        baseline_offset_hours: where the baseline window starts (default 24h ago,
            so baseline = [24h..24+window_hours ago], i.e. same hour-of-day yesterday)
        min_baseline: skip spheres with fewer than this many baseline articles
            (avoids "1 / 0.5 = 2x" noise on tiny spheres)
        limit: how many spheres to return (sorted by velocity_ratio desc)
    """
    baseline_end = baseline_offset_hours
    baseline_start = baseline_offset_hours + window_hours

    conn = _connect(db_path)
    try:
        # One query: for each sphere, count articles in current and baseline windows.
        # json_each unpacks the spheres_json list so each article counts in every
        # sphere it belongs to.
        rows = conn.execute(f"""
            SELECT je.value AS sphere,
                   SUM(CASE WHEN a.published_at >= datetime('now', '-{window_hours} hours')
                            THEN 1 ELSE 0 END) AS current_count,
                   SUM(CASE WHEN a.published_at >= datetime('now', '-{baseline_start} hours')
                              AND a.published_at <  datetime('now', '-{baseline_end} hours')
                            THEN 1 ELSE 0 END) AS baseline_count
            FROM articles a, json_each(a.spheres_json) je
            WHERE a.published_at >= datetime('now', '-{baseline_start + 1} hours')
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
        if baseline == 0:
            ratio = None
        else:
            ratio = round(current / baseline, 2)
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
        "baseline_window": f"{baseline_end}-{baseline_start}h ago",
        "min_baseline": min_baseline,
        "spheres_evaluated": len(out),
        "spheres": out[:limit],
    }


def main(argv: list[str]) -> int:
    db = argv[1] if len(argv) > 1 else "echolot.db"
    window = int(argv[2]) if len(argv) > 2 else 6
    baseline_off = int(argv[3]) if len(argv) > 3 else 24
    if not Path(db).exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 2
    r = compute_sphere_velocity(db, window_hours=window, baseline_offset_hours=baseline_off)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
