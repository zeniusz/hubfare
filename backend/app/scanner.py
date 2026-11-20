"""Scan pipeline: fetch -> parse -> normalise (EUR) -> dedupe -> history -> score -> classify -> notify."""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import select

from . import notify
from .config import EXCLUDED_ORIGIN_COUNTRIES, RSS_FLIGHTS, TRAVELPAYOUTS_MAX_AIRPORTS, USER_AGENT
from .cruise import cruise_reference_total, complete_trip_cost, find_port, find_ports
from .db import Airport, Offer, PriceHistory, Provider, ScanLog, Setting, session_scope, utcnow
from .fx import refresh_rates, to_eur
from .geo import COUNTRY_ORIGINS, DEST_PLACES, ORIGIN_PLACES, REGIONS
from .images import destination_image
from .parsing import ParsedDeal, parse_deal
from . import positioning
from .providers import (CALENDAR_TARGETS, PROVIDER_BY_KEY, PROVIDERS, fetch_rss, fetch_travelpayouts,
                        fetch_travelpayouts_calendar, fetch_travelpayouts_special)
from .scoring import ScoreInput, band, classify, score

log = logging.getLogger(__name__)

EXPIRY_DAYS = {"flight": 10, "package": 14, "cruise": 21}
DEFAULT_PREFS = {
    "min_display_score": 60,         # offers below this are stored (for history) but never shown
    "max_price": {"flight": None, "package": None, "cruise": None},
    "preferred_destinations": [],     # dest keys or regions; boosts relevance
    "only_my_airports": False,
}


def get_prefs(s) -> dict:
    row = s.get(Setting, "preferences")
    prefs = dict(DEFAULT_PREFS)
    if row:
        prefs.update(row.value or {})
    return prefs


def ensure_seed() -> None:
    """Create provider and airport rows on first run (idempotent)."""
    from .geo import DEFAULT_ENABLED
    with session_scope() as s:
        for p in PROVIDERS:
            if not s.get(Provider, p.key):
                s.add(Provider(key=p.key, name=p.name, kind=p.kind, url=p.url, homepage=p.homepage, market=p.market,
                               interval_minutes=p.interval, priority=p.priority, requires_credentials=p.requires,
                               cost_per_call_eur=p.cost_per_call_eur, notes=p.notes))
            if p.kind == "rss" and p.focus == ["flight"] and not RSS_FLIGHTS:
                s.flush()
                s.get(Provider, p.key).enabled = False  # flight-only blog: flights now come from fare APIs
        for iata, place in ORIGIN_PLACES.items():
            if not s.get(Airport, iata):
                s.add(Airport(iata=iata, city=place.name, country=place.country, lat=place.lat, lon=place.lon,
                              enabled=iata in DEFAULT_ENABLED, priority=place.priority))
        if not s.get(Setting, "preferences"):
            s.add(Setting(key="preferences", value=DEFAULT_PREFS))
        from .db import AlertRule
        if not s.query(AlertRule).count():
            s.add(AlertRule(name="Exceptional deals from Vienna, Vilnius, Warsaw & Riga",
                            origins=["VIE", "VNO", "KUN", "WAW", "RIX"], min_score=85, channels=["inapp"], mode="auto"))
            s.add(AlertRule(name="Suspected error fares – any European airport", categories=["error_fare"],
                            min_score=0, channels=["inapp"], mode="instant"))


def _fingerprint(provider: str, external_id: str) -> str:
    return hashlib.sha256(f"{provider}|{external_id}".encode()).hexdigest()


def _route_key(subtype: str, origin: str, dest: str, cabin: str, trip: str, nights: int | None) -> str:
    nb = "" if nights is None else ("short" if nights <= 4 else "week" if nights <= 9 else "long")
    return f"{subtype}|{origin}|{dest}|{cabin}|{trip}|{nb}"


def _origin_country(code: str) -> str:
    if code.endswith("*"):
        return code[:2] if code != "EU*" else ""
    p = ORIGIN_PLACES.get(code)
    return p.country if p else ""


