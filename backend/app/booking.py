"""Booking-search links: send people straight to Skyscanner / Google Flights / Aviasales instead of the blog.

Two kinds of links:
* links found inside the deal post itself (the exact searches the editor used, unwrapped from affiliate redirects)
* links HubFare builds from the route and dates it extracted

A search link opens a live search for that route and dates – it is not a guaranteed booking of the advertised price.
Nothing is ever booked automatically.
"""
from __future__ import annotations

import html as _html
import logging
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import httpx

from .config import USER_AGENT

log = logging.getLogger(__name__)

BOOKING_SITES = {
    "skyscanner": "Skyscanner", "google.": "Google Flights", "aviasales": "Aviasales", "kiwi.com": "Kiwi.com",
    "momondo": "Momondo", "kayak": "Kayak", "esky": "eSky",
}
_A = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
# Skyscanner uses its own ids for multi-airport cities
SKY_CITY = {"NYC": "nyca", "TYO": "tyoa", "LON": "lond", "PAR": "pari", "ROM": "rome", "MIL": "mila", "RIO": "rioa",
            "SAO": "saoa", "MOW": "mosc", "OSA": "osaa", "SEL": "sela", "BJS": "bjsa", "STO": "stoc", "BUH": "buha",
            "CHI": "chia", "WAS": "wasa", "YTO": "ytoa", "BER": "ber"}


