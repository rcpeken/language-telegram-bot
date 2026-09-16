"""Telegram chat id'ni bulur.

Kullanim:
    1. Telegram'da @BotFather ile yeni bot olustur, token'i .env icine yaz.
    2. Olusturdugun bota Telegram'dan herhangi bir mesaj at ("merhaba" yeter).
    3. python get_chat_id.py

Bot, kendisine yazilmamis bir sohbete mesaj gonderemez - 2. adim sart.
"""
from __future__ import annotations

import os
import sys

import requests

from lingo.bootstrap import explain_missing_env, load_env

HAS_ENV_FILE = load_env()


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        if not HAS_ENV_FILE:
            explain_missing_env()
        else:
            print("TELEGRAM_BOT_TOKEN bos. @BotFather'dan aldigin token'i .env icine yaz.")
        return 1

    resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    if not resp.ok:
        print(f"Telegram {resp.status_code}: {resp.text[:300]}")
        print("Token yanlis olabilir - @BotFather'dan aldigin satirin tamamini kopyala.")
        return 1

    updates = resp.json().get("result", [])
    if not updates:
        print("Hic mesaj yok. Once Telegram'da botuna bir mesaj at, sonra tekrar calistir.")
        return 1

    seen: dict[int, str] = {}
    for update in updates:
        chat = (update.get("message") or update.get("channel_post") or {}).get("chat")
        if chat:
            name = chat.get("username") or chat.get("title") or chat.get("first_name", "?")
            seen[chat["id"]] = f"{name} ({chat.get('type')})"

    print("Bulunan sohbetler:\n")
    for chat_id, label in seen.items():
        print(f"  TELEGRAM_CHAT_ID={chat_id}    <- {label}")
    print("\nKendi kullanici adini gordugun satiri .env dosyasina yapistir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
