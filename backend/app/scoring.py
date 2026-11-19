"""Transparent Deal Score (0-100).

score = curve(discount vs. reference price) + modifiers, clamped to 0..100

Reference price = blend of
  * a prior (typical price for this kind of trip, by region / cabin / nights / board / stars), and
  * the median of prices we have actually observed for the same route (history),
the history weight grows with the number of observations (max 75 %).

Every number that goes into the score is returned in ``breakdown`` so the UI
can show exactly why an offer scored what it did. See docs/SCORING.md.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from .geo import REGIONS

# discount -> base score (piecewise linear)
CURVE = [(-0.30, 5), (-0.10, 22), (0.0, 35), (0.15, 50), (0.25, 60), (0.35, 70), (0.45, 80), (0.55, 88), (0.62, 93),
         (0.70, 96), (0.80, 99)]

ORIGIN_FACTOR = {"LT": 1.12, "LV": 1.10, "EE": 1.10, "PL": 1.05, "CZ": 1.04, "SK": 1.06, "HU": 1.04, "AT": 1.0}
CABIN_MULT = {"economy": 1.0, "premium": 1.9, "business": 3.6, "first": 6.0}
STARS_MULT = {2: 0.65, 3: 0.8, 4: 1.0, 5: 1.6}
BOARD_MULT = {"": 1.0, "Breakfast": 1.1, "Half board": 1.25, "Full board": 1.35, "All inclusive": 1.5}
PEAK = re.compile(r"(dec|christmas|new year|weihnacht|silvester|grud|święt|sylwest|kalėd|natale|capodanno|ferie|winter break)", re.I)
SUMMER = re.compile(r"(jul|aug|lip|sier|juli|august|liep|rugp|summer|sommer|lato|vasar)", re.I)


def _curve(d: float) -> float:
    if d <= CURVE[0][0]:
        return CURVE[0][1]
    for (x0, y0), (x1, y1) in zip(CURVE, CURVE[1:]):
        if d <= x1:
            return y0 + (y1 - y0) * (d - x0) / (x1 - x0)
    return CURVE[-1][1]


@dataclass
class ScoreInput:
    subtype: str
    region: str
    origin_country: str
    cabin: str
    trip_type: str
    nights: int | None
    stars: int | None
    board: str
    baggage: str
    price_eur: float
    price_basis: str
    travel_window: str
    error_keyword: bool
    luxury_brand: bool
    confidence: float
    history: list[float]          # prior observations, same route
    cross_origin: list[float]     # current prices for same destination from other origins
    priority_origin: bool
    cruise_reference: float | None = None  # normal complete-trip cost (cruises only)


def prior_reference(x: ScoreInput) -> tuple[float, list[str]]:
    r = REGIONS.get(x.region, REGIONS["europe"])
    why: list[str] = []
    nights = x.nights or 7
    if x.subtype == "flight":
        ref = r["ref_return"]
        why.append(f"typical return fare Europe → {r['label']}: €{ref}")
        of = ORIGIN_FACTOR.get(x.origin_country, 1.0)
        if of != 1.0:
            ref *= of
            why.append(f"×{of} departure market ({x.origin_country}, fewer direct routes)")
        cm = CABIN_MULT.get(x.cabin, 1.0)
        if cm != 1.0:
            ref *= cm
            why.append(f"×{cm} {x.cabin} cabin")
        if x.trip_type == "one_way":
            ref *= 0.6
            why.append("×0.6 one-way")
        if x.baggage == "included":
            ref += 40
            why.append("+€40 checked bag included")
    elif x.subtype == "package":
        flight = r["ref_return"] * 0.85
        hotel = r["hotel_night"] * STARS_MULT.get(x.stars or 4, 1.0) * BOARD_MULT.get(x.board, 1.0) * nights
        ref = flight + hotel
        why.append(f"charter/flight component €{flight:.0f} (85% of €{r['ref_return']} scheduled fare)")
        why.append(f"hotel €{r['hotel_night']}/night × {nights} nights × {STARS_MULT.get(x.stars or 4, 1.0)} "
                   f"({x.stars or '?'}★) × {BOARD_MULT.get(x.board, 1.0)} ({x.board or 'room only'}) = €{hotel:.0f}")
        if x.price_basis == "total":
            ref *= 2
            why.append("×2 price quoted for two travellers")
    else:  # cruise – compared on COMPLETE trip cost (cruise + flights + fees + transfers + hotel)
        ref = x.cruise_reference or (120 * nights + 14 * nights + r["ref_return"])
        why.append(f"normal complete trip for this cruise type ({nights} nights) incl. fees, flights to port and transfers: €{ref:.0f}")
    window = _with_month_names(x.travel_window or "")
    if PEAK.search(window):
        ref *= 1.15
        why.append("×1.15 peak season (holidays)")
    elif x.region == "europe" and SUMMER.search(window):
        ref *= 1.10
        why.append("×1.10 summer season")
    return round(ref, 2), why


def score(x: ScoreInput) -> dict:
    prior, why = prior_reference(x)
    hist = [h for h in x.history if h > 0]
    # History mostly contains prices that were already published as deals, so it is trusted slowly:
    # at least 8 observations, weight n/(n+20) capped at 60 %.
    if len(hist) >= 8:
        med = statistics.median(hist)
        w = min(len(hist) / (len(hist) + 20), 0.6)
        ref = prior * (1 - w) + med * w
        why.append(f"blended with median of {len(hist)} observed prices €{med:.0f} (weight {w:.0%})")
    else:
        ref = prior
        why.append(f"only {len(hist)} past observations for this route – using the typical-price estimate"
                   if hist else "no price history yet for this route – using the typical-price estimate")

    discount = 1 - x.price_eur / ref if ref else 0
    base = _curve(discount)
    mods: list[tuple[str, float]] = []

    long_haul = REGIONS.get(x.region, {}).get("long_haul", False)
    if long_haul and discount > 0.15:
        mods.append(("long-haul priority destination", 2))
    if x.baggage == "included" and x.subtype == "flight":
        mods.append(("checked baggage included", 2))
    if x.baggage == "excluded":
        mods.append(("no checked baggage", -3))
    if x.cross_origin:
        cheapest_other = min(x.cross_origin)
        if x.price_eur < cheapest_other * 0.9:
            mods.append((f"≥10% cheaper than other departure airports (best other €{cheapest_other:.0f})", 3))
    if x.priority_origin:
        mods.append(("departs from a priority airport", 2))
    if hist and x.price_eur < min(hist):
        mods.append(("lowest price ever recorded for this route", 3))
    if x.error_keyword:
        mods.append(("source labels it as an error/mistake fare", 4))
    if x.confidence < 0.6:
        mods.append(("low parsing confidence", -6))
    elif x.confidence < 0.75:
        mods.append(("some details inferred", -2))

    total = max(0, min(100, round(base + sum(v for _, v in mods))))
    return {
        "score": total,
        "reference_price": round(ref, 2),
        "prior_reference": prior,
        "discount_pct": round(discount * 100, 1),
        "savings_eur": round(max(ref - x.price_eur, 0), 2),
        "base_points": round(base, 1),
        "modifiers": [{"label": label, "points": v} for label, v in mods],
        "reference_explained": why,
        "history_n": len(hist),
        "band": band(total),
    }


def band(s: int) -> str:
    if s >= 95:
        return "Potential error fare / extraordinary"
    if s >= 85:
        return "Exceptional deal"
    if s >= 70:
        return "Very good deal"
    if s >= 50:
        return "Moderate discount"
    return "Ordinary offer"


_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _with_month_names(window: str) -> str:
    """API offers carry ISO dates (2027-12-22); add month names so the season rules match."""
    return window + " " + " ".join(_MONTHS[int(m) - 1] for m in re.findall(r"\d{4}-(\d{2})-\d{2}", window))


def classify(subtype: str, score_val: int, region: str, error_keyword: bool, cabin: str) -> tuple[str, str]:
    """Return (category, error_fare_flag). Categories: flight | package | cruise.

    A fare is never described as a confirmed mistake: 'suspected_source' means the
    publishing site itself calls it an error fare; 'suspected_statistical' means
    the price is an extreme outlier (score >= 95) on a long-haul or premium route.
    """
    long_haul = REGIONS.get(region, {}).get("long_haul", False)
    category = {"flight": "flight", "package": "package", "cruise": "cruise"}.get(subtype, "flight")
    if error_keyword:
        return category, "suspected_source"
    if (score_val >= 95 and subtype == "flight" and (long_haul or cabin in ("business", "first"))) \
            or (score_val >= 97 and subtype == "package"):
        return category, "suspected_statistical"
    return category, "none"