def _parsed_from_structured(raw) -> ParsedDeal | None:
    st = raw.structured
    dest = DEST_PLACES.get(st["dest_key"])
    if not dest:
        return None
    o = ORIGIN_PLACES.get(st["origin"])
    return ParsedDeal(
        title=raw.title, price_amount=st["price"], currency=st["currency"], price_basis="per_person",
        origin_codes=[st["origin"]], origin_label=o.name if o else st["origin"], dest=dest, trip_type=st.get("trip_type", "return"),
        cabin="economy", nights=None, stars=None, board="", baggage="unknown", subtype="flight",
        error_keyword=False, luxury_signal=False, last_minute=False, cruise_port=None, fly_cruise_package=False,
        travel_window=f"{st['depart_date']} – {st['return_date']}", confidence=0.95, notes=[f"airline {st.get('airline')}"],
    )


def _cheapest_flight_to_region(s, region: str) -> float | None:
    rows = s.execute(select(Offer.price_eur).where(Offer.status == "active", Offer.subtype == "flight",
                                                  Offer.dest_region == region, Offer.trip_type == "return",
                                                  Offer.cabin == "economy")).scalars().all()
    return min(rows) if rows else None


def _score_offer(s, o: Offer, d: ParsedDeal, enabled_codes: set[str], text: str) -> None:
    since = utcnow() - timedelta(days=365)
    route = _route_key(o.subtype, o.origin_code, o.dest_key, o.cabin, o.trip_type, o.nights)
    hist = s.execute(select(PriceHistory.price_eur).where(PriceHistory.route_key == route,
                                                          PriceHistory.observed_at >= since,
                                                          PriceHistory.offer_id != o.id)).scalars().all()
    cross = s.execute(select(Offer.price_eur).where(Offer.status == "active", Offer.dest_key == o.dest_key,
                                                    Offer.subtype == o.subtype, Offer.cabin == o.cabin,
                                                    Offer.origin_code != o.origin_code, Offer.id != o.id)).scalars().all()
    # authoritative price: a fresh live airline quote replaces the cached/advertised one
    price_for_score = effective_price(o)
    cruise_ref = None
    breakdown_extra = {}
    origin_country = _origin_country(o.origin_code)
    # every trip starts at one of your home hubs: add the flight to the departure airport if needed
    pos = positioning.plan(s, o.origin_code, o.origin_codes, REGIONS.get(o.dest_region, {}).get("long_haul", False),
                           o.depart_date or "", o.return_date or "")
    if pos:
        breakdown_extra["positioning"] = pos
        origin_country = ORIGIN_PLACES[pos["hub"]].country
        if o.subtype != "cruise" or d.fly_cruise_package:
            per_person = 2 if o.price_basis == "total" else 1  # "total" prices are for two travellers
            price_for_score = price_for_score + pos["price"] * per_person
            hist = [h + pos["price"] * per_person for h in hist]  # compare like with like
    if o.subtype == "cruise":
        start, end_port = find_ports(text)
        port = d.cruise_port or start
        if end_port and port and end_port.key == port.key:
            end_port = None
        flight = _cheapest_flight_to_region(s, port.region) if port else None
        fare_pp = o.price_eur / 2 if o.price_basis == "total" else o.price_eur  # "€X for two" → per person
        trip = complete_trip_cost(fare_pp, o.nights, port, d.fly_cruise_package, text, flight, origin_country, end_port)
        cruise_ref = cruise_reference_total(port, o.nights, d.fly_cruise_package, origin_country, text, end_port)
        price_for_score = trip["total_pp"] + (pos["price"] if pos and d.fly_cruise_package else 0)
        breakdown_extra["trip_cost"] = trip
    x = ScoreInput(
        subtype=o.subtype, region=o.dest_region, origin_country=origin_country, cabin=o.cabin,
        trip_type=o.trip_type, nights=o.nights, stars=o.stars, board=o.board, baggage=o.baggage,
        price_eur=price_for_score,
        price_basis="per_person" if o.subtype == "cruise" else o.price_basis,  # cruise total is already per person
        travel_window=o.travel_window, error_keyword=d.error_keyword,
        luxury_brand=d.luxury_signal, confidence=o.confidence, history=list(hist), cross_origin=list(cross),
        priority_origin=bool(set(o.origin_codes or []) & enabled_codes), cruise_reference=cruise_ref,
    )
    res = score(x)
    # Plausibility guard: a huge discount on loosely parsed data is more likely a parsing error than a deal
    if res["discount_pct"] > 70 and o.confidence < 0.8:
        res["score"] = min(res["score"], 69)
        res["band"] = band(res["score"])
        res["modifiers"].append({"label": "implausibly large discount on inferred data – capped, check source", "points": 0})
    category, flag = classify(o.subtype, res["score"], o.dest_region, d.error_keyword, o.cabin)
    o.category = category
    o.error_fare_flag = flag
    o.deal_score = res["score"]
    o.reference_price = res["reference_price"]
    o.savings_eur = res["savings_eur"]
    o.discount_pct = res["discount_pct"]
    res.update(breakdown_extra)
    res["effective_total"] = round(price_for_score)
    res["advertised_price"] = round(o.price_eur)
    res["parse_notes"] = d.notes
    res["last_minute"] = d.last_minute
    res["fly_cruise_package"] = d.fly_cruise_package
    o.score_breakdown = res


