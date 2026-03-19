"""
HírMagnet MCP — News Sources Configuration

188 source slots. Starter set below — replace/extend with your original HírMagnet sources.py.
Categories: politika, gazdaság, világpolitika, tech, sport, kultúra, tudomány, belföldi, EU, vélemény, bulvár

Each source dict:
    name:     Display name
    url:      RSS feed URL
    category: Topic category
    language: "hu", "en", "de" (default: "hu")
"""

NEWS_SOURCES = [
    # ===================================================================
    #  MAGYAR ÁLTALÁNOS / BELFÖLDI
    # ===================================================================
    {"name": "Telex", "url": "https://telex.hu/rss", "category": "belföldi", "language": "hu"},
    {"name": "HVG", "url": "https://hvg.hu/rss", "category": "belföldi", "language": "hu"},
    {"name": "Index", "url": "https://index.hu/24ora/rss/", "category": "belföldi", "language": "hu"},
    {"name": "444", "url": "https://444.hu/feed", "category": "belföldi", "language": "hu"},
    {"name": "24.hu", "url": "https://24.hu/feed/", "category": "belföldi", "language": "hu"},
    {"name": "Magyar Nemzet", "url": "https://magyarnemzet.hu/feed/", "category": "belföldi", "language": "hu"},
    {"name": "Origo", "url": "https://www.origo.hu/contentpartner/rss/origo/origo.xml", "category": "belföldi", "language": "hu"},
    {"name": "MTI", "url": "https://mti.hu/rss/top", "category": "belföldi", "language": "hu"},
    {"name": "Mandiner", "url": "https://mandiner.hu/rss", "category": "belföldi", "language": "hu"},
    {"name": "Válasz Online", "url": "https://www.valaszonline.hu/feed/", "category": "belföldi", "language": "hu"},
    {"name": "Szabad Európa", "url": "https://www.szabadeuropa.hu/api/z-pqpiev-qpp", "category": "belföldi", "language": "hu"},
    {"name": "Népszava", "url": "https://nepszava.hu/feed", "category": "belföldi", "language": "hu"},
    {"name": "Magyar Hang", "url": "https://hang.hu/feed", "category": "belföldi", "language": "hu"},

    # ===================================================================
    #  POLITIKA
    # ===================================================================
    {"name": "Telex Politika", "url": "https://telex.hu/rss/belfold", "category": "politika", "language": "hu"},
    {"name": "HVG Itthon", "url": "https://hvg.hu/rss/itthon", "category": "politika", "language": "hu"},
    {"name": "Index Politika", "url": "https://index.hu/belfold/rss/", "category": "politika", "language": "hu"},
    {"name": "Magyar Nemzet Politika", "url": "https://magyarnemzet.hu/belfold/feed/", "category": "politika", "language": "hu"},
    {"name": "Kormany.hu", "url": "https://kormany.hu/hirek/rss", "category": "politika", "language": "hu"},

    # ===================================================================
    #  GAZDASÁG
    # ===================================================================
    {"name": "Portfolio", "url": "https://www.portfolio.hu/rss/all.xml", "category": "gazdaság", "language": "hu"},
    {"name": "Napi.hu", "url": "https://www.napi.hu/rss.xml", "category": "gazdaság", "language": "hu"},
    {"name": "G7", "url": "https://g7.hu/feed/", "category": "gazdaság", "language": "hu"},
    {"name": "Bank360", "url": "https://bank360.hu/rss", "category": "gazdaság", "language": "hu"},
    {"name": "Pénzcentrum", "url": "https://www.penzcentrum.hu/rss/", "category": "gazdaság", "language": "hu"},
    {"name": "HVG Gazdaság", "url": "https://hvg.hu/rss/gazdasag", "category": "gazdaság", "language": "hu"},
    {"name": "Világgazdaság", "url": "https://www.vg.hu/feed/", "category": "gazdaság", "language": "hu"},
    {"name": "MNB sajtóközlemények", "url": "https://www.mnb.hu/sajtoszoba/sajtokozlemenyek/rss", "category": "gazdaság", "language": "hu"},

    # ===================================================================
    #  VILÁGPOLITIKA / INTERNATIONAL
    # ===================================================================
    {"name": "Telex Külföld", "url": "https://telex.hu/rss/kulfold", "category": "világpolitika", "language": "hu"},
    {"name": "HVG Világ", "url": "https://hvg.hu/rss/vilag", "category": "világpolitika", "language": "hu"},
    {"name": "Index Külföld", "url": "https://index.hu/kulfold/rss/", "category": "világpolitika", "language": "hu"},
    {"name": "Reuters World", "url": "https://feeds.reuters.com/Reuters/worldNews", "category": "világpolitika", "language": "en"},
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "category": "világpolitika", "language": "en"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "category": "világpolitika", "language": "en"},
    {"name": "DW News", "url": "https://rss.dw.com/rdf/rss-en-all", "category": "világpolitika", "language": "en"},
    {"name": "France24", "url": "https://www.france24.com/en/rss", "category": "világpolitika", "language": "en"},
    {"name": "Euronews", "url": "https://www.euronews.com/rss", "category": "világpolitika", "language": "en"},
    {"name": "The Guardian World", "url": "https://www.theguardian.com/world/rss", "category": "világpolitika", "language": "en"},
    {"name": "AP News", "url": "https://rsshub.app/apnews/topics/world-news", "category": "világpolitika", "language": "en"},

    # ===================================================================
    #  EU / EURÓPA
    # ===================================================================
    {"name": "EUrologus", "url": "https://eurologus.444.hu/feed", "category": "EU", "language": "hu"},
    {"name": "Politico EU", "url": "https://www.politico.eu/feed/", "category": "EU", "language": "en"},
    {"name": "EurActiv", "url": "https://www.euractiv.com/feed/", "category": "EU", "language": "en"},
    {"name": "European Council", "url": "https://www.consilium.europa.eu/en/rss/", "category": "EU", "language": "en"},
    {"name": "EU Observer", "url": "https://euobserver.com/rss.xml", "category": "EU", "language": "en"},

    # ===================================================================
    #  TECH / TUDOMÁNY
    # ===================================================================
    {"name": "HVG Tech", "url": "https://hvg.hu/rss/tudomany", "category": "tech", "language": "hu"},
    {"name": "HWSW", "url": "https://www.hwsw.hu/rss.xml", "category": "tech", "language": "hu"},
    {"name": "Prohardver", "url": "https://prohardver.hu/rss/fresh.xml", "category": "tech", "language": "hu"},
    {"name": "Rakéta", "url": "https://raketa.hu/feed", "category": "tech", "language": "hu"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "category": "tech", "language": "en"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "category": "tech", "language": "en"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "category": "tech", "language": "en"},
    {"name": "Wired", "url": "https://www.wired.com/feed/rss", "category": "tech", "language": "en"},

    # ===================================================================
    #  TUDOMÁNY
    # ===================================================================
    {"name": "Qubit", "url": "https://qubit.hu/feed", "category": "tudomány", "language": "hu"},
    {"name": "National Geographic HU", "url": "https://ng.hu/feed/", "category": "tudomány", "language": "hu"},
    {"name": "Science", "url": "https://www.science.org/rss/news_current.xml", "category": "tudomány", "language": "en"},
    {"name": "Nature News", "url": "https://www.nature.com/nature.rss", "category": "tudomány", "language": "en"},

    # ===================================================================
    #  SPORT
    # ===================================================================
    {"name": "NSO", "url": "https://www.nemzetisport.hu/rss", "category": "sport", "language": "hu"},
    {"name": "M4Sport", "url": "https://www.m4sport.hu/rss/", "category": "sport", "language": "hu"},
    {"name": "Goal.com", "url": "https://www.goal.com/feeds/en/news", "category": "sport", "language": "en"},

    # ===================================================================
    #  KULTÚRA
    # ===================================================================
    {"name": "HVG Kultúra", "url": "https://hvg.hu/rss/kultura", "category": "kultúra", "language": "hu"},
    {"name": "Index Kultúra", "url": "https://index.hu/kultur/rss/", "category": "kultúra", "language": "hu"},
    {"name": "Librarius", "url": "https://librarius.hu/feed/", "category": "kultúra", "language": "hu"},

    # ===================================================================
    #  PÉNZÜGY / TŐZSDE (international)
    # ===================================================================
    {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/markets/news.rss", "category": "gazdaság", "language": "en"},
    {"name": "Financial Times", "url": "https://www.ft.com/rss/home", "category": "gazdaság", "language": "en"},
    {"name": "CNBC", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "category": "gazdaság", "language": "en"},
    {"name": "MarketWatch", "url": "https://feeds.marketwatch.com/marketwatch/topstories/", "category": "gazdaság", "language": "en"},

    # ===================================================================
    #  GERMAN-LANGUAGE (bonus — V4 context)
    # ===================================================================
    {"name": "Der Spiegel", "url": "https://www.spiegel.de/schlagzeilen/index.rss", "category": "világpolitika", "language": "de"},
    {"name": "FAZ", "url": "https://www.faz.net/rss/aktuell/", "category": "világpolitika", "language": "de"},
    {"name": "Die Zeit", "url": "https://newsfeed.zeit.de/index", "category": "világpolitika", "language": "de"},
    {"name": "NZZ", "url": "https://www.nzz.ch/recent.rss", "category": "világpolitika", "language": "de"},

    # ===================================================================
    #  V4 / REGIONÁLIS
    # ===================================================================
    {"name": "Denník N (SK)", "url": "https://dennikn.sk/feed/", "category": "világpolitika", "language": "sk"},
    {"name": "Novinky.cz", "url": "https://www.novinky.cz/rss", "category": "világpolitika", "language": "cs"},
    {"name": "Gazeta Wyborcza", "url": "https://wyborcza.pl/0,0.html?disableRedirects=true", "category": "világpolitika", "language": "pl"},

    # ===================================================================
    #  VÉLEMÉNY / ELEMZÉS
    # ===================================================================
    {"name": "Project Syndicate", "url": "https://www.project-syndicate.org/rss", "category": "vélemény", "language": "en"},
    {"name": "Foreign Policy", "url": "https://foreignpolicy.com/feed/", "category": "vélemény", "language": "en"},
    {"name": "Foreign Affairs", "url": "https://www.foreignaffairs.com/rss.xml", "category": "vélemény", "language": "en"},
    {"name": "Brookings", "url": "https://www.brookings.edu/feed/", "category": "vélemény", "language": "en"},

    # ===================================================================
    #  TODO: Add remaining sources from original HírMagnet sources.py
    #  The original had 188 sources — merge them here.
    #  Use: python scraper.py --source "SourceName" to test individual feeds
    # ===================================================================
]

# Quick stats
if __name__ == "__main__":
    from collections import Counter
    cats = Counter(s["category"] for s in NEWS_SOURCES)
    langs = Counter(s.get("language", "hu") for s in NEWS_SOURCES)
    print(f"\nHírMagnet Sources: {len(NEWS_SOURCES)} total")
    print(f"\nBy category:")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")
    print(f"\nBy language:")
    for lang, count in langs.most_common():
        print(f"  {lang}: {count}")
