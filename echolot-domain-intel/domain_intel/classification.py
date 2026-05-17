"""
Domain category classification.

Strategy:
  1. Look up domain in Echolot's own sphere DB (free, fastest, most authoritative)
  2. AI classification via OpenAI-compatible endpoint (Bridge / SiliconFlow)
  3. Keyword-based fallback (offline, instant)

For news/media analysis, the Echolot corpus is the gold standard since it's
purpose-built for this. The AI fallback handles long-tail unknown domains.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

from domain_intel.models import CategoryInfo, ConfidenceLevel

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Keyword-based fallback patterns (used when AI is unavailable)
# -----------------------------------------------------------------------------
KEYWORD_PATTERNS: dict[str, list[str]] = {
    "news_media": [
        "news", "press", "media", "post", "times", "tribune", "herald",
        "gazette", "daily", "weekly", "journal", "report", "hirek", "hir",
        "novosti", "izvestiya", "pravda", "newsroom", "telex", "index",
        "haaretz", "tass", "ria", "rt", "haber",
    ],
    "government": [
        "gov", "gouv", "kormany", "parliament", "ministry", "minister",
        "official", "state", ".gov.", "europa.eu",
    ],
    "academia": [
        "edu", "university", "college", "academic", ".ac.", "research",
        "institute", "egyetem",
    ],
    "tech": [
        "github", "stack", "tech", "dev", "coder", "engineer", "software",
        "hacker", "code",
    ],
    "social_media": [
        "twitter", "facebook", "instagram", "tiktok", "reddit", "linkedin",
        "telegram", "vk.com", "weibo", "youtube",
    ],
    "finance": [
        "bank", "finance", "trading", "invest", "stock", "crypto", "money",
        "wall", "forex", "bourse",
    ],
    "ecommerce": [
        "shop", "store", "buy", "market", "amazon", "ebay", "alibaba",
    ],
    "entertainment": [
        "netflix", "spotify", "music", "movie", "film", "tv", "show",
    ],
    "search_engine": [
        "google", "bing", "yandex", "baidu", "duckduckgo", "search",
    ],
}


# -----------------------------------------------------------------------------
# Classifier
# -----------------------------------------------------------------------------
class CategoryClassifier:
    """
    Classifies a domain into a category.

    Constructor args:
      - echolot_corpus_lookup: optional callable (domain) -> Optional[dict]
        returning {sphere, category, ...} if domain is in the Echolot DB
      - ai_api_base / ai_api_key / ai_model: optional OpenAI-compatible
        endpoint for AI classification (e.g. SiliconFlow with Kimi K2)
    """

    def __init__(
        self,
        echolot_corpus_lookup=None,
        ai_api_base: Optional[str] = None,
        ai_api_key: Optional[str] = None,
        ai_model: str = "moonshotai/Kimi-K2-Instruct",
    ):
        self.echolot_corpus_lookup = echolot_corpus_lookup
        self.ai_api_base = ai_api_base
        self.ai_api_key = ai_api_key
        self.ai_model = ai_model

    async def classify(
        self,
        domain: str,
        page_text: Optional[str] = None,
        page_title: Optional[str] = None,
    ) -> CategoryInfo:
        """Classify a domain into a primary category + sub-categories."""

        # 1. Echolot corpus lookup (highest authority for news/media)
        if self.echolot_corpus_lookup:
            try:
                hit = self.echolot_corpus_lookup(domain)
                if hit:
                    return CategoryInfo(
                        primary_category=hit.get("category", "news_media"),
                        sub_categories=hit.get("sub_categories", []),
                        echolot_sphere=hit.get("sphere"),
                        classification_method="echolot_corpus",
                        confidence=ConfidenceLevel.HIGH,
                    )
            except Exception as e:
                logger.debug(f"echolot lookup failed: {e}")

        # 2. AI classification (if configured and we have page content)
        if self.ai_api_base and self.ai_api_key and (page_text or page_title):
            ai_result = await self._ai_classify(domain, page_title, page_text)
            if ai_result:
                return ai_result

        # 3. Keyword fallback
        return self._keyword_classify(domain, page_title, page_text)

    async def _ai_classify(
        self,
        domain: str,
        page_title: Optional[str],
        page_text: Optional[str],
    ) -> Optional[CategoryInfo]:
        """Use AI model (Kimi K2 / DeepSeek / etc.) to classify."""
        text_sample = (page_text or "")[:1500]
        prompt = f"""Classify this website into a category. Return ONLY JSON.

Domain: {domain}
Title: {page_title or 'N/A'}
Content sample: {text_sample}

Categories: news_media, government, academia, tech, social_media, finance,
ecommerce, entertainment, search_engine, ngo, religion, sports, health, other

Return JSON: {{"primary_category": "...", "sub_categories": ["...", "..."]}}"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.ai_api_base.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.ai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.ai_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 200,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]

                import json
                parsed = json.loads(content)
                primary = parsed.get("primary_category", "other")
                subs = parsed.get("sub_categories", [])

                return CategoryInfo(
                    primary_category=primary,
                    sub_categories=subs if isinstance(subs, list) else [],
                    classification_method="ai_classifier",
                    confidence=ConfidenceLevel.MEDIUM,
                )
        except Exception as e:
            logger.warning(f"AI classification failed for {domain}: {e}")
        return None

    def _keyword_classify(
        self,
        domain: str,
        page_title: Optional[str] = None,
        page_text: Optional[str] = None,
    ) -> CategoryInfo:
        """Last-resort keyword matching."""
        haystack = " ".join(filter(None, [
            domain.lower(),
            (page_title or "").lower(),
            (page_text or "")[:2000].lower(),
        ]))

        scores: dict[str, int] = {}
        for cat, keywords in KEYWORD_PATTERNS.items():
            score = sum(1 for kw in keywords if kw in haystack)
            if score > 0:
                scores[cat] = score

        if scores:
            ranked = sorted(scores.items(), key=lambda x: -x[1])
            primary = ranked[0][0]
            subs = [c for c, _ in ranked[1:3]]
            return CategoryInfo(
                primary_category=primary,
                sub_categories=subs,
                classification_method="keyword_fallback",
                confidence=ConfidenceLevel.LOW,
            )

        return CategoryInfo(
            primary_category=None,
            classification_method="unknown",
            confidence=ConfidenceLevel.UNKNOWN,
        )
