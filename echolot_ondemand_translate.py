"""On-demand UI translation — translate displayed snippets into the user's
language at render time, cached in the DB so each (text, lang) is paid for once.

Direct original→target translation (no English pivot — matches the Kommandant's
N×N flash test). Shares the SiliconFlow/DeepSeek-V4-Flash config + key gate with
the classifier. If no key, or on failure, returns identity (original text) — the
UI degrades to original, never blocks.

Public API:
  translate_map(texts, target_lang, db_path) -> {original: translated}
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.request

from echolot_classifier import _config, _parse_json_lenient, REQUEST_TIMEOUT

_LANG_NAME = {
    "hu": "Hungarian", "en": "English", "de": "German", "fr": "French",
    "it": "Italian", "es": "Spanish", "pl": "Polish", "ru": "Russian",
    "uk": "Ukrainian", "zh": "Chinese", "ja": "Japanese",
}
_BATCH = 20
_MAX_TEXTS = 80  # hard cap per render call (keeps page latency bounded)


def _h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _ensure_cache(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS translation_cache (
            text_hash   TEXT NOT NULL,
            target_lang TEXT NOT NULL,
            translated  TEXT NOT NULL,
            created_at  TEXT,
            PRIMARY KEY (text_hash, target_lang)
        )""")


def _call_translate(cfg: dict, texts: list[str], target_lang: str,
                    retries: int = 2) -> dict[str, str]:
    """Translate a small batch; return {original: translated}. {} on failure."""
    name = _LANG_NAME.get(target_lang, target_lang)
    numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
    system = (
        f"You are a precise translator. Translate each numbered text into {name}. "
        "Keep proper nouns and named entities intact; translate faithfully, do not "
        'summarize. Respond ONLY with JSON: {"results":[{"i":<n>,"t":"<translation>"}]} '
        "— one object per text, same i numbers."
    )
    body = json.dumps({
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": numbered}],
        "temperature": 0.1, "max_tokens": 2200,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
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
            results = parsed.get("results") if isinstance(parsed, dict) else parsed
            if results:
                out = {}
                for rec in results:
                    try:
                        i = int(rec.get("i"))
                    except (TypeError, ValueError):
                        continue
                    t = str(rec.get("t", "")).strip()
                    if 0 <= i < len(texts) and t:
                        out[texts[i]] = t
                if out:
                    return out
        except Exception:
            pass
        time.sleep(1.0 * (attempt + 1))
    return {}


def translate_map(texts, target_lang: str, db_path: str = "echolot.db") -> dict[str, str]:
    """Return {original: translated} for the given texts into target_lang.

    Cache-first; misses translated in batches via flash and cached. Always
    returns an entry for every non-empty input (identity if no key / failure)."""
    target_lang = (target_lang or "en").lower()
    uniq = list({t for t in (texts or []) if t and t.strip()})[:_MAX_TEXTS]
    if not uniq:
        return {}
    out: dict[str, str] = {}
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_cache(conn)
        misses = []
        for t in uniq:
            row = conn.execute(
                "SELECT translated FROM translation_cache WHERE text_hash=? AND target_lang=?",
                (_h(t), target_lang)).fetchone()
            if row:
                out[t] = row[0]
            else:
                misses.append(t)
        cfg = _config()
        if misses and cfg is not None:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for i in range(0, len(misses), _BATCH):
                chunk = misses[i:i + _BATCH]
                tr = _call_translate(cfg, chunk, target_lang)
                for orig, trans in tr.items():
                    out[orig] = trans
                    conn.execute(
                        "INSERT OR REPLACE INTO translation_cache VALUES (?,?,?,?)",
                        (_h(orig), target_lang, trans, now))
            conn.commit()
        for t in uniq:        # identity fallback for anything still missing
            out.setdefault(t, t)
        return out
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    lang = sys.argv[1] if len(sys.argv) > 1 else "hu"
    samples = ["Иран нанёс удары по американским базам",
               "Germany blocked the EU sanctions package",
               "楽天モバイルが新サービスを開始"]
    print(json.dumps(translate_map(samples, lang, "echolot.db"),
                     ensure_ascii=False, indent=2))
