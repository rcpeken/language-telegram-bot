"""Diller, seviyeler, gunluk yuk ve tekrar araliklari.

Sistemi kisisellestirmek icin duzenlemen gereken tek dosya burasi. Buradaki
her degeri .env uzerinden de gecersiz kilabilirsin - GitHub Actions'ta repo
degiskenleri (Settings > Variables) ayni isi goruyor.
"""
from __future__ import annotations

import datetime as dt
import os

# --- LLM saglayicisi -------------------------------------------------------
# gemini | groq | openrouter -> ucretsiz katman
# anthropic                  -> ucretli, en iyi kelime secimi
LLM_PROVIDER = os.getenv("LINGO_PROVIDER", "gemini").strip().lower()

DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "anthropic": "claude-opus-5",
}
LLM_MODEL = os.getenv("LINGO_MODEL") or DEFAULT_MODELS.get(LLM_PROVIDER, "")
EFFORT = os.getenv("LINGO_EFFORT", "medium")  # sadece anthropic icin

# --- Diller ----------------------------------------------------------------
# Kod bastan cok dilli: LINGO_LANGS="en,es" yazip ispanyolcayi actigin anda
# yeni kelime kotasi diller arasinda paylastirilir, tekrarlar ortak havuzdan
# gelir. Simdilik sadece ingilizce acik.
LANGS = [x.strip().lower() for x in os.getenv("LINGO_LANGS", "en").split(",") if x.strip()]

LANG_SPECS: dict[str, dict] = {
    "en": {
        "label": "Ingilizce",
        "flag": "\U0001F1EC\U0001F1E7",     # GB bayragi
        "name_en": "English",
        # gTTS ses kodu. "co.uk" British aksani verir; "com" Amerikan.
        "tts_lang": "en",
        "tts_tld": os.getenv("LINGO_EN_ACCENT", "co.uk"),
        "level": os.getenv("LINGO_EN_LEVEL", "B2-C1"),
    },
    "es": {
        "label": "Ispanyolca",
        "flag": "\U0001F1EA\U0001F1F8",     # ES bayragi
        "name_en": "Spanish",
        "tts_lang": "es",
        "tts_tld": os.getenv("LINGO_ES_ACCENT", "es"),
        "level": os.getenv("LINGO_ES_LEVEL", "A1-A2"),
    },
}

# --- Gunluk yuk ------------------------------------------------------------
# Her mesaj 5 kart: 3 yeni + 2 tekrar. Gunde 5 calisma -> 15 yeni kelime.
# Yeni sayisini yukseltmek kisa vadede daha hizli hissettirir ama tekrar
# kuyrugu sismeye basladiginda ogrenme degil biriktirme olur.
NEW_PER_RUN = int(os.getenv("LINGO_NEW_PER_RUN", "3"))
REVIEW_PER_RUN = int(os.getenv("LINGO_REVIEW_PER_RUN", "2"))

# Ayni kelime bir daha cikmasin diye tum gecmis yerel olarak suzuluyor;
# bu sayi sadece isteme eklenen "bunlari verme" listesinin boyu. Tamamini
# gondermek istemi gereksiz sisiriyor.
EXCLUDE_HINT_LIMIT = int(os.getenv("LINGO_EXCLUDE_HINT", "250"))

# --- Aralikli tekrar (Leitner) --------------------------------------------
# Kutu -> bir sonraki gosterime kac gun. Dogru bildikce kutu yukselir,
# bilemedigin kelime 1. kutuya duser ve ertesi gun tekrar karsina cikar.
BOX_INTERVALS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16, 6: 32}
MAX_BOX = max(BOX_INTERVALS)

# Kart gosterildi ama butona basilmadi: her calismada tekrar gonderilmesin
# diye yarina oteleniyor. Cevap sonradan gelirse gercek aralik uygulanir.
UNANSWERED_DEFER_DAYS = 1

# --- Teslim ----------------------------------------------------------------
AUDIO_ENABLED = os.getenv("LINGO_AUDIO", "1") != "0"
BUTTONS_ENABLED = os.getenv("LINGO_BUTTONS", "1") != "0"

# Ayni slot icin ikinci kez mesaj atilmasin. GitHub cron'u gecikmeli
# tetikleyebildigi icin workflow'da bir de yedek deneme var; bu esik
# ikisinin ayni karti iki kez gondermesini engelliyor.
MIN_GAP_HOURS = float(os.getenv("LINGO_MIN_GAP_HOURS", "2"))

HTTP_TIMEOUT = 30
TELEGRAM_LIMIT = 4096
# sendAudio/sendPhoto aciklamasi 1024 karakterle sinirli - kart metni
# bunun altinda kalmali, yoksa Telegram mesaji tumden reddediyor.
CAPTION_LIMIT = 1024

# --- Saat dilimi -----------------------------------------------------------
# Turkiye yil boyu UTC+3; yaz saati uygulamasi yok. Tarihleri UTC yerine
# TR gununden hesapliyoruz, yoksa aksam 21:00 gonderimi "ertesi gun" gibi
# gorunup tekrar takvimini bir gun kaydiriyor.
TR_TZ = dt.timezone(dt.timedelta(hours=3))


def today_tr() -> dt.date:
    return dt.datetime.now(TR_TZ).date()


def now_tr() -> dt.datetime:
    return dt.datetime.now(TR_TZ)


def lang_spec(lang: str) -> dict:
    """Bilinmeyen dil kodu icin makul bir varsayilan uretir."""
    return LANG_SPECS.get(lang, {
        "label": lang.upper(),
        "flag": "\U0001F310",
        "name_en": lang,
        "tts_lang": lang,
        "tts_tld": "com",
        "level": "B1",
    })