def _site(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    for key, name in BOOKING_SITES.items():
        if key in host and (key != "google." or "/travel" in path or "/flights" in path):
            return name
    return None


def _unwrap(url: str) -> str:
    """Affiliate redirects (…?u=https%3A%2F%2Fwww.skyscanner…) → the real search URL."""
    url = _html.unescape(url)
    for _ in range(2):
        q = parse_qs(urlparse(url).query)
        inner = next((v[0] for k in ("u", "url", "murl", "dest", "destination", "redirect") for v in [q.get(k)] if v), None)
        if inner and inner.startswith("http"):
            url = unquote(inner) if "%3A" in inner else inner
        else:
            break
    return url


def _label_from_skyscanner(url: str) -> str:
    m = re.search(r"/transport/flights/([a-z]{3,4})/([a-z]{3,4})/(\d{6})?/?(\d{6})?", url, re.I)
    if not m:
        return ""
    o, d, out, back = m.groups()
    fmt = lambda s: f"{int(s[4:6])} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(s[2:4]) - 1]}" if s else ""
    dates = f" · {fmt(out)}" + (f" – {fmt(back)}" if back else "") if out else ""
    return f"{o.upper()} → {d.upper()}{dates}"


class _Anchors(HTMLParser):
    """Collect (href, text) for every <a> – robust to quoting and attribute order, unlike a regex."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href") or "", []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text)))
            self._href = None


_TRACKING = re.compile(r"^(utm_|associateid|affilid|mediaid|ref$|clickref|irgwc|irclickid|gclid|fbclid)", re.I)


def _dedupe_key(url: str) -> str:
    """Same search = same host, path and query minus tracking params (two different routes never collide)."""
    p = urlparse(url)
    q = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k))
    return urlunparse((p.scheme.lower(), p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", urlencode(q), ""))


def extract_links(html: str, limit: int = 12) -> list[dict]:
    """Booking-search links inside a post, deduplicated, affiliate wrappers removed."""
    out, seen = [], set()
    parser = _Anchors()
    try:
        parser.feed(html or "")
    except Exception:  # malformed HTML: keep what was parsed
        pass
    for href, text in parser.links:
        url = _unwrap(href)
        site = _site(url)
        if not site:
            continue
        key = _dedupe_key(url)
        if key in seen:
            continue
        seen.add(key)
        label = _html.unescape(_TAGS.sub("", text)).strip()[:60]
        if site == "Skyscanner":
            label = _label_from_skyscanner(url) or label
        out.append({"site": site, "label": label or site, "url": url, "from_post": True})
        if len(out) >= limit:
            break
    return out


def fetch_article_links(url: str, client: httpx.Client) -> list[dict]:
    r = client.get(url)
    r.raise_for_status()
    return extract_links(r.text)


# ---------------------------------------------------------------- built links
def _ymd(iso: str) -> str:
    return iso[2:4] + iso[5:7] + iso[8:10] if iso and len(iso) >= 10 else ""


def skyscanner_url(org: str, dst: str, dep: str = "", ret: str = "") -> str:
    o, d = SKY_CITY.get(org, org.lower()), SKY_CITY.get(dst, dst.lower())
    base = f"https://www.skyscanner.net/transport/flights/{o}/{d}/"
    if dep:
        base += f"{_ymd(dep)}/" + (f"{_ymd(ret)}/" if ret else "")
    return base + f"?adultsv2=1&cabinclass=economy&rtn={1 if ret or not dep else 0}"


def google_url(org: str, dst: str, dep: str = "", ret: str = "") -> str:
    q = f"Flights from {org} to {dst}"
    if dep:
        q += f" on {dep[:10]}" + (f" through {ret[:10]}" if ret else " one way")
    return "https://www.google.com/travel/flights?q=" + quote(q)


def aviasales_url(org: str, dst: str, dep: str, ret: str = "") -> str:
    dd = lambda s: s[8:10] + s[5:7]
    return f"https://www.aviasales.com/search/{org}{dd(dep)}{dst}{dd(ret) if ret else ''}1"


def build_links(origins: list[str], dst: str, dep: str = "", ret: str = "", connection: dict | None = None,
                max_routes: int = 3) -> list[dict]:
    """Search links for each departure airport (and the connecting leg from your hub)."""
    links = []
    for org in [o for o in origins if o and not o.endswith("*")][:max_routes]:
        label = f"{org} → {dst}" + (f" · {dep[:10]}" + (f" – {ret[:10]}" if ret else "") if dep else " · any dates")
        links.append({"site": "Skyscanner", "label": label, "url": skyscanner_url(org, dst, dep, ret)})
        links.append({"site": "Google Flights", "label": label, "url": google_url(org, dst, dep, ret)})
        if dep:
            links.append({"site": "Aviasales", "label": label, "url": aviasales_url(org, dst, dep, ret)})
    if connection and connection.get("mode") == "flight" and connection.get("gateway"):
        h, g = connection["hub"], connection["gateway"]
        # the connecting ticket may leave the day before / come back the day after (hotel night)
        cdep, cret = connection.get("conn_depart") or dep, connection.get("conn_return") or ret
        links.append({"site": "Skyscanner", "label": f"Connecting flight {h} → {g}" + (f" · {cdep[:10]}" if cdep else ""),
                      "connection": True, "url": skyscanner_url(h, g, cdep, cret)})
    return links


def for_origin(links: list[dict], code: str) -> list[dict]:
    """Searches for this departure airport first (post links are labelled 'VIE → MRU · …')."""
    return sorted(links or [], key=lambda l: not (l.get("label") or "").upper().startswith(code.upper()))


def enrich_from_articles(limit: int = 10) -> dict:
    """For the best blog flight deals: read the article once and keep the booking links it contains."""
    from .db import Offer, session_scope
    from .providers import PROVIDER_BY_KEY, robots_allows
    out = {"checked": 0, "found": 0}
    with session_scope() as s:
        rows = (s.query(Offer).filter(Offer.status == "active", Offer.subtype == "flight", Offer.deal_score >= 70,
                                      Offer.booking_links.is_(None))
                .order_by(Offer.deal_score.desc()).limit(limit * 2).all())
        targets, seen_urls = [], set()
        for o in rows:
            if PROVIDER_BY_KEY.get(o.provider_key) and PROVIDER_BY_KEY[o.provider_key].kind == "rss" \
                    and o.source_url not in seen_urls and len(targets) < limit:
                seen_urls.add(o.source_url)
                targets.append((o.id, o.source_url))
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as c:
        for oid, url in targets:
            links = []
            try:
                if robots_allows(url, c):
                    links = fetch_article_links(url, c)
            except Exception as e:  # keep going; the deal still gets HubFare-built links
                log.info("article links %s: %s", url, e)
            with session_scope() as s:
                for row in s.query(Offer).filter(Offer.source_url == url, Offer.booking_links.is_(None)).all():
                    row.booking_links = for_origin(links, row.origin_code)
            out["checked"] += 1
            out["found"] += bool(links)
            time.sleep(2.0)  # polite: one article every 2 s
    return out
