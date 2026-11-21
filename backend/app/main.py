"""HubFare API + dashboard host.   uvicorn app.main:app --port 8000   (from backend/)"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select

from . import notify, scanner
from .config import EXCLUDED_ORIGIN_COUNTRIES, ROOT
from .db import (AlertRule, Airport, Notification, Offer, PriceHistory, Provider, ScanLog, Setting, WatchItem,
                 init_db, session_scope, utcnow)
from .geo import COUNTRY_ORIGINS, REGIONS
from .providers import PROVIDER_BY_KEY, UNAVAILABLE_SOURCES

app = FastAPI(title="HubFare", version="1.0")
FRONTEND = ROOT / "frontend"


@app.middleware("http")
async def _no_stale_ui(request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache"  # always pick up a new dashboard version
    return resp


@app.on_event("startup")
def _startup():
    init_db()
    scanner.ensure_seed()


# ------------------------------------------------------------------ helpers
def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _my_countries(s) -> set[str]:
    return {a.country for a in s.query(Airport).filter(Airport.enabled).all()}


def _relevant(o: Offer, my_codes: set[str], my_cc: set[str]) -> bool:
    codes = set(o.origin_codes or [o.origin_code])
    if codes & my_codes:
        return True
    if o.origin_code == "EU*":
        return o.subtype == "cruise"  # unknown departure airport is not "from your airports"
    if o.origin_code.endswith("*"):
        cc = o.origin_code[:2]
        return cc in my_cc or (cc == "DE" and "AT" in my_cc)
    return False


def _unresolved(o: Offer) -> bool:
    """Departure airport unknown: can't be priced from your city, so it never leads a list."""
    return o.origin_code == "EU*" and o.subtype != "cruise"


def _urgency(o: Offer) -> dict:
    b = o.score_breakdown or {}
    age_h = ((utcnow() - (o.published_at or o.first_seen_at)).total_seconds()) / 3600
    window_h = scanner.EXPIRY_DAYS.get(o.subtype, 14) * 24
    if o.error_fare_flag != "none":
        return {"level": "high", "label": "Error fares usually disappear within hours"}
    if b.get("last_minute"):
        return {"level": "high", "label": "Last-minute – limited availability"}
    if o.deal_score >= 90:
        return {"level": "medium", "label": "Unusually low price – these rarely last long"}
    if age_h > window_h * 0.6:
        return {"level": "medium", "label": f"Published {int(age_h // 24)} days ago – check availability"}
    return {"level": "low", "label": ""}


def _from_airport(s, o: Offer, d: dict, code: str) -> dict | None:
    """Re-price a deal as a trip starting at the airport the user picked (train/bus or connecting flight added).
    Deals with an unknown departure airport are skipped, except cruises (their flights are priced to the port)."""
    from . import positioning
    from .scanner import effective_price
    if o.origin_code == "EU*" and o.subtype != "cruise":
        return None
    b = o.score_breakdown or {}
    pos = positioning.plan(s, o.origin_code, o.origin_codes, REGIONS.get(o.dest_region, {}).get("long_haul", False),
                           o.depart_date or "", o.return_date or "", homes=[code])
    if o.subtype == "cruise":
        base = (b.get("trip_cost") or {}).get("total_pp") or o.price_eur
        extra = pos["price"] if pos and (b.get("trip_cost") or {}).get("kind") == "fly_cruise_package" else 0
    else:
        base = effective_price(o)
        extra = (pos["price"] if pos else 0) * (2 if o.price_basis == "total" else 1)
    d = dict(d)
    d["positioning"] = pos
    d["home_total"] = round(base + extra) if extra else None
    d["total"] = round(base + extra)
    d["picked_airport"] = code
    d["booking"] = _links(o, d)[:12]  # search links from the picked airport
    return d


