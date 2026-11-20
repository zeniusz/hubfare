"""Parser and scoring tests using real headlines captured from the monitored feeds (13 Nov 2026)."""
import pytest

from app.cruise import complete_trip_cost, cruise_reference_total, find_port
from app.parsing import parse_deal
from app.scoring import ScoreInput, band, classify, score


def P(title, summary="", market="EU*"):
    return parse_deal(title, summary, market)


def test_flight_with_origin_and_destination():
    d = P("Full service flights from Milan to Tokyo, JAPAN from €538")
    assert d.subtype == "flight"
    assert d.origin_codes == ["MXP"]
    assert d.dest.key == "tokyo"
    assert d.price_amount == 538 and d.currency == "EUR"
    assert d.trip_type == "return"


def test_baltic_origin_and_baggage():
    d = P("Caribbean Island! Flights from Riga to Saint Lucia €719 (checked baggage incl.)")
    assert d.origin_codes == ["RIX"]
    assert d.dest.key == "stlucia"
    assert d.baggage == "included"


def test_one_way_detection():
    d = P("One-way NON STOP flights from Warsaw to CAPE VERDE for €135")
    assert d.trip_type == "one_way"
    assert d.origin_codes == ["WAW"]


def test_polish_package_in_pln_from_market_default():
    d = P("Mauritius na ferie zimowe za 3068 PLN 🏝️🌊 Loty + apartament na tydzień", "", "PL*")
    assert d.subtype == "package"
    assert d.currency == "PLN" and d.price_amount == 3068
    assert d.nights == 7
    assert d.origin_codes == ["PL*"]


def test_package_stars_board_nights():
    d = P("Cypr z all inclusive za 2561 PLN 😎☀️ Tydzień w 5* King Evelthon Beach z Poznania", "", "PL*")
    assert d.subtype == "package" and d.stars == 5 and d.board == "All inclusive" and d.nights == 7


def test_standalone_hotel_is_rejected():
    assert P("Well-rated 4* Kasa El Paseo Miami Beach 😎 🏖️ for €99/double") is None
    assert P("Conrad Hong Kong: €239/Night With Breakfast, $100 Credit & More") is None


def test_reverse_direction_is_rejected():
    assert P("Flights from Hanoi, Vietnam to BARCELONA from €171 one-way") is None
    assert P("❗HIT❗ Loty z Tajlandii (Bangkok) do Europy w jedną stronę za 560 zł") is None
    assert P("‼️ -50% auf Hawaii: Von L.A. nach Honolulu & NYC", "ab 1700 €", "DE*") is None


def test_news_without_price_is_dropped():
    assert P("Washington Dulles opens its first new concourse in 20 years") is None


def test_cruise_port_and_brand_detection():
    d = P("MSC Magnifica: Last-Minute 7-Night Mediterranean Cruise from Barcelona for €409")
    assert d.subtype == "cruise" and d.nights == 7 and d.last_minute
    assert d.cruise_port.key == "barcelona"
    d2 = P("Mein Schiff Relax: Kanaren im Februar", "ab 899 €", "DE*")
    assert d2.subtype == "cruise"


def test_business_class_and_error_keyword():
    d = P("Error fare! Business class from Frankfurt to New York for €650 return")
    assert d.cabin == "business" and d.error_keyword
    assert d.origin_codes == ["FRA"] and d.dest.key == "newyork"


def _si(**kw):
    base = dict(subtype="flight", region="se_asia", origin_country="AT", cabin="economy", trip_type="return", nights=None,
                stars=None, board="", baggage="unknown", price_eur=700, price_basis="per_person", travel_window="",
                error_keyword=False, luxury_brand=False, confidence=0.9, history=[], cross_origin=[], priority_origin=False)
    base.update(kw)
    return ScoreInput(**base)


def test_typical_price_scores_as_ordinary():
    r = score(_si(price_eur=720))
    assert r["score"] < 50 and band(r["score"]) == "Ordinary offer"


def test_big_discount_scores_high_and_is_explained():
    r = score(_si(price_eur=320))
    assert r["score"] >= 85
    assert r["reference_explained"] and r["modifiers"]


def test_history_moves_reference():
    hist = [520, 510, 530, 505, 515, 525, 500, 510]
    prior_only = score(_si(price_eur=500, history=hist[:7]))["reference_price"]  # < 8 observations: prior only
    r = score(_si(price_eur=500, history=hist))
    assert 515 < r["reference_price"] < prior_only  # moves towards the observed market, but cautiously
    assert r["history_n"] == 8


def test_error_fare_classification_never_confirmed():
    assert classify("flight", 96, "east_asia", False, "economy") == ("flight", "suspected_statistical")
    assert classify("flight", 60, "europe", True, "economy") == ("flight", "suspected_source")
    assert classify("flight", 96, "europe", False, "economy") == ("flight", "none")


def test_cruise_complete_trip_includes_flights_for_independent_booking():
    port = find_port("7-night cruise from Miami")
    trip = complete_trip_cost(300, 7, port, False, "7-night cruise from Miami", None, "LT")
    labels = " ".join(p["label"] for p in trip["parts"])
    assert trip["kind"] == "independent_combination"
    assert "flight" in labels.lower() and trip["total_pp"] > 300 + 500
    pkg = complete_trip_cost(900, 7, port, True, "fly & cruise incl. flights", None, "LT")
    assert pkg["kind"] == "fly_cruise_package" and pkg["total_pp"] < 900 + 200


