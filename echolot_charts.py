"""Echolot trending charts — inline-SVG, no JS dep.

Two charts for the /dashboard/trending page:
  1) hourly_volume_svg(): 24h hourly volume per top-5 sphere (line chart)
  2) polit_spectrum_svg(): articles by language × political lean (stacked bar)

Both query `articles` joined as needed and bucket on `published_at` via
julianday() so they work on a fresh DB (Railway dev-mode, no volume).
"""
from __future__ import annotations

import sqlite3
from html import escape
from pathlib import Path

# Distinct color palette for line chart (color-blind friendly-ish).
_LINE_COLORS = ["#60a5fa", "#f87171", "#34d399", "#fbbf24", "#a78bfa"]

# Political lean → fill color (matches dashboard's status palette).
_LEAN_COLORS = {
    "left":     "#60a5fa",  # blue
    "center":   "#9ca3af",  # gray
    "right":    "#f87171",  # red
    "unknown":  "#374151",  # dim
}


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def hourly_volume_svg(
    db_path: str | Path,
    hours: int = 24,
    top_n: int = 5,
    width: int = 760,
    height: int = 220,
) -> str:
    """Line chart: per-hour article count over the last `hours`, for the
    top `top_n` spheres ranked by total count in that window.

    Returns an inline <svg>...</svg> string, or "" if no data.
    """
    conn = _connect(db_path)
    try:
        # First find top-N spheres in the window
        top_rows = conn.execute(f"""
            SELECT je.value AS sphere, COUNT(*) AS n
            FROM articles a, json_each(a.spheres_json) je
            WHERE a.published_at IS NOT NULL
              AND (julianday('now') - julianday(a.published_at)) * 24 <= {hours}
              AND (julianday('now') - julianday(a.published_at)) * 24 >= 0
            GROUP BY je.value
            ORDER BY n DESC
            LIMIT {top_n}
        """).fetchall()
        if not top_rows:
            return ""
        top_spheres = [r["sphere"] for r in top_rows]

        # Bucket each sphere into hour-buckets [0..hours-1] where 0 = most recent
        series = {s: [0] * hours for s in top_spheres}
        placeholders = ",".join("?" for _ in top_spheres)
        rows = conn.execute(f"""
            SELECT je.value AS sphere,
                   CAST((julianday('now') - julianday(a.published_at)) * 24 AS INTEGER) AS hr_ago,
                   COUNT(*) AS n
            FROM articles a, json_each(a.spheres_json) je
            WHERE a.published_at IS NOT NULL
              AND (julianday('now') - julianday(a.published_at)) * 24 <= {hours}
              AND (julianday('now') - julianday(a.published_at)) * 24 >= 0
              AND je.value IN ({placeholders})
            GROUP BY je.value, hr_ago
        """, top_spheres).fetchall()
        for r in rows:
            s = r["sphere"]
            h = int(r["hr_ago"])
            if 0 <= h < hours and s in series:
                series[s][h] = r["n"]
    finally:
        conn.close()

    # Chart geometry
    pad_l, pad_r, pad_t, pad_b = 40, 14, 14, 28
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_y = max((max(v) for v in series.values()), default=0) or 1
    # x increases LEFT→RIGHT chronologically: leftmost = (hours)h ago, rightmost = now
    def x_for_h(h_ago: int) -> float:
        # h_ago 0 → rightmost; h_ago (hours-1) → leftmost
        return pad_l + plot_w * (1.0 - h_ago / max(1, hours - 1))
    def y_for_v(v: float) -> float:
        return pad_t + plot_h * (1.0 - v / max_y)

    # Build SVG
    parts = [
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="hourly volume" '
        f'style="max-width:100%;height:auto;font-family:ui-sans-serif,system-ui,-apple-system,sans-serif">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="transparent"/>',
    ]
    # Y-axis: a few horizontal grid lines + labels
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = pad_t + plot_h * (1.0 - frac)
        v = int(max_y * frac)
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" '
            f'stroke="#374151" stroke-width="1" stroke-dasharray="2,3" opacity="0.5"/>'
        )
        parts.append(
            f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end" '
            f'fill="#9ca3af" font-size="10">{v}</text>'
        )
    # X-axis tick labels (every ~6h)
    for h in (0, hours // 4, hours // 2, 3 * hours // 4, hours - 1):
        x = x_for_h(h)
        label = "most" if h == 0 else f"-{h}ó"
        parts.append(
            f'<text x="{x:.1f}" y="{pad_t + plot_h + 16:.1f}" text-anchor="middle" '
            f'fill="#9ca3af" font-size="10">{label}</text>'
        )

    # Polylines per sphere
    for i, sphere in enumerate(top_spheres):
        color = _LINE_COLORS[i % len(_LINE_COLORS)]
        pts = []
        # build left-to-right by iterating from h=(hours-1) down to 0
        for h in range(hours - 1, -1, -1):
            v = series[sphere][h]
            pts.append(f"{x_for_h(h):.1f},{y_for_v(v):.1f}")
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="1.8" '
            f'points="{" ".join(pts)}"/>'
        )

    # Legend (top-right corner)
    legend_x = pad_l + 8
    legend_y = pad_t + 4
    for i, sphere in enumerate(top_spheres):
        color = _LINE_COLORS[i % len(_LINE_COLORS)]
        y = legend_y + i * 14
        parts.append(
            f'<rect x="{legend_x}" y="{y}" width="10" height="10" '
            f'rx="2" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{legend_x + 14}" y="{y + 9}" fill="#e5e7eb" '
            f'font-size="11" font-family="ui-monospace,Menlo,monospace">'
            f'{escape(sphere)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def polit_spectrum_svg(
    db_path: str | Path,
    hours: int = 24,
    top_n: int = 10,
    width: int = 760,
    bar_height: int = 26,
    row_gap: int = 6,
) -> str:
    """Stacked horizontal bar chart: articles by language × political lean,
    aggregated over the last `hours`. Languages sorted by total count desc.

    Returns inline <svg>...</svg> or "" if no data.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(f"""
            SELECT a.language AS lang,
                   COALESCE(s.lean, 'unknown') AS lean,
                   COUNT(*) AS n
            FROM articles a
            LEFT JOIN sources s ON s.id = a.source_id
            WHERE a.published_at IS NOT NULL
              AND (julianday('now') - julianday(a.published_at)) * 24 <= {hours}
              AND (julianday('now') - julianday(a.published_at)) * 24 >= 0
            GROUP BY a.language, COALESCE(s.lean, 'unknown')
        """).fetchall()
    finally:
        conn.close()
    if not rows:
        return ""

    # Aggregate per language
    by_lang: dict[str, dict[str, int]] = {}
    for r in rows:
        lang = r["lang"] or "?"
        lean = (r["lean"] or "unknown").lower()
        if lean not in _LEAN_COLORS:
            lean = "unknown"
        by_lang.setdefault(lang, {"left": 0, "center": 0, "right": 0, "unknown": 0})
        by_lang[lang][lean] += int(r["n"])

    # Sort languages by total desc, take top_n
    ranked = sorted(
        by_lang.items(),
        key=lambda kv: -sum(kv[1].values()),
    )[:top_n]
    max_total = max((sum(v.values()) for _, v in ranked), default=0) or 1

    # Layout
    pad_l, pad_r, pad_t, pad_b = 56, 56, 28, 14
    row_h = bar_height + row_gap
    height = pad_t + pad_b + row_h * len(ranked)
    plot_w = width - pad_l - pad_r

    parts = [
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="political spectrum" '
        f'style="max-width:100%;height:auto;font-family:ui-sans-serif,system-ui,-apple-system,sans-serif">',
    ]
    # Top legend
    legend_items = [("left", "bal"), ("center", "közép"), ("right", "jobb"), ("unknown", "ismeretlen")]
    lx = pad_l
    for key, label in legend_items:
        parts.append(
            f'<rect x="{lx}" y="6" width="12" height="12" rx="2" fill="{_LEAN_COLORS[key]}"/>'
        )
        parts.append(
            f'<text x="{lx + 16}" y="16" fill="#e5e7eb" font-size="11">{escape(label)}</text>'
        )
        lx += 80

    # Bars
    for i, (lang, leans) in enumerate(ranked):
        y = pad_t + i * row_h
        # Language label
        parts.append(
            f'<text x="{pad_l - 8}" y="{y + bar_height * 0.65:.1f}" text-anchor="end" '
            f'fill="#e5e7eb" font-size="12" font-family="ui-monospace,Menlo,monospace">'
            f'{escape(lang)}</text>'
        )
        # Stacked segments — left/center/right/unknown in that order
        x = pad_l
        total = sum(leans.values())
        bar_total_w = plot_w * (total / max_total)
        for key in ("left", "center", "right", "unknown"):
            n = leans.get(key, 0)
            if n <= 0:
                continue
            seg_w = bar_total_w * (n / total) if total else 0
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{seg_w:.1f}" height="{bar_height}" '
                f'fill="{_LEAN_COLORS[key]}" opacity="0.92">'
                f'<title>{escape(lang)} · {escape(key)}: {n}</title>'
                f'</rect>'
            )
            x += seg_w
        # Total count to the right
        parts.append(
            f'<text x="{pad_l + bar_total_w + 6:.1f}" y="{y + bar_height * 0.65:.1f}" '
            f'fill="#9ca3af" font-size="11" font-family="ui-monospace,Menlo,monospace">'
            f'{total}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)
