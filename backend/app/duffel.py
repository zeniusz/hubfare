"""Live price re-check of the best flight deals against airline inventory (Duffel API).

Travelpayouts tells us *where* fares are cheap (cached prices found by Aviasales users).
Duffel then asks the airlines directly for the same route and dates, so a deal is only
marked "confirmed" when the price is really bookable right now. Nothing is ever booked.

Cost: Duffel bills searches beyond a 1,500:1 search-to-book ratio (≈ $0.005 each), so the
number of checks per day is capped by DUFFEL_MAX_CHECKS_PER_DAY.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

import httpx

from . import config as C
from .db import Offer, Setting, session_scope, utcnow
from .fx import to_eur

log = logging.getLogger(__name__)
API = "https://api.duffel.com/air/offer_requests"
TOLERANCE = 1.10  # live price within +10 % of the advertised price still counts as confirmed


def _budget_left(s) -> int:
    row = s.get(Setting, "duffel_usage")
    today = utcnow().strftime("%Y-%m-%d")
    used = row.value.get("count", 0) if row and row.value.get("day") == today else 0
    return max(0, C.DUFFEL_MAX_CHECKS_PER_DAY - used)


def _spend(s, n: int) -> None:
    row = s.get(Setting, "duffel_usage")
    today = utcnow().strftime("%Y-%m-%d")
    if not row:
        row = Setting(key="duffel_usage", value={})
        s.add(row)
    used = row.value.get("count", 0) if row.value.get("day") == today else 0
    row.value = {"day": today, "count": used + n}


def search(origin: str, dest: str, depart: str, ret: str, cabin: str = "economy") -> dict | None:
    """Cheapest live offer for a return trip, or None if no seats are offered."""
    slices = [{"origin": origin, "destination": dest, "departure_date": depart}]
    if ret:
        slices.append({"origin": dest, "destination": origin, "departure_date": ret})
    body = {"data": {"slices": slices, "passengers": [{"type": "adult"}], "cabin_class": cabin, "max_connections": 2}}
    r = httpx.post(API, params={"return_offers": "true", "supplier_timeout": 20000}, json=body, timeout=60,
                   headers={"Authorization": f"Bearer {C.DUFFEL_TOKEN}", "Duffel-Version": "v2",
                            "Accept": "application/json", "Content-Type": "application/json"})
    r.raise_for_status()
    offers = r.json().get("data", {}).get("offers", [])
    if not offers:
        return None
    best = min(offers, key=lambda o: to_eur(float(o["total_amount"]), o["total_currency"]))
    return {"price_eur": to_eur(float(best["total_amount"]), best["total_currency"]),
            "airline": (best.get("owner") or {}).get("name", ""),
            "stops": max(len(sl.get("segments", [])) - 1 for sl in best.get("slices", [{}]))}


def check_top_flights(limit: int = 25) -> dict:
    """Re-check the highest-scoring flight deals that have exact dates."""
    out = {"checked": 0, "confirmed": 0, "higher": 0, "unavailable": 0, "errors": 0}
    if not C.DUFFEL_TOKEN:
        out["skipped"] = "needs DUFFEL_TOKEN"
        return out
    today = utcnow().strftime("%Y-%m-%d")
    with session_scope() as s:
        n = min(limit, _budget_left(s))
        cutoff = utcnow() - timedelta(hours=12)
        rows = (s.query(Offer)
                .filter(Offer.status == "active", Offer.subtype == "flight", Offer.deal_score >= C.DUFFEL_MIN_SCORE,
                        Offer.dest_iata != "", Offer.depart_date > today, Offer.duplicate_of.is_(None))
                .filter((Offer.live_checked_at.is_(None)) | (Offer.live_checked_at < cutoff))
                .order_by(Offer.deal_score.desc()).limit(n).all())
        targets = [(o.id, o.origin_code, o.dest_iata, o.depart_date, o.return_date, o.cabin, o.price_eur) for o in rows]
    confirmed: list[int] = []
    for oid, org, dst, dep, ret, cabin, advertised in targets:
        try:
            res = search(org, dst, dep, ret, cabin)
        except Exception as e:
            log.warning("duffel check %s failed: %s", oid, e)
            out["errors"] += 1
            with session_scope() as s:
                _spend(s, 1)
            continue
        with session_scope() as s:
            _spend(s, 1)
            o = s.get(Offer, oid)
            o.live_checked_at = utcnow()
            if res is None:
                o.live_status, o.live_price_eur, o.live_detail = "unavailable", None, "No matching live offer (Duffel does not cover every airline)"
            else:
                o.live_price_eur = round(res["price_eur"], 2)
                stops = "direct" if res["stops"] == 0 else f"{res['stops']} stop(s)"
                o.live_detail = f"{res['airline']} · {stops}"[:200]
                o.live_status = "confirmed" if res["price_eur"] <= advertised * TOLERANCE else "higher"
            out[o.live_status] += 1
            from .scanner import rescore_offer
            rescore_offer(s, o)  # score, savings and total now use the live price
            if o.live_status == "confirmed":
                confirmed.append(o.id)
        out["checked"] += 1
        time.sleep(1.0)
    if confirmed:
        from . import notify
        out["alerts"] = notify.process_new_offers(confirmed)  # never sends the same deal twice
    return out