def _links(o: Offer, d: dict) -> list[dict]:
    """Booking-search links: first the exact ones from the post, then HubFare-built searches."""
    from . import booking
    from .geo import DEST_PLACES
    if o.subtype != "flight":
        return []
    dest = o.dest_iata or (DEST_PLACES[o.dest_key].iata if o.dest_key in DEST_PLACES else "")
    pos = d.get("positioning") or {}
    # the airport the main flight leaves from: your hub (home), the nearby airport you reach by train, or the gateway
    lead = pos.get("hub") if pos.get("mode") == "home" else pos.get("gateway") or o.origin_code
    built = []
    if dest:
        origins = [c for c in (o.origin_codes or [o.origin_code]) if not c.endswith("*")]
        if not origins and pos.get("hub"):
            origins = [pos["hub"]]
        if lead and not lead.endswith("*"):
            origins = [lead] + [c for c in origins if c != lead]
        built = booking.build_links(origins, dest, o.depart_date or "", o.return_date or "", pos)
    post = booking.for_origin(o.booking_links or [], lead) if lead else (o.booking_links or [])
    if lead and post and built and not post[0].get("label", "").upper().startswith(lead.upper()) \
            and any(l["label"].upper().startswith(lead.upper()) for l in built):
        return built + post  # the post has no search from this airport: our own search from it comes first
    return post + built


def _cruise_split(tc: dict | None) -> dict | None:
    if not tc:
        return None
    parts = tc.get("parts", [])
    fare = sum(p["eur"] for p in parts if p["label"].startswith("Cruise fare"))
    flights = sum(p["eur"] for p in parts if "flight" in p["label"].lower() and not p["label"].startswith("Cruise fare"))
    return {"fare": round(fare), "flights": round(flights), "extras": round(tc["total_pp"] - fare - flights),
            "flights_included": tc.get("kind") == "fly_cruise_package",
            "port": tc.get("port"), "end_port": tc.get("end_port")}


def _home_total(o: Offer, b: dict) -> int | None:
    """The one price every view uses: live/advertised price + getting there from your hub (+ cruise extras).
    None when it equals the advertised price, so the UI shows the plain price."""
    total = b.get("effective_total")
    base = (b.get("trip_cost") or {}).get("total_pp") if o.subtype == "cruise" else o.price_eur
    if not total or base is None or abs(total - base) < 1:
        return None
    return round(total)


def ser(o: Offer, my_codes=frozenset(), my_cc=frozenset(), saved=frozenset(), full: bool = False) -> dict:
    b = o.score_breakdown or {}
    d = {
        "id": o.id, "title": o.title, "category": o.category, "subtype": o.subtype, "provider": o.provider_key,
        "provider_name": PROVIDER_BY_KEY[o.provider_key].name if o.provider_key in PROVIDER_BY_KEY else o.provider_key,
        "url": o.source_url, "origin": o.origin_code, "origin_label": o.origin_label, "origin_codes": o.origin_codes,
        "dest_key": o.dest_key, "dest": o.dest_label, "dest_country": o.dest_country,
        "region": REGIONS.get(o.dest_region, {}).get("label", o.dest_region),
        "price": round(o.price_eur), "price_original": o.price_original, "currency": o.currency,
        "price_basis": o.price_basis,
        "price_for_two": round(o.price_eur * 2) if o.price_basis == "per_person" and o.subtype != "flight" else None,
        "trip_total": round(b["trip_cost"]["total_pp"]) if b.get("trip_cost") else None,
        "trip_kind": b.get("trip_cost", {}).get("kind"),
        # cruise cost split: fare / flights to and from the port / fees + transfers + hotel
        "trip_split": _cruise_split(b.get("trip_cost")),
        "reference": round(o.reference_price), "savings": round(o.savings_eur), "discount": o.discount_pct,
        "score": o.deal_score, "band": b.get("band", ""), "error_flag": o.error_fare_flag,
        "last_minute": bool(b.get("last_minute")), "trip_type": o.trip_type, "cabin": o.cabin, "nights": o.nights,
        "board": o.board, "stars": o.stars, "baggage": o.baggage, "travel_window": o.travel_window,
        "depart_date": o.depart_date, "return_date": o.return_date, "image": o.image_url,
        "published_at": _iso(o.published_at), "first_seen_at": _iso(o.first_seen_at), "last_seen_at": _iso(o.last_seen_at),
        "last_verified_at": _iso(o.last_verified_at), "link_status": o.link_status, "status": o.status,
        "previous_price": round(o.previous_price_eur) if o.previous_price_eur else None,
        "is_new": o.first_seen_at > utcnow() - timedelta(hours=24), "confidence": o.confidence,
        "relevant": _relevant(o, set(my_codes), set(my_cc)) if my_codes or my_cc else True,
        "saved": o.id in saved, "urgency": _urgency(o), "is_demo": o.is_demo,
        "port": b.get("trip_cost", {}).get("port"), "lat": o.lat, "lon": o.lon,
        "positioning": b.get("positioning"),
        "home_total": _home_total(o, b),
        "total": round(scanner.trip_total(o)),
        "shared_price": b.get("shared_price"),
        "unresolved": o.origin_code == "EU*" and o.subtype != "cruise",
        "live_status": o.live_status, "live_price": round(o.live_price_eur) if o.live_price_eur else None,
        "live_detail": o.live_detail, "live_checked_at": _iso(o.live_checked_at),
    }
    d["booking"] = _links(o, d)[:12]
    if full:
        d["breakdown"] = b
        d["summary"] = o.summary[:1500]
    return d


