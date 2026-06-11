"""Nyelvközi entitás-dedup — Wikidata QID linking (echolot-entity-dedup-spec).

Hadicél: "Donald Trump" + "Трамп" + "Дональд Трамп" = EGY entitás (Q22686).
KISS: nincs saját entity-linking modell — a Wikidata adja a többnyelvű
alias-térképet, mi egy vékony linking + cache réteget teszünk fölé.

3 fogaskerék (spec §1):
  1. entity_alias tábla   — alias+lang → QID cache (~95% hit idővel)
  2. Wikidata linker      — wbsearchentities + P31/sitelink diszambiguáció
  3. entity_canonical     — QID, kanonikus nevek, hydrate-elt aliasokkal

A linking SOSEM a hot path-on fut: aszinkron worker (start.py szál),
hits szerint csökkenő sorrendben (top-200 entitás ≈ említések ~80%-a).
Rate limit: ~1 link/sec (2 Wikidata-hívás linkenként, udvarias UA-val).

Diszambiguációs fa (spec §4):
  1. P31 (instance of) egyezés az etype-pal
  2. sitelink-prior (a "híres" olvasat nyer)
  3. küszöb: sitelinks < 5 VAGY top-2 közeli → 'ambiguous', NEM linkelünk
     (hamis merge > hiányzó merge kár)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("echolot.entity_linker")

WD_API = "https://www.wikidata.org/w/api.php"
_UA = "Echolot/1.0 (entity-linker; https://github.com/Tamas54/hirelemzoMCP)"

# A felület nyelvei — a hydrate ezekre tölti elő az aliasokat.
LANGS = ("en", "hu", "de", "fr", "it", "es", "pl", "ru", "uk", "zh")

# Diszambiguációs típus-szűrő: instance-of (P31) osztályok etype-onként.
ETYPE_P31 = {
    "person": {"Q5"},
    "org": {"Q43229", "Q4830453", "Q7210356", "Q484652", "Q2659904",
            "Q7278", "Q31855", "Q15911314", "Q163740"},
    "place": {"Q515", "Q6256", "Q56061", "Q82794", "Q3957", "Q1549591",
              "Q5119", "Q35657", "Q10864048", "Q15284"},
}
MIN_SITELINKS = 5          # ez alatt 'ambiguous'
RUNNERUP_RATIO = 0.8       # top2/top1 e fölött → 'ambiguous'


def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(str(db_path), timeout=15)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def ensure_tables(db_path: str) -> None:
    conn = _conn(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_canonical (
                qid        TEXT PRIMARY KEY,
                label_en   TEXT,
                label_hu   TEXT,
                etype      TEXT,
                sitelinks  INTEGER,
                updated_at TEXT
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_alias (
                alias  TEXT NOT NULL,
                lang   TEXT NOT NULL,
                qid    TEXT,
                status TEXT DEFAULT 'pending',
                hits   INTEGER DEFAULT 1,
                PRIMARY KEY (alias, lang)
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_alias_status "
                     "ON entity_alias(status, hits DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_alias_qid ON entity_alias(qid)")
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── Wikidata hívások ───────────────────────────────────────────────────

def _wd_get(params: dict) -> dict:
    url = WD_API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def search_candidates(alias: str, lang: str, limit: int = 6) -> list[dict]:
    """wbsearchentities — nyelv-tudatos jelölt-keresés."""
    try:
        r = _wd_get({"action": "wbsearchentities", "search": alias,
                     "language": lang, "uselang": lang,
                     "type": "item", "limit": limit})
        return r.get("search", []) or []
    except Exception as exc:
        log.warning("wbsearchentities(%r, %s) failed: %s", alias, lang, exc)
        return []


def get_entities(qids: list[str]) -> dict:
    """wbgetentities — P31 + sitelinks + labelek/aliasok a LANGS nyelveken."""
    if not qids:
        return {}
    try:
        r = _wd_get({"action": "wbgetentities", "ids": "|".join(qids[:10]),
                     "props": "claims|sitelinks|labels|aliases",
                     "languages": "|".join(LANGS)})
        return r.get("entities", {}) or {}
    except Exception as exc:
        log.warning("wbgetentities(%s) failed: %s", qids[:3], exc)
        return {}


def _p31_set(ent: dict) -> set[str]:
    out = set()
    for c in (ent.get("claims", {}).get("P31") or []):
        dv = c.get("mainsnak", {}).get("datavalue")
        if dv and isinstance(dv.get("value"), dict):
            out.add(dv["value"].get("id", ""))
    return out


# ─── Linking + hydrate ──────────────────────────────────────────────────

def link_alias(db_path: str, alias: str, lang: str, etype: str = "") -> str:
    """Egy alias linkelése. Visszaadja a státuszt: linked|ambiguous|no_match.

    Sikeres linknél: entity_canonical upsert + TELJES alias-hydrate (a QID
    minden nyelvi labelje/aliasa bekerül a cache-be → a következő variáns
    már Wikidata-hívás NÉLKÜL talál) + article_entities.qid visszatöltés."""
    cands = search_candidates(alias, lang)
    if not cands:
        _set_status(db_path, alias, lang, "no_match", None)
        return "no_match"
    ents = get_entities([c["id"] for c in cands])
    if not ents:
        _set_status(db_path, alias, lang, "no_match", None)
        return "no_match"

    # 1) etype-szűrő (P31)
    allowed = ETYPE_P31.get((etype or "").lower())
    scored: list[tuple[int, str, dict]] = []
    for qid, ent in ents.items():
        if allowed and not (_p31_set(ent) & allowed):
            continue
        scored.append((len(ent.get("sitelinks") or {}), qid, ent))
    if not scored and allowed:
        # etype-szűrés mindent kiejtett → engedjük szűrő nélkül (az F1 etype
        # is LLM-becslés, lehet téves), de a küszöbök szigorúan élnek
        scored = [(len(e.get("sitelinks") or {}), q, e) for q, e in ents.items()]
    if not scored:
        _set_status(db_path, alias, lang, "no_match", None)
        return "no_match"

    # 2) sitelink-prior
    scored.sort(key=lambda x: -x[0])
    top_links, top_qid, top_ent = scored[0]

    # 3) bizonytalansági küszöbök
    if top_links < MIN_SITELINKS:
        _set_status(db_path, alias, lang, "ambiguous", None)
        return "ambiguous"
    if len(scored) > 1 and scored[1][0] >= top_links * RUNNERUP_RATIO:
        _set_status(db_path, alias, lang, "ambiguous", None)
        return "ambiguous"

    _save_canonical(db_path, top_qid, top_ent, etype)
    hydrate_aliases(db_path, top_qid, top_ent)
    _set_status(db_path, alias, lang, "linked", top_qid)
    _backfill_mentions(db_path, top_qid)
    return "linked"


def _save_canonical(db_path: str, qid: str, ent: dict, etype: str) -> None:
    labels = ent.get("labels") or {}
    conn = _conn(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO entity_canonical
               (qid, label_en, label_hu, etype, sitelinks, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (qid,
             (labels.get("en") or {}).get("value"),
             (labels.get("hu") or {}).get("value"),
             etype or None,
             len(ent.get("sitelinks") or {}), _now()))
        conn.commit()
    finally:
        conn.close()


def hydrate_aliases(db_path: str, qid: str, ent: dict) -> int:
    """A QID ÖSSZES nyelvi labelje + aliasa a cache-be (spec: 'az igazi erőmű').
    A meglévő pending sorokat is linked-re állítja, ha egyeznek."""
    rows: list[tuple] = []
    labels = ent.get("labels") or {}
    aliases = ent.get("aliases") or {}
    for lg in LANGS:
        seen: set[str] = set()
        lab = (labels.get(lg) or {}).get("value")
        if lab:
            seen.add(lab)
        for a in (aliases.get(lg) or []):
            v = a.get("value")
            if v and len(v) <= 80:
                seen.add(v)
        for v in seen:
            rows.append((v, lg, qid))
    if not rows:
        return 0
    conn = _conn(db_path)
    try:
        conn.executemany(
            """INSERT INTO entity_alias (alias, lang, qid, status, hits)
               VALUES (?,?,?,'linked',0)
               ON CONFLICT(alias, lang) DO UPDATE
               SET qid=excluded.qid, status='linked'
               WHERE entity_alias.qid IS NULL""", rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _set_status(db_path: str, alias: str, lang: str, status: str,
                qid: str | None) -> None:
    conn = _conn(db_path)
    try:
        conn.execute(
            """INSERT INTO entity_alias (alias, lang, qid, status)
               VALUES (?,?,?,?)
               ON CONFLICT(alias, lang) DO UPDATE SET qid=?, status=?""",
            (alias, lang, qid, status, qid, status))
        conn.commit()
    finally:
        conn.close()


def _backfill_mentions(db_path: str, qid: str) -> int:
    """article_entities.qid kitöltése minden olyan említésre, aminek a labelje
    a most linkelt QID bármely aliasával egyezik (case-insensitive)."""
    conn = _conn(db_path)
    try:
        cur = conn.execute(
            """UPDATE article_entities SET qid=?
               WHERE qid IS NULL AND label COLLATE NOCASE IN
                 (SELECT alias FROM entity_alias WHERE qid=?)""", (qid, qid))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def lookup_qid(db_path: str, alias: str) -> str | None:
    """Cache-lookup (bármely nyelven) — a classifier írás-időben hívja."""
    try:
        conn = _conn(db_path)
        try:
            row = conn.execute(
                "SELECT qid FROM entity_alias WHERE alias=? COLLATE NOCASE "
                "AND qid IS NOT NULL LIMIT 1", (alias,)).fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return None


# ─── Worker ─────────────────────────────────────────────────────────────

def seed_from_mentions(db_path: str) -> int:
    """Friss, még QID nélküli említés-labelek beöntése a pending sorba,
    hits = előfordulás-szám (a worker a gyakoriakat linkeli először)."""
    ensure_tables(db_path)
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            """SELECT ae.label, COALESCE(NULLIF(a.language,''),'en') lg,
                      MAX(ae.entity_type) et, COUNT(*) n
               FROM article_entities ae
               JOIN articles a ON a.article_id = ae.article_id
               WHERE ae.qid IS NULL
               GROUP BY ae.label COLLATE NOCASE, lg""").fetchall()
        for label, lg, et, n in rows:
            conn.execute(
                """INSERT INTO entity_alias (alias, lang, qid, status, hits)
                   VALUES (?,?,NULL,'pending',?)
                   ON CONFLICT(alias, lang) DO UPDATE
                   SET hits = CASE WHEN entity_alias.status='pending'
                                   THEN ? ELSE entity_alias.hits END""",
                (label, lg, n, n))
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _etype_for_alias(db_path: str, alias: str) -> str:
    conn = _conn(db_path)
    try:
        row = conn.execute(
            """SELECT entity_type, COUNT(*) n FROM article_entities
               WHERE label=? COLLATE NOCASE GROUP BY entity_type
               ORDER BY n DESC LIMIT 1""", (alias,)).fetchone()
        return (row[0] or "") if row else ""
    finally:
        conn.close()


def run_cycle(db_path: str, max_links: int = 60) -> dict:
    """Egy worker-ciklus: seed + a top-N pending alias linkelése (~1/sec)."""
    seeded = seed_from_mentions(db_path)
    conn = _conn(db_path)
    try:
        pend = conn.execute(
            """SELECT alias, lang FROM entity_alias
               WHERE status='pending' ORDER BY hits DESC LIMIT ?""",
            (max_links,)).fetchall()
    finally:
        conn.close()
    stats = {"seeded": seeded, "linked": 0, "ambiguous": 0, "no_match": 0}
    for alias, lang in pend:
        etype = _etype_for_alias(db_path, alias)
        try:
            res = link_alias(db_path, alias, lang, etype)
            stats[res] = stats.get(res, 0) + 1
        except Exception as exc:
            log.warning("link_alias(%r) failed: %s", alias, exc)
        time.sleep(1.1)  # Wikidata-udvariasság (2 hívás/link)
    if pend:
        log.info("linker cycle: %s", stats)
    return stats


def worker_loop(db_path: str, interval: int = 900) -> None:
    """start.py daemon-szál: 15 percenként egy ciklus (max 60 link/ciklus)."""
    time.sleep(60)  # boot-rush után
    while True:
        try:
            run_cycle(db_path)
        except Exception as exc:
            log.warning("linker cycle failed: %s", exc)
        time.sleep(interval)


def canonical_labels(db_path: str, qids: list[str]) -> dict[str, dict]:
    """{qid: {label_en, label_hu}} a megjelenítéshez (lista-oldal)."""
    ids = [q for q in (qids or []) if q]
    if not ids:
        return {}
    conn = _conn(db_path)
    try:
        qm = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT qid, label_en, label_hu FROM entity_canonical "
            f"WHERE qid IN ({qm})", ids).fetchall()
        return {r[0]: {"en": r[1], "hu": r[2]} for r in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    db = sys.argv[1] if len(sys.argv) > 1 else "echolot.db"
    print(run_cycle(db, max_links=int(sys.argv[2]) if len(sys.argv) > 2 else 10))
