"""Cruises + Flights: embarkation ports and complete-trip cost estimation.

A cheap cruise is only a deal if the *whole trip* is cheap. For independently
booked combinations we add: return flight to the port (cheapest observed fare
in our database for that port's region, else the regional reference fare),
mandatory fees / gratuities (if not stated as included), transfers, and one
pre-cruise hotel night (recommended when flying in on the day is risky).
Fly-and-cruise packages that include flights are treated as protected packages
and only gratuities are added.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .geo import REGIONS


@dataclass
class Port:
    key: str
    name: str
    country: str
    region: str          # REGIONS key used for flight cost to reach the port
    airport: str
    lat: float
    lon: float
    aliases: tuple


PORTS = [
    Port("southampton", "Southampton", "United Kingdom", "europe", "LON", 50.90, -1.40, ("southampton",)),
    Port("hamburg", "Hamburg", "Germany", "europe", "HAM", 53.55, 9.99, ("hamburg",)),
    Port("kiel", "Kiel", "Germany", "europe", "HAM", 54.32, 10.14, ("kiel", "kilonii")),
    Port("warnemuende", "Rostock-Warnemünde", "Germany", "europe", "BER", 54.18, 12.09, ("warnemünde", "warnemuende", "rostock")),
    Port("copenhagen", "Copenhagen", "Denmark", "europe", "CPH", 55.68, 12.57, ("copenhagen", "kopenhag", "kopenhaga")),
    Port("amsterdam", "Amsterdam", "Netherlands", "europe", "AMS", 52.37, 4.90, ("amsterdam",)),
    Port("barcelona", "Barcelona", "Spain", "europe", "BCN", 41.38, 2.17, ("barcelona", "barcelony")),
    Port("civitavecchia", "Rome (Civitavecchia)", "Italy", "europe", "FCO", 42.09, 11.80, ("civitavecchia", "rome", "rom", "rzym")),
    Port("genoa", "Genoa", "Italy", "europe", "GOA", 44.41, 8.93, ("genoa", "genua", "genova")),
    Port("savona", "Savona", "Italy", "europe", "GOA", 44.31, 8.48, ("savona",)),
    Port("venice", "Venice / Trieste", "Italy", "europe", "VCE", 45.44, 12.33, ("venice", "venedig", "wenecj", "trieste", "triest")),
    Port("piraeus", "Athens (Piraeus)", "Greece", "europe", "ATH", 37.94, 23.65, ("piraeus", "pireus", "athens", "aten")),
    Port("lisbon", "Lisbon", "Portugal", "europe", "LIS", 38.71, -9.14, ("lisbon", "lissabon", "lizbon")),
    Port("marseille", "Marseille", "France", "europe", "MRS", 43.30, 5.37, ("marseille", "marsylii")),
    Port("palma", "Palma de Mallorca", "Spain", "europe", "PMI", 39.57, 2.65, ("palma", "mallorca", "majork")),
    Port("istanbul", "Istanbul", "Turkey", "europe", "IST", 41.01, 28.98, ("istanbul", "stambuł")),
    Port("stockholm", "Stockholm", "Sweden", "europe", "ARN", 59.33, 18.07, ("stockholm", "sztokholm")),
    Port("tenerife", "Canary Islands", "Spain", "canaries_nafrica", "TFS", 28.46, -16.25, ("tenerife", "teneryf", "gran canaria", "las palmas", "kanaren", "canary")),
    Port("dubai", "Dubai", "UAE", "middle_east", "DXB", 25.27, 55.29, ("dubai", "dubaj", "abu dhabi")),
    Port("miami", "Miami / Fort Lauderdale", "United States", "na_east", "MIA", 25.77, -80.17, ("miami", "fort lauderdale", "port canaveral", "orlando")),
    Port("newyork", "New York", "United States", "na_east", "NYC", 40.71, -74.01, ("new york", "nowy jork")),
    Port("singapore", "Singapore", "Singapore", "se_asia", "SIN", 1.26, 103.82, ("singapore", "singapur")),
    Port("hongkong", "Hong Kong", "Hong Kong", "china_hk", "HKG", 22.29, 114.17, ("hong kong",)),
    Port("tokyo", "Tokyo / Yokohama", "Japan", "east_asia", "TYO", 35.45, 139.64, ("yokohama", "tokyo", "tokio")),
    Port("sydney", "Sydney", "Australia", "oceania", "SYD", -33.86, 151.21, ("sydney",)),
    Port("buenosaires", "Buenos Aires", "Argentina", "south_america", "BUE", -34.60, -58.37, ("buenos aires",)),
    Port("rio", "Rio de Janeiro", "Brazil", "south_america", "RIO", -22.90, -43.17, ("rio de janeiro", "santos")),
    Port("capetown", "Cape Town", "South Africa", "southern_africa", "CPT", -33.91, 18.42, ("cape town", "kapstadt", "kapsztad")),
    Port("mauritius", "Port Louis", "Mauritius", "indian_ocean", "MRU", -20.16, 57.50, ("mauritius", "port louis")),
    Port("seychelles", "Mahé", "Seychelles", "indian_ocean", "SEZ", -4.62, 55.45, ("seychelles", "seychellen", "mahé", "mahe")),
    Port("maldives", "Malé", "Maldives", "indian_ocean", "MLE", 4.18, 73.51, ("maldives", "malediven", "malediw")),
    Port("caribbean", "Caribbean (San Juan / Barbados / Guadeloupe)", "Caribbean", "caribbean", "SJU", 18.47, -66.11,
         ("san juan", "barbados", "bridgetown", "guadeloupe", "martinique", "karibik", "caribbean", "karaib")),
    Port("dover", "Dover", "United Kingdom", "europe", "LGW", 51.12, 1.31, ("dover",)),
    Port("valencia", "Valencia", "Spain", "europe", "VLC", 39.45, -0.32, ("valencia", "walencj")),
    Port("naples", "Naples", "Italy", "europe", "NAP", 40.84, 14.26, ("naples", "napoli", "neapel", "neapol")),
    Port("split", "Split", "Croatia", "europe", "SPU", 43.51, 16.44, ("split",)),
    Port("dubrovnik", "Dubrovnik", "Croatia", "europe", "DBV", 42.65, 18.09, ("dubrovnik",)),
    Port("vancouver", "Vancouver / Seattle (Alaska)", "Canada", "na_west", "YVR", 49.29, -123.11, ("vancouver", "seattle", "alaska")),
]

_PORT_RX = [(re.compile(rf"(?<!\w){re.escape(a)}\w{{0,3}}(?!\w)", re.I), p) for p in PORTS for a in p.aliases]
_FROM_RX = re.compile(r"(?:from|ab|z|iš|da|departing)\s+([^,.;:()]{3,40})", re.I)


_FROM_TO_PORTS = re.compile(r"(?:from|ab|von|z|iš|da)\s+([^,.;:()]{3,40}?)\s+(?:to|nach|bis|do|į|a)\s+([^,.;:()]{3,40})", re.I)


def _port_in(seg: str) -> Port | None:
    for rx, p in _PORT_RX:
        if rx.search(seg):
            return p
    return None


def find_ports(text: str) -> tuple[Port | None, Port | None]:
    """(embarkation, disembarkation). Disembarkation is None for round trips or when not stated."""
    for m in _FROM_TO_PORTS.finditer(text):
        a, b = _port_in(m.group(1)), _port_in(m.group(2))
        if a and b and a.key != b.key:
            return a, b
    return find_port(text), None


ONE_WAY_SHARE = 0.55  # a one-way ticket typically costs a little more than half a return


def _flights_to_ports(port: Port | None, end_port: Port | None, text: str, cheapest_return: float | None,
                      origin_country: str) -> tuple[float, str]:
    uplift = 1.08 if origin_country in ("LT", "LV", "EE") else 1.0
    region = port.region if port else "europe"
    out_ret = (cheapest_return or REGIONS[region]["ref_return"] * uplift)
    if end_port and end_port.key != (port.key if port else None):
        back_ret = REGIONS[end_port.region]["ref_return"] * uplift
        return (out_ret * ONE_WAY_SHARE + back_ret * ONE_WAY_SHARE,
                f"One-way to {port.airport if port else '?'} + one-way home from {end_port.airport}")
    if _REPOSITION.search(text):
        # ends somewhere else, but the second port is not stated: assume another continent
        return out_ret * ONE_WAY_SHARE * 2, "Two one-way flights (repositioning, end port not stated)"
    return out_ret, f"Return flight to/from port{' – ' + port.airport if port else ' – port unknown, Europe assumed'}"


def find_port(text: str) -> Port | None:
    """Prefer a port named right after 'from/ab/z' (embarkation); otherwise the first port mentioned."""
    for m in _FROM_RX.finditer(text):
        seg = m.group(1)
        for rx, p in _PORT_RX:
            if rx.search(seg):
                return p
    first = None
    for rx, p in _PORT_RX:
        m = rx.search(text)
        if m and (first is None or m.start() < first[0]):
            first = (m.start(), p)
    return first[1] if first else None


_INCL_FEES = re.compile(r"(gratuities included|tips included|trinkgeld inklusive|inkl\.? trinkgeld|napiwki w cenie|service charges included|"
                        r"incl\.? gratuities|all[- ]inclusive)", re.I)
_REPOSITION = re.compile(r"(reposition\w*|transatlantic|transatlantik|transatlantyk|überführung|one[- ]way cruise)", re.I)

GRATUITY_PER_DAY = 14.0
TRANSFER_EUR = 40.0
HOTEL_NIGHT_EUR = 95.0


def complete_trip_cost(cruise_price_pp: float, nights: int | None, port: Port | None, fly_cruise: bool,
                       text: str, cheapest_flight_to_region: float | None, origin_country: str = "",
                       end_port: Port | None = None) -> dict:
    n = nights or 7
    parts = [{"label": "Cruise fare (per person)", "eur": round(cruise_price_pp, 2), "source": "offer"}]
    if not _INCL_FEES.search(text):
        parts.append({"label": f"Gratuities / service charges ({n} days × €{GRATUITY_PER_DAY:.0f})",
                      "eur": GRATUITY_PER_DAY * n, "source": "estimate"})
    if fly_cruise:
        kind = "fly_cruise_package"
        parts.append({"label": "Flights", "eur": 0.0, "source": "included in package"})
        parts.append({"label": "Transfers", "eur": 0.0, "source": "usually included – check offer"})
    else:
        kind = "independent_combination"
        flight, label = _flights_to_ports(port, end_port, text, cheapest_flight_to_region, origin_country)
        parts.append({
            "label": label,
            "eur": round(flight, 2),
            "source": "cheapest observed fare in database" if cheapest_flight_to_region else "regional reference fare",
        })
        parts.append({"label": "Airport ↔ port transfers", "eur": TRANSFER_EUR, "source": "estimate"})
        parts.append({"label": "Pre-cruise hotel night (½ double room)", "eur": HOTEL_NIGHT_EUR / 2, "source": "estimate"})
    total = round(sum(p["eur"] for p in parts), 2)
    return {"kind": kind, "parts": parts, "total_pp": total, "nights": n,
            "port": port.name if port else None, "port_region": port.region if port else None,
            "end_port": end_port.name if end_port else None}


_LUXURY_LINE = re.compile(r"(scenic|regent|silversea|seabourn|explora|ritz-carlton yacht|crystal|ponant|oceania cruises|"
                          r"windstar|four seasons yacht|luxury cruise)", re.I)


def cruise_night_reference(text: str) -> tuple[float, str]:
    if _LUXURY_LINE.search(text):
        return 400.0, "luxury line"
    if _REPOSITION.search(text):
        return 60.0, "repositioning / transatlantic"
    return 95.0, "standard cruise"


def cruise_reference_total(port: Port | None, nights: int | None, fly_cruise: bool, origin_country: str = "",
                           text: str = "", end_port: Port | None = None) -> float:
    """What a *normal* complete trip of this shape costs per person."""
    n = nights or 7
    per_night, _ = cruise_night_reference(text)
    cruise_normal = per_night * n  # typical inside/ocean-view cabin, per person per night incl. port taxes
    fees = GRATUITY_PER_DAY * n
    flight, _ = _flights_to_ports(port, end_port, text, None, origin_country)
    if fly_cruise:
        return round(cruise_normal + fees + flight, 2)
    return round(cruise_normal + fees + flight + TRANSFER_EUR + HOTEL_NIGHT_EUR / 2, 2)