def _ctx(s):
    my_codes = {a.iata for a in s.query(Airport).filter(Airport.enabled).all()}
    my_cc = {a.country for a in s.query(Airport).filter(Airport.enabled).all()}
    saved = {w.value.get("offer_id") for w in s.query(WatchItem).filter(WatchItem.kind == "offer").all()}
    return my_codes, my_cc, saved


def _visible(s):
    prefs = scanner.get_prefs(s)
    q = s.query(Offer).filter(Offer.status == "active", Offer.duplicate_of.is_(None),
                              Offer.deal_score >= prefs.get("min_display_score", 60))
    return q, prefs


def _apply_prefs(rows, prefs, my_codes, my_cc):
    out = []
    for o in rows:
        mp = (prefs.get("max_price") or {}).get(o.category)
        if mp and scanner.trip_total(o) > mp:
            continue
        if prefs.get("only_my_airports") and not _relevant(o, my_codes, my_cc):
            continue
        out.append(o)
    return out


def _monitoring(s) -> dict:
    hb = s.get(Setting, "worker_heartbeat")
    hb_at = datetime.fromisoformat(hb.value["at"]) if hb and hb.value.get("at") else None
    provs = s.query(Provider).all()
    active = [p for p in provs if p.enabled and p.status != "needs_credentials"]
    last = s.query(func.max(ScanLog.finished_at)).filter(ScanLog.ok).scalar()
    nxt = min([p.next_run_at for p in active if p.next_run_at] or [None]) if active else None
    worker_ok = bool(hb_at and hb_at > utcnow() - timedelta(minutes=3))
    failing = [p.name for p in active if p.status in ("failing", "degraded")]
    return {"worker_running": worker_ok, "worker_heartbeat": _iso(hb_at),
            "sources_active": len([p for p in active if p.status == "ok"]), "sources_total": len(active),
            "sources_failing": failing, "last_scan": _iso(last), "next_scan": _iso(nxt),
            "state": "ok" if worker_ok and not failing else ("degraded" if worker_ok else "stopped")}


