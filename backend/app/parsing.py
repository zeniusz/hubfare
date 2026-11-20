"""Turn free-text deal posts (EN/PL/DE/LT/IT) into structured offers.

The parser is intentionally conservative: if no price or destination can be
identified, the item is dropped (it is usually news, not a deal). Every parsed
offer carries a ``confidence`` value that the scoring engine uses.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from .geo import COUNTRY_ORIGINS, DEST_PLACES, ORIGIN_PLACES, REGIONS, Place, find_places
from .cruise import Port, find_port

_TAG = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    text = html.unescape(_TAG.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- price
_NUM = r"(\d{1,3}(?:[ ., ]\d{3})+|\d+)(?:[.,](\d{1,2}))?"
_CUR_BEFORE = re.compile(r"(€|£|\$|EUR|GBP|USD|PLN)\s?" + _NUM, re.I)
_CUR_AFTER = re.compile(_NUM + r"\s?(€|£|\$|EUR|GBP|USD|PLN|zł|zl|Kč|CZK|euro|eur)(?![a-z])", re.I)
_CUR_MAP = {"€": "EUR", "eur": "EUR", "euro": "EUR", "£": "GBP", "gbp": "GBP", "$": "USD", "usd": "USD",
            "pln": "PLN", "zł": "PLN", "zl": "PLN", "kč": "CZK", "czk": "CZK"}
# A price followed by these words is not the deal price (credits, discounts, deposits ...)
_NOT_PRICE_AFTER = re.compile(r"^\s?(?:/\s?)?(credit|rabatt|discount|off|bonus|cashback|zniżk|taniej|günstiger|"
                              r"gutschein|voucher|kredyt|deposit|anzahlung|rabat|nuolaid)", re.I)
_NOT_PRICE_BEFORE = re.compile(r"(save|sparen?|spart|oszczędź|up to|bis zu|do|aż|nawet|extra|\+|plus|with)\s*$", re.I)


def _to_float(whole: str, frac: str | None) -> float:
    w = re.sub(r"[ ., ]", "", whole)
    return float(f"{w}.{frac}") if frac else float(w)


@dataclass
class Price:
    amount: float
    currency: str
    start: int
    end: int


def find_prices(text: str) -> list[Price]:
    out: list[Price] = []
    for rx, before in ((_CUR_BEFORE, True), (_CUR_AFTER, False)):
        for m in rx.finditer(text):
            if before:
                cur, whole, frac = m.group(1), m.group(2), m.group(3)
            else:
                whole, frac, cur = m.group(1), m.group(2), m.group(3)
            amount = _to_float(whole, frac)
            tail = text[m.end(): m.end() + 14]
            head = text[max(0, m.start() - 14): m.start()]
            if _NOT_PRICE_AFTER.match(tail) or _NOT_PRICE_BEFORE.search(head) or "%" in tail[:2]:
                continue
            if amount < 15 or amount > 25000:
                continue
            out.append(Price(amount, _CUR_MAP.get(cur.lower(), cur.upper()), m.start(), m.end()))
    out.sort(key=lambda p: p.start)
    # drop overlaps
    dedup: list[Price] = []
    for p in out:
        if not dedup or p.start >= dedup[-1].end:
            dedup.append(p)
    return dedup


# ---------------------------------------------------------------- attributes
_RETURN = re.compile(r"\b(return|round[- ]?trip|both ways|r/t|hin und zurück|hin- und rückflug|tam i z powrotem|"
                     r"w obie strony|andata e ritorno|a/r|į abi puses|pirmyn atgal|roundtrip)\b", re.I)
_ONE_WAY = re.compile(r"\b(one[- ]way|oneway|w jedną stronę|nur hinflug|one way|sola andata|į vieną pusę|einfach)\b", re.I)
_NIGHTS = re.compile(r"(\d{1,2})\s*(?:-|\s)?\s*(?:nights?|nocy|noce|nocą|noclegi|noclegów|nächte|nächten|übernachtungen|"
                     r"naktys|naktų|naktis|notti|n\.|day stay|days?|dni|tage|dienų|giorni)\b", re.I)
_WEEK = re.compile(r"\b(a week|one week|1 week|tydzień|tygodniow\w*|eine woche|1 woche|savaitei|savaitė\w*|una settimana)\b", re.I)
_STARS_EMOJI = re.compile(r"(\d)\s?(?:⭐|★|\*(?!\*)|-star|\s?star|\s?gwiazdk\w*|\s?sterne?|\s?žvaigžd\w*|\s?stelle)", re.I)
_STAR_RUN = re.compile(r"((?:⭐️?|★){3,5})")
_BUSINESS = re.compile(r"\b(business class|business-class|biznes klas\w*|klasie biznes|klasa biznes|business-klasse|"
                       r"verslo klas\w*|in business|business)\b", re.I)
_PREMIUM = re.compile(r"\b(premium economy|premium eco|premium-economy)\b", re.I)
_FIRST = re.compile(r"\b(first class|pierwsza klasa|first-class)\b", re.I)
_ERROR = re.compile(r"\b(error fare|mistake fare|price glitch|pricing error|fare glitch|błąd taryfowy|błąd cenowy|błędna cena|"
                    r"preisfehler|fehlerpreis|kainos klaida|errore tariffario|error-fare|glitch)\b", re.I)
_PER_PERSON = re.compile(r"(p\.?\s?p\.?\b|per person|pro person|pro kopf|/\s?os\.?|za osobę|od osoby|/person|asmeniui|a persona|"
                         r"per adult|pro erwachsene\w*|each)", re.I)
_PER_NIGHT = re.compile(r"(/\s?night|per night|a night|/\s?nacht|pro nacht|za noc|/\s?noc|už naktį|a notte|/night|/\s?double|"
                        r"/\s?room|per room|/\s?dz\b|pro zimmer|/\s?doppelzimmer)", re.I)
_TOTAL_FOR_TWO = re.compile(r"(for two|for 2|für zwei|für 2|dla dwojga|dla 2 osób|dla dwóch|dviem|per due|total)", re.I)
_PACKAGE = re.compile(r"(holiday|package|all[- ]inclusive|resort|hotel|apartment|stay|loty \+|flights \+|flug \+|"
                      r"pauschal|urlaub|wakacj|wczas|noclegi|nocleg|apartament|kelion\w*|poilsis|pacchett|vacanz|"
                      r"\bhb\b|\bbb\b|\bai\b|safari|lodge|villa|wycieczk|ferie|reise\b|incl\. hotel|\+ hotel|hotel \+)", re.I)
_FLIGHT = re.compile(r"(flights?|fly|airfare|tickets?|loty|\blot\b|bilety|flüge|flug\b|skrydži\w*|voli|volo|airways|airlines|"
                     r"lufthansa|ryanair|wizz|lot polish|airbaltic|emirates|qatar airways|etihad|turkish|sas\b|finnair|klm|"
                     r"business class|economy class|premium economy|first class|error fare|mistake fare|\breturn\b|round[- ]?trip|one[- ]way)", re.I)
_CRUISE = re.compile(r"\b(cruises?|kreuzfahrt\w*|rejs\w*|kruiz\w*|crociera|mein schiff|aida\w*|msc [a-z]+|costa [a-z]+|royal caribbean|"
                     r"norwegian cruise|celebrity [a-z]+|princess cruises|cunard|holland america|carnival [a-z]+|viking ocean|"
                     r"tui cruises|hurtigruten|havila|p&o cruises|virgin voyages|explora journeys)\b", re.I)
_FROM_TO = re.compile(r"\b(from|von|ab|iš|da)\s+([^.;:!()]{2,40}?)\s+(to|nach|į|a|zum|zur)\b", re.I)
_NON_EU = re.compile(r"\b(l\.a\.|los angeles|new york|bangkok|dubai|singapore|tokyo|miami|sydney|usa|asia|asien)\b", re.I)
_LUX_BRAND = re.compile(r"(ritz[- ]carlton|four seasons|mandarin oriental|conrad|waldorf|st\.? regis|park hyatt|aman\b|"
                        r"rosewood|six senses|soneva|raffles|bulgari|peninsula|one&only|jumeirah|anantara|w hotel|"
                        r"autograph collection|luxury collection|sofitel|fairmont|kempinski|banyan tree)", re.I)
_BOARD = [
    ("All inclusive", re.compile(r"(all[- ]?inclusive|all inkl|\bai\b|ultra all|wszystko w cenie|viskas įskaičiuota)", re.I)),
    ("Full board", re.compile(r"(full board|vollpension|pełne wyżywienie|pilnas maitinimas|pensione completa)", re.I)),
    ("Half board", re.compile(r"(half board|halbpension|\bhb\b|obiadokolacj|pusryčiai ir vakarienė|mezza pensione)", re.I)),
    ("Breakfast", re.compile(r"(breakfast|frühstück|śniadani|pusryči|colazione|\bbb\b)", re.I)),
]
_BAG_INC = re.compile(r"(checked baggage incl|with luggage|with baggage|incl\.? luggage|inkl\.? gepäck|z bagażem|bagaż rejestrowany w cenie|"
                      r"su bagažu|bagaglio incluso|23 ?kg|25 ?kg|baggage included)", re.I)
_BAG_EXC = re.compile(r"(hand luggage only|without luggage|no checked|only cabin|bez bagażu|nur handgepäck|be bagažo|solo bagaglio a mano|"
                      r"doesn.t include checked)", re.I)
_MONTHS = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|januar|februar|märz|mai|juni|juli|okt|dez|stycz|lut|marz|kwie|maj|czerw|lip|sierp|wrze|paźdz|listop|grud)\w*"
_FLIGHTS_INCL = re.compile(r"(flights?|flug|flüge|loty|\blot\b|airfare|z przelotem|przelot|skrydži\w*|skrydis|voli|volo|"
                           r"\+ ?flug|inkl\.? flug|incl\.? flights?|with flights|charter|fly\b|flying)", re.I)
_DEPOSIT = re.compile(r"(deposit|anzahlung|zaliczk\w*|avans\w*|acconto|down ?payment)", re.I)
_LAST_MINUTE = re.compile(r"(last[- ]?minute|lastminute|kurzfristig|last call|ostatni(?:a|ej) chwil\w*|paskutin\w* minut\w*|"
                          r"ultimo minuto|departing (?:this|next) week|this weekend|in den nächsten tagen|flash sale|blitz)", re.I)
_FLY_CRUISE = re.compile(r"(fly[ &-]+cruise|fly and cruise|incl\.? flights?|including flights|flights included|with flights|inkl\.? flug|"
                         r"inklusive flug|mit flug|z przelotem|z lotem|loty w cenie|su skrydžiu|volo incluso|voli inclusi)", re.I)
_WINDOW = re.compile(r"((?:in|from|between|until|till|im|von|bis|w|od|do)\s+" + _MONTHS + r"(?:\s*(?:20\d\d))?(?:\s*(?:to|–|-|and|bis|do)\s*" + _MONTHS + r"(?:\s*20\d\d)?)?)", re.I)


@dataclass
class ParsedDeal:
    title: str
    price_amount: float
    currency: str
    price_basis: str
    origin_codes: list[str]
    origin_label: str
    dest: Place | None
    trip_type: str
    cabin: str
    nights: int | None
    stars: int | None
    board: str
    baggage: str
    subtype: str
    error_keyword: bool
    luxury_signal: bool
    last_minute: bool
    cruise_port: "Port | None"
    fly_cruise_package: bool
    travel_window: str
    confidence: float
    notes: list[str] = field(default_factory=list)


def _find_origins(text: str) -> list[Place]:
    found = find_places(text, "origin")
    # keep the order of appearance, unique
    seen, out = set(), []
    for _, _, p in found:
        if p.key not in seen:
            seen.add(p.key)
            out.append(p)
    return out


def _dest_after_origin(text: str, origins: list[Place]) -> Place | None:
    """Prefer destinations that are not origins and appear after 'to/nach/do/į/a'."""
    dests = [(s, e, p) for s, e, p in find_places(text, "dest")]
    if not dests:
        return None
    origin_names = {o.name.lower() for o in origins}
    candidates = [d for d in dests if d[2].name.lower() not in origin_names]
    if not candidates:
        return None
    long_haul = [d for d in candidates if REGIONS[d[2].region]["long_haul"]]
    pool = long_haul or candidates
    first = pool[0][2]
    # A specific place beats a generic region/country mention ("Caribbean Island! … Saint Lucia", "Japan … Tokyo")
    if first.key in _GENERIC or first.name == first.country:
        for _, _, p in pool[1:]:
            if p.key not in _GENERIC and (p.country == first.country or first.key in _GENERIC):
                return p
    return first


_GENERIC = {"caribbean", "usa"}
_BUS = re.compile(r"\b(autobus\w*|bus|coach|autokar\w*|reisebus|pullman)\b", re.I)


def parse_deal(title: str, summary: str, default_origin: str = "EU*") -> ParsedDeal | None:
    title_c = clean(title)
    summary_c = clean(summary)[:900]
    text = f"{title_c} . {summary_c}"
    notes: list[str] = []
    confidence = 0.9

    prices = find_prices(title_c)
    if not prices:
        prices = find_prices(summary_c[:400])
        confidence -= 0.15
        if prices:
            notes.append("price taken from description")
    if not prices:
        return None
    price = prices[0]
    # "from €499 ... (€528 with luggage)": first price is the headline price

    # Origin: explicit "from X" in title, then summary, then the source market default
    origins = _find_origins(title_c) or _find_origins(summary_c[:500])
    explicit_origin = bool(origins)
    dest = _dest_after_origin(title_c, origins) or _dest_after_origin(summary_c[:500], origins)
    if dest is None and _CRUISE.search(title_c):
        port = find_port(text)
        if port:  # e.g. "Mediterranean cruise from Barcelona": the itinerary starts at the port
            dest = Place(port.key, f"{port.name} cruise", port.country, port.region, port.lat, port.lon, port.airport)
    if dest is None:
        return None

    if _CRUISE.search(title_c) and not re.search(r"flights? from|flüge ab|loty z", text, re.I):
        origins = []  # for cruises the departure market is the user's; the port is handled separately
    if origins:
        codes = [o.key for o in origins][:6]
        label = " / ".join(o.name for o in origins[:3]) + (f" +{len(origins) - 3}" if len(origins) > 3 else "")
    else:
        codes = [default_origin]
        label = COUNTRY_ORIGINS.get(default_origin, ("Europe (various)",))[0]
        confidence -= 0.1
        notes.append("departure airport inferred from source market")

    # Non-European origin (e.g. "Bangkok to Oslo") -> not relevant, unless a European origin exists.
    # Cruises are exempt: "from Miami" names the embarkation port, and flights there are added to the trip cost.
    cruise_title = bool(_CRUISE.search(title_c))
    m_from = _FROM_TO.search(title_c)
    if not cruise_title and m_from and not _find_origins(m_from.group(2)) and (
            find_places(m_from.group(2), "dest") or _NON_EU.search(m_from.group(2))):
        return None
    if not cruise_title and re.search(r"\b(from|von|ab|z|iš|da)\s+(l\.a\.|los angeles|new york|bangkok|dubai|singapore|tokyo|miami|sydney)",
                                      title_c, re.I):
        return None
    # "Loty z Tajlandii do Europy", "Flights from Hanoi, Vietnam to Barcelona": departs outside Europe
    for m in ([] if cruise_title else re.finditer(r"\b(from|von|ab|z|ze|iš|da)\s+([^\s,.;:!()]+(?:\s+[^\s,.;:!()]+)?)", title_c, re.I)):
        seg = m.group(2)
        hits = find_places(seg, "dest")
        if hits and REGIONS[hits[0][2].region]["long_haul"] and not _find_origins(seg):
            return None

    trip_type = "one_way" if _ONE_WAY.search(text) and not _RETURN.search(title_c) else "return"
    cabin = "economy"
    if _FIRST.search(title_c):
        cabin = "first"
    elif _BUSINESS.search(title_c):
        cabin = "business"
    elif _PREMIUM.search(title_c):
        cabin = "premium"

    nights = None
    nm = _NIGHTS.search(title_c) or _NIGHTS.search(summary_c[:500])
    if nm:
        n = int(nm.group(1))
        unit = nm.group(0).lower()
        if any(u in unit for u in ("day", "dni", "tage", "dien", "giorn")):
            n = max(n - 1, 1)
        if 1 <= n <= 30:
            nights = n
    elif _WEEK.search(text):
        nights = 7

    stars = None
    sm = _STARS_EMOJI.search(title_c) or _STARS_EMOJI.search(summary_c[:400])
    if sm and 2 <= int(sm.group(1)) <= 5:
        stars = int(sm.group(1))
    else:
        run = _STAR_RUN.search(title_c)
        if run:
            stars = min(5, len(re.findall(r"⭐|★", run.group(1))))

    board = ""
    for label_b, rx in _BOARD:
        if rx.search(text):
            board = label_b
            break

    baggage = "included" if _BAG_INC.search(text) else ("excluded" if _BAG_EXC.search(text) else "unknown")

    is_cruise = bool(_CRUISE.search(title_c))
    per_night = bool(_PER_NIGHT.search(title_c[price.end: price.end + 14]))
    has_package_words = bool(_PACKAGE.search(title_c)) or nights is not None or bool(board)
    has_flight_words = bool(_FLIGHT.search(title_c))
    is_bus = bool(_BUS.search(text)) and not has_flight_words
    if is_bus:
        return None  # coach tours are out of scope
    # an explicit departure airport city ("z Poznania", "ab Wien") on a holiday offer means a flight package
    flights_stated = bool(_FLIGHTS_INCL.search(text)) or has_flight_words
    flights_included = flights_stated or explicit_origin

    if _DEPOSIT.search(title_c[max(0, price.start - 18): price.start]):  # "deposit €99", "Anzahlung 99 €"
        confidence -= 0.25
        notes.append("headline price may be a deposit – check the full price")

    if per_night:
        return None  # standalone hotel deals are out of scope
    if is_cruise:
        subtype = "cruise"
    elif has_package_words and (nights or board or stars or not has_flight_words):
        if not flights_included:
            return None  # HubFare packages must include flights + accommodation
        if not flights_stated:
            confidence -= 0.1
            notes.append("flights inferred from the departure city, not stated – check inclusion")
        subtype = "package"
    elif has_flight_words:
        subtype = "flight"
    else:
        return None  # a stay without flights, or unclear item

    cruise_port = None
    if is_cruise:
        cruise_port = find_port(text)
        if cruise_port is None:
            notes.append("embarkation port not identified")
            confidence -= 0.1

    if subtype == "package" and not nights:
        nights = 7 if re.search(r"(week|tydzie|woche|savait)", text, re.I) else None
        if nights is None:
            confidence -= 0.1
            notes.append("number of nights not stated")

    basis = "per_person"
    if per_night:
        basis = "per_night"
    elif _TOTAL_FOR_TWO.search(title_c[max(0, price.start - 30): price.end + 30]):
        basis = "total"
    elif subtype in ("package", "cruise") and not _PER_PERSON.search(text):
        notes.append("assumed per-person pricing (agency convention)")
        confidence -= 0.05

    luxury_signal = bool(stars == 5 or cabin in ("business", "first") or _LUX_BRAND.search(title_c))
    last_minute = bool(_LAST_MINUTE.search(text))
    wm = _WINDOW.search(summary_c) or _WINDOW.search(title_c)

    return ParsedDeal(
        title=title_c, price_amount=price.amount, currency=price.currency, price_basis=basis,
        origin_codes=codes, origin_label=label, dest=dest, trip_type=trip_type, cabin=cabin,
        nights=nights, stars=stars, board=board, baggage=baggage, subtype=subtype,
        error_keyword=bool(_ERROR.search(text)), luxury_signal=luxury_signal, last_minute=last_minute,
        cruise_port=cruise_port, fly_cruise_package=bool(is_cruise and _FLY_CRUISE.search(text)),
        travel_window=wm.group(1)[:60] if wm else "", confidence=max(0.2, round(confidence, 2)), notes=notes,
    )


def dest_by_key(key: str) -> Place | None:
    return DEST_PLACES.get(key)


def origin_by_code(code: str) -> Place | None:
    return ORIGIN_PLACES.get(code)
