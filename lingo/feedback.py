"""Butona basilan cevaplari toplar ve tekrar takvimine isler.

Telegram'in inline dugmeleri bir "callback_query" uretir ve bunu okumak
icin iki yol var: surekli ayakta duran bir webhook sunucusu, ya da arada
bir getUpdates cagirmak. Sunucu tutmak ucretsiz kalma hedefini bozardi;
bu yuzden her calisma once birikmis cevaplari okuyor, sonra yeni kartlari
gonderiyor. Pratikte cevabin islenmesi en fazla bir slot (3 saat) gecikir.

Bunun tek gorunur yan etkisi: dugmeye bastigin anda Telegram kisa bir
yukleniyor animasyonu gosterir ve cevapsiz kalir. Kart bir sonraki
calismada "biliyordum - 4 gun sonra tekrar" seklinde guncellenir.

Not: Telegram bekleyen guncellemeleri 24 saat tutar. Gunde bes calisma
oldugu icin cevaplarin kaybolmasi soz konusu degil.
"""
from __future__ import annotations

import datetime as dt
import json

from . import config, deliver, srs


def _answer_query(query_id: str, text: str) -> None:
    """Dugmenin yukleniyor animasyonunu kapatir.

    Cevap gecikmeli islendigi icin cogu zaman Telegram "query is too old"
    doner - bu beklenen durum, hata sayilmaz ve calismayi durdurmamali.
    """
    deliver.call(
        "answerCallbackQuery",
        data={"callback_query_id": query_id, "text": text},
        raise_on_error=False,
    )


def _update_keyboard(chat_id: int, message_id: int, card: dict) -> None:
    """Kartin altindaki dugmeleri islenmis cevapla degistirir."""
    deliver.call(
        "editMessageReplyMarkup",
        data={
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": json.dumps(deliver.answered_keyboard(card)),
        },
        raise_on_error=False,
    )


def poll(state: dict, today: dt.date, *, edit_messages: bool = True,
         long_poll: int = 0) -> dict:
    """Bekleyen cevaplari okur, karta isler ve ozet dondurur.

    long_poll: Telegram'in yeni cevap bekleyecegi saniye. Planli
    calismalarda 0 (ne varsa al, cik). `--watch` modunda 25 - baglanti
    acik tutulur ve dugmeye basildigi anda cevap gelir.

    HTTP zaman asimini beklemenin ustune ekliyoruz: Telegram 25 saniye
    bekleyecekse bizim 30 saniyelik varsayilan sinirimiz soguk baglantinin
    el sikisma suresiyle birlikte kolayca asilir ve istek cevap gelmeden
    kopar.
    """
    ozet = {"biliyordum": 0, "bilmiyordum": 0, "eslesmeyen": 0}

    yanit = deliver.call(
        "getUpdates",
        data={"offset": state.get("update_offset", 0), "timeout": long_poll,
              "limit": 100},
        raise_on_error=False,
        timeout=long_poll + config.HTTP_TIMEOUT,
    )
    if not yanit.get("ok"):
        print(f"  Cevaplar okunamadi: {yanit.get('description', 'bilinmeyen hata')}")
        return ozet

    guncellemeler = yanit.get("result") or []
    if not guncellemeler:
        return ozet

    # Offset'i TUM guncellemelerin en buyugune gore ilerletiyoruz: aradaki
    # duz mesajlari da onaylamis oluyoruz, yoksa ayni kuyruk her seferinde
    # bastan okunur.
    state["update_offset"] = max(g["update_id"] for g in guncellemeler) + 1

    for guncelleme in guncellemeler:
        sorgu = guncelleme.get("callback_query")
        if not sorgu:
            continue

        veri = str(sorgu.get("data", ""))
        if veri == "noop":
            _answer_query(sorgu["id"], "Bu kart zaten cevaplandi.")
            continue
        if ":" not in veri:
            continue

        eylem, _, kart_id = veri.partition(":")
        card = state["cards"].get(kart_id)
        if card is None:
            # Durum dosyasi sifirlanmis ya da kart elle silinmis olabilir.
            ozet["eslesmeyen"] += 1
            _answer_query(sorgu["id"], "Bu kart artik hafizada yok.")
            continue

        if eylem == "k":
            srs.on_known(card, today)
            ozet["biliyordum"] += 1
            bilgi = f"Kaydedildi - {srs.interval_days(card['box'])} gun sonra tekrar"
        elif eylem == "u":
            srs.on_unknown(card, today)
            ozet["bilmiyordum"] += 1
            bilgi = "Kaydedildi - yarin tekrar karsina cikacak"
        else:
            continue

        _answer_query(sorgu["id"], bilgi)
        mesaj = sorgu.get("message") or {}
        if edit_messages and mesaj.get("message_id"):
            _update_keyboard(mesaj["chat"]["id"], mesaj["message_id"], card)

    toplam = ozet["biliyordum"] + ozet["bilmiyordum"]
    if toplam:
        print(
            f"Cevaplar islendi: {ozet['biliyordum']} biliyordum, "
            f"{ozet['bilmiyordum']} bilmiyordum"
        )
    return ozet