# ------------------------------------------------------------------ overview & offers
@app.get("/api/overview")
def overview():
    with session_scope() as s:
        my_codes, my_cc, saved = _ctx(s)
        q, prefs = _visible(s)
        rows = _apply_prefs(q.order_by(Offer.deal_score.desc()).all(), prefs, my_codes, my_cc)
        since = utcnow() - timedelta(hours=24)
        cats = {}
        for c in ("flight", "package", "cruise"):
            rc = [o for o in rows if o.category == c]
            cats[c] = {"active": len(rc), "new": sum(1 for o in rc if o.first_seen_at > since),
                       "error_fares": sum(1 for o in rc if o.error_fare_flag != "none"),
                       "best_price": min([round(scanner.trip_total(o)) for o in rc if not _unresolved(o)] or [None]) if rc else None,
                       "top_score": max([o.deal_score for o in rc] or [0])}
        relevant = [o for o in rows if _relevant(o, my_codes, my_cc)]
        # top lists only show trips HubFare can actually price: known departure airport, not failed a live check
        solid = [o for o in rows if not _unresolved(o) and o.live_status != "unavailable"]
        pool = [o for o in relevant if o in solid] or solid
        best = next((o for o in pool if o.link_status in ("ok", "unchecked", "blocked")), pool[0] if pool else None)
        latest = sorted([o for o in solid if o.deal_score >= 70 and (not best or o.id != best.id)],
                        key=lambda o: o.first_seen_at, reverse=True)[:6]
        urgent = [o for o in solid if _urgency(o)["level"] == "high" and (not best or o.id != best.id)][:5]
        unresolved = [o for o in rows if _unresolved(o)]
        drops = s.query(Offer).filter(Offer.status == "active", Offer.previous_price_eur.isnot(None),
                                      Offer.price_eur < Offer.previous_price_eur).order_by(Offer.price_changed_at.desc()).limit(5).all()
        unread = s.query(Notification).filter(Notification.read.is_(False), Notification.channel == "inapp").count()
        return {
            "categories": cats,
            "best": ser(best, my_codes, my_cc, saved, full=True) if best else None,
            "latest": [ser(o, my_codes, my_cc, saved) for o in latest],
            "expiring": [ser(o, my_codes, my_cc, saved) for o in urgent],
            "price_drops": [ser(o, my_codes, my_cc, saved) for o in drops],
            "relevant_count": len(relevant), "total_count": len(rows), "unresolved_count": len(unresolved),
            "monitoring": _monitoring(s), "unread": unread,
            "my_airports": [a.iata for a in s.query(Airport).filter(Airport.enabled).order_by(Airport.priority, Airport.city)],
            "min_display_score": prefs.get("min_display_score", 60),
        }


@app.get("/api/airports")
def airports_for_picker():
    """Departure airports for the 'From' picker: home hubs first, then other watched airports."""
    from . import positioning
    with session_scope() as s:
        homes, _ = positioning.home_settings(s)
        rows = s.query(Airport).order_by(Airport.priority, Airport.city).all()
        out = [{"iata": a.iata, "city": a.city, "country": a.country, "enabled": a.enabled, "home": a.iata in homes}
               for a in rows if a.country not in EXCLUDED_ORIGIN_COUNTRIES]
        out.sort(key=lambda a: (not a["home"], homes.index(a["iata"]) if a["home"] else 0, a["city"]))
        return {"airports": out}


@app.get("/api/offers")
def offers(category: str | None = None, error: bool = False, last_minute: bool = False, origin: str | None = None,
           region: str | None = None, cabin: str | None = None, min_score: int | None = None, max_price: float | None = None,
           relevant: bool = False, sort: str = "score", trip_kind: str | None = None, limit: int = 120,
           from_airport: str | None = None):
    with session_scope() as s:
        my_codes, my_cc, saved = _ctx(s)
        q, prefs = _visible(s)
        if category:
            q = q.filter(Offer.category == category)
        if error:
            q = q.filter(Offer.error_fare_flag != "none")
        if cabin:
            q = q.filter(Offer.cabin == cabin)
        if min_score:
            q = q.filter(Offer.deal_score >= min_score)
        order = {"score": Offer.deal_score.desc(), "new": Offer.first_seen_at.desc(), "price": Offer.price_eur.asc(),
                 "savings": Offer.savings_eur.desc()}.get(sort, Offer.deal_score.desc())
        rows = _apply_prefs(q.order_by(order).all(), prefs, my_codes, my_cc)
        out = []
        for o in rows:
            d = ser(o, my_codes, my_cc, saved)
            if max_price and not from_airport and d["total"] > max_price:
                continue
            if last_minute and not d["last_minute"]:
                continue
            if origin and origin not in (o.origin_codes or [o.origin_code]) and o.origin_code != origin:
                continue
            if region and o.dest_region != region:
                continue
            if relevant and not d["relevant"]:
                continue
            if trip_kind and d["trip_kind"] != trip_kind:
                continue
            if from_airport:
                d = _from_airport(s, o, d, from_airport.upper())
                if d is None or (max_price and d["total"] > max_price):
                    continue
            out.append(d)
        if sort == "price":
            out.sort(key=lambda x: x["total"])
        return {"items": out[:limit], "count": len(out)}


