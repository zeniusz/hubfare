"""Runtime configuration. All secrets come from environment variables (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() or default


DATA_DIR = Path(env("DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = env("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'travelradar.db').as_posix()}")

# Wikimedia and some feeds require a descriptive User-Agent with a contact URL (set CONTACT_URL to your repo/site)
CONTACT_URL = env("CONTACT_URL", "https://github.com/zeniusz/travel-edge")
USER_AGENT = env("USER_AGENT", f"TravelEdge/1.0 (self-hosted travel deal monitor; {CONTACT_URL}) python-httpx")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:8000")
TIMEZONE = env("TIMEZONE", "Europe/Vilnius")
DIGEST_HOUR = int(env("DIGEST_HOUR", "8"))
INSTANT_MIN_SCORE = int(env("INSTANT_MIN_SCORE", "85"))

# Optional data providers
TRAVELPAYOUTS_TOKEN = env("TRAVELPAYOUTS_TOKEN")
TRAVELPAYOUTS_MARKER = env("TRAVELPAYOUTS_MARKER")
TRAVELPAYOUTS_MAX_AIRPORTS = int(env("TRAVELPAYOUTS_MAX_AIRPORTS", "12"))
# Duffel: live airline prices, used to re-check the best flight deals before you see them
DUFFEL_TOKEN = env("DUFFEL_TOKEN")
DUFFEL_MAX_CHECKS_PER_DAY = int(env("DUFFEL_MAX_CHECKS_PER_DAY", "10"))  # keep the search-to-book ratio low
DUFFEL_MIN_SCORE = int(env("DUFFEL_MIN_SCORE", "85"))
# Flight deals from blogs (TravelFree, Fly4free…) are shown next to fare-API flights; set false to use APIs only
RSS_FLIGHTS = env("RSS_FLIGHTS", "true").lower() in ("1", "true", "yes")

# Notifications (each channel is enabled only when its credentials are present)
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
SMTP_HOST = env("SMTP_HOST")
SMTP_PORT = int(env("SMTP_PORT", "587"))
SMTP_USER = env("SMTP_USER")
SMTP_PASSWORD = env("SMTP_PASSWORD")
SMTP_FROM = env("SMTP_FROM")
ALERT_EMAIL_TO = env("ALERT_EMAIL_TO")
NTFY_TOPIC_URL = env("NTFY_TOPIC_URL")  # e.g. https://ntfy.sh/my-secret-topic-name
WHATSAPP_TOKEN = env("WHATSAPP_TOKEN")  # Meta WhatsApp Cloud API
WHATSAPP_PHONE_NUMBER_ID = env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TO = env("WHATSAPP_TO")
MESSENGER_PAGE_TOKEN = env("MESSENGER_PAGE_TOKEN")  # Facebook Messenger Send API
MESSENGER_PSID = env("MESSENGER_PSID")
WEBHOOK_URL = env("WEBHOOK_URL")

# AI assistant (Anthropic). Falls back to a deterministic answerer without a key.
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", "claude-opus-5-5")
