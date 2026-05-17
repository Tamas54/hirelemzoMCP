"""
Calibration data for rank → audience size conversion.

Two data sets here:

1. COUNTRY_DATA — population + internet penetration for each country.
   Sources: World Bank (2024), ITU, UN. Updated annually.
   Internet penetration = % of population using internet at least quarterly.

2. CALIBRATION_ANCHORS — known (rank, monthly_unique_visitors) pairs from
   publicly disclosed / audited sources. Used to fit the power-law curve:
       monthly_uniques = A * rank ** (-alpha)

   Global anchors are from Similarweb's public top-sites page (snapshot 2026-Q1).
   Country-level anchors are from local audit bodies:
     - HU: DKT (Digitális Közönségmérés) — gemius.hu monthly reports
     - DE: IVW / AGOF — agof.de
     - PL: Gemius/PBI
     - IL: TGI Israel
     - RU: Mediascope
     - IR: estimates from Alexa snapshots + Statista
     - US/UK: Similarweb publicly disclosed

Re-fit the power-law via `scripts/calibrate_cloudflare.py` once you have
Cloudflare Radar data — that gives finer per-country curves.
"""

from __future__ import annotations

from typing import Final


# -----------------------------------------------------------------------------
# Country population + internet penetration
# -----------------------------------------------------------------------------
# Format: iso2 -> (population, internet_penetration_pct, region)
# Population in absolute count, penetration as a fraction (0-1).
COUNTRY_DATA: Final[dict[str, tuple[int, float, str]]] = {
    # Echolot core sphere
    "HU": (9_580_000, 0.89, "europe_central"),
    "RU": (143_700_000, 0.88, "europe_east"),
    "UA": (37_000_000, 0.82, "europe_east"),
    "BY": (9_200_000, 0.85, "europe_east"),
    "IL": (9_840_000, 0.91, "middle_east"),
    "IR": (88_500_000, 0.78, "middle_east"),
    "TR": (85_800_000, 0.83, "middle_east"),
    "SA": (36_400_000, 0.99, "middle_east"),
    "AE": (10_080_000, 0.99, "middle_east"),
    "EG": (111_200_000, 0.72, "middle_east"),

    # Europe Western/Northern
    "DE": (84_400_000, 0.94, "europe_west"),
    "AT": (9_100_000, 0.94, "europe_west"),
    "CH": (8_900_000, 0.97, "europe_west"),
    "FR": (68_400_000, 0.88, "europe_west"),
    "GB": (67_900_000, 0.97, "europe_west"),
    "IE": (5_100_000, 0.95, "europe_west"),
    "NL": (17_700_000, 0.98, "europe_west"),
    "BE": (11_750_000, 0.94, "europe_west"),
    "ES": (48_400_000, 0.93, "europe_west"),
    "PT": (10_400_000, 0.85, "europe_west"),
    "IT": (58_900_000, 0.87, "europe_west"),
    "GR": (10_400_000, 0.85, "europe_west"),
    "SE": (10_550_000, 0.98, "europe_north"),
    "NO": (5_500_000, 0.98, "europe_north"),
    "DK": (5_950_000, 0.99, "europe_north"),
    "FI": (5_580_000, 0.96, "europe_north"),

    # Europe Central/East EU
    "PL": (37_700_000, 0.88, "europe_central"),
    "CZ": (10_900_000, 0.87, "europe_central"),
    "SK": (5_460_000, 0.89, "europe_central"),
    "RO": (19_000_000, 0.81, "europe_central"),
    "BG": (6_840_000, 0.80, "europe_central"),
    "HR": (3_870_000, 0.83, "europe_central"),
    "SI": (2_120_000, 0.91, "europe_central"),
    "RS": (6_650_000, 0.82, "europe_central"),

    # Asia
    "CN": (1_412_000_000, 0.78, "asia_east"),
    "JP": (123_000_000, 0.93, "asia_east"),
    "KR": (51_700_000, 0.97, "asia_east"),
    "IN": (1_429_000_000, 0.55, "asia_south"),
    "ID": (277_500_000, 0.77, "asia_se"),
    "SG": (5_920_000, 0.96, "asia_se"),

    # Americas
    "US": (334_900_000, 0.92, "americas_north"),
    "CA": (40_770_000, 0.94, "americas_north"),
    "MX": (128_500_000, 0.78, "americas_central"),
    "BR": (216_400_000, 0.84, "americas_south"),
    "AR": (45_800_000, 0.89, "americas_south"),

    # Other
    "AU": (26_640_000, 0.96, "oceania"),
    "ZA": (60_400_000, 0.78, "africa"),
}


