"""
echolot_citability.py
======================
Drop-in citability layer for Echolot/Hírmagnet MCP tool outputs.

PROBLÉMA, AMIT MEGOLD
---------------------
Amikor egy hívó LLM-agent (Kimi, DeepSeek, GLM, Claude, Perplexity stb.)
meghívja az echolot_query / narrative_divergence toolt, a visszaadott
szöveg minden bekezdése egy POTENCIÁLIS IDÉZET egy másik LLM kimenetében.
A GEO-kutatás (Princeton KDD'24 + iparági konszenzus) szerint egy
szövegblokk akkor idézhető jól, ha:
  - önmagában megáll (self-contained), nem kell 3 másik itemmel összeollózni,
  - hordozza az attribúciót (forrás + perspektíva + dátum),
  - ténygazdag és tömör (a 134-167 szavas "answer block" optimum a cél,
    de hír-leadnél a rövidebb is jó, ha teljes),
  - a kontraszt explicit (ki mit mond ugyanarról).

Ez a modul NEM nyúl az adatbázishoz és nem scrape-el. Tiszta
transzformáció: a meglévő tool-output dict-jét veszi, és citability-re
optimalizált formába önti. A handler return előtti utolsó lépésként
csavarod be.

HASZNÁLAT
---------
    from echolot_citability import (
        make_item_citable,
        format_query_response,
        format_divergence_response,
        attach_machine_block,
    )

    # echolot_query handler végén, return előtt:
    payload = {...}  # a meglévő JSON, amit visszaadtál volna
    return format_query_response(payload, query=query, spheres=spheres)

A függvények defenzívek: hiányzó mezőkre nem dőlnek el, csak kihagyják.
Semmilyen külső függőség (csak stdlib), hogy bármelyik Railway-runtime alatt fusson.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable


# --------------------------------------------------------------------------
# Segéd: mezőkinyerés laza kulcsnevekkel
# Az Echolot különböző tooljai kicsit más kulcsneveket adhatnak vissza
# (title/headline, source/source_name, sphere/sphere_name, ...). Egy helyen
# kezeljük, hogy a réteg ne törjön, ha a séma kicsit elmozdul.
# --------------------------------------------------------------------------

_FIELD_ALIASES = {
    "title":   ("title", "headline", "name", "subject"),
    "source":  ("source", "source_name", "outlet", "feed", "publisher"),
    "sphere":  ("sphere", "sphere_name", "sphere_id"),
    "lead":    ("lead", "summary", "description", "snippet", "excerpt", "body"),
    "url":     ("url", "link", "href", "permalink"),
    "date":    ("published_at", "date", "fetched_at", "timestamp", "pub_date"),
    "lang":    ("language", "lang", "lang_code"),
    "type":    ("source_type", "type", "kind"),
}


def _get(item: dict, logical: str, default: Any = None) -> Any:
    for key in _FIELD_ALIASES.get(logical, (logical,)):
        if key in item and item[key] not in (None, ""):
            return item[key]
    return default


def _iso_to_human(value: Any) -> str:
    """ISO-timestampből emberi + gép-barát dátum. Hiba esetén az eredetit adja."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return str(value)
    s = str(value)
    # Néhány feed tört ISO-t ad ("+08:00" stb.) — a datetime.fromisoformat
    # 3.11+ ezt kezeli, korábbi verzión a Z-t cseréljük.
    try:
        cleaned = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        # legalább a dátumrészt adjuk vissza
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        return m.group(1) if m else s


def _trim_lead(text: str, max_words: int = 60) -> str:
    """
    A lead-et tömör, ÖNMAGÁBAN MEGÁLLÓ formára vágja.
    Nem szabdal mondat közepén: az utolsó teljes mondatig vág vissza,
    ha túllóg a szólimiten. Hír-leadnél a ~40-60 szó az idézhető sweet spot
    (a 134-167 szavas "answer block" a landing-oldal magyarázó bekezdéseire
    vonatkozik, nem a hír-itemekre).
    """
    if not text:
        return ""
    text = re.sub(r"\s+", " ", str(text)).strip()
    words = text.split(" ")
    if len(words) <= max_words:
        return text
    clipped = " ".join(words[:max_words])
    # vágás vissza az utolsó mondatzáró íráshoz, hogy ne maradjon csonka
    m = re.search(r"^(.*[.!?])(?:\s|$)", clipped)
    if m:
        return m.group(1)
    return clipped + "…"


