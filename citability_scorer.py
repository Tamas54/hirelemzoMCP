"""
citability_scorer.py
====================
Pontozza, mennyire idézhető egy szövegblokk egy AI-kereső/agent számára.

A GEO-kutatás (Princeton "GEO: Generative Engine Optimization", KDD 2024 +
iparági konszenzus) szerint a jól idézett passzusok közös jegyei:
  - hossz: ~134-167 szó az "answer block" sweet spot,
  - önállóság: az első mondat kontextus nélkül is megáll,
  - ténysűrűség: számok, dátumok, tulajdonnevek jelenléte,
  - attribúció: forrás/idézet megnevezése,
  - kérdés-orientáltság: a blokkot kérdés-alakú heading vezeti be.

Ez egy HEURISZTIKUS scorer — nem garancia idézésre (semmi sem az), hanem
egy gyors, megismételhető visszajelzés, hogy a landing-szövegeidet a
helyes irányba csiszold. Nulla függőség.

HASZNÁLAT
    python citability_scorer.py < blokk.txt
    # vagy importálva:
    from citability_scorer import score_block
    score_block("A heading kérdés?", "A bekezdés szövege...")
"""

from __future__ import annotations
import re
import sys


_FACT_PATTERNS = [
    r"\b\d{4}\b",                       # évszám
    r"\b\d+([.,]\d+)?\s?%\b",           # százalék
    r"\b\d+([.,]\d+)?\b",               # bármilyen szám
    r"\b[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüű]+\b",  # tulajdonnév-jelölt (nagybetűs szó)
]

_ATTRIBUTION_HINTS = [
    "szerint", "according to", "said", "mondta", "states", "reports",
    "kutatás", "study", "data", "adatok", "forrás", "source",
]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÁÉÍÓÖŐÚÜŰáéíóöőúüű]+\b", text))


def _length_score(words: int) -> tuple[int, str]:
    """40 pont. Optimum 134-167 szó; sávosan csökken."""
    if 134 <= words <= 167:
        return 40, f"{words} szó — optimális answer-block hossz."
    if 100 <= words < 134 or 167 < words <= 220:
        return 28, f"{words} szó — közel az optimumhoz, finomítható."
    if 60 <= words < 100 or 220 < words <= 300:
        return 16, f"{words} szó — túl rövid/hosszú, az idézhetőség romlik."
    return 6, f"{words} szó — messze az optimális 134-167 szavas sávtól."


def _self_contained_score(text: str) -> tuple[int, str]:
    """
    20 pont. Az első mondat ne kezdődjön anaforával ('Ez', 'Az', 'It',
    'They', 'Ezért'...), mert akkor csak kontextussal idézhető.
    """
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].lower()
    anaphora = ("ez ", "az ", "ezért", "emiatt", "it ", "they ", "this ",
                "that ", "these ", "those ", "such ")
    if first.startswith(anaphora):
        return 6, "Az első mondat anaforával indul — kontextus nélkül nem áll meg."
    if len(first.split()) < 5:
        return 12, "Az első mondat nagyon rövid; lehet, hogy nem hordoz teljes állítást."
    return 20, "Az első mondat önállóan megáll."


def _fact_density_score(text: str) -> tuple[int, str]:
    """20 pont. Számok, dátumok, tulajdonnevek aránya."""
    words = max(_word_count(text), 1)
    hits = 0
    for pat in _FACT_PATTERNS:
        hits += len(re.findall(pat, text))
    density = hits / words
    if density >= 0.18:
        return 20, f"Magas ténysűrűség ({hits} ténymarker)."
    if density >= 0.10:
        return 13, f"Közepes ténysűrűség ({hits} ténymarker) — több konkrétum segítene."
    return 5, f"Alacsony ténysűrűség ({hits} ténymarker) — tegyél bele számot, dátumot, nevet."


def _attribution_score(text: str) -> tuple[int, str]:
    """10 pont. Van-e attribúciós jel (szerint/according to/...)."""
    low = text.lower()
    found = [h for h in _ATTRIBUTION_HINTS if h in low]
    if found:
        return 10, f"Tartalmaz attribúciót ({', '.join(sorted(set(found))[:3])})."
    return 3, "Nincs attribúciós jel — egy LLM nehezebben tulajdonít neked állítást."


def _heading_score(heading: str) -> tuple[int, str]:
    """10 pont. Kérdés-alakú heading bónusz."""
    if not heading:
        return 2, "Nincs heading megadva — kérdés-alakú headinggel idézhetőbb."
    if heading.strip().endswith("?"):
        return 10, "Kérdés-alakú heading — illeszkedik a felhasználói query-khez."
    if "?" in heading:
        return 7, "A heading tartalmaz kérdést."
    return 5, "Kijelentő heading — működik, de a kérdés-alak jobb."


def score_block(heading: str, body: str) -> dict:
    words = _word_count(body)
    parts = {
        "length": _length_score(words),
        "self_contained": _self_contained_score(body),
        "fact_density": _fact_density_score(body),
        "attribution": _attribution_score(body),
        "heading": _heading_score(heading),
    }
    total = sum(p[0] for p in parts.values())
    grade = ("A — kiváló" if total >= 85 else
             "B — jó" if total >= 70 else
             "C — közepes" if total >= 50 else
             "D — gyenge")
    return {
        "score": total,
        "grade": grade,
        "word_count": words,
        "breakdown": {k: {"points": v[0], "note": v[1]} for k, v in parts.items()},
    }


if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if not raw:
        # demó az echolot_schema példa-FAQ-jával
        heading = "What is sphere-aware news grounding?"
        body = (
            "Sphere-aware news grounding is the practice of supplying a language "
            "model with current news that is tagged not only by topic and region, "
            "but by editorial perspective. Echolot groups its 750+ sources into "
            "90+ narrative spheres — for example cn_state for Chinese state media, "
            "iran_opposition for diaspora outlets, or ua_front_osint for Ukrainian "
            "open-source intelligence. When an AI agent asks how a single event is "
            "covered, Echolot returns the same topic seen through each sphere side "
            "by side, with explicit source and perspective attribution. This lets "
            "the model reason about disagreement between outlets rather than "
            "flattening every source into one undifferentiated feed, which is the "
            "usual failure mode of plain news APIs."
        )
    else:
        # első sor = heading, többi = body (ha csak body, üres heading)
        lines = raw.split("\n", 1)
        if len(lines) == 2:
            heading, body = lines[0], lines[1]
        else:
            heading, body = "", raw

    import json
    print(json.dumps(score_block(heading, body), ensure_ascii=False, indent=2))