def process_items(provider_key: str, items) -> dict:
    stats = {"fetched": len(items), "parsed": 0, "new": 0, "updated": 0, "new_ids": [], "dropped_ids": []}
    need_images: list = []
    try:
        _process(items, provider_key, stats, need_images)
    finally:
        # Image lookups use their own DB session, so run them after the scan transaction has committed
        for oid, key, name in [(o.id, k, n) for o, k, n in need_images if o.id]:
            url = destination_image(key, name)
            if url:
                with session_scope() as s:
                    row = s.get(Offer, oid)
                    if row and not row.image_url:
                        row.image_url = url
    return stats


def _process(items, provider_key: str, stats: dict, need_images: list) -> None:
    with session_scope() as s:
        enabled_codes = {a.iata for a in s.query(Airport).filter(Airport.enabled).all()}
        for raw in items:
            d = _parsed_from_structured(raw) if raw.structured else parse_deal(raw.title, raw.summary, raw.default_origin)
            if not d or not d.dest:
                continue
            if d.subtype == "flight" and not raw.structured and not RSS_FLIGHTS:
                continue  # flights come from fare APIs, not deal-blog posts
            stats["parsed"] += 1
            price_eur = to_eur(d.price_amount, d.currency)
            fp = _fingerprint(provider_key, raw.external_id or raw.url)
            o = s.execute(select(Offer).where(Offer.fingerprint == fp)).scalar_one_or_none()
            now = utcnow()
            origin_code = d.origin_codes[0]
            origin_lat_ok = origin_code in ORIGIN_PLACES or origin_code in COUNTRY_ORIGINS
            if not origin_lat_ok or excluded_origin(d.origin_codes):
                continue
            is_new = o is None
            if is_new:
                o = Offer(fingerprint=fp, provider_key=provider_key, first_seen_at=now)
                s.add(o)
            elif abs(o.price_eur - price_eur) >= 1:
                o.previous_price_eur = o.price_eur
                o.price_changed_at = now
                o.live_status, o.live_price_eur, o.live_checked_at = "", None, None  # old live check no longer applies
            text = f"{d.title} {raw.summary[:900]}"
            o.source_url = raw.url[:800]
            if raw.booking_links:
                o.booking_links = raw.booking_links
            o.title = d.title[:400]
            o.summary = (raw.summary or "")[:2000]
            o.subtype = d.subtype
            o.origin_code = origin_code
            o.origin_codes = d.origin_codes
            o.origin_label = d.origin_label[:120]
            o.dest_key, o.dest_label, o.dest_country = d.dest.key, d.dest.name, d.dest.country
            o.dest_region, o.lat, o.lon = d.dest.region, d.dest.lat, d.dest.lon
            o.price_original, o.currency, o.price_eur = d.price_amount, d.currency, price_eur
            o.price_basis, o.trip_type, o.cabin = d.price_basis, d.trip_type, d.cabin
            o.nights, o.board, o.stars, o.baggage = d.nights, d.board, d.stars, d.baggage
            o.travel_window = d.travel_window
            if raw.structured:
                o.depart_date = raw.structured.get("depart_date", "")
                o.return_date = raw.structured.get("return_date", "")
                o.dest_iata = raw.structured.get("dest_iata", "")
                o.depart_at = raw.structured.get("depart_at", "")
                o.back_arrive_at = raw.structured.get("back_arrive_at", "")
            o.published_at = raw.published or o.published_at or now
            o.last_seen_at = now
            o.confidence = d.confidence
            o.status = "active"
            if not o.image_url:
                o.image_url = raw.image_url
            if not o.image_url:
                need_images.append((o, d.dest.key, d.dest.name))
            month = raw.structured.get("depart_date", "")[:7] if raw.structured else ""
            o.dedupe_key = f"{d.subtype}|{origin_code}|{d.dest.key}|{d.cabin}|{month}|{round(price_eur / 20)}"
            o.category = o.category or d.subtype
            s.flush()
            # record history on first sight and on every price change
            if is_new or o.price_changed_at == now:
                s.add(PriceHistory(route_key=_route_key(o.subtype, o.origin_code, o.dest_key, o.cabin, o.trip_type, o.nights),
                                   offer_id=o.id, provider_key=provider_key, origin_code=o.origin_code, dest_key=o.dest_key,
                                   category=o.subtype, price_eur=price_eur, observed_at=now,
                                   travel_month=(o.depart_date or "")[:7]))
            _score_offer(s, o, d, enabled_codes, text)
            # cross-provider duplicate: same trip, similar price, seen recently from another source
            dup = s.execute(select(Offer).where(Offer.dedupe_key == o.dedupe_key, Offer.id != o.id,
                                                Offer.status == "active", Offer.duplicate_of.is_(None),
                                                Offer.first_seen_at >= now - timedelta(days=5))
                            .order_by(Offer.first_seen_at)).scalars().first()
            o.duplicate_of = dup.id if dup and dup.first_seen_at <= o.first_seen_at else None
            if is_new:
                stats["new"] += 1
                stats["new_ids"].append(o.id)
            else:
                stats["updated"] += 1
                if o.previous_price_eur and o.price_changed_at == now and price_eur < o.previous_price_eur:
                    stats["dropped_ids"].append(o.id)
    return stats


