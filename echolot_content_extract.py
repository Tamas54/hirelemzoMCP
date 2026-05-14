"""Article main-content extraction for Echolot scrape_url path.

Brave-relay returns full page HTML/text without main-content extraction —
nav menus, footers, sidebars, <style>, <svg> all included. This module
post-processes it down to just the article body.

Extraction chain:
  1. trafilatura.extract()  — purpose-built for news articles, BEST
  2. readability-lxml       — Mozilla's readability port, good fallback
  3. regex strip            — emergency: drop tags + collapse whitespace

Each extractor returns a dict with `text`, `title`, `char_count`,
`extractor` (name of the one that succeeded), `lang` (only trafilatura).

Usage:
    from echolot_content_extract import extract_main_text
    result = extract_main_text(brave_response.get("text"), url=article_url)
    article_body = result["text"]
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger("echolot.content_extract")

try:
    import trafilatura
    _HAVE_TRAFILATURA = True
except ImportError:
    log.warning("trafilatura not installed — falling back to readability + regex")
    _HAVE_TRAFILATURA = False

try:
    from readability import Document as _ReadabilityDocument
    _HAVE_READABILITY = True
except ImportError:
    _HAVE_READABILITY = False

# Looks-like-HTML detector (must contain at least one tag)
_HTML_LIKE = re.compile(r"<\s*(html|body|article|main|p|div|h[1-6])\b", re.IGNORECASE)


def _is_html(s: str) -> bool:
    return bool(_HTML_LIKE.search(s or ""))


def _try_trafilatura(raw: str, url: Optional[str]) -> Optional[dict]:
    if not _HAVE_TRAFILATURA:
        return None
    try:
        # If raw doesn't look like HTML, trafilatura.extract still works on text
        # but we get better results passing HTML directly.
        text = trafilatura.extract(
            raw, url=url, include_comments=False, include_tables=False,
            favor_precision=True, no_fallback=False,
        )
        if not text or not text.strip():
            return None
        # Try to extract metadata (title, lang)
        meta = trafilatura.extract_metadata(raw, default_url=url) if _is_html(raw) else None
        return {
            "text": text.strip(),
            "title": (meta.title if meta else None),
            "char_count": len(text),
            "extractor": "trafilatura",
            "lang": (meta.language if meta else None),
        }
    except Exception as exc:
        log.warning("trafilatura failed: %s: %s", type(exc).__name__, exc)
        return None


def _try_readability(raw: str) -> Optional[dict]:
    if not _HAVE_READABILITY or not _is_html(raw):
        return None
    try:
        doc = _ReadabilityDocument(raw)
        title = doc.short_title()
        # summary() returns HTML — strip tags to get plain text
        summary_html = doc.summary()
        text = re.sub(r"<[^>]+>", " ", summary_html)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None
        return {
            "text": text,
            "title": title,
            "char_count": len(text),
            "extractor": "readability",
            "lang": None,
        }
    except Exception as exc:
        log.warning("readability failed: %s: %s", type(exc).__name__, exc)
        return None


# Tags whose content should be DROPPED entirely (not just unwrapped)
_DROP_TAG_RE = re.compile(
    r"<(script|style|svg|nav|header|footer|aside|form|noscript|iframe)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos|nbsp|ndash|mdash|hellip|#\d+|#x[0-9a-fA-F]+);")


def _try_regex_strip(raw: str) -> dict:
    """Last-resort: strip script/style/svg blocks, then all tags, collapse whitespace."""
    import html as html_module
    s = _DROP_TAG_RE.sub(" ", raw or "")
    s = _TAG_RE.sub(" ", s)
    s = html_module.unescape(s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return {
        "text": s,
        "title": None,
        "char_count": len(s),
        "extractor": "regex_strip",
        "lang": None,
    }


def extract_main_text(
    raw: str,
    *,
    url: Optional[str] = None,
    fallback_min_chars: int = 200,
) -> dict:
    """Extract main article text from raw HTML or junk-laden text.

    Tries trafilatura → readability → regex strip in order. Returns the
    first result with text length >= fallback_min_chars, or the longest
    one if all fall short.
    """
    if not raw or not raw.strip():
        return {"text": "", "title": None, "char_count": 0, "extractor": "empty", "lang": None}

    candidates: list[dict] = []
    for fn in (lambda: _try_trafilatura(raw, url),
               lambda: _try_readability(raw),
               lambda: _try_regex_strip(raw)):
        result = fn()
        if result and result["char_count"] >= fallback_min_chars:
            return result
        if result:
            candidates.append(result)
    if candidates:
        # Return the longest one — better than nothing
        return max(candidates, key=lambda r: r["char_count"])
    # All extractors failed (shouldn't happen because regex_strip always returns)
    return _try_regex_strip(raw)


__all__ = ["extract_main_text"]
