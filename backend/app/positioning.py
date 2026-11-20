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
         depart: str = "", ret: str = "", homes: list[str] | None = None) -> dict | None:
    """How you get from home to this deal's departure airport. None = departure unknown (EU*).
    `homes` overrides the home hubs, e.g. to price everything from one airport the user picked."""
    default_homes, nearby_km = home_settings(s)
    homes = [h for h in (homes or default_homes) if h in ORIGIN_PLACES] or default_homes
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
                            "dates": f"{dated.depart_date} – {dated.return_date}", "estimated": False, "date_matched": True,
                            "hotel_nights": dated.hotel_nights or 0, "connection": dated.detail}
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
                    cand["note"] += f" – {cand['connection'] or 'matched to your dates'} ({cand['airline']})"
                    nights = cand["hotel_nights"]
                elif dated is not None:
                    cand["note"] += " – no fare found on matching dates yet, typical fare used"
                    nights = 1 if long_haul else 0
                else:
                    nights = 1 if long_haul else 0
                if nights:
                    cand["hotel"] = HOTEL_NIGHT * nights
                    cand["price"] += HOTEL_NIGHT * nights
                    cand["note"] += f" + ≈ €{HOTEL_NIGHT * nights} for {nights} hotel night{'s' if nights > 1 else ''}"
                elif cand.get("date_matched"):
                    cand["same_day"] = True
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


def _one_ways(c: httpx.Client, org: str, dst: str, day: str, limit: int = 10) -> list[dict]:
    """Cheapest one-way fares on one day (several, so we can choose by time)."""
    r = c.get(TP_URL, params={"origin": org, "destination": dst, "departure_at": day, "currency": "eur",
                              "one_way": "true", "sorting": "price", "limit": limit, "page": 1},
              headers={"X-Access-Token": C.TRAVELPAYOUTS_TOKEN})
    if r.status_code == 429:
        time.sleep(5)
        return []
    r.raise_for_status()
    return r.json().get("data", []) or []


def _cheapest_one_way(c: httpx.Client, org: str, dst: str, day: str) -> dict | None:
    data = _one_ways(c, org, dst, day, limit=1)
    return data[0] if data else None


def _dt(iso: str):
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def _leg_times(t: dict):
    dep = _dt(t.get("departure_at", ""))
    minutes = t.get("duration_to") or t.get("duration")
    arr = dep + timedelta(minutes=int(minutes)) if dep and minutes else None
    return dep, arr


def pick_outbound(same_day: list[dict], main_depart_iso: str, min_connect_h: float) -> dict | None:
    """Cheapest hub → gateway flight that lands at least `min_connect_h` before the main flight leaves."""
    main = _dt(main_depart_iso)
    if not main:
        return None
    ok = []
    for t in same_day:
        _, arr = _leg_times(t)
        if arr and arr <= main - timedelta(hours=min_connect_h):
            ok.append(t)
    return min(ok, key=lambda t: float(t["price"])) if ok else None


def pick_return(same_day: list[dict], main_arrive_iso: str, min_connect_h: float) -> dict | None:
    """Cheapest gateway → hub flight leaving at least `min_connect_h` after the main return flight lands."""
    main = _dt(main_arrive_iso)
    if not main:
        return None
    ok = []
    for t in same_day:
        dep, _ = _leg_times(t)
        if dep and dep >= main + timedelta(hours=min_connect_h):
            ok.append(t)
    return min(ok, key=lambda t: float(t["price"])) if ok else None


def _hhmm(iso: str) -> str:
    d = _dt(iso)
    return d.strftime("%H:%M") if d else ""


def refresh_dated(limit_offers: int = 25) -> dict:
    """For the best deals with exact dates, build the trip from your hub on separate tickets:
    a same-day connection when there is at least MIN_CONNECTION_HOURS between flights, otherwise the evening
    before / the day after with a hotel night. Then re-score those deals."""
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
            todo.append((o.id, pos["hub"], pos["gateway"], o.depart_date, o.return_date, key,
                         o.depart_at or "", o.back_arrive_at or ""))
    done = []
    with httpx.Client(timeout=20, headers={"User-Agent": C.USER_AGENT}) as c:
        for oid, hub, gw, dep, ret, key, dep_at, back_at in todo[:limit_offers]:
            try:
                nights, parts = 0, []
                # outbound: same day with a safe transfer, else the evening before (+ hotel night)
                out_leg = pick_outbound(_one_ways(c, hub, gw, dep[:10]), dep_at, C.MIN_CONNECTION_HOURS) if dep_at else None
                out["calls"] += 1 if dep_at else 0
                if out_leg:
                    lands = _leg_times(out_leg)[1].astimezone(_dt(dep_at).tzinfo)  # local time at the transfer airport
                    parts.append(f"same-day connection: lands {lands:%H:%M}, "
                                 f"main flight {_hhmm(dep_at)}")
                else:
                    out_leg = _cheapest_one_way(c, hub, gw, _day_before(dep))
                    out["calls"] += 1
                    nights += 1
                    parts.append("fly in the day before")
                # return: same day after landing, else next day (+ hotel night)
                back_day = (back_at or ret)[:10]
                back_leg = None
                if out_leg and back_at:
                    back_leg = pick_return(_one_ways(c, gw, hub, back_day), back_at, C.MIN_CONNECTION_HOURS)
                    out["calls"] += 1
                    if back_leg:
                        parts.append(f"home same day at {_hhmm(back_leg.get('departure_at', ''))}")
                if out_leg and not back_leg:
                    nd = back_day if not back_at else (_dt(back_at) + timedelta(days=1)).date().isoformat()
                    back_leg = _cheapest_one_way(c, gw, hub, nd)
                    out["calls"] += 1
                    if back_at:
                        nights += 1
                        parts.append("home the next day")
            except Exception as e:
                log.warning("dated positioning %s failed: %s", key, e)
                continue
            with session_scope() as s:
                row = s.get(PositioningFare, key) or PositioningFare(key=key, hub=hub, gateway=gw)
                if out_leg and back_leg:
                    row.price_eur = float(out_leg["price"]) + float(back_leg["price"])
                    row.airline = "/".join(sorted({out_leg.get("airline", ""), back_leg.get("airline", "")} - {""}))
                    row.depart_date = (out_leg.get("departure_at") or _day_before(dep))[:10]
                    row.return_date = (back_leg.get("departure_at") or ret)[:10]
                    row.hotel_nights = nights
                    row.detail = "; ".join(parts)[:240]
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
