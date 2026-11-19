# Data sources (verified 13 November 2026)

Each source was checked for an accessible feed/API and for `robots.txt` permission before integration.
The worker re-checks `robots.txt` daily and stops if a feed becomes disallowed.

## Integrated (live, free)

| Source | Market | Feed | Categories | Default interval |
|---|---|---|---|---|
| TravelFree.info | Baltics / CEE | `travelfree.info/feed/` | Flights | 45 min (priority) |
| Fly4free | Europe | `fly4free.com/feed/` | Flights, packages, cruises | 45 min (priority) |
| Travel-Dealz | Europe (DE) | `travel-dealz.com/feed/` | Premium cabins, error fares, cruises | 60 min (priority) |
| Fly4free.pl | Poland | `fly4free.pl/feed/` | Flights, packages | 120 min |
| Wakacyjni Piraci | Poland | `wakacyjnipiraci.pl/feed` | Packages | 120 min |
| Urlaubspiraten | Germany / Austria | `urlaubspiraten.de/feed` | Packages, cruises | 120 min |
| HolidayPirates | UK | `holidaypirates.com/feed` | Packages, cruises | 120 min |
| Makalius | Lithuania (tour operator) | `makalius.lt/feed/` | Packages (most current items are coach tours → filtered out) | 120 min |
| ECB reference rates | – | `ecb.europa.eu/.../eurofxref-daily.xml` | Currency conversion | daily |
| Wikipedia REST API | – | `/api/rest_v1/page/summary/{title}` | Destination photos (CC-licensed, Wikimedia Commons) | cached |

## Implemented, needs credentials

| Source | Access | Notes |
|---|---|---|
| Aviasales Data API (Travelpayouts) `v3/prices_for_dates` | Free partner token | Cheapest fares found by Aviasales users in the last 48 h, per departure airport, **any destination**, with dates and airline. Rate-limited, 0.4 s between calls, up to 8 enabled airports per run |

| Duffel `air/offer_requests` | Self sign-up, pay-as-you-go | Live airline prices for the exact route and dates of the top flight deals. Searches beyond a 1,500:1 search-to-book ratio cost ≈ $0.005 each; capped by `DUFFEL_MAX_CHECKS_PER_DAY` |

Since 17 Nov 2026 flight deals come only from these APIs; deal-blog posts are used for holiday packages and cruises only
(TravelFree.info, which is flights-only, is disabled). Set `RSS_FLIGHTS=true` to bring blog flight posts back.

## Researched – not integrated

| Source | Reason |
|---|---|
| Secret Flying, Flynous | Feed returns HTTP 403 to automated readers. Not bypassed |
| Urlaubsguru | Feed returns HTTP 401. Not bypassed |
| Amadeus Self-Service | Shut down 17 July 2026; Enterprise APIs need a contract |
| Kiwi.com Tequila | Public sign-up closed |
| Skyscanner | Partner-only API |
| Google Flights | No API; scraping prohibited |
| Novaturas, Tez Tour, Join UP!, TUI, ITAKA, Rainbow, Exim Tours, DERTOUR, Kelionių akademija | No public feed or API. Product/price feeds are typically offered to affiliates (Awin, Travelpayouts, direct partner XML). Add as a new provider once you have access |
| lastminute.com, Restplatzbörse | Affiliate programme required |

## Recommended next sources

1. **Travelpayouts token** – unlocks real fare data with dates for every enabled airport (biggest gain).
2. **Tour-operator affiliate feeds** (Awin / direct) for ITAKA, Rainbow, TUI, Novaturas – structured package
   prices with hotel, board and departure airport.
3. More regional RSS deal blogs that permit feeds (check `robots.txt` and terms first).
