"""Alert rules, de-duplicated delivery and notification channels.

High-priority matches (score >= INSTANT_MIN_SCORE or suspected error fares) are
sent immediately; everything else that matches goes into the daily digest.
A (rule, offer, channel) combination is only ever sent once. Nothing is ever
booked or purchased automatically.
"""
from __future__ import annotations

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy.exc import IntegrityError

from . import config as C
from .db import AlertRule, Notification, Offer, SessionLocal, session_scope, utcnow
from .geo import ORIGIN_PLACES

log = logging.getLogger(__name__)

CATEGORY_LABEL = {"flight": "Flight", "package": "Holiday package", "cruise": "Cruise + flights"}


def channel_status() -> dict:
    return {
        "inapp": {"label": "In-app & browser notifications", "configured": True, "needs": ""},
        "telegram": {"label": "Telegram", "configured": bool(C.TELEGRAM_BOT_TOKEN and C.TELEGRAM_CHAT_ID),
                     "needs": "TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"},
        "email": {"label": "Email (SMTP)", "configured": bool(C.SMTP_HOST and C.ALERT_EMAIL_TO and C.SMTP_FROM),
                  "needs": "SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, ALERT_EMAIL_TO"},
        "ntfy": {"label": "Mobile push (ntfy)", "configured": bool(C.NTFY_TOPIC_URL), "needs": "NTFY_TOPIC_URL"},
        "whatsapp": {"label": "WhatsApp (Meta Cloud API)",
                     "configured": bool(C.WHATSAPP_TOKEN and C.WHATSAPP_PHONE_NUMBER_ID and C.WHATSAPP_TO),
                     "needs": "WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_TO (approved Business account)"},
        "messenger": {"label": "Facebook Messenger", "configured": bool(C.MESSENGER_PAGE_TOKEN and C.MESSENGER_PSID),
                      "needs": "MESSENGER_PAGE_TOKEN, MESSENGER_PSID (approved Page app)"},
        "webhook": {"label": "Webhook (Slack/Discord/Zapier…)", "configured": bool(C.WEBHOOK_URL), "needs": "WEBHOOK_URL"},
    }


