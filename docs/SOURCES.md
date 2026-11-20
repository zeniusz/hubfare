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

Flight deals come from both: the fare APIs above and flight posts from the deal blogs (TravelFree.info, Fly4free,
Travel-Dealz…). Blog fares are priced from your home hub like everything else. Set `RSS_FLIGHTS=false` to use the APIs only.

## How deal sites find fares – and how HubFare does the same legally

Deal publishers such as TravelFree.info appear to find fares mostly by hand: editors browse flexible searches on
Skyscanner ("Everywhere", whole-month view) and Google Flights, and then post what is unusually cheap. Those sites
cannot be queried automatically (no public API, scraping forbidden), so HubFare does the equivalent with permitted data:

| Their manual step | HubFare (automatic) |
|---|---|
| "From Vilnius to Everywhere" | `travelpayouts`: cheapest fares from each departure airport to **any** destination, hourly, rotating through 12 airports at a time |
| Month view: cheapest day of the month | `tp_calendar`: whole-month price calendar from your home hubs to 24 long-haul destinations (cheapest day per month, next 3 months) |
| "Is this cheap?" | Deal score against typical prices and price history |
| Fly to Stockholm, then on to China | Connecting flights from your hub, same day with ≥ `MIN_CONNECTION_HOURS` (default 3 h) between separate tickets, otherwise the evening before + hotel night |

HubFare also keeps reading the blogs themselves, so anything their editors find shows up too.

## Lithuanian travel agencies (checked 20 Nov 2026)

Novaturas, Tez Tour, Join UP!, Gruda, Kelionių akademija and skrendu.lt publish **no RSS feed**; travelplanet.lt has a
feed with travel stories only. Lithuanian departures currently come from TravelFree.info, Fly4free and Makalius.
Agency offers can be added with their affiliate/XML feeds, or by parsing their newsletters from a mailbox.

## UK deals

Deals that depart only from the UK are hidden (`EXCLUDED_ORIGIN_COUNTRIES=GB`), and HolidayPirates (UK edition) is off.

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
