"""
Geography detection — replaces Cloudflare Radar's "top countries" feature
using only free + commercial-safe signals.

Signals collected, each contributing to the country score with a weight:
  1. WHOIS country         (weight 0.6)  - registrant's country
  2. DNS A → IP geo         (weight 0.5) - hosting infrastructure country
  3. TLD heuristic         (weight 0.7)  - .ru → RU, .hu → HU, etc.
  4. HTML lang attribute   (weight 0.8)  - declared content language
  5. Content-Language hdr  (weight 0.6)
  6. Language detection    (weight 0.5)  - langdetect on page text
  7. Echolot corpus signal (weight 1.0)  - if domain already classified

Note: this is NOT exactly "top visitor countries" like Similarweb gives —
it's "geographic profile of the domain" inferred from supply-side signals.
For news portals this is usually a strong proxy (a Russian-language site
on .ru with RU hosting almost certainly has predominantly RU audience).
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from pathlib import Path
from typing import Optional

import dns.asyncresolver
import dns.exception
import httpx
import whois
from bs4 import BeautifulSoup
from langdetect import detect_langs, DetectorFactory, LangDetectException

from domain_intel.models import ConfidenceLevel, CountrySignal, GeographyInfo

logger = logging.getLogger(__name__)

# Deterministic langdetect
DetectorFactory.seed = 0


# -----------------------------------------------------------------------------
# TLD → country mapping (ccTLDs)
# -----------------------------------------------------------------------------
CCTLD_MAP: dict[str, str] = {
    # Eastern Europe / CIS
    "hu": "HU", "ru": "RU", "ua": "UA", "by": "BY", "pl": "PL", "cz": "CZ",
    "sk": "SK", "ro": "RO", "bg": "BG", "rs": "RS", "hr": "HR", "si": "SI",
    "lt": "LT", "lv": "LV", "ee": "EE", "md": "MD", "mk": "MK", "ba": "BA",
    "me": "ME", "al": "AL", "ge": "GE", "am": "AM", "az": "AZ", "kz": "KZ",
    # Western/Northern Europe
    "de": "DE", "at": "AT", "ch": "CH", "fr": "FR", "be": "BE", "nl": "NL",
    "lu": "LU", "uk": "GB", "ie": "IE", "es": "ES", "pt": "PT", "it": "IT",
    "gr": "GR", "se": "SE", "no": "NO", "dk": "DK", "fi": "FI", "is": "IS",
    # Middle East
    "il": "IL", "ir": "IR", "tr": "TR", "sa": "SA", "ae": "AE", "qa": "QA",
    "eg": "EG", "lb": "LB", "sy": "SY", "iq": "IQ", "jo": "JO", "kw": "KW",
    # Asia
    "cn": "CN", "jp": "JP", "kr": "KR", "kp": "KP", "tw": "TW", "hk": "HK",
    "in": "IN", "pk": "PK", "bd": "BD", "id": "ID", "my": "MY", "sg": "SG",
    "th": "TH", "vn": "VN", "ph": "PH",
    # Americas
    "us": "US", "ca": "CA", "mx": "MX", "br": "BR", "ar": "AR", "cl": "CL",
    "co": "CO", "pe": "PE", "ve": "VE", "uy": "UY",
    # Africa & Oceania
    "za": "ZA", "ng": "NG", "ke": "KE", "ma": "MA", "tn": "TN", "dz": "DZ",
    "au": "AU", "nz": "NZ",
}

# Language code → likely countries (used as last-resort signal)
LANG_TO_COUNTRIES: dict[str, list[str]] = {
    "hu": ["HU"], "ru": ["RU", "BY", "KZ", "UA"], "uk": ["UA"],
    "de": ["DE", "AT", "CH"], "fr": ["FR", "BE", "CA"], "es": ["ES", "MX", "AR"],
    "pt": ["PT", "BR"], "it": ["IT"], "nl": ["NL", "BE"], "pl": ["PL"],
    "cs": ["CZ"], "sk": ["SK"], "ro": ["RO", "MD"], "bg": ["BG"],
    "el": ["GR"], "sv": ["SE"], "no": ["NO"], "da": ["DK"], "fi": ["FI"],
    "tr": ["TR"], "he": ["IL"], "ar": ["SA", "EG", "AE"], "fa": ["IR"],
    "zh-cn": ["CN"], "zh-tw": ["TW"], "ja": ["JP"], "ko": ["KR"],
    "en": ["US", "GB"],  # ambiguous, low weight
}


# -----------------------------------------------------------------------------
# Individual signal collectors
# -----------------------------------------------------------------------------
class GeographyDetector:
    """Collects geographic signals for a domain."""

    def __init__(
        self,
        geoip_db_path: Optional[Path] = None,
        echolot_corpus_lookup=None,  # optional callable: (domain) -> Optional[country]
    ):
        self.geoip_db_path = geoip_db_path
        self._geoip_reader = None
        self.echolot_corpus_lookup = echolot_corpus_lookup

        if geoip_db_path and Path(geoip_db_path).exists():
            try:
                import geoip2.database
                self._geoip_reader = geoip2.database.Reader(str(geoip_db_path))
                logger.info(f"GeoIP DB loaded: {geoip_db_path}")
            except Exception as e:
                logger.warning(f"GeoIP DB load failed: {e}")

    async def analyze(self, domain: str, page_text: Optional[str] = None) -> GeographyInfo:
        """Run all signal collectors in parallel."""
        signals: list[CountrySignal] = []

        # Run signal collectors concurrently
        results = await asyncio.gather(
            self._signal_tld(domain),
            self._signal_whois(domain),
            self._signal_dns_geo(domain),
            self._signal_html_lang(domain),
            return_exceptions=True,
        )

        for r in results:
            if isinstance(r, CountrySignal):
                signals.append(r)
            elif isinstance(r, list):
                signals.extend(r)
            elif isinstance(r, Exception):
                logger.debug(f"signal failed: {r}")

        # Content-based language detection
        if page_text:
            lang_signal = self._signal_content_lang(page_text)
            if lang_signal:
                signals.extend(lang_signal)

        # Echolot corpus lookup (if available)
        if self.echolot_corpus_lookup:
            try:
                cc = self.echolot_corpus_lookup(domain)
                if cc:
                    signals.append(CountrySignal(
                        method="echolot_corpus",
                        country_code=cc,
                        weight=1.0,
                        detail="domain known in Echolot sphere DB",
                    ))
            except Exception as e:
                logger.debug(f"echolot corpus lookup failed: {e}")

        return self._aggregate(signals)

    # ----- Signal collectors -----

    async def _signal_tld(self, domain: str) -> Optional[CountrySignal]:
        """TLD heuristic — strong signal for ccTLDs."""
        parts = domain.lower().rsplit(".", 1)
        if len(parts) == 2:
            tld = parts[1]
            if tld in CCTLD_MAP:
                return CountrySignal(
                    method="tld",
                    country_code=CCTLD_MAP[tld],
                    weight=0.7,
                    detail=f".{tld} ccTLD",
                )
        return None

    async def _signal_whois(self, domain: str) -> Optional[CountrySignal]:
        """WHOIS country — registrant's country."""
        try:
            # python-whois is blocking, run in thread
            w = await asyncio.to_thread(whois.whois, domain)
            country = getattr(w, "country", None)
            if country:
                if isinstance(country, list):
                    country = country[0]
                country = str(country).upper().strip()
                if len(country) == 2:
                    return CountrySignal(
                        method="whois",
                        country_code=country,
                        weight=0.6,
                        detail=f"registrant country: {country}",
                    )
        except Exception as e:
            logger.debug(f"WHOIS for {domain} failed: {e}")
        return None

    async def _signal_dns_geo(self, domain: str) -> Optional[CountrySignal]:
        """Resolve to IP, lookup country via MaxMind GeoLite2."""
        if not self._geoip_reader:
            return None
        try:
            resolver = dns.asyncresolver.Resolver()
            resolver.timeout = 5.0
            resolver.lifetime = 5.0
            answer = await resolver.resolve(domain, "A")
            for record in answer:
                ip = str(record)
                try:
                    response = self._geoip_reader.country(ip)
                    cc = response.country.iso_code
                    if cc:
                        return CountrySignal(
                            method="dns_ip_geo",
                            country_code=cc,
                            weight=0.5,
                            detail=f"hosting IP {ip} in {cc}",
                        )
                except Exception:
                    continue
        except (dns.exception.DNSException, Exception) as e:
            logger.debug(f"DNS geo for {domain} failed: {e}")
        return None

    async def _signal_html_lang(self, domain: str) -> list[CountrySignal]:
        """Fetch homepage, look at <html lang="..."> and Content-Language header."""
        signals = []
        url = f"https://{domain}"
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; EcholotIntel/1.0)"},
            ) as client:
                resp = await client.get(url)

                # Content-Language header
                cl = resp.headers.get("content-language", "").lower()
                if cl:
                    lang = cl.split(",")[0].split("-")[0].strip()
                    countries = LANG_TO_COUNTRIES.get(lang, [])
                    for cc in countries[:1]:  # only top match
                        signals.append(CountrySignal(
                            method="content_language_header",
                            country_code=cc,
                            weight=0.6,
                            detail=f"Content-Language: {cl}",
                        ))

                # <html lang="..."> attribute
                if resp.status_code == 200 and "html" in resp.headers.get("content-type", ""):
                    try:
                        soup = BeautifulSoup(resp.text[:50000], "lxml")
                        html_tag = soup.find("html")
                        if html_tag and html_tag.get("lang"):
                            lang_attr = html_tag["lang"].lower()
                            # Could be "hu", "en-US", "ru-RU", etc.
                            if "-" in lang_attr:
                                lang_part, region_part = lang_attr.split("-", 1)
                                region_part = region_part.upper()[:2]
                                if region_part.isalpha():
                                    signals.append(CountrySignal(
                                        method="html_lang_attr",
                                        country_code=region_part,
                                        weight=0.8,
                                        detail=f'<html lang="{lang_attr}">',
                                    ))
                            else:
                                lang = lang_attr.strip()
                                countries = LANG_TO_COUNTRIES.get(lang, [])
                                for cc in countries[:1]:
                                    signals.append(CountrySignal(
                                        method="html_lang_attr",
                                        country_code=cc,
                                        weight=0.5,
                                        detail=f'<html lang="{lang_attr}">',
                                    ))
                    except Exception as e:
                        logger.debug(f"html parse failed: {e}")
        except Exception as e:
            logger.debug(f"http fetch failed for {url}: {e}")

        return signals

    def _signal_content_lang(self, text: str) -> list[CountrySignal]:
        """Detect language from a chunk of page text."""
        signals = []
        try:
            sample = text[:5000]
            detected = detect_langs(sample)
            for d in detected[:2]:
                if d.prob > 0.5:
                    countries = LANG_TO_COUNTRIES.get(d.lang, [])
                    for cc in countries[:1]:
                        signals.append(CountrySignal(
                            method="content_langdetect",
                            country_code=cc,
                            weight=0.4 * d.prob,
                            detail=f"langdetect: {d.lang} (p={d.prob:.2f})",
                        ))
        except LangDetectException:
            pass
        return signals

    # ----- Aggregation -----

    def _aggregate(self, signals: list[CountrySignal]) -> GeographyInfo:
        """Combine signals into a ranked country list."""
        # Sum weights per country, tracking which methods contributed
        country_scores: dict[str, dict] = {}
        for sig in signals:
            cc = sig.country_code.upper()
            if cc not in country_scores:
                country_scores[cc] = {"score": 0.0, "methods": []}
            country_scores[cc]["score"] += sig.weight
            country_scores[cc]["methods"].append(sig.method)

        # Sort by score desc
        ranked = sorted(country_scores.items(), key=lambda x: -x[1]["score"])
        top_countries = [
            {"country_code": cc, "score": round(v["score"], 2), "methods": v["methods"]}
            for cc, v in ranked[:5]
        ]

        primary = top_countries[0]["country_code"] if top_countries else None

        # Confidence based on number and agreement of signals
        if len(signals) >= 4 and len({s.country_code for s in signals[:4]}) <= 2:
            confidence = ConfidenceLevel.HIGH
        elif len(signals) >= 2:
            confidence = ConfidenceLevel.MEDIUM
        elif len(signals) >= 1:
            confidence = ConfidenceLevel.LOW
        else:
            confidence = ConfidenceLevel.UNKNOWN

        return GeographyInfo(
            top_countries=top_countries,
            primary_country=primary,
            signals=signals,
            confidence=confidence,
        )
