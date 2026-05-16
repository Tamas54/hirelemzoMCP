"""Top Stories cluster + bias-bar számolás a Ground News-szerű főoldalra.

24h-os ablakban a fetched_at szerinti friss cikkeket csoportosítjuk
title-overlap alapján (3-shingle bucket + Jaccard refinement union-find-fel),
és minden cluster-re kiszámoljuk a Left/Center/Right bias-eloszlást a
source-ok lean mezője alapján (gov-finomítással sphere-ek alapján).

Pure Python, semmi külső lib. Cél: ≤ 5s 10 000 cikkre.

Public API:
    cluster_top_stories(db_path, hours=24, min_sources=3, limit=8) -> list[dict]
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("echolot.top_stories")

# ---------------------------------------------------------------------------
# Config

LEAN_TO_BIAS: dict[str, str] = {
    "left":              "L",
    "opposition":        "L",
    "right":             "R",
    "right_independent": "R",
    "gov":               "R",   # default — finomítás sphere alapján
    "center":            "C",
    "analytical":        "C",
    "independent":       "C",
    "unknown":           "C",
}

# Általános "general press" sphere-ek, amik egy forrást mainstream-mé tesznek.
# A rovat-szűréshez "pure topical" source-okat preferáljuk: olyan source-okat
# akiknek a sphere-jük NEM tartalmazza ezeket. Pl. hu_press-szel taggelt
# Tudás.hu (hu_press, hu_premium, hu_tech) mainstream tagolású, NEM tiszta
# tech forrás. Csak a hu_qubit / hu_raketa / hu_bitport tisztán tech.
GENERAL_PRESS_SPHERES: frozenset[str] = frozenset({
    "hu_press", "hu_premium",
    "regional_us", "regional_uk", "regional_german", "regional_french",
    "regional_spanish", "regional_italian", "regional_polish",
    "regional_russian", "regional_ukrainian", "regional_chinese",
})

# Állami propaganda-szférák → R marad (még a "regional_*" finomításnál is)
PROPAGANDA_SPHERES: frozenset[str] = frozenset({
    "cn_state",
    "ru_state_media",
    "iran_regime",
    "ru_state",
    "north_korea_state",
})

# Közszolgálati gov source-ok → C
PUBLIC_SERVICE_SPHERES: frozenset[str] = frozenset({
    "regional_german",
    "regional_french",
    "regional_japanese",
    "regional_uk",
    "regional_us",
    "regional_italian",
    "regional_spanish",
    "regional_canadian",
    "regional_australian",
    "regional_nordic",
})

STOP_WORDS: frozenset[str] = frozenset("""
a an the of to in on at by with for from is are was were be been being have
has had do does did will would shall should can could may might must not no
this that these those it its his her their our your my we you they he she
i as if then than so but or and into out about over under up down off only
just also more most less few many much new old say said says report reports
reported new live update updates latest breaking
és és a az egy az hogy mint mert ha akkor van volt lesz lehet kell után előtt
mellett között után fel le ki be át el meg ma ma még már nem igen vagy de
hanem hogy ami aki amely
der die das ein eine und oder aber wenn dann ist sind war waren wird wurde
wurden haben hat hatte einen einer eines im am zum zur des den dem
le la les un une et ou mais si alors est sont était étaient sera ont a avoir
de du des au aux pour par avec sans sur sous dans
el la los las y o pero si entonces es son era eran será han ha haber
de del al en por con sin sobre bajo entre
il la i lo gli e o ma se allora è sono era erano sarà ha hanno
di del della dei dello degli al alla ai con su per fra tra
""".split())

CACHE_TTL = 600  # 10 perc — frissül de nem lóverseny
CACHE_TTL_EMPTY = 30  # üres eredményt csak 30s-ig cache-eljük, hogy a deploy
                     # után gyorsan felépüljön mikor a DB feltöltődik
JACCARD_THRESHOLD = 0.5
SHINGLE_SIZE = 3
MIN_TOKENS_FOR_SHINGLE = 4   # rövid címeknél token-Jaccard, nem shingle
MAX_TOKENS_PER_TITLE = 20    # cap a normalizált tokeneknél (zaj-csökkentés)

_cache: dict[tuple, tuple[float, list[dict]]] = {}

# ---------------------------------------------------------------------------
# Normalizáció

_WORD_RE = re.compile(r"[a-z0-9]+")


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _tokenize(title: str) -> list[str]:
    """Lowercase + ékezet-mentesítés + word-tokenizáció + stop-word szűrés."""
    if not title:
        return []
    s = _strip_accents(title.lower())
    toks = _WORD_RE.findall(s)
    out = [t for t in toks if t not in STOP_WORDS and len(t) > 1]
    if len(out) > MAX_TOKENS_PER_TITLE:
        out = out[:MAX_TOKENS_PER_TITLE]
    return out


def _shingles(tokens: list[str]) -> list[tuple[str, ...]]:
    """3-token egymásutáni shingle-ek (bag, sorrendet megőrizve)."""
    n = len(tokens)
    if n < SHINGLE_SIZE:
        return []
    return [tuple(tokens[i:i + SHINGLE_SIZE]) for i in range(n - SHINGLE_SIZE + 1)]


# ---------------------------------------------------------------------------
# Bias-mapping

def _bias_for(lean: str | None, spheres: list[str]) -> str:
    lean_key = (lean or "unknown").lower().strip()
    base = LEAN_TO_BIAS.get(lean_key, "C")
    if lean_key == "gov":
        sph = set(spheres or [])
        if sph & PROPAGANDA_SPHERES:
            return "R"
        if sph & PUBLIC_SERVICE_SPHERES:
            return "C"
        return "R"
    return base


def _age_hours(ts: str | None, now_dt: datetime | None = None) -> float | None:
    """Parse ISO-8601 timestamp, return age in hours from `now_dt` (UTC).

    Returns None if `ts` is empty or unparseable.
    """
    if not ts:
        return None
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    s = ts.strip()
    # Sokféle formátum: 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DDTHH:MM:SS', 'YYYY-MM-DDTHH:MM:SSZ', '...+00:00'
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now_dt - dt
    return max(0.0, delta.total_seconds() / 3600.0)


def _parse_spheres(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v]
    except (ValueError, TypeError):
        pass
    return []


# ---------------------------------------------------------------------------
# Union-find

class _UF:
    __slots__ = ("p", "r")

    def __init__(self, n: int) -> None:
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, x: int) -> int:
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.r[ra] < self.r[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]:
            self.r[ra] += 1


# ---------------------------------------------------------------------------
# DB-fetch

_FETCH_SQL = """
SELECT
    a.article_id,
    a.title,
    a.url,
    a.source_id,
    a.source_name,
    a.language,
    a.category,
    a.published_at,
    a.fetched_at,
    a.spheres_json    AS article_spheres,
    s.lean            AS source_lean,
    s.trust_tier      AS trust_tier,
    s.spheres_json    AS source_spheres
