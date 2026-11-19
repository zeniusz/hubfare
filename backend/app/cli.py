"""Command-line helpers.

    python -m app.cli scan            # run every enabled provider once
    python -m app.cli scan fly4free   # one provider
    python -m app.cli verify | expire | rescore | digest
    python -m app.cli test-notify inapp telegram
    python -m app.cli live-check       # re-check top flights with Duffel (live airline prices)
    python -m app.cli telegram-setup   # find your chat id, save it, send a test
"""
from __future__ import annotations

import json
import logging
import sys

from . import notify, scanner
from .db import Provider, init_db, session_scope

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def telegram_setup() -> None:
    """Find the chat id of whoever last messaged the bot and save it to .env."""
    import httpx

    from . import config as C

    if not C.TELEGRAM_BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN in .env first (from @BotFather).")
        return
    r = httpx.get(f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/getUpdates", timeout=15).json()
    if not r.get("ok"):
        print(f"Telegram rejected the token: {r.get('description')}")
        return
    chats = {}
    for u in r.get("result", []):
        m = u.get("message") or u.get("channel_post") or {}
        if m.get("chat"):
            c = m["chat"]
            chats[c["id"]] = c.get("title") or c.get("first_name") or c.get("username") or "chat"
    if not chats:
        print("No messages found. Open your bot in Telegram, press Start (or send any message), then run this again.")
        return
    chat_id, name = list(chats.items())[-1]
    env_path = C.ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    lines = [ln for ln in lines if not ln.startswith("TELEGRAM_CHAT_ID=")] + [f"TELEGRAM_CHAT_ID={chat_id}"]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    C.TELEGRAM_CHAT_ID = str(chat_id)
    print(f"Saved TELEGRAM_CHAT_ID={chat_id} ({name}) to .env")
    print(json.dumps(notify.send_test(["telegram"]), indent=2))


def main(argv: list[str]) -> None:
    init_db()
    scanner.ensure_seed()
    cmd = argv[0] if argv else "scan"
    if cmd == "scan":
        with session_scope() as s:
            keys = argv[1:] or [p.key for p in s.query(Provider).filter(Provider.enabled).all()]
        for k in keys:
            r = scanner.run_provider(k)
            print(json.dumps({x: v for x, v in r.items() if x not in ("new_ids", "dropped_ids")}))
    elif cmd == "verify":
        print(scanner.verify_links())
    elif cmd == "expire":
        print(scanner.expire_offers())
    elif cmd == "rescore":
        print(scanner.rescore_all())
    elif cmd == "images":
        print(scanner.backfill_images())
    elif cmd == "digest":
        print(notify.send_daily_digest())
    elif cmd == "test-notify":
        print(json.dumps(notify.send_test(argv[1:] or ["inapp"]), indent=2))
    elif cmd == "live-check":
        from . import duffel
        print(duffel.check_top_flights())
    elif cmd == "telegram-setup":
        telegram_setup()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