def _calendar_batch(s, per_run: int = 6) -> tuple[list[str], list[str], list[str]]:
    """Home hubs × a rotating handful of long-haul destinations × the next 3 months (≈ 72 calls per run)."""
    homes, _ = positioning.home_settings(s)
    row = s.get(Setting, "cal_rotation") or Setting(key="cal_rotation", value={"offset": 0})
    start = int((row.value or {}).get("offset", 0)) % len(CALENDAR_TARGETS)
    targets = [CALENDAR_TARGETS[(start + i) % len(CALENDAR_TARGETS)] for i in range(per_run)]
    row.value = {"offset": (start + per_run) % len(CALENDAR_TARGETS)}
    s.merge(row)
    today = utcnow().date()
    months = []
    y, m = today.year, today.month
    for _ in range(3):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        months.append(f"{y}-{m:02d}")
    return list(homes), targets, months


def excluded_origin(codes: list[str]) -> bool:
    """True when every departure option is in an excluded country (default: UK-only deals)."""
    countries = {(c[:2] if c.endswith("*") else (ORIGIN_PLACES[c].country if c in ORIGIN_PLACES else "")) for c in codes}
    return bool(countries) and countries <= EXCLUDED_ORIGIN_COUNTRIES


def _rotating_origins(s, key: str) -> list[str]:
    """Home hubs on every scan; the other enabled airports take turns so all of them get covered."""
    enabled = [a.iata for a in s.query(Airport).filter(Airport.enabled).order_by(Airport.priority, Airport.iata).all()]
    if key != "travelpayouts":
        return enabled[:TRAVELPAYOUTS_MAX_AIRPORTS]
    homes, _ = positioning.home_settings(s)
    fixed = list(homes)  # home hubs are always scanned
    others = [a for a in enabled if a not in fixed]
    slots = max(0, TRAVELPAYOUTS_MAX_AIRPORTS - len(fixed))
    if not others or not slots:
        return fixed
    row = s.get(Setting, "tp_rotation") or Setting(key="tp_rotation", value={"offset": 0})
    start = int((row.value or {}).get("offset", 0)) % len(others)
    batch = [others[(start + i) % len(others)] for i in range(min(slots, len(others)))]
    row.value = {"offset": (start + len(batch)) % len(others)}
    s.merge(row)
    return fixed + batch


