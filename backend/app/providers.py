"""Data providers. Add a new source by appending to PROVIDERS (RSS) or writing a
``fetch_<key>`` function that returns ``RawItem``s and registering it in FETCHERS.

Only sources that permit automated access are used: public RSS feeds whose
robots.txt allows the feed URL, and official APIs with a token. Sources that
block automated readers (HTTP 401/403) or require a commercial agreement are
listed in UNAVAILABLE_SOURCES and are never scraped.
"""
from __future__ import annotations

import calendar
import hashlib
import logging
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import httpx

from .config import TRAVELPAYOUTS_MARKER, TRAVELPAYOUTS_TOKEN, USER_AGENT

log = logging.getLogger(__name__)


@dataclass
class RawItem:
    provider_key: str
    external_id: str
    url: str
    title: str
    summary: str = ""
    published: datetime | None = None
    image_url: str = ""
    default_origin: str = "EU*"
    structured: dict | None = None  # API providers supply parsed fields directly


@dataclass
class ProviderDef:
    key: str
    name: str
    kind: str
    url: str
    homepage: str
    market: str           # default departure market when a post does not name an airport
    interval: int         # minutes
    priority: bool = False
    requires: str = ""
    notes: str = ""
    cost_per_call_eur: float = 0.0
    focus: list[str] = field(default_factory=list)


PROVIDERS: list[ProviderDef] = [
    ProviderDef("travelfree", "TravelFree.info", "rss", "https://travelfree.info/feed/", "https://travelfree.info",
                "EU*", 45, True, notes="Baltic & CEE-focused flight deals (Riga, Vilnius, Warsaw…)", focus=["flight"]),
    ProviderDef("fly4free", "Fly4free", "rss", "https://www.fly4free.com/feed/", "https://www.fly4free.com",
                "EU*", 45, True, notes="European flight deals, error fares and package holidays", focus=["flight", "package", "cruise"]),
    ProviderDef("traveldealz", "Travel-Dealz", "rss", "https://travel-dealz.com/feed/", "https://travel-dealz.com",
                "EU*", 60, True, notes="Premium cabin, error fares and cruise deals from Europe", focus=["flight", "cruise"]),
    ProviderDef("fly4free_pl", "Fly4free.pl", "rss", "https://www.fly4free.pl/feed/", "https://www.fly4free.pl",
                "PL*", 120, notes="Polish market: flights + packages from Polish airports", focus=["flight", "package"]),
    ProviderDef("wakacyjnipiraci", "Wakacyjni Piraci", "rss", "https://www.wakacyjnipiraci.pl/feed", "https://www.wakacyjnipiraci.pl",
                "PL*", 120, notes="Polish package holidays and flash sales", focus=["package"]),
    ProviderDef("urlaubspiraten", "Urlaubspiraten", "rss", "https://www.urlaubspiraten.de/feed", "https://www.urlaubspiraten.de",
                "DE*", 120, notes="German/Austrian package holidays and cruises", focus=["package", "cruise"]),
    ProviderDef("holidaypirates", "HolidayPirates", "rss", "https://www.holidaypirates.com/feed", "https://www.holidaypirates.com",
                "GB*", 120, notes="UK-market packages and cruises (prices converted from GBP)", focus=["package", "cruise"]),
    ProviderDef("makalius", "Makalius", "rss", "https://www.makalius.lt/feed/", "https://www.makalius.lt",
                "LT*", 120, notes="Lithuanian tour operator – packages from Vilnius/Kaunas", focus=["package", "cruise"]),
    ProviderDef("travelpayouts", "Aviasales Data API (Travelpayouts)", "api",
                "https://api.travelpayouts.com/aviasales/v3/prices_for_dates", "https://www.travelpayouts.com",
                "EU*", 60, True, requires="TRAVELPAYOUTS_TOKEN",
                notes="Cheapest fares found by Aviasales users in the last 48h, per departure airport, to any destination. "
                      "Free with a Travelpayouts partner account.", focus=["flight"]),
]
PROVIDER_BY_KEY = {p.key: p for p in PROVIDERS}

