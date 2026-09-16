"""Telaffuz sesi uretir (gTTS -> mp3 bayt dizisi).

gTTS, Google Translate'in konusma ucunu kullanir: API anahtari istemez,
ucretsizdir ve ingilizce/ispanyolca icin dogal bir ses verir. Karsiliginda
resmi bir servis degil - ucu gecici olarak yanit vermeyebilir. Bu yuzden
buradaki her hata yutuluyor ve None donuyor: sesi olmayan kart hala
ise yarar, ses yuzunden gonderimi tumden kaybetmek ise yaramaz.
"""
from __future__ import annotations

import io

from . import config

_UYARI_VERILDI = False


def _uyar(mesaj: str) -> None:
    """gTTS ile ilgili uyariyi calisma basina bir kez basar."""
    global _UYARI_VERILDI
    if not _UYARI_VERILDI:
        print(f"  Ses uretilemedi: {mesaj}")
        print("  Kartlar sesli mesaj yerine duz metin olarak gidecek.")
        _UYARI_VERILDI = True


def speech_text(card: dict) -> str:
    """Seslendirilecek metin: once kelime, sonra ornek cumle.

    Kelimeyi iki kez okutuyoruz - ilk duyusta cogu kelime kacar, ikincisi
    de cumle baglaminin hemen oncesine denk gelir.
    """
    kelime = card.get("word", "")
    ornek = card.get("example", "")
    return f"{kelime}. {kelime}. {ornek}"


def synthesize(card: dict) -> bytes | None:
    """Kartin mp3 sesini dondurur; uretilemezse None."""
    if not config.AUDIO_ENABLED:
        return None
    try:
        from gtts import gTTS
    except ImportError:
        _uyar("gTTS paketi kurulu degil (pip install gTTS)")
        return None

    spec = config.lang_spec(card.get("lang", "en"))
    try:
        konusma = gTTS(
            text=speech_text(card),
            lang=spec["tts_lang"],
            tld=spec["tts_tld"],
            slow=False,
        )
        tampon = io.BytesIO()
        konusma.write_to_fp(tampon)
    except Exception as exc:  # gTTSError, aglar, ad cozumleme...
        _uyar(f"{type(exc).__name__}: {exc}")
        return None

    veri = tampon.getvalue()
    # Bos ya da saka kabilinden kucuk dosya calmaz, Telegram'a gondermeyelim.
    return veri if len(veri) > 1024 else None