def _ago(dt) -> str:
    if not dt:
        return "not yet verified"
    mins = int((utcnow() - dt).total_seconds() // 60)
    if mins < 60:
        return f"{mins} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} days ago"


def format_offer(o: Offer) -> tuple[str, str]:
    b = o.score_breakdown or {}
    flag = {"suspected_source": "🚨 SUSPECTED ERROR FARE", "suspected_statistical": "🚨 POSSIBLE PRICING ERROR (unconfirmed)"}.get(o.error_fare_flag)
    head = flag or ("🚨 EXCEPTIONAL TRAVEL DEAL" if o.deal_score >= 85 else "✈️ TRAVEL DEAL")
    title = f"{head} — {o.deal_score}/100"
    lines = [title, f"{o.origin_label} → {o.dest_label}"]
    if o.subtype == "package":
        what = f"{o.nights or '?'} nights with return flights and accommodation"
    elif o.subtype == "cruise":
        tc = b.get("trip_cost", {})
        what = f"{o.nights or '?'}-night cruise" + (" (fly & cruise package)" if tc.get("kind") == "fly_cruise_package"
                                                     else " + independently booked flights")
    else:
        what = f"{'Return' if o.trip_type == 'return' else 'One-way'} flight, {o.cabin}"
    lines.append(what)
    basis = {"per_person": "per person", "total": "total for 2", "per_night": "per night"}.get(o.price_basis, "")
    lines.append(f"Price: €{o.price_eur:,.0f} {basis}" + (f" (orig. {o.price_original:,.0f} {o.currency})" if o.currency != "EUR" else ""))
    if o.subtype == "cruise" and b.get("trip_cost"):
        lines.append(f"Estimated complete trip: €{b['trip_cost']['total_pp']:,.0f} per person")
    pos = b.get("positioning") or {}
    if pos.get("mode") == "flight" and o.subtype != "cruise":
        lines.append(f"+ {'≈' if pos.get('estimated') else ''}€{pos['price']} return flight {pos['hub_name']} ⇄ {pos.get('gateway_name', '')} "
                     f"(separate ticket) = €{o.price_eur + pos['price']:,.0f} from {pos['hub_name']}")
    elif pos.get("mode") == "nearby":
        lines.append(f"Departure is {pos['km']} km from {pos['hub_name']} (train/bus)")
    lines.append(f"Typical comparable price from your hub: €{o.reference_price:,.0f}")
    lines.append(f"Estimated savings: €{o.savings_eur:,.0f} ({o.discount_pct:.0f}%)")
    if o.travel_window or o.depart_date:
        lines.append(f"Travel: {o.depart_date or o.travel_window}" + (f" → {o.return_date}" if o.return_date else ""))
    if o.live_status == "confirmed":
        lines.append(f"✅ Live airline price confirmed: €{o.live_price_eur:,.0f} ({o.live_detail})")
    if o.stars:
        lines.append(f"Hotel: {o.stars}-star")
    if o.board:
        lines.append(f"Meals: {o.board}")
    from .providers import PROVIDER_BY_KEY
    lines.append(f"Provider: {PROVIDER_BY_KEY[o.provider_key].name if o.provider_key in PROVIDER_BY_KEY else o.provider_key}")
    lines.append(f"Last verified: {_ago(o.last_verified_at or o.last_seen_at)}")
    lines.append(f"View offer: {o.source_url}")
    lines.append("Prices change quickly – check the final price before booking. TravelEdge never books automatically.")
    return title, "\n".join(lines)


# ------------------------------------------------------------------ channels
def _send(channel: str, title: str, body: str, url: str = "") -> None:
    if channel == "inapp":
        return  # stored in the notifications table; the dashboard shows it and fires a browser notification
    if channel == "telegram":
        r = httpx.post(f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/sendMessage",
                       json={"chat_id": C.TELEGRAM_CHAT_ID, "text": body, "disable_web_page_preview": False}, timeout=15)
        r.raise_for_status()
    elif channel == "email":
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = title, C.SMTP_FROM, C.ALERT_EMAIL_TO
        msg.set_content(body)
        with smtplib.SMTP(C.SMTP_HOST, C.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            if C.SMTP_USER:
                smtp.login(C.SMTP_USER, C.SMTP_PASSWORD)
            smtp.send_message(msg)
    elif channel == "ntfy":
        headers = {"Title": title.encode("utf-8", "ignore").decode("latin-1", "ignore")[:200], "Priority": "high"}
        if url:
            headers["Click"] = url
        httpx.post(C.NTFY_TOPIC_URL, content=body.encode("utf-8"), headers=headers, timeout=15).raise_for_status()
    elif channel == "whatsapp":
        # Free-form text works inside the 24h customer-service window; outside it Meta requires an approved template.
        r = httpx.post(f"https://graph.facebook.com/v21.0/{C.WHATSAPP_PHONE_NUMBER_ID}/messages",
                       headers={"Authorization": f"Bearer {C.WHATSAPP_TOKEN}"},
                       json={"messaging_product": "whatsapp", "to": C.WHATSAPP_TO, "type": "text",
                             "text": {"body": body[:4000], "preview_url": True}}, timeout=15)
        r.raise_for_status()
    elif channel == "messenger":
        r = httpx.post("https://graph.facebook.com/v21.0/me/messages", params={"access_token": C.MESSENGER_PAGE_TOKEN},
                       json={"recipient": {"id": C.MESSENGER_PSID}, "messaging_type": "MESSAGE_TAG",
                             "tag": "ACCOUNT_UPDATE", "message": {"text": body[:2000]}}, timeout=15)
        r.raise_for_status()
    elif channel == "webhook":
        httpx.post(C.WEBHOOK_URL, json={"title": title, "text": body, "url": url}, timeout=15).raise_for_status()
    else:
        raise ValueError(f"unknown channel {channel}")


def deliver(rule_id: int | None, dedupe_key: str, offer_id: int | None, channels: list[str], title: str, body: str,
            kind: str, url: str = "") -> list[dict]:
    status = channel_status()
    results = []
    for ch in channels:
        s = SessionLocal()
        try:
            n = Notification(rule_id=rule_id, dedupe_key=dedupe_key, offer_id=offer_id, channel=ch, kind=kind,
                             title=title[:300], body=body, status="queued")
            s.add(n)
            s.commit()  # unique constraint = never send the same deal twice per rule & channel
        except IntegrityError:
            s.rollback()
            s.close()
            results.append({"channel": ch, "status": "duplicate_skipped"})
            continue
        try:
            if not status.get(ch, {}).get("configured"):
                n.status, n.error = "skipped", f"channel not configured ({status.get(ch, {}).get('needs', '')})"
            else:
                for attempt in range(3):
                    try:
                        _send(ch, title, body, url)
                        n.status, n.sent_at = "sent", utcnow()
                        break
                    except Exception as e:
                        n.status, n.error = "failed", f"{type(e).__name__}: {e}"[:400]
                        import time
                        time.sleep(1.5 * (attempt + 1))
            s.commit()
            results.append({"channel": ch, "status": n.status, "error": n.error})
        finally:
            s.close()
    return results


# ------------------------------------------------------------------ rules
def _origin_match(rule: AlertRule, o: Offer) -> bool:
    if not rule.origins:
        return True
    codes = set(o.origin_codes or [o.origin_code])
    if codes & set(rule.origins):
        return True
    if o.origin_code == "EU*":
        return True
    if o.origin_code.endswith("*"):
        cc = o.origin_code[:2]
        return any((ORIGIN_PLACES.get(r) and ORIGIN_PLACES[r].country == cc) or (cc == "DE" and ORIGIN_PLACES.get(r) and
                   ORIGIN_PLACES[r].country == "AT") for r in rule.origins)
    return False


def rule_matches(rule: AlertRule, o: Offer) -> bool:
    if o.duplicate_of or o.status != "active":
        return False
    if rule.categories:
        cats = set(rule.categories)
        ok = o.category in cats or ("error_fare" in cats and o.error_fare_flag != "none") or \
            ("last_minute" in cats and (o.score_breakdown or {}).get("last_minute"))
        if not ok:
            return False
    if o.deal_score < (rule.min_score or 0):
        return False
    price = (o.score_breakdown or {}).get("trip_cost", {}).get("total_pp", o.price_eur) if o.subtype == "cruise" else o.price_eur
    if rule.max_price and price > rule.max_price:
        return False
    if rule.min_discount_pct and o.discount_pct < rule.min_discount_pct:
        return False
    if rule.cabins and o.subtype == "flight" and o.cabin not in rule.cabins:
        return False
    if rule.min_nights and (o.nights or 0) < rule.min_nights and o.subtype != "flight":
        return False
    if rule.max_nights and o.nights and o.nights > rule.max_nights:
        return False
    if rule.destinations:
        targets = {d.lower() for d in rule.destinations}
        if not ({o.dest_key.lower(), o.dest_country.lower(), o.dest_region.lower(), o.dest_label.lower()} & targets):
            return False
    return _origin_match(rule, o)


def process_new_offers(offer_ids: list[int]) -> int:
    if not offer_ids:
        return 0
    sent = 0
    with session_scope() as s:
        rules = s.query(AlertRule).filter(AlertRule.enabled).all()
        offers = s.query(Offer).filter(Offer.id.in_(offer_ids)).all()
        jobs = []
        for o in offers:
            if o.live_status == "unavailable":
                continue  # no matching live offer found
            if o.subtype == "flight" and o.dest_iata and C.DUFFEL_TOKEN and o.live_status != "confirmed":
                continue  # with live checks on, flights are alerted only once the airline price is confirmed
            for r in rules:
                if not rule_matches(r, o):
                    continue
                instant = r.mode == "instant" or (r.mode == "auto" and (o.deal_score >= C.INSTANT_MIN_SCORE or o.error_fare_flag != "none"))
                if not instant:
                    continue  # picked up by the daily digest
                title, body = format_offer(o)
                jobs.append((r.id, f"offer:{o.dedupe_key}:{round(o.price_eur)}", o.id, r.channels or ["inapp"], title, body, o.source_url))
    for rid, key, oid, chans, title, body, url in jobs:
        res = deliver(rid, key, oid, chans, title, body, "instant", url)
        sent += sum(1 for x in res if x["status"] == "sent")
    return sent


def send_daily_digest() -> dict:
    since = utcnow() - timedelta(hours=24)
    out = {"rules": 0, "offers": 0}
    with session_scope() as s:
        rules = s.query(AlertRule).filter(AlertRule.enabled, AlertRule.mode != "instant").all()
        offers = s.query(Offer).filter(Offer.status == "active", Offer.first_seen_at >= since,
                                       Offer.duplicate_of.is_(None)).order_by(Offer.deal_score.desc()).all()
        jobs = []
        for r in rules:
            matched = [o for o in offers if rule_matches(r, o) and o.live_status != "unavailable"][:12]
            if not matched:
                continue
            lines = [f"TravelEdge daily digest — {len(matched)} new deal(s) for “{r.name}”", ""]
            for o in matched:
                total = (o.score_breakdown or {}).get("effective_total") or o.price_eur
                lines.append(f"• {o.deal_score}/100  {o.origin_label} → {o.dest_label}  €{total:,.0f}  "
                             f"(typ. €{o.reference_price:,.0f})  {o.source_url}")
            jobs.append((r.id, f"digest:{utcnow():%Y-%m-%d}", r.channels or ["inapp"], f"TravelEdge digest: {len(matched)} new deals",
                         "\n".join(lines), len(matched)))
    for rid, key, chans, title, body, n in jobs:
        deliver(rid, key, None, chans, title, body, "digest")
        out["rules"] += 1
        out["offers"] += n
    return out


def send_test(channels: list[str], offer_id: int | None = None) -> list[dict]:
    with session_scope() as s:
        o = s.get(Offer, offer_id) if offer_id else (s.query(Offer).filter(Offer.status == "active", Offer.duplicate_of.is_(None),
                                                                        Offer.is_demo.is_(False))
                                                      .order_by(Offer.deal_score.desc()).first())
        if o:
            title, body = format_offer(o)
            url = o.source_url
        else:
            title, body, url = "TravelEdge test notification", "Your notification channel works.", ""
    return deliver(None, f"test:{utcnow().isoformat()}", offer_id, channels, "[TEST] " + title, "[TEST]\n" + body, "test", url)