@app.get("/api/offers/{oid}")
def offer_detail(oid: int):
    with session_scope() as s:
        o = s.get(Offer, oid)
        if not o:
            raise HTTPException(404)
        my_codes, my_cc, saved = _ctx(s)
        d = ser(o, my_codes, my_cc, saved, full=True)
        hist = s.execute(select(PriceHistory.observed_at, PriceHistory.price_eur, PriceHistory.origin_code, PriceHistory.provider_key)
                         .where(PriceHistory.dest_key == o.dest_key, PriceHistory.category == o.subtype)
                         .order_by(PriceHistory.observed_at)).all()
        d["history"] = [{"t": _iso(t), "price": round(p), "origin": oc, "provider": pk} for t, p, oc, pk in hist]
        comps = (s.query(Offer).filter(Offer.dest_key == o.dest_key, Offer.subtype == o.subtype, Offer.id != o.id,
                                       Offer.status == "active").order_by(Offer.price_eur).limit(8).all())
        d["comparables"] = [{"id": c.id, "origin": c.origin_label, "price": round(c.price_eur), "score": c.deal_score,
                             "provider": c.provider_key, "duplicate": bool(c.duplicate_of)} for c in comps]
        dups = s.query(Offer).filter(Offer.duplicate_of == o.id).all()
        d["also_seen_at"] = [{"provider": x.provider_key, "url": x.source_url, "price": round(x.price_eur)}
                             for x in dups if x.source_url != o.source_url]
        d["other_cities"] = [{"id": x.id, "origin": x.origin_label, "code": x.origin_code, "total": round(scanner.trip_total(x)),
                              "positioning": (x.score_breakdown or {}).get("positioning")}
                             for x in sorted(dups, key=scanner.trip_total) if x.source_url == o.source_url]
        return d


@app.post("/api/offers/{oid}/save")
def save_offer(oid: int):
    with session_scope() as s:
        o = s.get(Offer, oid)
        if not o:
            raise HTTPException(404)
        exists = [w for w in s.query(WatchItem).filter(WatchItem.kind == "offer").all() if w.value.get("offer_id") == oid]
        if exists:
            for w in exists:
                s.delete(w)
            return {"saved": False}
        s.add(WatchItem(kind="offer", label=f"{o.origin_label} → {o.dest_label}", value={"offer_id": oid}))
        return {"saved": True}


@app.get("/api/saved")
def saved_offers():
    with session_scope() as s:
        my_codes, my_cc, saved = _ctx(s)
        ids = [i for i in saved if i]
        rows = s.query(Offer).filter(Offer.id.in_(ids)).order_by(Offer.deal_score.desc()).all()
        watch = s.query(WatchItem).filter(WatchItem.kind != "offer").all()
        return {"offers": [ser(o, my_codes, my_cc, saved) for o in rows],
                "watch": [{"id": w.id, "kind": w.kind, "label": w.label, "value": w.value} for w in watch]}


# ------------------------------------------------------------------ alerts & notifications
class RuleIn(BaseModel):
    name: str
    origins: list[str] = []
    destinations: list[str] = []
    categories: list[str] = []
    cabins: list[str] = []
    max_price: float | None = None
    min_discount_pct: float | None = None
    min_score: int = 70
    min_nights: int | None = None
    max_nights: int | None = None
    channels: list[str] = ["inapp"]
    mode: str = "auto"
    enabled: bool = True