def test_cheap_cruise_far_away_is_not_exceptional():
    """A €300 Caribbean cruise is not a deal from Vilnius once flights are added."""
    port = find_port("Caribbean cruise from Barbados")
    trip = complete_trip_cost(300, 7, port, False, "", None, "LT")
    ref = cruise_reference_total(port, 7, False, "LT")
    r = score(_si(subtype="cruise", region="caribbean", price_eur=trip["total_pp"], nights=7, cruise_reference=ref))
    assert r["score"] < 85


def test_duffel_search_picks_cheapest_offer(monkeypatch):
    from app import duffel

    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"data": {"offers": [
                {"total_amount": "310.00", "total_currency": "EUR", "owner": {"name": "airBaltic"},
                 "slices": [{"segments": [1]}, {"segments": [1, 2]}]},
                {"total_amount": "289.50", "total_currency": "EUR", "owner": {"name": "LOT"},
                 "slices": [{"segments": [1]}, {"segments": [1]}]},
            ]}}
    sent = {}
    monkeypatch.setattr(duffel.httpx, "post", lambda url, **kw: sent.update(kw) or R())
    res = duffel.search("VNO", "BKK", "2027-02-01", "2027-02-15")
    assert res == {"price_eur": 289.5, "airline": "LOT", "stops": 0}
    assert len(sent["json"]["data"]["slices"]) == 2


def test_positioning_adds_flight_from_home_hub():
    from app import positioning
    from app.db import init_db, session_scope
    init_db()
    with session_scope() as s:
        home = positioning.plan(s, "VNO")
        near = positioning.plan(s, "KUN")
        far = positioning.plan(s, "ARN")
        unknown = positioning.plan(s, "EU*")
    assert home["mode"] == "home" and home["price"] == 0
    assert near["mode"] == "nearby" and near["hub"] == "VNO"
    assert far["mode"] == "flight" and far["price"] > 0 and far["hub"] in ("RIX", "VNO", "WAW", "VIE")
    assert unknown is None


def test_iso_dates_trigger_christmas_season():
    from app.scoring import _with_month_names
    assert "dec" in _with_month_names("2027-12-22 – 2028-01-05")


def test_cruise_never_flagged_as_statistical_error_fare():
    from app.scoring import classify
    assert classify("cruise", 99, "caribbean", False, "economy")[1] == "none"
    assert classify("flight", 96, "se_asia", False, "economy")[1] == "suspected_statistical"


def test_fresh_live_price_replaces_cached_price():
    from datetime import timedelta
    from app.db import Offer, utcnow
    from app.scanner import effective_price
    o = Offer(price_eur=199.0, live_status="higher", live_price_eur=499.0, live_checked_at=utcnow())
    assert effective_price(o) == 499.0
    o.live_checked_at = utcnow() - timedelta(days=2)  # stale check is ignored
    assert effective_price(o) == 199.0
    o.live_status, o.live_checked_at = "unavailable", utcnow()
    assert effective_price(o) == 199.0


def test_cruise_between_two_ports_prices_two_one_way_flights():
    from app.cruise import complete_trip_cost, find_ports
    start, end = find_ports("Western Mediterranean cruise from Naples to Genoa for €379 (7 nights)")
    assert (start.key, end.key) == ("naples", "genoa")
    one = complete_trip_cost(379, 7, start, False, "cruise", None, "", end)
    rt = complete_trip_cost(379, 7, start, False, "cruise", None, "", None)
    assert one["end_port"] == "Genoa" and "One-way" in one["parts"][2]["label"]
    assert one["total_pp"] > rt["total_pp"]  # two one-ways cost a bit more than one return
    assert find_ports("Eastern Mediterranean cruise from/to Split for €539")[1] is None


def test_package_with_deposit_price_loses_confidence():
    from app.parsing import parse_deal
    d = parse_deal("Antalya: deposit only €99 for 7 nights all inclusive with flights from Warsaw", "", "PL*")
    full = parse_deal("Antalya: 7 nights all inclusive with flights from Warsaw for €499 (deposit €99)", "", "PL*")
    assert full.price_amount == 499 and not any("deposit" in n for n in full.notes)
    assert d is not None and d.confidence < 0.8
    assert any("deposit" in n for n in d.notes)


def test_positioning_uses_fare_matched_to_deal_dates():
    from app import positioning
    from app.db import PositioningFare, init_db, session_scope
    init_db()
    key = positioning.dated_key("VNO", "ARN", "2031-02-14", "2031-02-28")
    try:
        with session_scope() as s:
            s.merge(PositioningFare(key=key, hub="VNO", gateway="ARN", price_eur=58.0, airline="BT",
                                    depart_date="2031-02-13", return_date="2031-02-28"))
        with session_scope() as s:
            p = positioning.plan(s, "ARN", ["ARN"], True, "2031-02-14", "2031-02-28")
        assert p["date_matched"] and p["hub"] == "VNO"
        assert p["price"] == 58 + positioning.HOTEL_NIGHT  # flight on matching dates + night before long-haul
        assert positioning._day_before("2031-03-01") == "2031-02-28"
    finally:
        with session_scope() as s:
            row = s.get(PositioningFare, key)
            if row:
                s.delete(row)


def test_worldwide_cruises_are_kept_but_foreign_flights_are_not():
    from app.parsing import parse_deal
    d = parse_deal("7-night Bahamas cruise from Miami for $299", "", "EU*")
    assert d is not None and d.subtype == "cruise" and d.dest.key == "bahamas" and d.cruise_port.key == "miami"
    assert parse_deal("Flights from Bangkok to Oslo for €300", "", "EU*") is None
