"""Getting from your home hub to the departure airport of a deal.

Every deal is judged as a trip that starts at one of your home hubs (default Vienna,
Vilnius, Warsaw, Riga):

* departs from a home hub ............ no extra cost
* departs within NEARBY_KM of a hub .. "nearby" – reachable by train/bus, no flight added
* departs further away (e.g. Stockholm → Thailand) .. the cheapest return flight
  hub ⇄ departure airport is added, and the deal is scored on the combined total.

Positioning fares come from the Travelpayouts Data API (refreshed twice a day, no network
calls during scoring). Without a token, a distance-based estimate is used and labelled
"estimated".
"""
from __future__ import annotations

import logging
import math
import time
from datetime import timedelta

import httpx

from . import config as C
from .db import Airport, PositioningFare, Setting, session_scope, utcnow
from .geo import COUNTRY_ORIGINS, ORIGIN_PLACES

log = logging.getLogger(__name__)

DEFAULT_HOME = ["VIE", "VNO", "WAW", "RIX"]
DEFAULT_NEARBY_KM = 300
# country-wide "various airports" origins → the airport you would most likely fly into
COUNTRY_GATEWAY = {"GB*": "LON", "DE*": "MUC", "IT*": "MXP"}
TP_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def ground_return(distance_km: float) -> float:
    """Train/bus to a nearby airport and back (estimate)."""
    return round((15 + 0.15 * distance_km) / 5) * 5


HOTEL_NIGHT = 60  # night near the departure airport before a long-haul flight on a separate ticket


def estimate_return(distance_km: float) -> float:
    """Typical low-cost return fare inside Europe for that distance (deliberately not optimistic)."""
    return round((30 + 0.07 * distance_km) / 5) * 5


def home_settings(s) -> tuple[list[str], int]:
    row = s.get(Setting, "preferences")
    v = (row.value or {}) if row else {}
    homes = [h for h in (v.get("home_airports") or DEFAULT_HOME) if h in ORIGIN_PLACES]
    return homes or DEFAULT_HOME, int(v.get("nearby_km") or DEFAULT_NEARBY_KM)


def _coords(code: str) -> tuple[float, float] | None:
    if code in ORIGIN_PLACES:
        p = ORIGIN_PLACES[code]
        return p.lat, p.lon
    if code in COUNTRY_GATEWAY and COUNTRY_GATEWAY[code] in ORIGIN_PLACES:
        p = ORIGIN_PLACES[COUNTRY_GATEWAY[code]]
        return p.lat, p.lon
    if code in COUNTRY_ORIGINS:
        _, lat, lon = COUNTRY_ORIGINS[code]
        return lat, lon
    return None


def dated_key(hub: str, gateway: str, depart: str, ret: str) -> str:
    return f"{hub}-{gateway}-{depart}-{ret}"


def _day_before(iso: str) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(iso[:10]) - timedelta(days=1)).isoformat()


def plan(s, origin_code: str, origin_codes: list[str] | None = None, long_haul: bool = False,
         depart: str = "", ret: str = "") -> dict | None:
    """How you get from home to this deal's departure airport. None = departure unknown (EU*)."""
    homes, nearby_km = home_settings(s)
    codes = [c for c in (origin_codes or [origin_code]) if c] or [origin_code]
    if set(codes) & set(homes):
        hub = next(c for c in codes if c in homes)
        return {"mode": "home", "hub": hub, "hub_name": ORIGIN_PLACES[hub].name, "price": 0}
    if origin_code == "EU*":
        return None
    best = None
    for code in codes:
        xy = _coords(code)
        if not xy:
            continue
        gateway = COUNTRY_GATEWAY.get(code, code)
        for h in homes:
            d = km((ORIGIN_PLACES[h].lat, ORIGIN_PLACES[h].lon), xy)
            if d <= nearby_km:
                g = ground_return(d)
                cand = {"mode": "nearby", "hub": h, "hub_name": ORIGIN_PLACES[h].name, "km": round(d), "price": g,
                        "estimated": True,
                        "note": f"{round(d)} km from {ORIGIN_PLACES[h].name} – train/bus ≈ €{g} return"}
            else:
                fare = s.get(PositioningFare, f"{h}-{gateway}")
                dated = s.get(PositioningFare, dated_key(h, gateway, depart, ret)) if depart else None
                if dated and dated.price_eur:
                    cand = {"mode": "flight", "hub": h, "hub_name": ORIGIN_PLACES[h].name, "gateway": gateway,
                            "km": round(d), "price": round(dated.price_eur), "airline": dated.airline,
                            "dates": f"{dated.depart_date} – {dated.return_date}", "estimated": False, "date_matched": True}
                elif fare and fare.price_eur:
                    cand = {"mode": "flight", "hub": h, "hub_name": ORIGIN_PLACES[h].name, "gateway": gateway,
                            "km": round(d), "price": round(fare.price_eur), "airline": fare.airline,
                            "dates": f"{fare.depart_date} – {fare.return_date}".strip(" –"), "estimated": False}
                else:
                    cand = {"mode": "flight", "hub": h, "hub_name": ORIGIN_PLACES[h].name, "gateway": gateway,
                            "km": round(d), "price": estimate_return(d), "estimated": True}
                gname = ORIGIN_PLACES[gateway].name if gateway in ORIGIN_PLACES else gateway
                cand["gateway_name"] = gname
                cand["flight_price"] = cand["price"]
                cand["note"] = (f"Return flight {cand['hub_name']} ⇄ {gname} "
                                f"{'≈ ' if cand['estimated'] else ''}€{cand['price']} on a separate ticket")
                if cand.get("date_matched"):
                    cand["note"] += f" – matched to your dates ({cand['dates']}, {cand['airline']})"
                elif dated is not None:
                    cand["note"] += " – no fare found on matching dates yet, typical fare used"
                if long_haul:
                    cand["hotel"] = HOTEL_NIGHT
                    cand["price"] += HOTEL_NIGHT
                    cand["note"] += f" + ≈ €{HOTEL_NIGHT} hotel night (arrive the day before)"
            if best is None or cand["price"] < best["price"]:
                best = cand
    return best