FROM articles a
JOIN sources s ON a.source_id = s.id
WHERE a.fetched_at >= ?
"""


def _fetch_articles(db_path: str, hours: int, lang: str | None = None) -> list[dict]:
    """Lekéri az utolsó `hours` órás cikkeket.

    Ha `lang` megadva, csak az adott `articles.language`-jű cikkek jönnek
    vissza — különben minden nyelv vegyesen.

    Üres ha sehol — fallback: max(fetched_at)-tól visszafelé.
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        cutoff = cur.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
            (f"-{int(hours)} hours",),
        ).fetchone()[0]
        sql = _FETCH_SQL
        params: list = [cutoff]
        if lang:
            sql = sql + " AND a.language = ?"
            params.append(lang)
        rows = cur.execute(sql, params).fetchall()
        if not rows:
            # Fallback: ha 0 cikk az utóbbi `hours`-ban, használjuk a max(fetched_at)-ot referenciának
            if lang:
                max_ft = cur.execute(
                    "SELECT MAX(fetched_at) FROM articles WHERE language = ?",
                    (lang,),
                ).fetchone()[0]
            else:
                max_ft = cur.execute("SELECT MAX(fetched_at) FROM articles").fetchone()[0]
            if max_ft:
                cutoff2 = cur.execute(
                    "SELECT strftime('%Y-%m-%dT%H:%M:%S', ?, ?)",
                    (max_ft, f"-{int(hours)} hours"),
                ).fetchone()[0]
                params2: list = [cutoff2]
                if lang:
                    params2.append(lang)
                rows = cur.execute(sql, params2).fetchall()
                logger.info(
                    "top_stories: empty live window, fell back to max(fetched_at) cutoff=%s lang=%s",
                    cutoff2, lang,
                )
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Clustering