# Researched, but not integrated – shown in Settings for transparency.
UNAVAILABLE_SOURCES = [
    {"name": "Secret Flying", "reason": "Feed returns HTTP 403 to automated readers – not bypassed."},
    {"name": "Flynous", "reason": "Feed returns HTTP 403 to automated readers – not bypassed."},
    {"name": "Urlaubsguru", "reason": "Feed returns HTTP 401 – not bypassed."},
    {"name": "Amadeus Self-Service API", "reason": "Self-service portal and keys were shut down on 17 July 2026; Enterprise access needs a contract."},
    {"name": "Kiwi.com Tequila", "reason": "Public sign-ups closed; partner agreement required."},
    {"name": "Skyscanner", "reason": "Partner API only (commercial agreement)."},
    {"name": "Google Flights", "reason": "No public API; scraping prohibited by ToS."},
    {"name": "Novaturas, Tez Tour, Join UP!, TUI, ITAKA, Rainbow, Exim Tours, DERTOUR, Kelionių akademija",
     "reason": "No public feed/API found; affiliate/XML feeds are available via partner programmes "
               "(e.g. Awin, Travelpayouts, direct agency agreements). Add credentials to enable."},
    {"name": "lastminute.com, Restplatzbörse", "reason": "No permitted automated feed; affiliate programme required."},
]

_robots_cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}


def robots_allows(url: str, client: httpx.Client) -> bool:
    base = "/".join(url.split("/")[:3])
    cached = _robots_cache.get(base)
    if not cached or cached[0] < time.time() - 86400:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = client.get(base + "/robots.txt")
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            rp.parse([])
        _robots_cache[base] = (time.time(), rp)
    return _robots_cache[base][1].can_fetch(USER_AGENT, url)


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, application/json"},
                        timeout=25, follow_redirects=True)


def _entry_image(e) -> str:
    for key in ("media_content", "media_thumbnail"):
        for m in e.get(key, []) or []:
            if m.get("url"):
                return m["url"]
    for link in e.get("links", []):
        if link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    html = (e.get("content") or [{}])[0].get("value", "") if e.get("content") else e.get("summary", "")
    import re
    m = re.search(r'<img[^>]+src="([^"]+)"', html or "")
    return m.group(1) if m else ""


def fetch_rss(p: ProviderDef) -> tuple[list[RawItem], int]:
    with _client() as c:
        if not robots_allows(p.url, c):
            raise PermissionError(f"robots.txt disallows {p.url}")
        r = c.get(p.url)
        r.raise_for_status()
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Invalid feed: {feed.bozo_exception}")
    items = []
    for e in feed.entries:
        pub = None
        if e.get("published_parsed"):
            pub = datetime.fromtimestamp(calendar.timegm(e.published_parsed), tz=timezone.utc).replace(tzinfo=None)
        summary = e.get("summary", "")
        if e.get("content"):
            summary = summary + " " + e.content[0].get("value", "")[:1500]
        items.append(RawItem(p.key, e.get("id") or e.get("link", ""), e.get("link", ""), e.get("title", ""),
                             summary, pub, _entry_image(e), p.market))
    return items, 1


def fetch_travelpayouts(p: ProviderDef, origins: list[str]) -> tuple[list[RawItem], int]:
    if not TRAVELPAYOUTS_TOKEN:
        raise LookupError("needs_credentials")
    from .geo import IATA_TO_DEST
    items: list[RawItem] = []
    calls = 0
    with _client() as c:
        for origin in origins:
            params = {"origin": origin, "currency": "eur", "sorting": "price", "direct": "false", "limit": 300,
                      "one_way": "false", "unique": "true", "page": 1}
            r = c.get(p.url, params=params, headers={"X-Access-Token": TRAVELPAYOUTS_TOKEN})
            calls += 1
            if r.status_code == 429:
                time.sleep(5)
                continue
            r.raise_for_status()
            for t in r.json().get("data", []):
                dest = IATA_TO_DEST.get(t.get("destination"))
                if not dest:
                    continue
                link = "https://www.aviasales.com" + t.get("link", "")
                if TRAVELPAYOUTS_MARKER:
                    link += ("&" if "?" in link else "?") + f"marker={TRAVELPAYOUTS_MARKER}"
                dep, ret = (t.get("departure_at") or "")[:10], (t.get("return_at") or "")[:10]
                ext = hashlib.sha1(f"{origin}{t.get('destination')}{dep}{ret}".encode()).hexdigest()
                items.append(RawItem(
                    p.key, ext, link,
                    f"{origin} → {dest.name}: €{t['price']:.0f} return with {t.get('airline', '')}",
                    f"{t.get('transfers', 0)} stop(s) out, {t.get('return_transfers', 0)} back",
                    None, "", origin,
                    structured={"origin": origin, "dest_key": dest.key, "price": float(t["price"]), "currency": "EUR",
                                "depart_date": dep, "return_date": ret, "airline": t.get("airline", ""), "dest_iata": t.get("destination", ""),
                                "transfers": t.get("transfers", 0)},
                ))
            time.sleep(0.4)  # stay far below the documented rate limit
    return items, calls
