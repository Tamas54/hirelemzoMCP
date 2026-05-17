"""
Cloudflare Radar calibration script.

Fetches per-country top-domain rankings from the Cloudflare Radar API,
saves them as `data/cf_radar/{CC}.csv` for use by domain_intel.ranking.

License note
------------
Cloudflare Radar data is CC BY-NC 4.0. We treat the per-country CSVs as
*internal calibration data* and never republish them. The derived
estimates (rank percentiles, audience numbers) are aggregated /
transformed outputs, not the raw dataset.

Setup
-----
  1. Create a Cloudflare account, go to https://dash.cloudflare.com/profile/api-tokens
  2. Create a token with the "Radar" permission (Read).
  3. Set CF_RADAR_TOKEN in your .env file.

Usage
-----
  python scripts/calibrate_cloudflare.py              # all Echolot countries, top 1000
  python scripts/calibrate_cloudflare.py --limit 5000 # top 5000 per country
  python scripts/calibrate_cloudflare.py --countries HU,RU,IL,IR

The script runs once -- after that, the lists live on disk and the runtime
service loads them at startup.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
from pathlib import Path

import httpx

# Make `domain_intel` importable when running this from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain_intel.calibration_data import COUNTRY_DATA  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("calibrate_cloudflare")


CF_RADAR_API = "https://api.cloudflare.com/client/v4/radar/ranking/top"


async def fetch_country_top(
    client: httpx.AsyncClient,
    token: str,
    country: str,
    limit: int,
) -> list[tuple[int, str]]:
    """
    Fetch Cloudflare Radar's top domains for one country.

    Returns: [(rank, domain), ...] sorted by rank ascending.
    """
    params = {
        "location": country,
        "limit": str(limit),
        # CF Radar exposes a "ranking type" — 'POPULAR' is the default,
        # 'TRENDING_RISE' / 'TRENDING_STEADY' are alternatives.
        # We stay with the default popularity ranking.
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = await client.get(CF_RADAR_API, params=params, headers=headers, timeout=60.0)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"CF Radar API error for {country}: {data.get('errors')}")

    entries = data.get("result", {}).get("top_0", [])
    out: list[tuple[int, str]] = []
    for i, item in enumerate(entries, start=1):
        domain = (item.get("domain") or "").lower().lstrip("www.")
        rank = item.get("rank") or i  # API gives `rank`; fall back to ordinal
        if domain:
            out.append((rank, domain))
    return out


def save_csv(path: Path, entries: list[tuple[int, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "domain"])
        for rank, domain in entries:
            w.writerow([rank, domain])


async def run(countries: list[str], limit: int, token: str, out_dir: Path) -> None:
    async with httpx.AsyncClient() as client:
        # CF Radar rate limits: be polite, sequential is fine for this volume
        for cc in countries:
            cc = cc.upper()
            logger.info(f"Fetching CF Radar top {limit} for {cc}...")
            try:
                entries = await fetch_country_top(client, token, cc, limit)
            except httpx.HTTPStatusError as e:
                logger.error(f"{cc}: HTTP {e.response.status_code}: {e.response.text[:300]}")
                continue
            except Exception as e:
                logger.error(f"{cc}: {e}")
                continue
            if not entries:
                logger.warning(f"{cc}: no entries returned")
                continue
            out_path = out_dir / f"{cc}.csv"
            save_csv(out_path, entries)
            logger.info(f"{cc}: saved {len(entries):,} domains -> {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Calibrate per-country ranks from CF Radar")
    parser.add_argument(
        "--limit", type=int, default=1000,
        help="Top N domains per country (default 1000)",
    )
    parser.add_argument(
        "--countries", type=str, default=None,
        help="Comma-separated ISO2 list (default: all Echolot countries)",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("./data/cf_radar"),
        help="Output directory (default ./data/cf_radar)",
    )
    args = parser.parse_args()

    token = os.getenv("CF_RADAR_TOKEN") or os.getenv("CLOUDFLARE_API_TOKEN")
    if not token:
        logger.error("CF_RADAR_TOKEN (or CLOUDFLARE_API_TOKEN) env var is required")
        sys.exit(2)

    if args.countries:
        countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    else:
        countries = sorted(COUNTRY_DATA.keys())

    logger.info(f"Calibrating {len(countries)} countries, limit={args.limit}")
    asyncio.run(run(countries, args.limit, token, args.out_dir))


if __name__ == "__main__":
    main()