def _build_clusters(articles: list[dict]) -> list[list[int]]:
    """3-shingle bucket → kandidát-párok → Jaccard ≥ THRESHOLD → union-find.

    Visszaad cluster-listát (mindegyik az `articles` indexeit tartalmazza).
    """
    n = len(articles)
    if n == 0:
        return []

    # Pre-compute tokens / token-set / shingles
    tokens_list: list[list[str]] = []
    tokset_list: list[set[str]] = []
    shingles_list: list[list[tuple[str, ...]]] = []
    for a in articles:
        toks = _tokenize(a.get("title") or "")
        tokens_list.append(toks)
        tokset_list.append(set(toks))
        shingles_list.append(_shingles(toks))

    # Bucket: shingle → list of article indices
    buckets: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for i, sh_list in enumerate(shingles_list):
        # dedup per article
        seen: set[tuple[str, ...]] = set()
        for sh in sh_list:
            if sh in seen:
                continue
            seen.add(sh)
            buckets[sh].append(i)

    # Túl nagy bucket-ek skip-elése (nyilván stop-word-szerű zaj)
    MAX_BUCKET = 80

    uf = _UF(n)
    pair_seen: set[tuple[int, int]] = set()

    for sh, idxs in buckets.items():
        if len(idxs) < 2 or len(idxs) > MAX_BUCKET:
            continue
        for ai in range(len(idxs)):
            i = idxs[ai]
            for bj in range(ai + 1, len(idxs)):
                j = idxs[bj]
                if i > j:
                    i, j = j, i
                key = (i, j)
                if key in pair_seen:
                    continue
                pair_seen.add(key)
                # ha már egy cluster-ben → skip
                if uf.find(i) == uf.find(j):
                    continue
                ti, tj = tokset_list[i], tokset_list[j]
                if not ti or not tj:
                    continue
                inter = len(ti & tj)
                if inter == 0:
                    continue
                union_sz = len(ti) + len(tj) - inter
                if union_sz == 0:
                    continue
                jacc = inter / union_sz
                if jacc >= JACCARD_THRESHOLD:
                    uf.union(i, j)

    # Rövid címeknél (n_tokens < MIN_TOKENS_FOR_SHINGLE) shingle nincs — ezeket
    # külön bucket-ezzük token-tartalom alapján: minden ritkább token egy bucket.
    short_idxs = [i for i in range(n) if len(tokens_list[i]) < MIN_TOKENS_FOR_SHINGLE]
    if short_idxs:
        tok_buckets: dict[str, list[int]] = defaultdict(list)
        for i in short_idxs:
            for t in tokset_list[i]:
                tok_buckets[t].append(i)
        for t, idxs in tok_buckets.items():
            if len(idxs) < 2 or len(idxs) > MAX_BUCKET:
                continue
            for ai in range(len(idxs)):
                i = idxs[ai]
                for bj in range(ai + 1, len(idxs)):
                    j = idxs[bj]
                    if i > j:
                        i, j = j, i
                    if uf.find(i) == uf.find(j):
                        continue
                    ti, tj = tokset_list[i], tokset_list[j]
                    if not ti or not tj:
                        continue
                    inter = len(ti & tj)
                    union_sz = len(ti) + len(tj) - inter
                    if union_sz == 0:
                        continue
                    if inter / union_sz >= JACCARD_THRESHOLD:
                        uf.union(i, j)

    # Group by root
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Aggregáció

def _bias_dist_pct(counts: Counter) -> dict[str, int]:
    total = sum(counts.values())
    if total == 0:
        return {"L": 0, "C": 0, "R": 0}
    raw = {k: counts.get(k, 0) * 100.0 / total for k in ("L", "C", "R")}
    rounded = {k: int(round(v)) for k, v in raw.items()}
    diff = 100 - sum(rounded.values())
    if diff != 0:
        # legnagyobb fractional remainderhez igazítsuk
        order = sorted(raw, key=lambda k: -(raw[k] - int(raw[k])))
        rounded[order[0]] += diff
    return rounded