def run_provider(key: str) -> dict:
    """Run one provider scan with logging, health tracking and notifications."""
    pdef = PROVIDER_BY_KEY[key]
    t0 = time.time()
    with session_scope() as s:
        prov = s.get(Provider, key)
        log_row = ScanLog(provider_key=key, started_at=utcnow())
        s.add(log_row)
        s.flush()
        log_id = log_row.id
        prov.last_run_at = utcnow()
        origins = _rotating_origins(s, key)
    result = {"provider": key, "ok": False}
    calls = 0
    try:
        refresh_rates()
        if pdef.kind == "rss":
            items, calls = fetch_rss(pdef)
        elif key == "travelpayouts":
            items, calls = fetch_travelpayouts(pdef, origins)
        elif key == "tp_special":
            with session_scope() as s2:
                hubs, _ = positioning.home_settings(s2)
            items, calls = fetch_travelpayouts_special(pdef, list(hubs))
        elif key == "tp_calendar":
            with session_scope() as s:
                hubs, targets, months = _calendar_batch(s)
            items, calls = fetch_travelpayouts_calendar(pdef, hubs, targets, months)
        else:
            raise NotImplementedError(key)
        stats = process_items(key, items)
        result.update(stats, ok=True)
        err = ""
    except LookupError:
        err = f"needs credentials: {pdef.requires}"
        stats = None
    except Exception as e:  # network, HTTP, parse errors
        log.exception("scan %s failed", key)
        err = f"{type(e).__name__}: {e}"[:500]
        stats = None
    with session_scope() as s:
        prov = s.get(Provider, key)
        lr = s.get(ScanLog, log_id)
        lr.finished_at = utcnow()
        lr.duration_ms = int((time.time() - t0) * 1000)
        lr.api_calls = calls
        prov.api_calls_month += calls
        prov.next_run_at = utcnow() + timedelta(minutes=prov.interval_minutes)
        if stats is not None:
            lr.ok, lr.fetched, lr.parsed, lr.new, lr.updated = True, stats["fetched"], stats["parsed"], stats["new"], stats["updated"]
            prov.status, prov.last_success_at, prov.last_error, prov.consecutive_failures = "ok", utcnow(), "", 0
            prov.offers_collected = s.query(Offer).filter(Offer.provider_key == key).count()
        else:
            lr.ok, lr.error = False, err
            prov.last_error = err
            if err.startswith("needs credentials"):
                prov.status = "needs_credentials"
            else:
                prov.consecutive_failures += 1
                prov.status = "failing" if prov.consecutive_failures >= 2 else "degraded"
    if stats is not None:
        if key in ("travelpayouts", "tp_calendar", "tp_special"):
            from . import duffel
            result["positioning"] = positioning.refresh_dated()  # connecting flights on the deal's own dates
            result["live_check"] = duffel.check_top_flights()  # confirm with airlines before alerting
        if pdef.kind == "rss":
            from . import booking
            result["article_links"] = booking.enrich_from_articles()  # exact search links from the posts
        notify.process_new_offers(stats["new_ids"] + stats["dropped_ids"])
    result["error"] = err
    return result


def expire_offers() -> int:
    n = 0
    now = utcnow()
    with session_scope() as s:
        disabled = {p.key for p in s.query(Provider).filter(Provider.enabled.is_(False)).all()}
        for o in s.query(Offer).filter(Offer.status == "active").all():
            age_ref = o.published_at or o.first_seen_at
            limit = EXPIRY_DAYS.get(o.subtype, 14)
            stale_api = o.provider_key in ("travelpayouts", "tp_calendar", "tp_special") and o.last_seen_at < now - timedelta(hours=26 if o.provider_key == "tp_calendar" else 8)
            blog_flight = o.subtype == "flight" and o.provider_key not in ("travelpayouts", "tp_calendar", "tp_special") and not RSS_FLIGHTS
            departed = o.depart_date and o.depart_date < now.strftime("%Y-%m-%d")
            if age_ref < now - timedelta(days=limit) or stale_api or blog_flight or o.provider_key in disabled or departed \
                    or excluded_origin(o.origin_codes or [o.origin_code]) or o.link_status == "gone":
                o.status = "expired"
                n += 1
    return n