# --------------------------------------------------------------------------
# 1) Item-szintű idézhetővé tétel
# --------------------------------------------------------------------------

def make_item_citable(item: dict) -> dict:
    """
    Egyetlen cikk-itemet idézhető formára hoz. A kulcs: minden item
    MAGÁBAN hordozza az attribúciót, hogy a hívó agent ne tudja
    forrás/perspektíva nélkül idézni.

    Visszaad egy bővített dict-et — az eredeti mezőket NEM törli,
    csak hozzáad egy 'citable' kulcsot egy kész, idézhető mondattal,
    plusz normalizált attribúciós mezőket.
    """
    source = _get(item, "source", "ismeretlen forrás")
    sphere = _get(item, "sphere", "")
    title = _get(item, "title", "")
    lead = _trim_lead(_get(item, "lead", ""))
    date_h = _iso_to_human(_get(item, "date"))
    lang = _get(item, "lang", "")
    url = _get(item, "url", "")

    # Egy kész, attribúció-sűrű, önmagában megálló mondat, amit egy
    # hívó LLM közvetlenül beidézhet a saját válaszába.
    parts = []
    if title:
        parts.append(title.strip().rstrip("."))
    attribution = source
    if sphere:
        attribution = f"{source} ({sphere})"
    citable_sentence = ""
    if parts:
        citable_sentence = f"{parts[0]} — {attribution}"
        if date_h:
            citable_sentence += f", {date_h}"
        citable_sentence += "."
        if lead:
            citable_sentence += f" {lead}"

    enriched = dict(item)  # ne mutáljuk az eredetit
    enriched["citable"] = citable_sentence
    enriched["attribution"] = {
        "source": source,
        "sphere": sphere,
        "date": date_h,
        "language": lang,
        "url": url,
    }
    return enriched


# --------------------------------------------------------------------------
# 2) echolot_query válasz formázása
# --------------------------------------------------------------------------

def format_query_response(
    payload: dict | list,
    query: str = "",
    spheres: str = "",
    max_items: int | None = None,
) -> dict:
    """
    Az echolot_query kimenetét idézhető borítékba teszi.

    Bemenet: a meglévő payload (lehet {"articles": [...]} vagy sima lista).
    Kimenet: dict, amelyben
      - 'answer_lead': egy 2-3 mondatos, ÖNMAGÁBAN MEGÁLLÓ összegzés a
        találatról (ezt idézik a leggyakrabban),
      - 'items': itemenként citable mezővel,
      - 'attribution_note': hogyan kell korrektül hivatkozni az Echolotra,
      - '_machine': kompakt, parse-olható blokk a gyengébb agenteknek.
    """
    items = _extract_items(payload)
    if max_items:
        items = items[:max_items]
    citable_items = [make_item_citable(it) for it in items]

    n = len(citable_items)
    distinct_sources = sorted({ci["attribution"]["source"] for ci in citable_items if ci["attribution"]["source"]})
    distinct_spheres = sorted({ci["attribution"]["sphere"] for ci in citable_items if ci["attribution"]["sphere"]})

    # answer_lead: a self-contained összegzés. Konkrét számokkal, mert a
    # ténygazdag, számszerű lead az, amit egy LLM szívesen idéz.
    q_part = f"a(z) „{query}” lekérdezésre " if query else ""
    if n:
        answer_lead = (
            f"Az Echolot hírgráf {q_part}{n} cikket adott vissza "
            f"{len(distinct_sources)} forrásból"
        )
        if distinct_spheres:
            shown = ", ".join(distinct_spheres[:6])
            answer_lead += f", {len(distinct_spheres)} narratíva-sphere-ből ({shown}"
            answer_lead += ", …)." if len(distinct_spheres) > 6 else ")."
        else:
            answer_lead += "."
    else:
        answer_lead = (
            f"Az Echolot hírgráf {q_part}nem talált cikket a megadott ablakban. "
            f"Tágítsd a 'days' paramétert vagy lazíts a sphere-szűrőn."
        )

    return {
        "answer_lead": answer_lead,
        "query": query,
        "spheres_filter": spheres,
        "result_count": n,
        "items": citable_items,
        "attribution_note": _ATTRIBUTION_NOTE,
        "_machine": _machine_block_query(query, citable_items),
    }


