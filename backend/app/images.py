"""Destination photography via the Wikipedia REST summary API (free, no key, CC-licensed images).
Used only when the deal source does not supply its own image."""
from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import quote

import httpx

from .config import USER_AGENT
from .db import GeoCache, session_scope, utcnow

log = logging.getLogger(__name__)

# Better-looking Wikipedia articles for some destinations
WIKI_TITLE = {
    "colombo": "Sri Lanka", "maldives": "Maldives", "bangkok": "Bangkok", "thailand": "Phi Phi Islands",
    "phuket": "Phuket province", "bali": "Bali", "tokyo": "Tokyo", "japan": "Mount Fuji", "zanzibar": "Zanzibar",
    "canaries": "Tenerife", "egypt": "Hurghada", "capeverde": "Cape Verde", "caribbean": "Caribbean",
    "stlucia": "Saint Lucia", "cancun": "Cancún", "puntacana": "Punta Cana", "riodejaneiro": "Rio de Janeiro",
    "saopaulo": "São Paulo", "newyork": "New York City", "hongkong": "Hong Kong", "sydney": "Sydney",
    "auckland": "New Zealand", "seychelles": "Seychelles", "mauritius": "Mauritius", "lapland": "Lapland (Finland)",
    "usa": "United States", "shanghai": "Shanghai", "jakarta": "Indonesia", "kualalumpur": "Kuala Lumpur",
    "vietnam": "Ha Long Bay", "aruba": "Curaçao", "mallorca": "Mallorca", "madeira": "Madeira", "iceland": "Iceland",
    "kazakhstan": "Almaty", "taipei": "Taipei", "toronto": "Toronto", "miami": "Miami", "losangeles": "Los Angeles",
    # country-level destinations: use a scenic article (country articles lead with a flag or map)
    "cyprus": "Ayia Napa", "malta": "Valletta", "barbados": "Bridgetown", "tropea": "Tropea", "sardinia": "Costa Smeralda",
    "seychelles": "La Digue", "india": "Taj Mahal", "kathmandu": "Kathmandu", "nairobi": "Maasai Mara",
    "tanzania": "Mount Kilimanjaro", "capetown": "Table Mountain", "namibia": "Sossusvlei", "greece": "Santorini",
    "croatia": "Dubrovnik", "bulgaria": "Nesebar", "montenegro": "Kotor", "albania": "Berat", "norway": "Geirangerfjord",
    "austria_alps": "Innsbruck", "oman": "Muscat", "jordan": "Petra", "qatar": "Doha", "dubai": "Dubai", "georgia": "Tbilisi",
    "uzbekistan": "Registan", "kyrgyzstan": "Issyk-Kul", "pakistan": "Hunza Valley", "ethiopia": "Lalibela", "senegal": "Dakar",
    "madagascar": "Avenue of the Baobabs", "manila": "El Nido, Palawan", "cambodia": "Angkor Wat", "bogota": "Cartagena, Colombia",
    "lima": "Machu Picchu", "santiago": "Torres del Paine National Park", "quito": "Galápagos Islands", "buenosaires": "Buenos Aires",
    "jamaica": "Montego Bay", "havana": "Havana", "morocco": "Marrakesh", "tunisia": "Sidi Bou Said", "zanzibar": "Stone Town",
    "singapore": "Marina Bay Sands", "seoul": "Seoul", "kualalumpur": "Petronas Towers", "colombo": "Sigiriya",
    "jakarta": "Borobudur", "mauritius": "Le Morne Brabant", "capeverde": "Santa Maria, Cape Verde", "caribbean": "Grand Anse Beach",
    "maldives": "Malé", "crete": "Chania", "bali": "Tanah Lot", "madeira": "Funchal", "aruba": "Willemstad", "rhodes": "Lindos", "antalya": "Antalya", "porto": "Porto", "algarve": "Benagil",
}


def _usable(url: str) -> bool:
    low = url.lower()
    return bool(url) and not (".svg" in low or "flag_of" in low or "locator" in low or "_map" in low or "map_of" in low
                              or "coat_of_arms" in low or "orthographic" in low)


def destination_image(key: str, name: str) -> str:
    title = WIKI_TITLE.get(key, name)
    with session_scope() as s:
        row = s.get(GeoCache, title)
        if row and (row.image_url or row.fetched_at > utcnow() - timedelta(hours=12)):
            return row.image_url
        url = ""
        try:
            r = httpx.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}",
                          headers={"User-Agent": USER_AGENT}, timeout=10, follow_redirects=True)
            if r.status_code == 200:
                j = r.json()
                orig = j.get("originalimage") or {}
                thumb = (j.get("thumbnail") or {}).get("source", "")
                # prefer a ~1280px rendition instead of a multi-MB original (Wikimedia standard thumb size)
                if orig.get("width", 0) > 1600 and thumb and "/thumb/" in thumb:
                    import re
                    url = re.sub(r"/\d+px-", "/1280px-", thumb)
                else:
                    url = orig.get("source") or thumb
                if not _usable(url) and not _usable(orig.get("source", "")):
                    url = ""
        except Exception as e:
            log.info("wiki image lookup failed for %s: %s", title, e)
        s.merge(GeoCache(name=title, image_url=url, fetched_at=utcnow()))
    if not url and title != name and key != "_fallback":
        return destination_image("_fallback", name)  # try the plain destination article
    return url
