"""Echolot F1 analytical-layer classifier — frame + emotion + sentiment.

The batch worker that fills the F1 columns on `articles` (frame, frame_confidence,
emotion, sentiment, sentiment_intensity). ONE LLM prompt → all three fields for a
whole batch, ingest-time, cached on the row (classification_status). The
narrative_passport and the §2.5 tools (frame_divergence, source_profile, ...)
only AGGREGATE these columns — they never call the model synchronously.

KEY-GATED: if no API key is configured the worker is a no-op (logs once and
returns). Nothing here costs anything until a key is present. Wire a key via:
  CLASSIFIER_API_KEY   (+ optional CLASSIFIER_API_BASE, CLASSIFIER_MODEL)
On Railway set these as service env vars. For local testing you can point
CLASSIFIER_ENV_FILE at a dotenv that defines CLASSIFIER_API_KEY (e.g. the key
the Kommandant keeps in ~/Claus/.env — copy it into the var, don't hard-couple).

Taxonomies (spec §2.1–2.4):
  frame   : conflict | human_interest | economic | morality | vulnerability |
            responsibility | security_threat | progress | other   (Semetko–Valkenburg)
  emotion : anger | fear | joy | surprise | sadness | trust | disgust | other  (Plutchik)
  sentiment: float -1..+1 ; sentiment_intensity: low | medium | high
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("echolot-classifier")

# Ring-buffer a legutóbbi log-sorokról — a /health?classifier=1 diagnosztika
# adja vissza, így Railway-log-hozzáférés nélkül is látszik, mire bukik a
# worker (rate limit? DB lock? parse hiba?).
from collections import deque as _deque
_recent_logs: "_deque[str]" = _deque(maxlen=25)


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _recent_logs.append(
                f"{time.strftime('%H:%M:%S', time.gmtime(record.created))}Z "
                f"{record.levelname} {record.getMessage()}")
        except Exception:
            pass


log.addHandler(_RingHandler())
log.setLevel(logging.INFO)

DB_PATH = Path(os.environ.get("DB_PATH", "echolot.db"))

FRAMES = {"conflict", "human_interest", "economic", "morality", "vulnerability",
          "responsibility", "security_threat", "progress", "other"}
EMOTIONS = {"anger", "fear", "joy", "surprise", "sadness", "trust", "disgust", "other"}
INTENSITIES = {"low", "medium", "high"}

BATCH_SIZE = int(os.environ.get("CLASSIFIER_BATCH", "12"))
LOOP_SLEEP = int(os.environ.get("CLASSIFIER_LOOP_SLEEP", "30"))  # seconds between batches
REQUEST_TIMEOUT = int(os.environ.get("CLASSIFIER_TIMEOUT", "60"))


# ---------------------------------------------------------------------------
# Config / key gating
# ---------------------------------------------------------------------------
def _load_env_file_once() -> None:
    """Optionally hydrate CLASSIFIER_* from a dotenv pointed to by
    CLASSIFIER_ENV_FILE (dev convenience; does not override real env vars)."""
    path = os.environ.get("CLASSIFIER_ENV_FILE")
    if not path or not Path(path).is_file():
        return
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k.startswith("CLASSIFIER_") and k not in os.environ:
                os.environ[k] = v
    except Exception as exc:  # never let dev-config break the worker
        log.warning("classifier env-file load failed: %s", exc)


_KEY_ENV_NAMES = ("CLASSIFIER_API_KEY", "CLASSIFYER_API_KEY",  # accept the common typo
                  "SILICONFLOW_API_KEY", "CLASSIFIER_KEY",
                  "ECHOLOT_LLM_KEY", "SILICONFLOW_KEY")


def _config() -> dict | None:
    _load_env_file_once()
    # Accept several env-var names so a Railway var named SILICONFLOW_API_KEY
    # (the key's natural name) works without renaming.
    key = None
    for name in _KEY_ENV_NAMES:
        if os.environ.get(name):
            key = os.environ[name]
            break
    if not key:
        return None
    return {
        "key": key,
        "base": os.environ.get("CLASSIFIER_API_BASE", "https://api.siliconflow.com/v1").rstrip("/"),
        "model": os.environ.get("CLASSIFIER_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
    }


def is_enabled() -> bool:
    return _config() is not None


# ---------------------------------------------------------------------------
# Prompt + LLM call
# ---------------------------------------------------------------------------
_SYSTEM = (
    "You are a precise news-analysis classifier. For each numbered article you "
    "receive (title + lead, in its ORIGINAL language — judge framing in that "
    "language, do not translate), return its dominant news frame, dominant "
    "emotion, and sentiment. Respond ONLY with JSON.\n\n"
    "frame ∈ [conflict, human_interest, economic, morality, vulnerability, "
    "responsibility, security_threat, progress, other] (Semetko–Valkenburg).\n"
    "emotion ∈ [anger, fear, joy, surprise, sadness, trust, disgust, other] (Plutchik).\n"
    "sentiment: float in [-1,1] (negative→positive). intensity ∈ [low, medium, high].\n"
    "frame_confidence: float in [0,1].\n\n"
    'Return: {"results":[{"i":<number>,"frame":"...","frame_confidence":0.0,'
    '"emotion":"...","sentiment":0.0,"intensity":"..."}, ...]} — one object per '
    "article, same i numbers, nothing else."
)


def _build_user_prompt(batch: list[dict]) -> str:
    lines = []
    for n, a in enumerate(batch):
        title = (a["title"] or "").replace("\n", " ").strip()
        lead = (a["lead"] or "").replace("\n", " ").strip()[:300]
        lines.append(f"[{n}] TITLE: {title}\n    LEAD: {lead}")
    return "Classify these articles:\n\n" + "\n\n".join(lines)


def _parse_json_lenient(content: str):
    """Parse model output that may be wrapped in markdown fences or have leading
    prose. Returns the parsed object or None."""
    if not content or not content.strip():
        return None
    s = content.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)  # first {...} blob
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


def _call_llm(cfg: dict, batch: list[dict], retries: int = 3) -> list[dict] | None:
    body = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _build_user_prompt(batch)},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
        # DeepSeek-V4-Flash defaults to Think mode; disable it (reasoning tokens
        # would eat the budget and can wrap the JSON). V4 form, NOT enable_thinking.
        "thinking": {"type": "disabled"},
    }).encode()
    # Retry on transient empties / rate limits / malformed JSON. Returning None
    # here makes the caller LEAVE the batch NULL (retried next cycle), so a
    # transient failure never permanently marks articles 'failed'.
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
            log.warning("classifier: unparseable response (attempt %d/%d)", attempt + 1, retries)
        except Exception as exc:
            log.warning("classifier LLM call failed (attempt %d/%d): %s", attempt + 1, retries, exc)
        time.sleep(1.5 * (attempt + 1))
    return None


def _sanitize(rec: dict) -> dict | None:
    """Coerce one model record into safe column values, or None if unusable."""
    try:
        frame = str(rec.get("frame", "other")).lower().strip()
        emotion = str(rec.get("emotion", "other")).lower().strip()
        sentiment = float(rec.get("sentiment", 0.0))
        intensity = str(rec.get("intensity", "low")).lower().strip()
        conf = float(rec.get("frame_confidence", 0.5))
    except (TypeError, ValueError):
        return None
    return {
        "frame": frame if frame in FRAMES else "other",
        "frame_confidence": max(0.0, min(1.0, conf)),
        "emotion": emotion if emotion in EMOTIONS else "other",
        "sentiment": max(-1.0, min(1.0, sentiment)),
        "sentiment_intensity": intensity if intensity in INTENSITIES else "low",
    }


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------
def _claim_batch(conn: sqlite3.Connection, size: int) -> list[dict]:
    rows = conn.execute(
        """SELECT article_id, title, lead FROM articles
           WHERE classification_status IS NULL
             AND title IS NOT NULL AND title != ''
           ORDER BY published_at DESC
           LIMIT ?""", (size,)
    ).fetchall()
    return [{"article_id": r[0], "title": r[1], "lead": r[2]} for r in rows]


def pending_count(db_path: str | Path = None) -> int:
    """How many articles still await classification (cheap)."""
    conn = sqlite3.connect(str(db_path or DB_PATH), timeout=15)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM articles WHERE classification_status IS NULL "
            "AND title IS NOT NULL AND title != ''").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def run_once(db_path: str | Path = None, batch_size: int = BATCH_SIZE) -> int:
    """Classify one batch of pending articles. Returns #articles written.
    Returns 0 (no-op) if no API key is configured."""
    cfg = _config()
    if cfg is None:
        return 0
    db_path = db_path or DB_PATH
    conn = sqlite3.connect(str(db_path), timeout=15)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        batch = _claim_batch(conn, batch_size)
        if not batch:
            return 0
        results = _call_llm(cfg, batch)
        if results is None:
            # Total/transient failure after retries — leave the batch NULL so it
            # is retried next cycle (do NOT burn it as 'failed').
            return 0
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        written = 0
        by_i = {}
        for rec in (results or []):
            try:
                by_i[int(rec.get("i"))] = rec
            except (TypeError, ValueError):
                continue
        for n, a in enumerate(batch):
            rec = by_i.get(n)
            vals = _sanitize(rec) if rec else None
            if vals is None:
                # Mark failed so we don't spin forever on a bad article/response.
                conn.execute(
                    "UPDATE articles SET classification_status='failed', classified_at=? "
                    "WHERE article_id=?", (now, a["article_id"]))
                continue
            conn.execute(
                """UPDATE articles SET frame=?, frame_confidence=?, emotion=?,
                       sentiment=?, sentiment_intensity=?,
                       classification_status='ok', classified_at=?
                   WHERE article_id=?""",
                (vals["frame"], vals["frame_confidence"], vals["emotion"],
                 vals["sentiment"], vals["sentiment_intensity"], now, a["article_id"]))
            written += 1
        conn.commit()
        return written
    finally:
        conn.close()


def diagnostics(db_path: str | Path = None) -> dict:
    """Élő állapot a /health végpontnak: kulcs-gating + DB-számlálók.
    A kulcs ÉRTÉKÉT soha nem adja vissza, csak hogy melyik env-név talált."""
    cfg = _config()
    matched_env = next((n for n in _KEY_ENV_NAMES if os.environ.get(n)), None)
    import threading as _th
    out: dict = {
        "enabled": cfg is not None,
        "key_env_matched": matched_env,
        "model": cfg["model"] if cfg else None,
        "base": cfg["base"] if cfg else None,
        # A start.py "classifier" nevű szála él-e még (ugyanaz a process).
        "thread_alive": any(
            t.name == "classifier" and t.is_alive() for t in _th.enumerate()),
        "recent_logs": list(_recent_logs),
    }
    try:
        conn = sqlite3.connect(str(db_path or DB_PATH), timeout=15)
        try:
            out["counts"] = dict(conn.execute(
                "SELECT COALESCE(classification_status,'pending'), COUNT(*) "
                "FROM articles GROUP BY 1").fetchall())
            out["last_classified_at"] = conn.execute(
                "SELECT MAX(classified_at) FROM articles "
                "WHERE classification_status='ok'").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:
        out["db_error"] = str(exc)
    return out


_probe_last: list[float] = [0.0]


def probe() -> dict:
    """Egy apró (2-cikkes dummy) LLM-hívás, ami visszaadja a NYERS hibát is —
    így a produkción kívülről kideríthető, miért bukik a hívás (401/404/
    network/parse). 60s throttle, hogy publikus végpontról se lehessen
    költséget generálni vele."""
    cfg = _config()
    if cfg is None:
        return {"ok": False, "error": "no API key configured"}
    now = time.time()
    if now - _probe_last[0] < 60:
        return {"ok": False, "error": "throttled — try again in a minute"}
    _probe_last[0] = now
    batch = [{"article_id": "probe", "title": "Test article about economy",
              "lead": "A short test lead."}]
    t0 = time.time()
    try:
        body = json.dumps({
            "model": cfg["model"],
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user", "content": _build_user_prompt(batch)}],
            "temperature": 0.1, "max_tokens": 500,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }).encode()
        req = urllib.request.Request(
            f"{cfg['base']}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {cfg['key']}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        parsed = _parse_json_lenient(content)
        return {"ok": parsed is not None,
                "latency_ms": int((time.time() - t0) * 1000),
                "raw_sample": content[:200] if parsed is None else None}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode()[:300]
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {exc.code}: {detail}",
                "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": int((time.time() - t0) * 1000)}


def worker_loop(db_path: str | Path = None) -> None:
    """Background loop for start.py. No-ops politely (and stops) if no key."""
    if not is_enabled():
        log.info("classifier disabled (no CLASSIFIER_API_KEY) — F1 columns stay 'pending'")
        return
    cfg = _config()
    log.info("classifier worker started: model=%s base=%s", cfg["model"], cfg["base"])
    idle = 0
    while True:
        try:
            n = run_once(db_path)
        except Exception as exc:
            log.warning("classifier batch error: %s", exc)
            n = 0
        if n:
            log.info("classified %d articles", n)
            idle = 0
            time.sleep(2)
        elif pending_count(db_path) > 0:
            log.info("batch wrote 0 but work remains — retry in 15s")
            # Batch yielded nothing but work REMAINS → transient (rate limit / bad
            # response). Retry soon; do NOT enter the long caught-up backoff (that
            # was making a single rate-limit look like a multi-minute stall).
            idle = 0
            time.sleep(15)
        else:
            idle += 1
            time.sleep(min(LOOP_SLEEP * idle, 300))  # truly caught up — ease off


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("classifier enabled:", is_enabled())
    if is_enabled():
        print("wrote:", run_once())