def _rule(r: AlertRule) -> dict:
    return {c: getattr(r, c) for c in ("id", "name", "origins", "destinations", "categories", "cabins", "max_price",
                                       "min_discount_pct", "min_score", "min_nights", "max_nights", "channels", "mode", "enabled")}


@app.get("/api/alerts")
def list_alerts():
    with session_scope() as s:
        rules = s.query(AlertRule).order_by(AlertRule.id).all()
        rows = s.query(Offer).filter(Offer.status == "active", Offer.duplicate_of.is_(None)).all()
        out = []
        for r in rules:
            d = _rule(r)
            d["matching_now"] = sum(1 for o in rows if notify.rule_matches(r, o))
            out.append(d)
        return {"rules": out, "channels": notify.channel_status(),
                "regions": [{"key": k, "label": v["label"]} for k, v in REGIONS.items()]}


@app.post("/api/alerts")
def create_alert(r: RuleIn):
    with session_scope() as s:
        row = AlertRule(**r.model_dump())
        s.add(row)
        s.flush()
        return _rule(row)


@app.put("/api/alerts/{rid}")
def update_alert(rid: int, r: RuleIn):
    with session_scope() as s:
        row = s.get(AlertRule, rid)
        if not row:
            raise HTTPException(404)
        for k, v in r.model_dump().items():
            setattr(row, k, v)
        return _rule(row)


@app.delete("/api/alerts/{rid}")
def delete_alert(rid: int):
    with session_scope() as s:
        row = s.get(AlertRule, rid)
        if row:
            s.delete(row)
        return {"ok": True}


class TestIn(BaseModel):
    channels: list[str] = ["inapp"]
    offer_id: int | None = None


@app.post("/api/notifications/test")
def test_notification(t: TestIn):
    return {"results": notify.send_test(t.channels, t.offer_id)}


@app.get("/api/notifications")
def notifications(limit: int = 40):
    with session_scope() as s:
        rows = s.query(Notification).order_by(Notification.created_at.desc()).limit(limit).all()
        return {"items": [{"id": n.id, "channel": n.channel, "kind": n.kind, "status": n.status, "title": n.title,
                           "body": n.body, "error": n.error, "offer_id": n.offer_id, "created_at": _iso(n.created_at),
                           "read": n.read} for n in rows]}


@app.post("/api/notifications/read")
def mark_read():
    with session_scope() as s:
        s.query(Notification).filter(Notification.read.is_(False)).update({"read": True})
        return {"ok": True}


# ------------------------------------------------------------------ settings & monitoring
@app.get("/api/settings")
def settings():
    with session_scope() as s:
        prefs = scanner.get_prefs(s)
        airports = [{"iata": a.iata, "city": a.city, "country": a.country, "enabled": a.enabled, "priority": a.priority,
                     "custom": a.custom} for a in s.query(Airport).order_by(Airport.priority, Airport.city).all()]
        provs = []
        month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for p in s.query(Provider).all():
            logs = s.query(ScanLog).filter(ScanLog.provider_key == p.key).order_by(ScanLog.started_at.desc()).limit(1).first()
            calls = s.query(func.coalesce(func.sum(ScanLog.api_calls), 0)).filter(ScanLog.provider_key == p.key,
                                                                                 ScanLog.started_at >= month_start).scalar()
            active = s.query(Offer).filter(Offer.provider_key == p.key, Offer.status == "active").count()
            provs.append({"key": p.key, "name": p.name, "kind": p.kind, "url": p.url, "homepage": p.homepage, "market": p.market,
                          "enabled": p.enabled, "priority": p.priority, "interval": p.interval_minutes, "status": p.status,
                          "requires": p.requires_credentials, "last_success": _iso(p.last_success_at),
                          "last_run": _iso(p.last_run_at), "next_run": _iso(p.next_run_at), "error": p.last_error,
                          "offers_total": p.offers_collected, "offers_active": active, "calls_month": int(calls),
                          "est_cost_month": round(int(calls) * p.cost_per_call_eur, 2), "notes": p.notes,
                          "last_scan": {"new": logs.new, "parsed": logs.parsed, "fetched": logs.fetched, "ok": logs.ok,
                                        "ms": logs.duration_ms} if logs else None})
        return {"preferences": prefs, "airports": airports, "providers": provs, "unavailable": UNAVAILABLE_SOURCES,
                "monitoring": _monitoring(s), "markets": {k: v[0] for k, v in COUNTRY_ORIGINS.items()},
                "regions": [{"key": k, "label": v["label"]} for k, v in REGIONS.items()],
                "costs": {"infra_note": "Self-hosted: €0. Small VPS (Hetzner CX22 / similar): ~€4–6/month. "
                                        "Managed Postgres (Supabase free tier): €0.",
                          "api_note": "All active sources are free (RSS, ECB, Wikipedia). Travelpayouts Data API: free with partner account. "
                                      "Optional AI features would be billed per token by Anthropic."}}


