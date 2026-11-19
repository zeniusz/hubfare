"""Currency conversion using the European Central Bank daily reference rates (free, no key)."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

import httpx

from .config import USER_AGENT
from .db import FxRate, session_scope, utcnow

log = logging.getLogger(__name__)
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
# Fallback only if the ECB is unreachable on first run (approximate, Nov 2026 order of magnitude)
FALLBACK = {"EUR": 1.0, "GBP": 0.86, "PLN": 4.25, "USD": 1.10, "CZK": 25.0, "HUF": 395.0, "SEK": 11.3,
            "DKK": 7.46, "NOK": 11.6, "CHF": 0.94, "TRY": 45.0}
_cache: dict[str, float] = {}


def refresh_rates(force: bool = False) -> dict[str, float]:
    with session_scope() as s:
        rows = s.query(FxRate).all()
        fresh = rows and all(r.fetched_at > utcnow() - timedelta(hours=20) for r in rows)
        if fresh and not force:
            _cache.update({r.currency: r.per_eur for r in rows})
            return dict(_cache)
        try:
            xml = httpx.get(ECB_URL, timeout=15, headers={"User-Agent": USER_AGENT}).text
            rates = {c: float(r) for c, r in re.findall(r"currency='([A-Z]{3})' rate='([\d.]+)'", xml)}
            rates["EUR"] = 1.0
            if len(rates) < 10:
                raise ValueError("ECB response incomplete")
            for c, r in rates.items():
                s.merge(FxRate(currency=c, per_eur=r, fetched_at=utcnow()))
            _cache.clear()
            _cache.update(rates)
        except Exception as e:  # keep the old rates
            log.warning("ECB rates refresh failed: %s", e)
            if not _cache:
                _cache.update({r.currency: r.per_eur for r in rows} or FALLBACK)
    return dict(_cache)


def to_eur(amount: float, currency: str) -> float:
    if currency.upper() == "EUR":
        return round(amount, 2)
    if not _cache:
        refresh_rates()
    rate = _cache.get(currency.upper()) or FALLBACK.get(currency.upper())
    if not rate:
        return amount
    return round(amount / rate, 2)
