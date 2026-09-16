"""Kartlari Telegram'a gonderir ve gunluk arsivi yazar.

Her kart tek bir mesaj: mp3 telaffuz + aciklama metni + iki dugme. Sesi
ayri mesaj olarak gondermek listeyi ikiye katliyor ve dugmeleri sesten
ayiriyordu; sendAudio hepsini tek baloncukta tutuyor.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
from pathlib import Path

import requests

from . import config, srs, tts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = PROJECT_ROOT / "archive"

API = "https://api.telegram.org/bot{token}/{method}"

# Tek oturum uzerinden gidiyoruz: api.telegram.org'a ilk baglanti bu agdan
# ~15 saniye suruyor (DNS + TLS el sikismasi). Oturum baglantiyi acik
# tutunca sonraki istekler ~0.1 saniyeye iniyor. Bir calismada 5 kart + ses
# gonderiyoruz ve --watch modu surekli yokluyor - fark birikiyor.
_SESSION = requests.Session()

NEW_EMOJI = "\U0001F195"      # NEW rozeti
REVIEW_EMOJI = "\U0001F501"   # tekrar oku
BOOK_EMOJI = "\U0001F4DA"
LINK_EMOJI = "\U0001F517"


class TelegramError(RuntimeError):
    """Telegram cagrisi basarisiz oldu."""


def _credentials() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise TelegramError(
            "TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID tanimli degil. "
            ".env dosyasini doldur veya --dry-run ile calistir."
        )
    return token, chat_id


def call(method: str, *, data: dict, files: dict | None = None,
         raise_on_error: bool = True, timeout: float | None = None) -> dict:
    """Telegram API cagrisi. Hata govdesini gizlemeden yukari tasir.

    timeout: saniye. Uzun yoklama (getUpdates) yapan cagrilar kendi
    beklemelerini de hesaba katan daha buyuk bir deger verir.
    """
    token, _ = _credentials()
    resp = _SESSION.post(
        API.format(token=token, method=method),
        data=data, files=files, timeout=timeout or config.HTTP_TIMEOUT,
    )
    if not resp.ok:
        if raise_on_error:
            raise TelegramError(f"{method} -> {resp.status_code}: {resp.text[:400]}")
        return {"ok": False, "description": resp.text[:400]}
    return resp.json()


def _escape(value: str) -> str:
    """Telegram metin govdesi icin kacis.

    quote=False onemli: varsayilan html.escape kesme isaretini &#x27; yapiyor
    ve hem ingilizce hem turkce metinde kesme isareti her yerde. Telegram
    sadece &lt; &gt; &amp; kacislarini garanti ediyor, sayisal varliklari
    degil - yani kullanici mesajda ham &#x27; gorurdu.
    """
    return html.escape(str(value), quote=False)


# --- Kart metni ------------------------------------------------------------

def render_card(card: dict, *, kind: str) -> str:
    """Tek bir kartin Telegram HTML govdesi.

    kind: "new" (ilk kez goruyorsun) | "review" (tekrar)
    """
    spec = config.lang_spec(card.get("lang", "en"))
    yeni = kind == "new"
    rozet = NEW_EMOJI if yeni else REVIEW_EMOJI

    bas = [
        f"{rozet} <b>{_escape(card['word'])}</b>  <code>{_escape(card['ipa'])}</code>",
    ]
    etiketler = [_escape(card.get("pos", "")), _escape(card.get("level", ""))]
    if not yeni:
        kutu = int(card.get("box", 1))
        etiketler.append(f"kutu {kutu}/{config.MAX_BOX} - {srs.maturity(card)}")
    bas.append(f"<i>{' - '.join(x for x in etiketler if x)}</i>  {spec['flag']}")
    bas.append("")
    bas.append(f"<b>{_escape(card['meaning_tr'])}</b>")
    bas.append(f"<i>{_escape(card['definition_en'])}</i>")
    bas.append("")
    bas.append("“" + _escape(card["example"]) + "”")
    bas.append(f"<i>{_escape(card['example_tr'])}</i>")

    esles = card.get("collocations") or []
    kuyruk = []
    if esles:
        kuyruk = ["", LINK_EMOJI + " " + _escape(" · ".join(esles))]

    metin = "\n".join(bas + kuyruk)
    if len(metin) > config.CAPTION_LIMIT:
        # Aciklama sinirini asan mesaji Telegram tumden reddediyor. Once
        # eslesmeleri at, o da yetmezse sert kes - kirpmak kaybetmekten iyi.
        metin = "\n".join(bas)
    if len(metin) > config.CAPTION_LIMIT:
        metin = metin[: config.CAPTION_LIMIT - 3] + "..."
    return metin


def card_keyboard(card_id: str) -> dict:
    """Kart altindaki iki dugme. callback_data 64 bayt siniri icinde kalir."""
    return {
        "inline_keyboard": [[
            {"text": "✅ Biliyordum", "callback_data": f"k:{card_id}"},
            {"text": "\U0001F501 Bilmiyordum", "callback_data": f"u:{card_id}"},
        ]]
    }


def answered_keyboard(card: dict) -> dict:
    """Cevap islendikten sonra dugmelerin yerine gecen bilgi satiri.

    Dugmeleri tumden silmek yerine tek bir pasif dugmeye cevirmek, hangi
    cevabi verdigini ve kelimenin ne zaman geri gelecegini gosteriyor.
    """
    bilinen = card.get("last_answer") == "known"
    isaret = "✅" if bilinen else "\U0001F501"
    gun = srs.interval_days(int(card.get("box", 1)))
    durum = "biliyordum" if bilinen else "bilmiyordum"
    return {
        "inline_keyboard": [[
            {"text": f"{isaret} {durum} - {gun} gun sonra tekrar",
             "callback_data": "noop"},
        ]]
    }


# --- Gonderim --------------------------------------------------------------

def send_message(text: str, *, keyboard: dict | None = None) -> int | None:
    _, chat_id = _credentials()
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    sonuc = call("sendMessage", data=data)
    return (sonuc.get("result") or {}).get("message_id")


def send_card(card: dict, *, kind: str, with_audio: bool = True,
              with_buttons: bool = True) -> int | None:
    """Karti gonderir, mesaj id'sini dondurur.

    Ses uretilemezse duz metne duser - bu bir hata degil, beklenen yol.
    """
    _, chat_id = _credentials()
    metin = render_card(card, kind=kind)
    klavye = card_keyboard(card["id"]) if with_buttons else None

    ses = tts.synthesize(card) if with_audio else None
    if ses is None:
        return send_message(metin, keyboard=klavye)

    data = {
        "chat_id": chat_id,
        "caption": metin,
        "parse_mode": "HTML",
        "title": card["word"],
        "performer": "lingo-radar",
    }
    if klavye:
        data["reply_markup"] = json.dumps(klavye)

    dosya_adi = "".join(ch for ch in card["word"] if ch.isalnum()) or "word"
    sonuc = call(
        "sendAudio",
        data=data,
        files={"audio": (f"{dosya_adi}.mp3", ses, "audio/mpeg")},
    )
    return (sonuc.get("result") or {}).get("message_id")


def send_header(*, new_count: int, review_count: int, stats: dict,
                now: dt.datetime) -> None:
    """Kartlardan once giden kisa baslik - hangi slot, ne kadar yol alindi."""
    parcalar = [
        f"{BOOK_EMOJI} <b>lingo-radar - {now.strftime('%H:%M')}</b>",
        f"{new_count} yeni + {review_count} tekrar",
        "",
        f"<i>Toplam {stats['toplam']} kelime - {stats['oturmus']} tanesi oturmus</i>",
    ]
    send_message("\n".join(parcalar))


# --- Arsiv -----------------------------------------------------------------

def archive_path(today: dt.date) -> Path:
    return ARCHIVE_DIR / f"{today.isoformat()}.md"


def append_archive(cards: list[tuple[dict, str]], now: dt.datetime) -> Path:
    """O gunun markdown gunlugune bu calismanin kartlarini ekler.

    Telegram gecmisinde arama yapmak zor; repodaki markdown hem aranabilir
    hem de gunu tek bakista gosteriyor.
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    yol = archive_path(now.date())
    yeni_dosya = not yol.exists()

    satirlar: list[str] = []
    if yeni_dosya:
        satirlar += [f"# lingo-radar - {now.date().isoformat()}", ""]
    satirlar += [f"## {now.strftime('%H:%M')}", ""]

    for card, kind in cards:
        etiket = "yeni" if kind == "new" else f"tekrar - kutu {card.get('box', 1)}"
        satirlar.append(f"### {card['word']} `{card['ipa']}` ({etiket})")
        satirlar.append("")
        satirlar.append(
            f"- **{card['meaning_tr']}** - {card.get('pos', '')} - {card.get('level', '')}"
        )
        satirlar.append(f"- {card['definition_en']}")
        satirlar.append(f"- _{card['example']}_")
        satirlar.append(f"- {card['example_tr']}")
        if card.get("collocations"):
            satirlar.append(f"- Eslesmeler: {', '.join(card['collocations'])}")
        satirlar.append("")

    with yol.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(satirlar) + "\n")
    print(f"Arsive eklendi: {yol.name}")
    return yol