def _aggregate_cluster(articles: list[dict], idxs: list[int]) -> dict[str, Any] | None:
    seen_sources: set[str] = set()
    bias_counts: Counter = Counter()
    sphere_set: set[str] = set()         # article-szintű spheres (a sztori tényleges témái)
    source_sphere_set: set[str] = set()  # source-szintű (a kiadó általános profilja)
    pure_topical_set: set[str] = set()   # csak "pure topical" sources spheres-ből (rovat-szűréshez)
    languages: set[str] = set()
    trust_vals: list[int] = []
    titles_by_source: dict[str, str] = {}

    earliest_ts: str | None = None
    earliest_url: str | None = None
    earliest_title: str | None = None
    latest_ts: str | None = None
    latest_url: str | None = None
    latest_title: str | None = None

    for i in idxs:
        a = articles[i]
        sid = a.get("source_id") or ""
        article_spheres = _parse_spheres(a.get("article_spheres"))
        source_spheres = _parse_spheres(a.get("source_spheres"))
        # bias source-szinten számoljuk (egy source egy "szavazat")
        if sid and sid not in seen_sources:
            seen_sources.add(sid)
            bias = _bias_for(a.get("source_lean"), source_spheres)
            bias_counts[bias] += 1
            try:
                tt = int(a.get("trust_tier") or 0)
                if tt > 0:
                    trust_vals.append(tt)
            except (ValueError, TypeError):
                pass
            if a.get("language"):
                languages.add(str(a["language"]))
            if a.get("title") and sid not in titles_by_source:
                titles_by_source[sid] = str(a["title"])

        # Article-spheres a "valódi" cluster-téma; source-spheres csak fallback
        # (ha az article_spheres üres, akkor a kiadó általános profilja jelzi).
        for sp in article_spheres:
            sphere_set.add(sp)
        for sp in source_spheres:
            source_sphere_set.add(sp)
        # Pure topical: ha a SOURCE-nak nincs general-press tagje (hu_press stb.),
        # akkor a sphere-ei "tisztán topikálisak" — rovat-szűréshez ezeket
        # preferáljuk. Pl. hu_qubit (csak hu_tech, global_science) PURE, de
        # Tudás.hu (hu_press, hu_premium, hu_tech) NEM PURE.
        if source_spheres and not (set(source_spheres) & GENERAL_PRESS_SPHERES):
            for sp in source_spheres:
                pure_topical_set.add(sp)

        ts = a.get("published_at") or a.get("fetched_at")
        if ts and (earliest_ts is None or ts < earliest_ts):
            earliest_ts = ts
            earliest_url = a.get("url")
            earliest_title = a.get("title")
        if ts and (latest_ts is None or ts > latest_ts):
            latest_ts = ts
            latest_url = a.get("url")
            latest_title = a.get("title")

    # Fallback: ha NINCS article-szintű sphere a clusterben (régi cikkek),
    # akkor a source-spheres válik a sphere_set-té.
    if not sphere_set:
        sphere_set = source_sphere_set

    if not seen_sources:
        return None

    sample_titles = list(titles_by_source.values())[:3]
    trust_avg = round(sum(trust_vals) / len(trust_vals), 2) if trust_vals else None

    # A lead URL most a LEGFRISSEBB cikkre mutat (nem a legkorábbira) — friss
    # tartalom magasabb kattintási értékkel; a lead_title is a friss cím lesz.
    return {
        "title": latest_title or earliest_title or (sample_titles[0] if sample_titles else ""),
        "lead_title": latest_title or earliest_title or "",
        "lead_url": latest_url or earliest_url or "",
        "source_count": len(seen_sources),
        "bias_dist": _bias_dist_pct(bias_counts),
        "sphere_set": sorted(sphere_set),
        "pure_topical_set": sorted(pure_topical_set),
        "languages": sorted(languages),
        "trust_avg": trust_avg,
        "first_published": earliest_ts or "",
        "latest_published": latest_ts or "",
        "sample_titles": sample_titles,
    }


# ---------------------------------------------------------------------------
# Public API

