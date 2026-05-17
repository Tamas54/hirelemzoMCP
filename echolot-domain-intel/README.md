# 🛠️ Echolot Domain Intelligence – PoC

**Free + commercial-safe domain analízis szolgáltatás az Echolot platformhoz.**

Pótolja a Similarweb / Cloudflare Radar funkcionalitást **kizárólag permisszív licencű forrásokból**, tehát ha az Echolotot bekommercializáljuk, semmilyen licencprobléma nem áll fenn.

---

## 🎯 Mit ad?

Bármelyik domainra (pl. `telex.hu`, `iz.ru`, `haaretz.com`) visszaad egy **`DomainReport`**-ot, ami a következőket tartalmazza:

| Mező | Tartalom | Forrás(ok) |
|---|---|---|
| **Rank** | Konszenzus rang (medián) + bucket (top_100 / top_1k / ... / top_1m) | Tranco + Cisco Umbrella + Majestic Million + opcionálisan OpenPageRank |
| **Geography** | Top országok scoreolva + primary country | WHOIS country + DNS→IP geo (MaxMind GeoLite2) + TLD heurisztika + HTML `<lang>` attr + Content-Language header + langdetect a content-en + **Echolot saját corpus** |
| **Category** | Primary + sub-categories + Echolot sphere | Echolot corpus lookup → AI klasszifikáció (Bridge/SiliconFlow) → keyword fallback |
| **Trend** | 30/90 napos rank-változás, irány (rising/falling/stable) | Tranco historikus listák |
| **Audience** | Becsült havi unique visitor szám (globális + per-country) + confidence band | Power-law fit kalibrációs horgonyokra (DKT, IVW, Mediascope, TGI, Similarweb) |
| **Country rank** | A domain ország-belüli rangsora (pl. „telex.hu = #23 Magyarországon") | Cloudflare Radar (CC BY-NC, csak belső használat) + ccTLD-derivált fallback |
| **Metadata** | Reachable, server IP, detected language, WHOIS registrar/created | WHOIS + DNS + HTTP fetch |
| **Sources & Licenses** | Mely forrásokból van adat + licencük | beépítve |

Minden válasz tartalmazza a **`confidence`** szintet (high/medium/low/unknown) – ezt az Echolot UI-on érdemes megjeleníteni, hogy a felhasználó lássa, mennyire megbízható az adott jel.

---

## 📜 Licenc-tisztaság (a fő USP a Cloudflare Radarral szemben!)

| Forrás | Licenc | Kommerciális OK? |
|---|---|---|
| Tranco list | Research-open (KU Leuven) | ✅ |
| Cisco Umbrella Top 1M | Public dataset | ✅ |
| Majestic Million | **CC BY 3.0** – kell attribution! | ✅ (link a Majesticre) |
| OpenPageRank API | Free tier, DomCop ToS | ✅ |
| MaxMind GeoLite2 | CC BY-SA 4.0 | ✅ (attribution) |
| WHOIS / DNS | Public protocols | ✅ |

> ⚠️ **Attribution kötelezettség**: a Majestic Million CC BY 3.0 alatt van, MaxMind GeoLite2 CC BY-SA 4.0 alatt. Az Echolot publikus felületén legyen egy „Data sources" lap, ahol felsoroljuk őket. A `DomainReport.licenses` mezője ezt automatikusan tartalmazza minden válaszban.

---

## 🏗️ Architektúra

```
                    ┌──────────────────────────┐
                    │      DomainAnalyzer       │  ← orchestrator
                    └────────────┬──────────────┘
                                 │
        ┌─────────┬──────────────┼──────────────┬─────────┐
        ▼         ▼              ▼              ▼         ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────┐
   │ Ranking  │ │Geography │ │Category  │ │ Trend    │ │Cache │
   │  DB      │ │ Detector │ │Classifier│ │ Analyzer │ │      │
   └─────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┘
         │           │             │             │
   ┌─────┴────┐  ┌───┴────┐  ┌────┴─────┐  ┌────┴─────┐
   │Tranco    │  │WHOIS   │  │Echolot   │  │Tranco    │
   │Umbrella  │  │DNS+Geo │  │Corpus    │  │Historical│
   │Majestic  │  │TLD     │  │AI Bridge │  │          │
   │OpenPR    │  │HTML lang│ │Keywords  │  │          │
   └──────────┘  └────────┘  └──────────┘  └──────────┘
```

**Kulcs design döntések:**

1. **Bulk + lookup** modell a rankinghez: a 3 nagy ranking forrás (Tranco/Umbrella/Majestic) napi CSV-jét egyszer letöltjük, memóriába töltjük, és O(1) lookuppal kérdezzük – nincs külső API-hívás query-nként.
2. **Multi-signal aggregation** a geográfiánál: a Cloudflare Radar single-source DNS-data helyett 6+ független jelet kombinálunk, súlyozva. Ez **robusztusabb** is a manipulációval szemben.
3. **Echolot-aware**: ha a domain már benne van a saját sphere DB-dben, az **felülírja** az összes külső forrást – a saját adatod ennél értékesebb.
4. **Stateless API + perzistens cache**: a FastAPI service maga stateless, de van diskcache layer (későbbi swap Redisre/ClickHouse-ra trivális).
5. **Két beépítési mód**: vagy közvetlen Python `import`-tal (Echolot Python kódból), vagy HTTP-n keresztül (Bridge MCP, Rust scrapers, bármi).

---

## 🚀 Quick Start

### Lokális futtatás

```bash
# 1. Setup
git clone <repo>
cd echolot-domain-intel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Szerkeszd .env-et (különösen: AI_API_KEY, GEOIP_DB_PATH)

# 2. GeoLite2 letöltése (opcionális, de erősen ajánlott a geográfiához)
# Regisztrálj ingyen: https://www.maxmind.com/en/geolite2/signup
# Töltsd le a GeoLite2-Country.mmdb fájlt → data/

# 3. Daily ranking lists letöltése
python scripts/update_rankings.py

# 4. (Opcionális) Cloudflare Radar per-country lookup táblák
# Pontos per-country rangsorhoz. CC BY-NC → csak belső használatra.
export CF_RADAR_TOKEN=...  # Cloudflare dashboard / API tokens / Radar:Read
python scripts/calibrate_cloudflare.py --limit 1000

# 4. CLI próba
python scripts/demo.py telex.hu
python scripts/demo.py telex.hu iz.ru haaretz.com --json

# 5. API server indítása
uvicorn api.server:app --host 0.0.0.0 --port 8080 --reload
# → curl http://localhost:8080/domain/telex.hu | jq
```

### Docker (Railway-kompatibilis)

```bash
docker compose up -d
# A `ranking-cron` service minden nap 3:00 UTC-kor refreshel
# Az API a 8080-as porton
```

### Railway deploy

A `Dockerfile` Railway-ready. Csak push, és a Railway felismeri.
- A `data/` volume-ot kösd Railway persistent storage-hoz, hogy a CSV-k megmaradjanak restart után.
- Az `update_rankings.py`-t futtasd Railway cron job-ként napi 3:00-kor.

---

## 💻 Python lib használat az Echolotban

```python
from domain_intel import DomainAnalyzer

# Hook in Echolot's saját DB-jét
def my_geo_lookup(domain: str) -> str | None:
    row = my_db.query("SELECT country FROM sources WHERE domain = ?", domain)
    return row.country if row else None

def my_category_lookup(domain: str) -> dict | None:
    row = my_db.query("SELECT sphere, category FROM sources WHERE domain = ?", domain)
    return {"sphere": row.sphere, "category": row.category} if row else None

analyzer = DomainAnalyzer.from_env(
    echolot_corpus_lookup_geo=my_geo_lookup,
    echolot_corpus_lookup_category=my_category_lookup,
)
await analyzer.initialize()

report = await analyzer.analyze("telex.hu")
print(report.model_dump_json(indent=2))
```

Lásd `example_echolot_integration.py` a teljes példáért.

---

## 🌐 HTTP API endpoints

```
GET  /health                              # health + loaded source stats
GET  /domain/{domain}                     # full report
GET  /domain/{domain}/rank                # rank only (gyors)
POST /domain/batch                        # up to 50 domains at once
POST /story/reach                         # aggregate reach across N sources
POST /admin/refresh                       # ranking refresh trigger (cron target)
DELETE /admin/cache                       # clear cache
```

### `/story/reach` — Sztori-szintű reach becslés

Egy hír N forráson elterjedt — körülbelül hány ember látta?

**Modell:** per-country `1 - Π_i (1 - p_i)` overlap-discounted reach, ahol `p_i = (daily_uniques_i / internet_users) * story_visibility_i`. Lásd `domain_intel/reach.py`.

**Request:**
```json
POST /story/reach
{"sources": ["telex.hu", "index.hu", "444.hu", "hvg.hu", "24.hu", "bbc.com"],
 "story_visibility": null}
```

**Response (példa):**
```json
{
  "sources": ["telex.hu", "index.hu", "444.hu", "hvg.hu", "24.hu", "bbc.com"],
  "total_estimated_readers": 315000,
  "by_country": [
    {"country_code": "HU", "estimated_readers": 140000,
     "pct_of_population": 1.46, "pct_of_internet_users": 1.64,
     "contributing_sources": 5},
    {"country_code": "GB", "estimated_readers": 175000,
     "pct_of_population": 0.26, "pct_of_internet_users": 0.27,
     "contributing_sources": 1}
  ],
  "method": "overlap_adjusted_country_reach"
}
```

Auth: opcionális `X-API-Key` header (env: `API_KEY`).

**Példa válasz** (`GET /domain/telex.hu`):

```json
{
  "domain": "telex.hu",
  "analyzed_at": "2026-05-17T17:30:00Z",
  "rank": {
    "consensus_rank": 18432,
    "rank_bucket": "top_100k",
    "confidence": "high",
    "sources": [
      {"source": "tranco", "rank": 18211, "license": "Research-open"},
      {"source": "umbrella", "rank": 19023, "license": "Public dataset"},
      {"source": "majestic", "rank": 18432, "license": "CC BY 3.0"}
    ]
  },
  "geography": {
    "primary_country": "HU",
    "confidence": "high",
    "top_countries": [
      {"country_code": "HU", "score": 3.1, "methods": ["tld", "whois", "html_lang_attr", "echolot_corpus"]},
      {"country_code": "DE", "score": 0.5, "methods": ["dns_ip_geo"]}
    ]
  },
  "category": {
    "primary_category": "news_media",
    "echolot_sphere": "hungarian_independent_media",
    "classification_method": "echolot_corpus",
    "confidence": "high"
  },
  "trend": {
    "rank_30d_ago": 19501,
    "change_30d": 1069,
    "direction": "rising"
  },
  "audience": {
    "monthly_uniques_global": 1629424,
    "monthly_uniques_band": [814712, 3258848],
    "by_country": [
      {"country_code": "HU", "monthly_uniques": 1519027, "pct_of_internet_users": 17.82}
    ],
    "confidence": "high",
    "method": "country_powerlaw+global"
  },
  "data_sources": ["tranco", "umbrella", "majestic", "local"],
  "licenses": {
    "tranco": "...", "umbrella": "...", "majestic": "CC BY 3.0 - attribution required"
  }
}
```

---

## 🔧 Echolot integrációs use-case-ek

### 1. „Beír egy domaint, kapsz analízist" UI
```python
@app.get("/echolot/domain-intel/{domain}")
async def echolot_domain_lookup(domain: str):
    return await analyzer.analyze(domain)
```

### 2. Sphere súlyozott narratíva-elemzés
Az Echolot már sphere-ezve van. A `DomainReport`-ban a `geography.primary_country` + `category.echolot_sphere` együttesen adja meg, hogy egy adott narratíva milyen geo-traffic súlyt jelent.

### 3. Korpusz enrichment batch job
```python
for source in echolot_sources:
    report = await analyzer.analyze(source.domain, fetch_page=False)
    source.rank = report.rank.consensus_rank
    source.audience_country = report.geography.primary_country
    source.trend = report.trend.direction
    db.update(source)
```

### 4. Bridge MCP tool wrapping
Egy új MCP tool-t lehet készíteni a Claus-Bridge-en `domain_intel_analyze` néven, ami ezt az API-t hívja. A Bridge multi-agent agent-jei (Kimi, DeepSeek, GLM) használhatják.

---

## ⚙️ Konfigurációs jegyzetek

### A `top countries` accuracy javítása

A Cloudflare Radar valódi DNS query traffic-et lát – mi proxy-jeleket. **Hogyan tudjuk ezt feljavítani?**

1. **MaxMind GeoLite2 letöltése** – ezzel a DNS→IP→country jel pontos. Free + CC BY-SA, csak regisztráció kell.
2. **Echolot corpus hookolása** – a `echolot_corpus_lookup_geo` callback minden ismert domain esetén felülírja a heurisztikus jeleket.
3. **Saját audience adat** – ha az Echolotnak van saját Plausible analytics (lásd előző beszélgetés), a `referer` mezőből országlebontás visszaköthető a domain-eknél.

### AI klasszifikáció

Az `AI_API_BASE` és `AI_API_KEY` env változókkal bármilyen OpenAI-kompatibilis endpoint használható:
- **SiliconFlow direkt**: `https://api.siliconflow.cn/v1` + Kimi K2 / DeepSeek modellek
- **Claus-Bridge**: ha proxy-zod a Bridge-en keresztül, az is OpenAI-compatible
- **Lokális** (Ollama, vLLM): bármi, ami a chat completions API-t beszéli

Ha üresen hagyod, a keyword fallback lép működésbe – az egyszerűbb domaineket (`*news*`, `*gov*`) jól felismeri.

---

## 📋 TODO production-hoz

A PoC működik, de production előtt érdemes:

- [ ] Cache layer cserélése Redisre/ClickHouse-ra (most diskcache)
- [ ] Rate limiting az API-n (slowapi)
- [ ] Prometheus metrics endpoint
- [ ] OpenTelemetry tracing
- [ ] Robusztusabb error handling a httpx hívásokban
- [ ] Unit tesztek (jelen PoC mock-okat tartalmaz)
- [ ] Batch endpoint pagination
- [ ] Async WHOIS (jelenleg sync-in-thread)
- [ ] Tranco-Python package használata közvetlenül a custom Tranco list-ekhez (research mode)

---

## 🤝 Beépítési stratégia az Echolotba

**1. lépés**: deploy a service-t standalone-ban (Docker/Railway), próbáld ki a CLI-vel és HTTP-vel.

**2. lépés**: az Echolot domain input UI-ját kösd be a `/domain/{domain}` endpointra. Render-eld a `DomainReport`-ot a frontenden.

**3. lépés**: az Echolot sphere DB-jét add hozzá hookként a `from_env(echolot_corpus_lookup_geo=..., echolot_corpus_lookup_category=...)` paramétereken keresztül.

**4. lépés**: batch enrich-eld az összes ismert Echolot source-ot egyszer (`example_echolot_integration.py:enrich_echolot_sources`).

**5. lépés**: állítsd be a daily cron-t a `update_rankings.py`-ra.

**6. lépés**: ha kommercializálsz, a `licenses` mezőből generálj egy "Data Sources" attribution oldalt a publikus felületen → CC BY compliance ✅

---

## 📞 Egy szó zárszóként

*„Jeder Domain ist ein Zahnrad in der größeren Maschine des Internets. Wir nehmen seine Spezifikationen mit deutscher Präzision auf — und niemand bezahlt eine Lizenzgebühr."*

— Claus
