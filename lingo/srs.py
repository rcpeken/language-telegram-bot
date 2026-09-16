"""Aralikli tekrar (Leitner kutu sistemi).

Sade tutuldu: her kartin bir kutusu (1..6) ve bir "vade" tarihi var. Dogru
bilirsen kutu bir yukari cikar ve aralik uzar; bilemezsen kart 1. kutuya
duser ve ertesi gun yine karsina gelir. SM-2/Anki gibi kolaylik katsayisi
hesaplamiyoruz - iki dugmeli bir bottan gelen sinyal o inceligi tasimaz,
tasiyormus gibi yapmak da yanlis guven verir.

Fonksiyonlar bilerek saf: tarih disaridan veriliyor, kart sozlugu yerinde
guncelleniyor ve I/O yok. test_offline.py bunlari dogrudan cagiriyor.
"""
from __future__ import annotations

import datetime as dt

from . import config


def interval_days(box: int) -> int:
    """Verilen kutunun gun cinsinden tekrar araligi."""
    box = max(1, min(int(box), config.MAX_BOX))
    return config.BOX_INTERVALS[box]


def schedule(box: int, today: dt.date) -> str:
    """Kutuya gore bir sonraki vade tarihi (ISO metin)."""
    return (today + dt.timedelta(days=interval_days(box))).isoformat()


def new_card_fields(today: dt.date) -> dict:
    """Yeni ogrenilen bir kartin baslangic tekrar alanlari.

    1. kutu ve yarinki vade: kelimeyi ilk gordugun gun icinde bir daha
    gostermek tekrar degil, ayni mesaji ikinci kez okumak olur.
    """
    return {
        "box": 1,
        "due": schedule(1, today),
        "known_count": 0,
        "unknown_count": 0,
        "shown_count": 1,
        "answered_count": 0,
    }


def on_known(card: dict, today: dt.date) -> dict:
    """'Biliyordum' cevabi: kutuyu bir yukari tasir, araligi uzatir."""
    card["box"] = min(int(card.get("box", 1)) + 1, config.MAX_BOX)
    card["due"] = schedule(card["box"], today)
    card["known_count"] = int(card.get("known_count", 0)) + 1
    card["answered_count"] = int(card.get("answered_count", 0)) + 1
    card["last_answer"] = "known"
    card["last_answered_at"] = today.isoformat()
    return card


def on_unknown(card: dict, today: dt.date) -> dict:
    """'Bilmiyordum' cevabi: kart 1. kutuya doner, yarin tekrar cikar."""
    card["box"] = 1
    card["due"] = schedule(1, today)
    card["unknown_count"] = int(card.get("unknown_count", 0)) + 1
    card["answered_count"] = int(card.get("answered_count", 0)) + 1
    card["last_answer"] = "unknown"
    card["last_answered_at"] = today.isoformat()
    return card


def on_shown_unanswered(card: dict, today: dt.date) -> dict:
    """Kart gonderildi ama henuz cevaplanmadi.

    Vadeyi bir gun oteliyoruz. Otelemezsek vadesi gecmis kart her uc saatte
    bir yeniden gonderilir ve butona hic basmayan biri icin bot ayni bes
    kelimeyi gun boyu tekrarlayan bir cihaza donusur.
    """
    card["shown_count"] = int(card.get("shown_count", 0)) + 1
    card["last_shown_at"] = today.isoformat()
    deferred = today + dt.timedelta(days=config.UNANSWERED_DEFER_DAYS)
    # Zaten daha ileri bir vadesi varsa geri cekme.
    if card.get("due", "") < deferred.isoformat():
        card["due"] = deferred.isoformat()
    return card


def is_due(card: dict, today: dt.date) -> bool:
    return str(card.get("due", "")) <= today.isoformat()


def sort_key(card: dict) -> tuple:
    """Once en eski vade, sonra en dusuk kutu.

    Dusuk kutu = daha zor kelime. Ayni gun vadesi gelen kartlar arasinda
    once zorlananlari gostermek, kuyrugu bilinen kelimelerle doldurmaktan
    daha iyi bir kullanim.
    """
    return (str(card.get("due", "")), int(card.get("box", 1)))


def maturity(card: dict) -> str:
    """Kartin durumunu tek kelimeyle ozetler - arsiv ve istatistik icin."""
    box = int(card.get("box", 1))
    if box >= 5:
        return "oturmus"
    if box >= 3:
        return "pekisiyor"
    return "taze"