def refresh(limit_calls: int = 120) -> dict:
    """Fetch the cheapest real return fare between each home hub and every other enabled airport."""
    out = {"calls": 0, "saved": 0}
    if not C.TRAVELPAYOUTS_TOKEN:
        out["skipped"] = "needs TRAVELPAYOUTS_TOKEN (using distance estimates)"
        return out
    with session_scope() as s:
        homes, nearby_km = home_settings(s)
        gateways = {a.iata for a in s.query(Airport).filter(Airport.enabled).all()} | set(COUNTRY_GATEWAY.values())
    pairs = []
    for h in homes:
        hp = ORIGIN_PLACES[h]
        for g in sorted(gateways - set(homes)):
            gp = ORIGIN_PLACES.get(g)
            if gp and km((hp.lat, hp.lon), (gp.lat, gp.lon)) > nearby_km:
                pairs.append((h, g))
    with httpx.Client(timeout=20, headers={"User-Agent": C.USER_AGENT}) as c:
        for h, g in pairs[:limit_calls]:
            try:
                r = c.get(TP_URL, params={"origin": h, "destination": g, "currency": "eur", "one_way": "false",
                                          "sorting": "price", "limit": 1, "page": 1},
                          headers={"X-Access-Token": C.TRAVELPAYOUTS_TOKEN})
                out["calls"] += 1
                if r.status_code == 429:
                    time.sleep(5)
                    continue
                r.raise_for_status()
                data = r.json().get("data", [])
            except Exception as e:
                log.warning("positioning %s-%s failed: %s", h, g, e)
                continue
            with session_scope() as s:
                row = s.get(PositioningFare, f"{h}-{g}") or PositioningFare(key=f"{h}-{g}", hub=h, gateway=g)
                if data:
                    t = data[0]
                    row.price_eur = float(t["price"])
                    row.airline = t.get("airline", "")
                    row.depart_date = (t.get("departure_at") or "")[:10]
                    row.return_date = (t.get("return_at") or "")[:10]
                    out["saved"] += 1
                else:
                    row.price_eur = None
                row.fetched_at = utcnow()
                s.merge(row)
            time.sleep(0.4)
    return out


def _cheapest_one_way(c: httpx.Client, org: str, dst: str, day: str) -> dict | None:
    r = c.get(TP_URL, params={"origin": org, "destination": dst, "departure_at": day, "currency": "eur",
                              "one_way": "true", "sorting": "price", "limit": 1, "page": 1},
              headers={"X-Access-Token": C.TRAVELPAYOUTS_TOKEN})
    if r.status_code == 429:
        time.sleep(5)
        return None
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0] if data else None


def refresh_dated(limit_offers: int = 25) -> dict:
    """For the best deals with exact dates: price hub → departure airport the day before departure,
    and departure airport → hub on the return day (two one-way tickets), then re-score them."""
    from .db import Offer
    out = {"offers": 0, "calls": 0, "matched": 0}
    if not C.TRAVELPAYOUTS_TOKEN:
        out["skipped"] = "needs TRAVELPAYOUTS_TOKEN"
        return out
    today = utcnow().strftime("%Y-%m-%d")
    with session_scope() as s:
        rows = (s.query(Offer).filter(Offer.status == "active", Offer.deal_score >= 75, Offer.depart_date > today,
                                      Offer.return_date != "", Offer.duplicate_of.is_(None))
                .order_by(Offer.deal_score.desc()).limit(limit_offers * 3).all())
        todo = []
        for o in rows:
            pos = (o.score_breakdown or {}).get("positioning") or {}
            if pos.get("mode") != "flight" or pos.get("date_matched"):
                continue
            key = dated_key(pos["hub"], pos["gateway"], o.depart_date, o.return_date)
            row = s.get(PositioningFare, key)
            if row and row.fetched_at > utcnow() - timedelta(hours=24):
                continue
            todo.append((o.id, pos["hub"], pos["gateway"], o.depart_date, o.return_date, key))
    done = []
    with httpx.Client(timeout=20, headers={"User-Agent": C.USER_AGENT}) as c:
        for oid, hub, gw, dep, ret, key in todo[:limit_offers]:
            try:
                out_leg = _cheapest_one_way(c, hub, gw, _day_before(dep))
                back_leg = _cheapest_one_way(c, gw, hub, ret[:10]) if out_leg else None
                out["calls"] += 2 if out_leg else 1
            except Exception as e:
                log.warning("dated positioning %s failed: %s", key, e)
                continue
            with session_scope() as s:
                row = s.get(PositioningFare, key) or PositioningFare(key=key, hub=hub, gateway=gw)
                if out_leg and back_leg:
                    row.price_eur = float(out_leg["price"]) + float(back_leg["price"])
                    row.airline = "/".join(sorted({out_leg.get("airline", ""), back_leg.get("airline", "")} - {""}))
                    row.depart_date, row.return_date = _day_before(dep), ret[:10]
                    out["matched"] += 1
                else:
                    row.price_eur = None  # remembered as "no fare on these dates"
                row.fetched_at = utcnow()
                s.merge(row)
            done.append(oid)
            out["offers"] += 1
            time.sleep(0.4)
    if done:
        from .scanner import rescore_offer
        with session_scope() as s:
            for o in s.query(Offer).filter(Offer.id.in_(done)).all():
                rescore_offer(s, o)
    return out