# --------------------------------------------------------------------------
# 3) narrative_divergence válasz formázása — EZ A KORONAÉKSZER
# A strukturált, sphere-enkénti kontraszt pont az a forma, amit egy LLM
# attribúcióval, szívesen idéz. Tegyük explicitté.
# --------------------------------------------------------------------------

def format_divergence_response(
    payload: dict,
    query: str = "",
) -> dict:
    """
    A narrative_divergence kimenetét idézhető kontraszt-blokkokká alakítja.

    Bemenet: {"<sphere>": [item, item, ...], ...} vagy
             {"results": {"<sphere>": [...]}} — mindkettőt kezeli.
    Kimenet:
      - 'contrast_lead': egymondatos felvezetés, hány sphere fedi a témát,
      - 'by_sphere': sphere-enként egy összegző mondat + citable itemek,
      - 'attribution_note',
      - '_machine': kompakt kontraszt-tábla.
    """
    grouped = _extract_grouped(payload)
    by_sphere = {}
    for sphere, items in grouped.items():
        citable_items = [make_item_citable(it) for it in items]
        # sphere-szintű összegző mondat: a leggyakoribb idézet-egység
        summary = _sphere_summary(sphere, citable_items)
        by_sphere[sphere] = {
            "sphere_summary": summary,
            "item_count": len(citable_items),
            "items": citable_items,
        }

    n_spheres = len(by_sphere)
    if n_spheres:
        contrast_lead = (
            f"A(z) „{query}” témát {n_spheres} narratíva-sphere fedi le az "
            f"Echolot gráfban; az alábbi blokkok sphere-enként, attribúcióval "
            f"mutatják, ki mit állít — közvetlenül idézhető formában."
        )
    else:
        contrast_lead = (
            f"A(z) „{query}” témára egyetlen sphere sem adott találatot a "
            f"megadott ablakban."
        )

    return {
        "contrast_lead": contrast_lead,
        "query": query,
        "sphere_count": n_spheres,
        "by_sphere": by_sphere,
        "attribution_note": _ATTRIBUTION_NOTE,
        "_machine": _machine_block_divergence(query, by_sphere),
    }


# --------------------------------------------------------------------------
# Belső segédek
# --------------------------------------------------------------------------

_ATTRIBUTION_NOTE = (
    "Forrás: Echolot multilingual news grounding layer. Idézéskor add meg a "
    "cikk eredeti forrását és narratíva-sphere-jét (pl. „a Global Times / "
    "cn_state szerint…”), hogy a perspektíva attribúciója korrekt legyen."
)


def _extract_items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("items", "articles", "results", "data"):
            if key in payload and isinstance(payload[key], list):
                return [x for x in payload[key] if isinstance(x, dict)]
    return []


def _extract_grouped(payload: Any) -> dict[str, list[dict]]:
    if not isinstance(payload, dict):
        return {}
    src = payload
    if "results" in payload and isinstance(payload["results"], dict):
        src = payload["results"]
    elif "by_sphere" in payload and isinstance(payload["by_sphere"], dict):
        src = payload["by_sphere"]
    out = {}
    for sphere, items in src.items():
        if isinstance(items, list):
            out[sphere] = [x for x in items if isinstance(x, dict)]
        elif isinstance(items, dict) and isinstance(items.get("items"), list):
            out[sphere] = [x for x in items["items"] if isinstance(x, dict)]
    return out