def cluster_top_stories(
    db_path: str,
    hours: int = 24,
    min_sources: int = 3,
    limit: int = 8,
    lang: str | None = None,
    sphere_filter: frozenset[str] | set[str] | None = None,
) -> list[dict]:
    """Visszaad top N legtöbb-source-fed cluster-t bias-bárral.

    Args:
        db_path: SQLite path (echolot.db).
        hours: visszamenőleges ablak órákban (fetched_at).
        min_sources: minimum distinct source-szám egy clusterben.
        limit: top N visszaadott cluster.
        lang: ha megadva, csak az `articles.language=lang` cikkek alapján
            clusterezünk (különben minden nyelv vegyesen).
        sphere_filter: ha megadva, csak azok a clusterek maradnak amik
            sphere_set-je legalább egy elemet tartalmaz a halmazból
            (post-hoc szűrés a clustering után). Tech/Sport/Bulvár rovatokhoz.

    Returns:
        list[dict] — lásd modul-docstring példa.
    """
    sf_key = tuple(sorted(sphere_filter)) if sphere_filter else None
    cache_key = (db_path, int(hours), int(min_sources), int(limit), lang, sf_key)
    now = time.time()
    cached = _cache.get(cache_key)
    if cached:
        # Üres eredményt csak rövid ideig (CACHE_TTL_EMPTY) cache-eljük, hogy
        # deploy után, mikor a DB feltöltődik, gyorsan felépüljön.
        ttl = CACHE_TTL_EMPTY if not cached[1] else CACHE_TTL
        if (now - cached[0]) < ttl:
            return cached[1]

    t0 = time.time()
    articles = _fetch_articles(db_path, hours, lang=lang)
    t_fetch = time.time() - t0
    logger.info("top_stories: fetched %d articles in %.2fs (lang=%s)", len(articles), t_fetch, lang)

    if not articles:
        _cache[cache_key] = (now, [])
        return []

    t0 = time.time()
    clusters = _build_clusters(articles)
    t_cluster = time.time() - t0
    logger.info(
        "top_stories: built %d clusters from %d articles in %.2fs",
        len(clusters),
        len(articles),
        t_cluster,
    )

    out: list[dict] = []
    for idxs in clusters:
        if len(idxs) < min_sources:
            # gyors szűrés: legalább `min_sources` cikk kell hogy egyáltalán legyen esély
            # `min_sources` distinct source-ra. (általában 1 cikk = 1 source.)
            continue
        agg = _aggregate_cluster(articles, idxs)
        if agg is None:
            continue
        if agg["source_count"] < min_sources:
            continue
        out.append(agg)

    # Recency-súlyú rangsor: a frissebb sztori magasabb pontszámot kap,
    # a régiebb lassan csúszik lefelé. Súly:
    #   0-3 óra:  1.00× (full weight)
    #   3-24 óra: 1.00 → 0.30 (lineáris csökkenés)
    #   24+ óra:  0.30× (nem nullázzuk, ne tűnjenek el)
    # score = source_count × recency_w + trust_bonus
    now_dt = datetime.now(timezone.utc)
    for c in out:
        age_h = _age_hours(c.get("latest_published") or c.get("first_published"), now_dt)
        if age_h is None:
            recency_w = 0.5
        elif age_h <= 3:
            recency_w = 1.0
        elif age_h >= 24:
            recency_w = 0.3
        else:
            recency_w = 1.0 - (age_h - 3) * (0.7 / 21.0)
        c["_score"] = c["source_count"] * recency_w + (c.get("trust_avg") or 0) * 0.05
        c["age_hours"] = round(age_h, 1) if age_h is not None else None
    # Sphere-szűrés (post-hoc): tech/sport/bulvár/gazdaság rovatokhoz.
    # ELSŐ: pure_topical_set match (PURE-topical source contributed a topikális sphere-t).
    # Ha üres ezzel, fallback: bármely sphere_set match (lazább).
    if sphere_filter:
        sf = set(sphere_filter)
        strict = [c for c in out if set(c.get("pure_topical_set", [])) & sf]
        if strict:
            out = strict
        else:
            out = [c for c in out if set(c.get("sphere_set", [])) & sf]

    out.sort(key=lambda c: -c["_score"])
    out = out[:limit]

    _cache[cache_key] = (now, out)
    logger.info(
        "top_stories: returning %d clusters (min_sources=%d, limit=%d), total %.2fs",
        len(out),
        min_sources,
        limit,
        t_fetch + t_cluster,
    )
    return out


# ---------------------------------------------------------------------------
# Convenience: cache-bust

def clear_cache() -> None:
    _cache.clear()


if __name__ == "__main__":
    import os
    import pprint

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    db = os.environ.get("ECHOLOT_DB", "/home/tamas1/Hirmagnetmcp/echolot.db")
    t0 = time.time()
    res = cluster_top_stories(db, hours=24, min_sources=2, limit=5)
    print(f"=== {len(res)} clusters in {time.time()-t0:.2f}s ===")
    for c in res:
        pprint.pprint(c)
        print("-" * 60)