# -----------------------------------------------------------------------------
# Calibration anchors — (rank, monthly_visits)
# -----------------------------------------------------------------------------
# Measured from Similarweb Apr 2026 (Worldwide, All traffic). 12 news domains
# spanning 8 countries, rank 73 → 16,826. Power-law fit on this set yields
# α ≈ 0.910, A ≈ 3.10e10 with mean abs log-error ~8%. Production-grade.
#
# NOTE: "visits" here are Similarweb sessions, NOT monthly uniques. News
# sites typically have ~3-4 visits per unique. The reach model in reach.py
# accounts for this via DAILY_TO_MONTHLY_RATIO.
#
# Election-bump caveat: telex.hu and index.hu Apr 2026 numbers are inflated
# (~28% for telex, ~6% for index) by the 2026-04-12 Hungarian parliamentary
# election. They still fit the global curve within tolerance, but DO NOT use
# them to re-derive HU COUNTRY_ANCHORS — wait for a normal-month snapshot.
SIMILARWEB_GLOBAL_ANCHORS_APR2026: Final[list[tuple[str, int, int, str]]] = [
    # (domain, global_rank, monthly_visits, country)
    ("nytimes.com",          73,    635_000_000, "US"),
    ("bbc.com",              93,    504_400_000, "GB"),
    ("reuters.com",         622,     94_140_000, "GB"),
    ("lemonde.fr",          649,     76_200_000, "FR"),
    ("asahi.com",           711,     71_910_000, "JP"),
    ("clarin.com",        1_000,     58_070_000, "AR"),
    ("telex.hu",          1_022,     72_210_000, "HU"),   # ⚡ election-inflated
    ("rt.com",            1_325,     43_350_000, "RU"),
    ("index.hu",          1_548,     36_800_000, "HU"),   # ⚡ election-inflated
    ("news24.com",        4_772,     14_160_000, "ZA"),
    ("haaretz.co.il",     5_412,     10_350_000, "IL"),
    ("xinhuanet.com",    16_826,      4_920_000, "CN"),
]

# Marks anchors whose visits are not representative of a normal month.
# AudienceEstimator skips these when fitting per-country curves.
ELECTION_INFLATED_DOMAINS: Final[set[str]] = {"telex.hu", "index.hu"}

# Anchor list used by AudienceEstimator power-law fit.
# Fit ONLY on measured anchors (no extrapolation tails) — adding head
# anchors (google rank 1 @ 4.5B) or tail anchors flattens alpha and breaks
# accuracy in the 100–10K range where most news domains live.
# Yields α ≈ 0.910, A ≈ 3.10e10 with mean abs log-error ~8%.
GLOBAL_ANCHORS: Final[list[tuple[int, int]]] = [
    (r, v) for _d, r, v, _cc in SIMILARWEB_GLOBAL_ANCHORS_APR2026
]

# -----------------------------------------------------------------------------
# Direct lookup tables for hybrid mode
# -----------------------------------------------------------------------------
# When a domain matches here, AudienceEstimator uses the known SW rank
# directly (skipping the DNS-based consensus_rank → power-law path). This
# bypasses the DNS/SW mismatch problem (DNS sources can disagree with SW by
# 2-17× depending on language/region/site profile).
#
# Includes the 12 measured anchors plus 5 implied ranks from comparison-
# chart visits-only screenshots (rank derived via the new power-law).
SIMILARWEB_KNOWN_RANKS: Final[dict[str, int]] = {
    # Measured anchors (Apr 2026)
    "nytimes.com": 73,
    "bbc.com": 93,
    "reuters.com": 622,
    "lemonde.fr": 649,
    "asahi.com": 711,
    "clarin.com": 1_000,
    "telex.hu": 1_022,
    "rt.com": 1_325,
    "index.hu": 1_548,
    "news24.com": 4_772,
    "haaretz.co.il": 5_412,
    "xinhuanet.com": 16_826,
    # Implied from visits + new power-law (screenshot rank cut off or subdomain)
    "news.yahoo.co.jp": 54,
    "elmundo.es": 542,
    "spiegel.de": 789,
    "abc.net.au": 902,
    "scmp.com": 6_980,
}

