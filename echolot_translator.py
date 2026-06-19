"""Echolot translation worker — English-pivot title/lead translation.

Sibling of echolot_classifier: same key gate, same batch shape. Fills
articles.title_en / lead_en for non-English articles so the passport can show
headline_translated and produce cross-lingual summaries. The frame classifier
still judges framing on the ORIGINAL language (spec §2.1) — EN is a pivot only,
not a replacement.

KEY-GATED: no-op without an API key. Shares CLASSIFIER_API_KEY / _API_BASE with
the classifier (one SiliconFlow/DeepSeek account); TRANSLATOR_MODEL overrides the
model (default a fast/flash model — translation is cheap, ~$0.0005/article per the
Kommandant's flash test). The production engine to port is
~/Claus/testtranslator/flash_translation_test.py.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import urllib.request
from pathlib import Path

from echolot_classifier import (
    _config as _shared_config,
    _load_env_file_once,
    _parse_json_lenient,
)  # shared key gate + lenient JSON parse

log = logging.getLogger("echolot-translator")

DB_PATH = Path(os.environ.get("DB_PATH", "echolot.db"))
BATCH_SIZE = int(os.environ.get("TRANSLATOR_BATCH", "12"))
LOOP_SLEEP = int(os.environ.get("TRANSLATOR_LOOP_SLEEP", "30"))
REQUEST_TIMEOUT = int(os.environ.get("TRANSLATOR_TIMEOUT", "60"))
# Kor-küszöb (mint a klasszifikátoré): csak e dátumtól (MÁTÓL) felfelé fordít —
# a 48k-s hátralékot NEM (token-megtakarítás). A CLASSIFIER_MIN_PUBLISHED-re
# esik vissza, így egy env-változó mindkét workert fedi. Üres = korlátlan.
MIN_PUBLISHED = (os.environ.get("TRANSLATOR_MIN_PUBLISHED")
                 or os.environ.get("CLASSIFIER_MIN_PUBLISHED", "")).strip()


def _config() -> dict | None:
    _load_env_file_once()
    cfg = _shared_config()  # None if no CLASSIFIER_API_KEY
    if cfg is None:
        return None
    # Translation is cheap → allow a separate (usually smaller/faster) model.
    cfg = dict(cfg)
    cfg["model"] = os.environ.get(
        "TRANSLATOR_MODEL",
        os.environ.get("CLASSIFIER_MODEL", "deepseek-ai/DeepSeek-V4-Flash"))
    return cfg


def is_enabled() -> bool:
    return _config() is not None


_SYSTEM = (
    "You are a precise news translator. Translate each numbered article's TITLE "
    "and LEAD into natural English. Keep proper nouns and named entities intact. "
    "Do not editorialize or summarize — translate faithfully. Respond ONLY with "
    'JSON: {"results":[{"i":<n>,"title_en":"...","lead_en":"..."}, ...]} — one '
    "object per article, same i numbers."
)


def _build_prompt(batch: list[dict]) -> str:
    lines = []
    for n, a in enumerate(batch):
        title = (a["title"] or "").replace("\n", " ").strip()
        lead = (a["lead"] or "").replace("\n", " ").strip()[:400]
        lines.append(f"[{n}] ({a['language']}) TITLE: {title}\n    LEAD: {lead}")
    return "Translate to English:\n\n" + "\n\n".join(lines)


def _call_llm(cfg: dict, batch: list[dict], retries: int = 3) -> list[dict] | None:
    body = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _build_prompt(batch)},
        ],
        "temperature": 0.1,
        "max_tokens": 2500,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},  # V4-Flash: force Non-Think (see classifier)
    }).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{cfg['base']}/chat/completions", data=body,
                headers={"Authorization": f"Bearer {cfg['key']}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            parsed = _parse_json_lenient(content)
            if parsed is not None:
                return parsed.get("results") if isinstance(parsed, dict) else parsed
            log.warning("translator: unparseable response (attempt %d/%d)", attempt + 1, retries)
        except Exception as exc:
            log.warning("translator LLM call failed (attempt %d/%d): %s", attempt + 1, retries, exc)
        time.sleep(1.5 * (attempt + 1))
    return None


def _claim_batch(conn: sqlite3.Connection, size: int) -> list[dict]:
    floor = " AND published_at >= ?" if MIN_PUBLISHED else ""
    params = ([MIN_PUBLISHED, size] if MIN_PUBLISHED else [size])
    rows = conn.execute(
        f"""SELECT article_id, title, lead, language FROM articles
           WHERE translation_status IS NULL
             AND language IS NOT NULL AND language != 'en'
             AND title IS NOT NULL AND title != ''{floor}
           ORDER BY published_at DESC
           LIMIT ?""", params
    ).fetchall()
    return [{"article_id": r[0], "title": r[1], "lead": r[2], "language": r[3]} for r in rows]


def _mark_english_identity(conn: sqlite3.Connection) -> int:
    """English articles need no translation — copy through (no LLM, runs always)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cur = conn.execute(
        """UPDATE articles SET title_en=title, lead_en=lead,
               translation_status='ok', translated_at=?
           WHERE translation_status IS NULL AND language='en'""", (now,))
    return cur.rowcount


