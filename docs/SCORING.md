# Deal Score methodology

Every offer gets a score from 0 to 100. The full calculation is stored per offer and shown in the deal drawer.

```
reference = prior × (1 − w) + median(observed history) × w        w = min(n / (n + 20), 0.6), needs n ≥ 8
discount  = 1 − price / reference
score     = curve(discount) + modifiers                            clamped to 0..100
```

## 1. Prior reference price (what this trip normally costs)

| Type | Prior |
|---|---|
| Flight | Typical **return economy** fare Europe → destination region (`geo.REGIONS.ref_return`) × departure-market factor (LT 1.12, LV/EE 1.10, PL/SK 1.05–1.06, CZ/HU 1.04) × cabin (premium 1.9, business 3.6, first 6.0) × 0.6 if one-way, + €40 if a checked bag is included |
| Package | 85 % of the regional fare (charter) + regional hotel price per night × nights (default 7) × stars (3★ 0.8, 4★ 1.0, 5★ 1.6) × board (BB 1.1, HB 1.25, FB 1.35, AI 1.5); ×2 if the price is for two |
| Cruise | **Complete trip**: per-night cruise norm (standard €95, repositioning €60, luxury lines €400) × nights + gratuities €14/day + flights (return to the port, or one-way out + one-way home when the cruise starts and ends in different ports, each ≈ 55 % of a return) + transfers €40 + ½ hotel night €47.50 (independent combos only). Prices quoted "for two" are halved first |

Season: ×1.15 for Christmas/New Year/winter-holiday travel, ×1.10 for European summer (also detected from
ISO travel dates of API fares).

Regional reference fares (return, EUR): Europe 160 · Canaries/N. Africa 260 · Egypt 330 · Middle East 420 ·
Central Asia 380 · India/Sri Lanka 680 · Maldives/Seychelles/Mauritius 850 · SE Asia 720 · Japan/Korea 850 ·
China/HK 650 · USA East/Canada 500 · USA West/Hawaii 720 · Caribbean/Mexico 780 · South America 880 ·
East Africa 720 · Southern Africa 820 · Cape Verde/W. Africa 380 · Australia/NZ 1350.
These are deliberately conservative "normal" prices and are progressively replaced by observed history.

## 1b. Everything is priced from your home hub

Home hubs default to Vienna, Vilnius, Warsaw and Riga (`home_airports` preference); `nearby_km` (default 300 km)
covers airports reachable by train or bus (Kaunas, Bratislava, Budapest, Prague…); a ground-transport
estimate (€15 + €0.15/km, return) is added for those.
A deal departing further away (e.g. Stockholm → Thailand, or "United Kingdom (various)") is scored on
**deal price + cheapest return flight hub ⇄ departure airport** on a separate ticket, compared with what the trip
normally costs from your hub. Positioning fares come from Travelpayouts (refreshed every 12 h); without a token a
distance estimate (€30 + €0.07/km, return) is used and shown with "≈".
For the best deals that have exact dates, the worker also prices the connecting flights **on the deal's own dates**
(hub → departure airport the day before, back on the return day, two one-way tickets) and uses that fare instead. For long-haul destinations a
pre-departure hotel night (≈ €60) is added, because a separate first ticket gives no missed-connection protection. "Multiple European airports" deals
are not adjusted because the departure airport is unknown.

## 1c. One authoritative price

Every view, filter, alert and the score use the same number: the effective trip total =
(live airline price if Duffel checked it in the last 24 h, else the advertised price) + getting there from your hub
(+ cruise extras). When the cached price changes, the old live check is discarded.

## 2. History

Every first sighting and every price change is written to `price_history` under a route key
`subtype|origin|destination|cabin|trip|nights-bucket`. Once two or more observations exist, their median is
blended into the reference only after 8 observations and never above 60 % weight, because most history consists of
prices that were already published as deals (a median of deals is not a normal market price). Scores are recomputed daily at 03:30.

## 3. Base points (discount curve)

| Discount vs reference | ≤ −30 % | −10 % | 0 % | 15 % | 25 % | 35 % | 45 % | 55 % | 62 % | 70 % | ≥ 80 % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Base points | 5 | 22 | 35 | 50 | 60 | 70 | 80 | 88 | 93 | 96 | 99 |

Linear interpolation between points.

## 4. Modifiers

| Condition | Points |
|---|---|
| Long-haul priority destination and discount > 15 % | +2 |
| Checked baggage included (flights) | +2 |
| No checked baggage | −3 |
| ≥ 10 % cheaper than the best offer to the same destination from other departure airports | +3 |
| Departs from one of your enabled airports | +2 |
| Lowest price ever recorded for this route | +3 |
| Source itself calls it an error/mistake fare | +4 |
| Parsing confidence < 0.6 / < 0.75 | −6 / −2 |
| Discount > 70 % on loosely parsed data (confidence < 0.8) | score capped at 69 – "check source" |

## 5. Bands

95–100 potential error fare / extraordinary · 85–94 exceptional · 70–84 very good · 50–69 moderate · < 50 ordinary.
Offers below the "show deals with score ≥" setting (default 60) are stored for history but never shown.

## 6. Error-fare labels (never "confirmed")

* `suspected_source` — the publishing site describes it as an error/mistake fare.
* `suspected_statistical` — score ≥ 95 on a long-haul or premium-cabin flight, or ≥ 97 on a package
  (never on cruises).

## 7. Known limitations

* RSS sources publish "from" prices and rarely exact dates; the score reflects the headline price.
* Hotel quality is inferred from stars only; reviews are not yet considered.
* Cruise fees, transfers and hotel are estimates; flight cost to the port uses the cheapest fare currently
  in the database for that region, else the regional reference.

## Honest prices

- **One deal per departure city.** When a post lists several cities with one "from" price
  ("Milan, Vienna, Paris → Mauritius from €364"), HubFare creates a separate deal for each city.
  Each one is priced from your hub via that city. The city that works best for you leads the card,
  and the others are listed in the deal panel. The price is labelled "lowest of N cities in the post",
  and its confidence is lowered, because the post doesn't say which city has it.
- **Unknown departure airport.** Deals that don't name a departure airport (cruises excepted) never
  appear in the best, latest or urgent lists. They also don't count as "from your airports" and don't
  trigger alerts with an origin filter.
- **One total everywhere.** The card price, list sorting, max-price filters, preferences and alert
  budgets all use the same number: the whole trip from your home city. That is the live or
  advertised fare, plus getting to the departure airport, plus cruise extras.
- **Booking links** start from the airport the trip actually leaves from. Connecting-flight searches
  use the connection's own dates (for example, the day before plus a hotel night).