class PrefsIn(BaseModel):
    min_display_score: int = 60
    max_price: dict = {}
    preferred_destinations: list[str] = []
    only_my_airports: bool = False
    home_airports: list[str] = ["VIE", "VNO", "WAW", "RIX"]
    nearby_km: int = 300


@app.put("/api/settings/preferences")
def set_prefs(p: PrefsIn):
    with session_scope() as s:
        s.merge(Setting(key="preferences", value=p.model_dump()))
    return {"ok": True}


class AirportIn(BaseModel):
    iata: str
    city: str
    country: str
    lat: float = 50.0
    lon: float = 10.0


@app.post("/api/airports")
def add_airport(a: AirportIn):
    with session_scope() as s:
        code = a.iata.upper().strip()[:4]
        s.merge(Airport(iata=code, city=a.city, country=a.country.upper()[:2], lat=a.lat, lon=a.lon, enabled=True,
                        priority=2, custom=True))
    return {"ok": True}


@app.patch("/api/airports/{iata}")
def toggle_airport(iata: str, enabled: bool):
    with session_scope() as s:
        a = s.get(Airport, iata)
        if not a:
            raise HTTPException(404)
        a.enabled = enabled
    return {"ok": True}


@app.delete("/api/airports/{iata}")
def delete_airport(iata: str):
    with session_scope() as s:
        a = s.get(Airport, iata)
        if a and a.custom:
            s.delete(a)
        elif a:
            a.enabled = False
    return {"ok": True}


class ProviderPatch(BaseModel):
    enabled: bool | None = None
    interval: int | None = None


@app.patch("/api/providers/{key}")
def patch_provider(key: str, p: ProviderPatch):
    with session_scope() as s:
        row = s.get(Provider, key)
        if not row:
            raise HTTPException(404)
        if p.enabled is not None:
            row.enabled = p.enabled
        if p.interval:
            row.interval_minutes = max(30, min(p.interval, 24 * 60))  # never hammer a source
    return {"ok": True}


_running: set[str] = set()


@app.post("/api/providers/{key}/scan")
def scan_now(key: str, wait: bool = False):
    if key not in PROVIDER_BY_KEY:
        raise HTTPException(404)
    if key in _running:
        return {"status": "already_running"}

    def run():
        _running.add(key)
        try:
            return scanner.run_provider(key)
        finally:
            _running.discard(key)

    if wait:
        res = run()
        return {k: v for k, v in res.items() if k not in ("new_ids", "dropped_ids")}
    threading.Thread(target=run, daemon=True).start()
    return {"status": "started"}


@app.get("/api/scanlogs")
def scanlogs(limit: int = 50):
    with session_scope() as s:
        rows = s.query(ScanLog).order_by(ScanLog.started_at.desc()).limit(limit).all()
        return {"items": [{"provider": r.provider_key, "started": _iso(r.started_at), "ok": r.ok, "fetched": r.fetched,
                           "parsed": r.parsed, "new": r.new, "updated": r.updated, "error": r.error, "ms": r.duration_ms}
                          for r in rows]}


@app.get("/api/health")
def health():
    with session_scope() as s:
        return {"ok": True, "monitoring": _monitoring(s)}


# ------------------------------------------------------------------ frontend
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