def run_once(db_path: str | Path = None, batch_size: int = BATCH_SIZE) -> int:
    cfg = _config()
    if cfg is None:
        return 0
    db_path = db_path or DB_PATH
    conn = sqlite3.connect(str(db_path), timeout=15)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        ident = _mark_english_identity(conn)
        batch = _claim_batch(conn, batch_size)
        written = ident
        if batch:
            results = _call_llm(cfg, batch)
            if results is None:
                conn.commit()  # keep the EN identity pass; retry non-EN next cycle
                return written
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            by_i = {}
            for rec in (results or []):
                try:
                    by_i[int(rec.get("i"))] = rec
                except (TypeError, ValueError):
                    continue
            for n, a in enumerate(batch):
                rec = by_i.get(n)
                if not rec or not str(rec.get("title_en", "")).strip():
                    conn.execute(
                        "UPDATE articles SET translation_status='failed', translated_at=? "
                        "WHERE article_id=?", (now, a["article_id"]))
                    continue
                conn.execute(
                    """UPDATE articles SET title_en=?, lead_en=?,
                           translation_status='ok', translated_at=?
                       WHERE article_id=?""",
                    (str(rec.get("title_en", "")).strip(),
                     str(rec.get("lead_en", "")).strip(), now, a["article_id"]))
                written += 1
        conn.commit()
        return written
    finally:
        conn.close()


def _pending_count(db_path) -> int:
    conn = sqlite3.connect(str(db_path or DB_PATH), timeout=15)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM articles WHERE translation_status IS NULL "
            "AND title IS NOT NULL AND title != ''").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def worker_loop(db_path: str | Path = None) -> None:
    if not is_enabled():
        log.info("translator disabled (no CLASSIFIER_API_KEY) — title_en stays empty")
        return
    # Kommandant 2026-06-19: a háttér cím/lead-fordító ALAPÉRTELMEZETTEN KI —
    # minden fordítás on-demand (a listák/landing renderkor cache-elve, a teljes
    # szöveg story-megnyitáskor). Háttér-előtöltés csak TRANSLATOR_BACKGROUND=1-re.
    if os.environ.get("TRANSLATOR_BACKGROUND", "").lower() not in ("1", "true", "yes", "on"):
        log.info("background translator disabled (on-demand only) — "
                 "set TRANSLATOR_BACKGROUND=1 to pre-fill title_en/lead_en")
        return
    cfg = _config()
    log.info("translator worker started: model=%s", cfg["model"])
    idle = 0
    while True:
        try:
            n = run_once(db_path)
        except Exception as exc:
            log.warning("translator batch error: %s", exc)
            n = 0
        if n:
            log.info("translated %d articles", n)
            idle = 0
            time.sleep(2)
        elif _pending_count(db_path) > 0:
            idle = 0
            time.sleep(15)  # transient — retry soon, no long backoff
        else:
            idle += 1
            time.sleep(min(LOOP_SLEEP * idle, 300))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("translator enabled:", is_enabled())
    if is_enabled():
        print("wrote:", run_once())