def verify_links(limit: int = 40) -> dict:
    """Check that the source post for top offers is still online (rate-limited, robots-respecting)."""
    out = {"checked": 0, "gone": 0}
    with session_scope() as s:
        cutoff = utcnow() - timedelta(hours=6)
        rows = (s.query(Offer).filter(Offer.status == "active", Offer.deal_score >= 60, Offer.is_demo.is_(False))
                .filter((Offer.last_verified_at.is_(None)) | (Offer.last_verified_at < cutoff))
                .order_by(Offer.deal_score.desc()).limit(limit).all())
        targets = [(o.id, o.source_url) for o in rows]
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True) as c:
        for oid, url in targets:
            try:
                r = c.head(url)
                if r.status_code in (405, 501):
                    r = c.get(url)
                status = "ok" if r.status_code < 400 else ("gone" if r.status_code in (404, 410) else "blocked")
            except Exception:
                status = "unreachable"
            with session_scope() as s:
                o = s.get(Offer, oid)
                o.link_status = status
                o.last_verified_at = utcnow()
                if status == "gone":
                    o.status = "expired"
                    out["gone"] += 1
            out["checked"] += 1
            time.sleep(1.0)
    return out


def backfill_images() -> int:
    with session_scope() as s:
        todo = [(o.id, o.dest_key, o.dest_label) for o in s.query(Offer).filter(Offer.status == "active", Offer.image_url == "")]
    n = 0
    for oid, key, name in todo:
        url = destination_image(key, name)
        if url:
            with session_scope() as s:
                s.get(Offer, oid).image_url = url
            n += 1
    return n


def effective_price(o: Offer) -> float:
    """Live airline quote if checked in the last 24 h, else the advertised/cached price."""
    fresh = o.live_checked_at and o.live_checked_at > utcnow() - timedelta(hours=24)
    if fresh and o.live_status in ("confirmed", "higher") and o.live_price_eur:
        return o.live_price_eur
    return o.price_eur


def rescore_offer(s, o: Offer) -> None:
    from .parsing import parse_deal as _pd
    enabled = {a.iata for a in s.query(Airport).filter(Airport.enabled).all()}
    d = _pd(o.title, o.summary, o.origin_code) if o.provider_key not in ("travelpayouts", "tp_calendar", "tp_special") else None
    if d is None:
        d = ParsedDeal(o.title, o.price_original, o.currency, o.price_basis, o.origin_codes or [o.origin_code],
                       o.origin_label, DEST_PLACES.get(o.dest_key), o.trip_type, o.cabin, o.nights, o.stars,
                       o.board, o.baggage, o.subtype, False, False, False, None, False, o.travel_window, o.confidence)
    _score_offer(s, o, d, enabled, f"{o.title} {o.summary[:900]}")


def rescore_all() -> int:
    """Daily: recompute scores with the latest history (history grows -> references improve)."""
    from .parsing import parse_deal as _pd
    n = 0
    with session_scope() as s:
        enabled = {a.iata for a in s.query(Airport).filter(Airport.enabled).all()}
        for o in s.query(Offer).filter(Offer.status == "active", Offer.is_demo.is_(False)).all():
            d = _pd(o.title, o.summary, o.origin_code) if o.provider_key not in ("travelpayouts", "tp_calendar", "tp_special") else None
            if d is None:
                if o.provider_key not in ("travelpayouts", "tp_calendar", "tp_special"):
                    o.status = "expired"  # parser rules tightened: no longer a qualifying offer
                    continue
                d = ParsedDeal(o.title, o.price_original, o.currency, o.price_basis, o.origin_codes or [o.origin_code],
                               o.origin_label, DEST_PLACES.get(o.dest_key), o.trip_type, o.cabin, o.nights, o.stars,
                               o.board, o.baggage, o.subtype, False, False, False, None, False, o.travel_window, o.confidence)
            _score_offer(s, o, d, enabled, f"{o.title} {o.summary[:900]}")
            n += 1
    return n
