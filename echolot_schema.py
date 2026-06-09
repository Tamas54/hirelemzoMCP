"""
echolot_schema.py
=================
JSON-LD (schema.org) generátor az Echolot/Hírmagnet kifelé-láthatóságához.

MIÉRT
-----
Az AI-keresők (Google AI Overviews, Perplexity, ChatGPT search) és a
crawlereik strukturált adatból olvassák ki, MI EZ AZ ENTITÁS. Egy
MCP-szervernek a 'SoftwareApplication' a befutó típus, az EU-projektnek és
a brandnek az 'Organization'. A 'sameAs' tömb köti össze az entitást a
GitHubbal, a Railway-deploymenttel és a projekt-oldallal — ez adja az
"entity consolidation"-t, amitől az AI tudja, hogy a GitHub-repo, a
Railway-szerver és az ECHOLOT EU-projekt UGYANAZ a dolog.

A kimenetet a landing-oldal <head>-jébe teszed:
    <script type="application/ld+json">{...}</script>

Tölts ki minden mezőt valós adattal a generálás előtt (lásd CONFIG).
"""

from __future__ import annotations
import json


# --------------------------------------------------------------------------
# CONFIG — itt írd át a valós adataidra. A placeholderek egyértelműen jelölve.
# --------------------------------------------------------------------------
CONFIG = {
    "name": "Echolot",
    "alternate_name": "Hírmagnet",
    "url": "https://web-production-02611.up.railway.app",   # cseréld saját domainre, ha lesz
    "github": "https://github.com/<USER>/<REPO>",            # TÖLTSD KI
    "description_short": (
        "Echolot is a sphere-aware, MCP-native, multilingual news grounding "
        "layer for LLMs and AI agents. It scrapes 750+ RSS and Telegram "
        "sources every 30 seconds, tags them into 90+ narrative spheres "
        "(regional, topical, and perspective-aligned), and exposes them to AI "
        "agents through the Model Context Protocol."
    ),
    "publisher_name": "Makronóm Institute — AI Division",   # vagy ahogy hivatalosan szerepel
    "publisher_url": "https://makronom.eu",                  # TÖLTSD KI / ellenőrizd
    "same_as": [
        # Minden hely, ahol az entitás megjelenik. Töltsd, amennyi van.
        "https://github.com/<USER>/<REPO>",                  # TÖLTSD KI
        # "https://www.crunchbase.com/...",
        # "https://news.ycombinator.com/item?id=...",
        # ECHOLOT EU-projekt oldal, ha van publikus URL
    ],
    "programming_language": "Python",
    "application_category": "DeveloperApplication",
    "operating_system": "Any (MCP-compatible)",
    "price": "0",            # ha ingyenes/nyílt; egyébként írd át
    "price_currency": "EUR",
}


def build_software_application(cfg: dict = CONFIG) -> dict:
    """A fő entitás: maga az Echolot MCP-szerver mint szoftver."""
    schema = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": cfg["name"],
        "alternateName": cfg["alternate_name"],
        "url": cfg["url"],
        "description": cfg["description_short"],
        "applicationCategory": cfg["application_category"],
        "operatingSystem": cfg["operating_system"],
        "programmingLanguage": cfg["programming_language"],
        "offers": {
            "@type": "Offer",
            "price": cfg["price"],
            "priceCurrency": cfg["price_currency"],
        },
        "sameAs": [s for s in cfg["same_as"] if "<" not in s],  # placeholdert kihagy
        "publisher": {
            "@type": "Organization",
            "name": cfg["publisher_name"],
            "url": cfg["publisher_url"],
        },
    }
    return schema


def build_organization(cfg: dict = CONFIG) -> dict:
    """A kiadó/projekt entitás — az ECHOLOT EU-projekt brandhez."""
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": cfg["publisher_name"],
        "url": cfg["publisher_url"],
        "sameAs": [s for s in cfg["same_as"] if "<" not in s],
    }


def build_faq_block(qa_pairs: list[tuple[str, str]]) -> dict:
    """
    FAQPage schema a landing 'mi ez / hogyan működik' blokkjához.
    FIGYELEM: a Google a FAQ rich resultot 2023 augusztusa óta csak
    kormányzati/egészségügyi tekintély-oldalakon jeleníti meg — tehát
    rich snippetet ettől NE várj. DE: a FAQPage strukturált adat az
    AI-crawlereknek továbbra is tiszta, parse-olható kérdés→válasz párokat
    ad, ami a citability-t segíti. Akkor tedd be, ha a válaszaid önmagukban
    is idézhető 'answer block'-ok (134-167 szó). Üres rich-result-ambíció
    nélkül, tisztán a gép-olvashatóságért.
    """
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in qa_pairs
        ],
    }


# Példa FAQ — ezek a válaszok IDÉZHETŐ answer block-ok (cél: ~134-167 szó).
EXAMPLE_FAQ = [
    (
        "What is sphere-aware news grounding?",
        ("Sphere-aware news grounding is the practice of supplying a language "
         "model with current news that is tagged not only by topic and region, "
         "but by editorial perspective. Echolot groups its 750+ sources into "
         "90+ narrative spheres — for example cn_state for Chinese state media, "
         "iran_opposition for diaspora outlets, or ua_front_osint for Ukrainian "
         "open-source intelligence. When an AI agent asks how a single event is "
         "covered, Echolot returns the same topic seen through each sphere side "
         "by side, with explicit source and perspective attribution. This lets "
         "the model reason about disagreement between outlets rather than "
         "flattening every source into one undifferentiated feed, which is the "
         "usual failure mode of plain news APIs."),
    ),
    (
        "How does Echolot differ from a standard news API?",
        ("A standard news API returns a flat list of articles ranked by recency "
         "or relevance. Echolot is built for AI agents over the Model Context "
         "Protocol, so its outputs are designed to be quoted directly by a "
         "downstream model: every item carries its source, narrative sphere, "
         "language, and timestamp, and the narrative_divergence tool returns a "
         "structured contrast showing what each perspective claims about the "
         "same topic. It scrapes RSS and Telegram every 30 seconds across "
         "multiple languages, so the grounding layer stays current without the "
         "agent having to manage polling, deduplication, or perspective "
         "tagging itself."),
    ),
]


if __name__ == "__main__":
    print("<!-- SoftwareApplication -->")
    print('<script type="application/ld+json">')
    print(json.dumps(build_software_application(), ensure_ascii=False, indent=2))
    print("</script>\n")

    print("<!-- Organization -->")
    print('<script type="application/ld+json">')
    print(json.dumps(build_organization(), ensure_ascii=False, indent=2))
    print("</script>\n")

    print("<!-- FAQPage (gép-olvashatóságért, nem rich snippetért) -->")
    print('<script type="application/ld+json">')
    print(json.dumps(build_faq_block(EXAMPLE_FAQ), ensure_ascii=False, indent=2))
    print("</script>")