# Visits-only domains harvested from Similarweb comparison charts (Apr 2026).
# Direct visits lookup — avoids any rank-→-visits power-law step entirely.
SIMILARWEB_KNOWN_VISITS: Final[dict[str, int]] = {
    # English/global
    "cnn.com":             458_300_000,
    "theguardian.com":     300_800_000,
    "washingtonpost.com":   71_200_000,
    "cnbc.com":            107_900_000,
    "aljazeera.com":       140_500_000,
    # Indian
    "timesofindia.indiatimes.com": 279_900_000,
    "ndtv.com":            200_500_000,
    "hindustantimes.com":  135_800_000,
    "indianexpress.com":    88_560_000,
    "thehindu.com":         63_290_000,
    # German
    "bild.de":             202_300_000,
    "welt.de":              81_030_000,
    "tagesschau.de":        74_850_000,
    "zeit.de":              54_980_000,
    # French
    "lefigaro.fr":          84_270_000,
    "ouest-france.fr":      71_520_000,
    "franceinfo.fr":        71_460_000,
    "liberation.fr":        16_980_000,
    # Israeli
    "ynet.co.il":           67_680_000,
    "maariv.co.il":         24_100_000,
    "israelhayom.co.il":    11_570_000,
    "kan.org.il":           10_070_000,
    # Spanish (Spain)
    "elpais.com":          114_900_000,
    "elconfidencial.com":   43_780_000,
    "eldiario.es":          39_730_000,
    "abc.es":               34_030_000,
    # Latin Spanish
    "infobae.com":         213_600_000,
    "lanacion.com.ar":      70_910_000,
    "tn.com.ar":            33_430_000,
    "pagina12.com.ar":      21_150_000,
    # Hungarian (note: April 2026 election-inflated, but kept for reach model)
    "origo.hu":             17_760_000,
    "24.hu":                25_040_000,
    "hvg.hu":               17_660_000,
    "444.hu":               27_040_000,
    # Russian
    "tass.com":              1_168_000,
    "sputnikglobe.com":        840_741,
    "russia.tv":                 7_714,
    # Chinese
    "news.cn":               5_011_000,
    "people.com.cn":         7_142_000,
    "thepaper.cn":           6_805_000,
    "chinanews.com.cn":      1_458_000,
    "globaltimes.cn":        2_717_000,
    "asia.nikkei.com":       1_377_000,
    "thestandard.com.hk":    1_024_000,
    # Japanese
    "yomiuri.co.jp":        79_600_000,
    "nikkei.com":           89_280_000,
    "mainichi.jp":          36_320_000,
    # South African
    "iol.co.za":             8_883_000,
    "timeslive.co.za":       5_205_000,
    "dailymaverick.co.za":   5_580_000,
    "citizen.co.za":         7_932_000,
    # Australian
    "sbs.com.au":            8_744_000,
    "news.com.au":          60_920_000,
}


# COUNTRY-SPECIFIC anchors: per-country rank vs in-country monthly uniques.
# These power the country-rank → country-visitors estimate. Only populate
# countries where you have decent local data; others fall back to a generic
# scaling from population × penetration.
#
# Format: country -> list[(country_rank, monthly_unique_in_country)]
COUNTRY_ANCHORS: Final[dict[str, list[tuple[int, int]]]] = {
    # Hungary — DKT/Gemius 2024-2025 monthly reports
    "HU": [
        (1, 7_500_000),       # facebook.com / google.com — ~95% reach
        (10, 4_500_000),      # index.hu / telex.hu tier
        (50, 1_500_000),      # niche national portals
        (100, 800_000),
        (500, 150_000),
        (1_000, 60_000),
        (10_000, 5_000),
    ],
    # Germany — AGOF
    "DE": [
        (1, 70_000_000),
        (10, 35_000_000),     # bild.de / spiegel.de tier
        (50, 12_000_000),
        (100, 6_000_000),
        (1_000, 600_000),
        (10_000, 50_000),
    ],
    # Russia — Mediascope
    "RU": [
        (1, 110_000_000),     # yandex / vk
        (10, 60_000_000),
        (50, 20_000_000),
        (100, 10_000_000),
        (1_000, 1_000_000),
        (10_000, 80_000),
    ],
    # Israel — TGI
    "IL": [
        (1, 8_500_000),
        (10, 3_500_000),      # ynet / haaretz tier
        (50, 800_000),
        (100, 400_000),
        (1_000, 40_000),
    ],
    # Iran — rough estimate from public Statista + Alexa snapshots
    "IR": [
        (1, 60_000_000),
        (10, 25_000_000),
        (50, 8_000_000),
        (100, 4_000_000),
        (1_000, 350_000),
        (10_000, 30_000),
    ],
    # United States
    "US": [
        (1, 280_000_000),
        (10, 180_000_000),
        (50, 80_000_000),
        (100, 50_000_000),
        (1_000, 5_000_000),
        (10_000, 500_000),
    ],
    # United Kingdom
    "GB": [
        (1, 60_000_000),
        (10, 35_000_000),
        (50, 12_000_000),
        (100, 6_000_000),
        (1_000, 500_000),
        (10_000, 40_000),
    ],
}


# Default power-law parameters when no per-country anchors are available.
# Calculated by fitting GLOBAL_ANCHORS, then scaling A by country
# (internet_users / world_internet_users).
WORLD_INTERNET_USERS: Final[int] = 5_400_000_000  # ITU 2024 estimate


# -----------------------------------------------------------------------------
# Story reach modelling constants
# -----------------------------------------------------------------------------
# Fraction of monthly uniques who are daily uniques.
# News sites have high return rate, so daily/monthly is around 1/8 (not 1/30).
DAILY_TO_MONTHLY_RATIO: Final[float] = 1 / 8

# Fraction of daily uniques who actually see a given story
# (front-page placement + visitor behaviour). Different by source tier.
STORY_VISIBILITY_DEFAULT: Final[float] = 0.12  # 12% of daily uniques see a top story
STORY_VISIBILITY_BUCKETS: Final[dict[str, float]] = {
    "top_100": 0.05,      # mega-portals; story buried in noise
    "top_1k": 0.08,
    "top_10k": 0.12,
    "top_100k": 0.18,     # smaller outlets focus more, stories are more visible
    "top_1m": 0.25,
    "beyond_1m": 0.30,
    "unranked": 0.30,
}
