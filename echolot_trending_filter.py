"""
Trending-keyword filter helpers for Echolot's `get_trending` MCP tool.

Goals (from a stress test surfacing 6 noise vectors):
  1. Multi-language stopword leakage  ("miatt", "first", "der", "que" ...)
  2. Year tokens dominating output    ("2026" appeared in 44 sources)
  3. Calendar boilerplate             (months, weekdays, HU+EN+DE)
  4. Lemmatization                    ("russia" + "russian" → one bucket)
  5. Cross-language collision         (filter functional words first)
  6. Functional-word leakage          (kept by capitalization signal)

This module exposes:
  - tokenize_with_case(title)         → list[(lower, was_capitalized_midsentence)]
  - normalize(token)                  → lemma (or "" if it should be dropped)
  - is_proper_noun_like(ratio)        → bool gate for strict mode
  - ALL_STOPWORDS, YEAR_RE, MANUAL_LEMMAS  → introspectable constants

No external NLP libs.  Pure stdlib.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Stopwords — 12 languages, ~40-60 high-frequency functional words each.
# ---------------------------------------------------------------------------

STOPWORDS_BY_LANG: dict[str, set[str]] = {
    "hu": {
        "a", "az", "egy", "és", "is", "hogy", "nem", "van", "volt", "lesz",
        "már", "még", "meg", "ezt", "azt", "mint", "csak", "vagy", "ide",
        "oda", "ami", "aki", "amely", "ez", "miatt", "után", "előtt", "alatt",
        "felett", "között", "során", "szerint", "nélkül", "ellen", "ezért",
        "azért", "így", "úgy", "ott", "itt", "most", "majd", "vele", "neki",
        "tehát", "ugyan", "tovább", "egyik", "másik", "minden", "néhány",
        "akár", "akkor", "amikor", "ahol", "olyan", "ilyen", "több", "kevés",
        "kell", "tud", "lehet", "kapja", "lett", "kapott", "ahogy", "amint",
        "annyira", "azonban", "azonnal", "bár", "bárki", "bármi", "csakis",
        "ellenére", "helyett", "honnan", "ide", "ilyenkor", "ismét", "jól",
        "kapcsán", "kerül", "képest", "ki", "lévő", "mellé", "miatt", "miért",
        "mikor", "mondta", "óta", "összes", "saját", "sem", "tud", "újabb",
        "viszont", "vissza", "végül", "akár", "annyi", "esetén",
    },
    "en": {
        "the", "and", "for", "with", "from", "has", "have", "are", "was",
        "will", "but", "not", "its", "can", "into", "over", "about", "after",
        "this", "that", "said", "says", "new", "more", "been", "also",
        "their", "than", "what", "when", "where", "which", "would", "could",
        "should", "first", "last", "next", "previous", "against", "before",
        "during", "since", "until", "while", "though", "although", "however",
        "therefore", "moreover", "furthermore", "indeed", "really", "very",
        "still", "yet", "even", "ever", "never", "always", "often",
        "sometimes", "many", "some", "most", "few", "all", "every", "each",
        "any", "such", "only", "just", "they", "them", "those", "these",
        "here", "there", "back", "down", "out", "off", "above", "below",
        "between", "through", "without", "within", "upon", "amid", "amidst",
        "year", "years", "today", "yesterday", "tomorrow", "week", "month",
        "amid", "ahead", "behind", "around", "between", "near", "across",
        "another", "amongst", "another",
    },
    "de": {
        "der", "die", "das", "und", "ist", "war", "von", "den", "dem", "ein",
        "eine", "einen", "einem", "wird", "werden", "noch", "auch", "auf",
        "mit", "für", "ohne", "über", "unter", "nach", "vor", "durch",
        "gegen", "während", "weil", "wenn", "aber", "oder", "doch", "nur",
        "schon", "mehr", "alle", "kein", "mein", "sein", "ihr", "sich", "wir",
        "sie", "ihn", "ihm", "uns", "euch", "habe", "hatte", "hat", "wurde",
        "geworden", "kann", "soll", "muss", "darf", "bei", "zur", "zum",
        "als", "wie", "auch", "nicht", "ich", "du", "es", "im", "an", "am",
    },
    "fr": {
        "les", "des", "que", "qui", "pour", "avec", "dans", "sur", "par",
        "une", "ses", "son", "leur", "cette", "votre", "notre", "mais",
        "donc", "car", "comme", "alors", "puis", "très", "trop", "plus",
        "moins", "aussi", "encore", "déjà", "toujours", "jamais", "peu",
        "beaucoup", "tout", "rien", "quel", "quelle", "ils", "elle", "elles",
        "nous", "vous", "est", "sont", "était", "été", "être", "avoir",
        "fait", "faire", "deux", "trois", "ans", "an", "jour", "jours",
        "selon", "entre", "sans", "vers", "chez", "depuis", "ces", "cet",
    },
    "es": {
        "los", "las", "que", "por", "para", "con", "una", "este", "esta",
        "del", "como", "más", "pero", "muy", "todo", "todos", "todas",
        "otro", "otra", "sus", "ese", "esa", "eso", "aquí", "allí", "cuando",
        "donde", "porque", "siempre", "nunca", "ahora", "son", "fue", "ser",
        "ha", "han", "está", "estaba", "entre", "hasta", "sobre", "desde",
        "hacia", "según", "contra", "sin", "tras", "ante", "bajo", "al",
        "lo", "le", "se", "te", "me", "nos", "os", "su", "sus",
    },
    "pt": {
        "que", "para", "com", "uma", "este", "esta", "esse", "essa", "como",
        "mais", "muito", "todo", "todos", "outras", "seus", "suas", "não",
        "são", "foi", "ser", "está", "estava", "entre", "até", "sobre",
        "desde", "segundo", "contra", "sem", "após", "ante", "sob", "ao",
        "lhe", "se", "te", "me", "nos", "os", "as", "do", "da", "dos", "das",
        "no", "na", "nos", "nas", "pelo", "pela", "pelos", "pelas", "ano",
    },
    "pl": {
        "jest", "nie", "tylko", "nawet", "także", "jeszcze", "który",
        "która", "które", "kiedy", "gdzie", "tutaj", "teraz", "może", "musi",
        "trzeba", "byli", "była", "było", "były", "jak", "ale", "lub", "czy",
        "się", "tym", "tej", "tym", "tego", "tym", "tych", "ten", "ta", "to",
        "od", "do", "na", "po", "za", "we", "ze", "bez", "pod", "nad",
        "przed", "przez", "przy", "około", "podczas", "dla",
    },
    "ru": {
        "что", "это", "как", "так", "уже", "ещё", "был", "была", "было",
        "быть", "есть", "нет", "или", "если", "когда", "очень", "совсем",
        "также", "только", "более", "менее", "хотя", "потому", "при", "над",
        "под", "между", "перед", "после", "через", "без", "для", "ради",
        "вместо", "около", "среди", "вокруг", "из", "от", "до", "по", "за",
        "на", "в", "о", "об", "не", "ни", "же", "ли", "бы", "он", "она",
        "оно", "они", "его", "её", "их", "мне", "тебе", "нам", "вам", "год",
    },
    "uk": {
        "що", "як", "так", "вже", "ще", "був", "була", "було", "бути", "чи",
        "якщо", "коли", "дуже", "також", "тільки", "більше", "менше", "при",
        "над", "під", "між", "перед", "після", "через", "без", "для", "із",
        "від", "до", "по", "за", "на", "в", "о", "не", "ні", "же", "би",
        "він", "вона", "воно", "вони", "його", "її", "їх", "мені", "тобі",
        "нам", "вам", "рік", "році", "роки",
    },
    "ja": {
        "こと", "もの", "それ", "これ", "ある", "する", "いる", "なる", "から",
        "まで", "より", "など", "ため", "について", "として",
    },
    "zh": {
        "的", "了", "和", "是", "在", "有", "为", "与", "都", "也", "就", "我",
        "你", "他", "她", "它", "们", "这", "那", "之", "于", "或", "但", "而",
    },
    "ar": {
        "في", "من", "إلى", "على", "أن", "كان", "هذا", "هذه", "ذلك", "تلك",
        "هو", "هي", "هم", "نحن", "أنت", "أنا", "ما", "لا", "لم", "لن", "قد",
        "كل", "بعض", "بين", "عند", "عن", "مع", "أو", "ثم", "حتى", "إذا",
    },
}

# Calendar boilerplate (months + weekdays in HU/EN/DE — tokens >=4 chars only,
# since the tokenizer drops shorter tokens; we add a few short ones anyway in
# case the min-len rule is ever relaxed).
CALENDAR_TOKENS: set[str] = {
    # English months
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec",
    # English weekdays
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday",
    # Hungarian months
    "január", "február", "március", "április", "május", "június", "július",
    "augusztus", "szeptember", "október",
    # Hungarian weekdays
    "hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap",
    # German months
    "januar", "februar", "märz", "mai", "juni", "juli", "august",
    "september", "oktober", "dezember",
    # German weekdays
    "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag",
    "sonntag",
}

ALL_STOPWORDS: set[str] = set().union(*STOPWORDS_BY_LANG.values()) | CALENDAR_TOKENS

# ---------------------------------------------------------------------------
# Year regex — matches plain 4-digit years 1900-2099.
# ---------------------------------------------------------------------------

YEAR_RE = re.compile(r"^(19|20)\d{2}$")

# ---------------------------------------------------------------------------
# Manual lemma map — collapses national adjectives onto country nouns and
# folds a few high-frequency English plurals.
# ---------------------------------------------------------------------------

MANUAL_LEMMAS: dict[str, str] = {
    # Nationality adjectives → country
    "russian": "russia", "russians": "russia",
    "ukrainian": "ukraine", "ukrainians": "ukraine",
    "chinese": "china",
    "american": "america", "americans": "america",
    "european": "europe", "europeans": "europe",
    "iranian": "iran", "iranians": "iran",
    "israeli": "israel", "israelis": "israel",
    "japanese": "japan",
    "korean": "korea", "koreans": "korea",
    "german": "germany", "germans": "germany",
    "french": "france",
    "italian": "italy", "italians": "italy",
    "spanish": "spain", "spaniards": "spain",
    "polish": "poland", "poles": "poland",
    "turkish": "turkey", "turks": "turkey",
    "indian": "india", "indians": "india",
    "british": "britain", "brits": "britain",
    "english": "england",
    "syrian": "syria", "syrians": "syria",
    "saudi": "saudiarabia", "saudis": "saudiarabia",
    "egyptian": "egypt", "egyptians": "egypt",
    "lebanese": "lebanon",
    "palestinian": "palestine", "palestinians": "palestine",
    "afghan": "afghanistan", "afghans": "afghanistan",
    "pakistani": "pakistan", "pakistanis": "pakistan",
    "venezuelan": "venezuela", "venezuelans": "venezuela",
    "mexican": "mexico", "mexicans": "mexico",
    "brazilian": "brazil", "brazilians": "brazil",
    # High-frequency newsy plurals
    "tariffs": "tariff", "drones": "drone", "strikes": "strike",
    "talks": "talk", "deals": "deal", "wars": "war", "sanctions": "sanction",
    "missiles": "missile", "weapons": "weapon", "soldiers": "soldier",
    "elections": "election", "protests": "protest", "attacks": "attack",
    "rallies": "rally", "votes": "vote", "leaders": "leader",
    "presidents": "president", "ministers": "minister",
}

# Russian adjective endings that should fold to a noun stem.
# Conservative list to avoid mis-folding non-Russian words.
_RU_SUFFIXES = ("ская", "ский", "ского", "скому", "ские", "ских", "ским",
                "скими", "ской")


def _strip_english_suffix(token: str) -> str:
    """Conservative suffix folding for English plurals.

    We deliberately avoid -ing/-ed (e.g. "united" → "unit", "airline" →
    "airlin" cause more harm than good in news headlines) and only collapse
    plurals when the singular form is clearly a real word stem (length 6+
    after stripping). The MANUAL_LEMMAS map handles the high-frequency
    irregular plurals up front, so this is just a safety net.
    """
    if len(token) < 7:
        return token
    if token.endswith("ies") and len(token) >= 7:
        return token[:-3] + "y"
    if token.endswith("es") and not token.endswith(("ses", "xes", "zes",
                                                     "ches", "shes")):
        # Only strip "es" if removing just "s" still ends in -e (e.g. "states"
        # → "state", not "horses" → "horse" handled separately).
        candidate = token[:-1]
        if len(candidate) >= 6:
            return candidate
        return token
    if token.endswith("s") and not token.endswith(("ss", "us", "is", "ous")):
        candidate = token[:-1]
        if len(candidate) >= 6:
            return candidate
        return token
    return token


def _strip_russian_suffix(token: str) -> str:
    """Light suffix folding for Russian adjective endings."""
    for suf in _RU_SUFFIXES:
        if len(token) > len(suf) + 2 and token.endswith(suf):
            return token[: -len(suf)]
    return token


# Token punctuation strip set (matches legacy behaviour + a few extras).
_STRIP_CHARS = ".:,;!?\"'()-–—„""''«»‹›[]{}…"

# Heuristic: a token is "Cyrillic-ish" if any character is in the Cyrillic
# Unicode block. Used to decide whether to apply Russian suffix folding.
def _is_cyrillic(token: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in token)


def _is_ascii_letters(token: str) -> bool:
    return all("a" <= ch <= "z" for ch in token)


def normalize(token_lower: str) -> str:
    """Apply manual lemma → suffix-fold → return canonical form, or ""
    to indicate the token should be dropped entirely.
    """
    if not token_lower:
        return ""
    if YEAR_RE.match(token_lower):
        return ""
    if token_lower in ALL_STOPWORDS:
        return ""
    if token_lower in MANUAL_LEMMAS:
        return MANUAL_LEMMAS[token_lower]
    if _is_ascii_letters(token_lower):
        folded = _strip_english_suffix(token_lower)
        return MANUAL_LEMMAS.get(folded, folded)
    if _is_cyrillic(token_lower):
        return _strip_russian_suffix(token_lower)
    return token_lower


def tokenize_with_case(title: str) -> list[tuple[str, bool]]:
    """Split a title into (lowercase_token, was_capitalized_midsentence) pairs.

    The first word of the title is NOT considered "midsentence-capitalized"
    even if it happens to start with an uppercase letter — that's just
    sentence case, not a proper-noun signal.
    """
    if not title:
        return []
    raw_words = title.split()
    out: list[tuple[str, bool]] = []
    for idx, raw in enumerate(raw_words):
        cleaned = raw.strip(_STRIP_CHARS)
        if not cleaned:
            continue
        # Capitalization signal: first letter is uppercase AND we're not the
        # first word of the title.
        was_capitalized = bool(cleaned[:1].isupper() and idx > 0)
        out.append((cleaned.lower(), was_capitalized))
    return out


def is_proper_noun_like(capitalized_count: int, total_count: int,
                        threshold: float = 0.5) -> bool:
    """Decide if a token's capitalization profile suggests a proper noun."""
    if total_count <= 0:
        return False
    return (capitalized_count / total_count) >= threshold