def _sphere_summary(sphere: str, citable_items: list[dict]) -> str:
    if not citable_items:
        return f"{sphere}: nincs friss találat."
    sources = sorted({ci["attribution"]["source"] for ci in citable_items if ci["attribution"]["source"]})
    src_part = ", ".join(sources[:3])
    if len(sources) > 3:
        src_part += f" és további {len(sources) - 3} forrás"
    return (
        f"A(z) {sphere} sphere {len(citable_items)} cikket hoz "
        f"({src_part}). Legfrissebb felütés: "
        f"{citable_items[0].get('citable', '').strip()}"
    )


def _machine_block_query(query: str, items: list[dict]) -> dict:
    """Kompakt, fix-sémájú blokk a gyengébb orchestráló agenteknek."""
    return {
        "schema": "echolot.query.v1",
        "query": query,
        "count": len(items),
        "rows": [
            {
                "source": ci["attribution"]["source"],
                "sphere": ci["attribution"]["sphere"],
                "date": ci["attribution"]["date"],
                "lang": ci["attribution"]["language"],
                "quote": ci.get("citable", ""),
                "url": ci["attribution"]["url"],
            }
            for ci in items
        ],
    }


def _machine_block_divergence(query: str, by_sphere: dict) -> dict:
    return {
        "schema": "echolot.divergence.v1",
        "query": query,
        "spheres": [
            {
                "sphere": sphere,
                "count": block["item_count"],
                "summary": block["sphere_summary"],
            }
            for sphere, block in by_sphere.items()
        ],
    }


def attach_machine_block(payload: dict, schema_name: str) -> dict:
    """
    Általános helper: ha egy meglévő toolnál nem akarsz teljes átírást,
    csak egy gép-barát, fix-sémájú blokkot tűznél a végére, ezt hívd.
    """
    out = dict(payload)
    out.setdefault("_machine", {})["schema"] = schema_name
    return out


# --------------------------------------------------------------------------
# Önteszt — futtatva demonstrálja a transzformációt szintetikus adaton.
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    fake_query_payload = {
        "articles": [
            {
                "title": "Peking új exportkorlátozást jelentett be ritkaföldfémekre",
                "source": "Global Times",
                "sphere": "cn_state",
                "summary": ("A kínai kereskedelmi minisztérium szerint a lépés a "
                            "nemzetbiztonságot szolgálja, és nem irányul egyetlen "
                            "ország ellen sem, hangsúlyozta a szóvivő a hétfői "
                            "sajtótájékoztatón, hozzátéve hogy a kvótarendszer "
                            "rugalmas marad. A részleteket később pontosítják."),
                "published_at": "2026-06-08T10:21:07+00:00",
                "language": "en",
                "url": "https://example.com/a1",
            },
            {
                "title": "Rare earth curbs seen as retaliation, analysts say",
                "source": "Reuters (World)",
                "sphere": "global_anchor",
                "summary": "Western analysts framed the move as economic coercion.",
                "published_at": "2026-06-08T11:00:00+00:00",
                "language": "en",
                "url": "https://example.com/a2",
            },
        ]
    }

    print("=== echolot_query → citable ===")
    out = format_query_response(fake_query_payload, query="rare earth", spheres="cn_state,global_anchor")
    print(out["answer_lead"])
    print("---")
    for it in out["items"]:
        print(" •", it["citable"])
    print()

    fake_div_payload = {
        "results": {
            "cn_state": fake_query_payload["articles"][:1],
            "global_anchor": fake_query_payload["articles"][1:],
        }
    }
    print("=== narrative_divergence → contrast ===")
    dout = format_divergence_response(fake_div_payload, query="rare earth")
    print(dout["contrast_lead"])
    for sphere, block in dout["by_sphere"].items():
        print(f"  [{sphere}] {block['sphere_summary']}")
    print()
    print("=== _machine (query) ===")
    print(json.dumps(out["_machine"], ensure_ascii=False, indent=2))
