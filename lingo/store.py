"""Kelime hafizasi: hangi kelimeyi gordun, hangisi ne zaman tekrar gelecek.

Tek bir JSON dosyasi (data/state.json). Veritabani yok, cunku esas calisma
ortami GitHub Actions: her calisma temiz bir makinede baslar ve tek kalici
sey repoya commit'lenen dosyalardir. JSON hem oraya sigar hem de gozle
okunabilir - gerekirse elle duzeltirsin.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import tempfile
from pathlib import Path

from . import config, srs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "state.json"
STATE_VERSION = 1


def card_id(lang: str, word: str) -> str:
    """Kart icin kisa ve kararli kimlik.

    Telegram callback_data 64 bayt ile sinirli ve kelimenin kendisi
    (ozellikle cok kelimeli kaliplarda) bunu asabiliyor; kisa ozet hem
    sigar hem de kelimeyi degistirmedigimiz surece ayni kalir.
    """
    raw = f"{lang.lower()}:{word.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def empty_state() -> dict:
    return {"version": STATE_VERSION, "update_offset": 0, "last_sent_at": None, "cards": {}}


def load_state() -> dict:
    """Durumu okur. Dosya yoksa veya bozuksa bos durumla devam eder.

    Bozuk JSON'da patlamak yerine devam etmek bilincli: dosya bozulmussa
    tek kaybimiz gecmis, ama bot calismaya devam eder. Sessiz de degil -
    ekrana uyari basiyoruz ve bozuk dosyayi .bozuk uzantisiyla sakliyoruz.
    """
    if not STATE_PATH.exists():
        return empty_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        yedek = STATE_PATH.with_suffix(".json.bozuk")
        print(f"UYARI: {STATE_PATH.name} okunamadi ({exc}). Yedegi: {yedek.name}")
        try:
            STATE_PATH.replace(yedek)
        except OSError:
            pass
        return empty_state()

    if not isinstance(data, dict) or "cards" not in data:
        print(f"UYARI: {STATE_PATH.name} beklenen bicimde degil, sifirdan baslaniyor.")
        return empty_state()
    data.setdefault("version", STATE_VERSION)
    data.setdefault("update_offset", 0)
    data.setdefault("last_sent_at", None)
    return data


def save_state(state: dict) -> Path:
    """Durumu atomik yazar.

    Dogrudan yazarken surec yarida kesilirse (Actions zaman asimi, agin
    kopmasi) dosya yarim kalir ve tum gecmis gider. Once gecici dosyaya
    yazip sonra yerine tasimak bunu imkansiz kilar.
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    metin = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=STATE_PATH.parent, prefix=".state-", suffix=".tmp",
        delete=False,
    ) as fh:
        fh.write(metin + "\n")
        gecici = Path(fh.name)
    gecici.replace(STATE_PATH)
    return STATE_PATH


# --- Sorgular --------------------------------------------------------------

def known_words(state: dict, lang: str | None = None) -> set[str]:
    """Daha once gonderilmis tum kelimeler (kucuk harfe indirgenmis)."""
    return {
        str(card.get("word", "")).strip().lower()
        for card in state["cards"].values()
        if lang is None or card.get("lang") == lang
    }


def recent_words(state: dict, lang: str, limit: int) -> list[str]:
    """Isteme eklenecek 'bunlari verme' listesi - en yeniler once."""
    kartlar = [c for c in state["cards"].values() if c.get("lang") == lang]
    kartlar.sort(key=lambda c: str(c.get("first_seen", "")), reverse=True)
    return [str(c.get("word", "")) for c in kartlar[:limit] if c.get("word")]


def due_cards(state: dict, today: dt.date, limit: int,
              langs: list[str] | None = None) -> list[dict]:
    """Vadesi gelmis tekrar kartlari - en aciliyetliden baslayarak."""
    havuz = [
        card for card in state["cards"].values()
        if (langs is None or card.get("lang") in langs) and srs.is_due(card, today)
    ]
    havuz.sort(key=srs.sort_key)
    return havuz[:limit]


def add_card(state: dict, word: dict, lang: str, today: dt.date,
             now_iso: str) -> tuple[str, dict]:
    """Yeni kelimeyi hafizaya ekler ve (id, kart) dondurur."""
    cid = card_id(lang, word["word"])
    card = {
        "id": cid,
        "lang": lang,
        "first_seen": now_iso,
        "last_shown_at": today.isoformat(),
        **{k: word[k] for k in word if k != "id"},
        **srs.new_card_fields(today),
    }
    state["cards"][cid] = card
    return cid, card


def stats(state: dict) -> dict:
    """Kisa ilerleme ozeti - mesaj altbilgisinde gosteriliyor."""
    kartlar = list(state["cards"].values())
    bugun = config.today_tr()
    return {
        "toplam": len(kartlar),
        "oturmus": sum(1 for c in kartlar if int(c.get("box", 1)) >= 5),
        "bekleyen": sum(1 for c in kartlar if srs.is_due(c, bugun)),
    }
