"""LLM'den yeni kelime kartlari uretir ve gelen cevabi siki siki dogrular.

Model cikti sozlesmesini her zaman tutmaz: alan eksik gelir, IPA yerine
duz yazi gelir, zaten ogrendigin kelimeyi yeniden onerir. Burasi o cikti
ile hafiza arasindaki suzgec - dogrulamayi gecemeyen kart sessizce
atiliyor, eksik kalan sayi bir sonraki calismada tamamlaniyor.
"""
from __future__ import annotations

import json
import re

from . import config, llm

# Kartta olmasi zorunlu alanlar. Biri eksikse kart atilir - yarim kart
# gostermek, o kelimeyi "gorulmus" diye isaretleyip bir daha hic
# getirmemek demek olurdu.
REQUIRED = ("word", "pos", "ipa", "meaning_tr", "definition_en", "example", "example_tr")

SYSTEM = """Sen deneyimli bir dil ogretmenisin. Turkce konusan bir ogrenciye
hedef dilde kelime karti hazirliyorsun.

Kurallar:
- SADECE gecerli JSON dondur. Aciklama, giris cumlesi, markdown kod bloku yok.
- Her kelime gunluk hayatta, haberlerde veya is yazismalarinda gercekten
  kullanilan bir kelime olsun. Sozluk susu, arkaik ya da teknik jargon olmasin.
- Ornek cumle dogal olsun ve kelimenin en yaygin kullanimini gostersin;
  8-16 kelime arasi, tek cumle.
- IPA'yi egik cizgiler arasinda ver: /ˈeksəmpəl/
- Turkce karsilik kisa olsun: en fazla uc alternatif, virgulle ayrilmis.
- definition_en hedef dilde ve ogrencinin seviyesinde sade bir tanim olsun.
"""

USER_TEMPLATE = """Dil: {dil}
Hedef seviye: {seviye} (CEFR)
Istenen kelime sayisi: {adet}

Su sozlugu dondur:
{{"words": [
  {{
    "word": "kelime veya kalip",
    "pos": "noun | verb | adjective | adverb | phrase",
    "ipa": "/.../",
    "level": "{seviye} araligindan tek bir CEFR etiketi, orn. B2",
    "meaning_tr": "kisa Turkce karsilik",
    "definition_en": "{dil} dilinde sade tanim",
    "example": "{dil} dilinde ornek cumle",
    "example_tr": "ornek cumlenin Turkce cevirisi",
    "collocations": ["sik kullanilan eslesme", "ikinci eslesme"]
  }}
]}}

Cesitlilik iste: {adet} kelimenin hepsi ayni turden (hepsi sifat gibi)
olmasin, mumkunse farkli alanlardan secilsin.
{haric}"""


class GenerateError(RuntimeError):
    """Kelime uretilemedi. main.py bunu yakalayip tekrarlarla devam eder."""


def _exclusion_block(exclude: list[str]) -> str:
    if not exclude:
        return ""
    liste = ", ".join(exclude)
    return (
        "\nAsagidaki kelimeler ogrenciye daha once verildi, HICBIRINI tekrar "
        f"verme ve turevlerinden de kacin:\n{liste}\n"
    )


def _strip_fences(text: str) -> str:
    """Model yine de ```json ... ``` sardiysa cikar."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_words(raw: str) -> list[dict]:
    """Ham LLM ciktisini kart listesine cevirir."""
    text = _strip_fences(raw)
    try:
        data = json.loads(text)
    except ValueError:
        # Bazi modeller JSON'un onune/arkasina laf ekliyor - en disdaki
        # sus parantezini yakalayip bir kez daha deniyoruz.
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise GenerateError(f"Model JSON dondurmedi: {text[:300]}") from None
        try:
            data = json.loads(m.group(0))
        except ValueError as exc:
            raise GenerateError(f"JSON ayristirilamadi: {exc}") from exc

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("words") or data.get("items") or []
    else:
        raise GenerateError(f"Beklenmeyen JSON turu: {type(data).__name__}")

    if not isinstance(items, list):
        raise GenerateError("'words' bir liste degil")
    return [x for x in items if isinstance(x, dict)]


def clean_word(item: dict, lang: str) -> dict | None:
    """Tek bir karti dogrular ve normalize eder. Gecemezse None."""
    kart: dict = {}
    for alan in REQUIRED:
        deger = item.get(alan)
        if not isinstance(deger, str) or not deger.strip():
            return None
        kart[alan] = deger.strip()

    # Tek kelimelik "ornek cumle" ya da kelimeyi hic icermeyen cumle ise
    # kart ogretici olmaktan cikar.
    if len(kart["example"].split()) < 4:
        return None

    ipa = kart["ipa"]
    if not ipa.startswith("/"):
        ipa = "/" + ipa.strip("/[]") + "/"
        kart["ipa"] = ipa

    seviye = item.get("level")
    kart["level"] = seviye.strip().upper() if isinstance(seviye, str) and seviye.strip() else "?"

    esles = item.get("collocations")
    if isinstance(esles, list):
        kart["collocations"] = [str(x).strip() for x in esles if str(x).strip()][:3]
    elif isinstance(esles, str) and esles.strip():
        kart["collocations"] = [esles.strip()]
    else:
        kart["collocations"] = []

    kart["lang"] = lang
    return kart


def generate(lang: str, count: int, exclude: list[str],
             known: set[str] | None = None) -> list[dict]:
    """`count` adet yeni kelime uretir.

    Modelden fazladan kelime istiyoruz: dogrulamadan dusenler ve zaten
    bilinen kelimeler elendikten sonra elde yeterince kart kalsin diye.
    Ikinci bir cagri yapmak hem yavas hem de kotadan yiyor.
    """
    if count <= 0:
        return []

    spec = config.lang_spec(lang)
    known = known or set()
    istenen = count + 3

    prompt = USER_TEMPLATE.format(
        dil=spec["name_en"],
        seviye=spec["level"],
        adet=istenen,
        haric=_exclusion_block(exclude),
    )
    ham = llm.complete(SYSTEM, prompt)
    adaylar = parse_words(ham)

    secilen: list[dict] = []
    gorulen: set[str] = set()
    for aday in adaylar:
        kart = clean_word(aday, lang)
        if kart is None:
            continue
        anahtar = kart["word"].lower()
        if anahtar in known or anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        secilen.append(kart)
        if len(secilen) == count:
            break

    if not secilen:
        raise GenerateError(
            f"{len(adaylar)} aday geldi ama hicbiri dogrulamayi gecemedi "
            f"veya hepsi zaten ogrenilmisti."
        )
    if len(secilen) < count:
        print(f"  Uyari: {count} kelime istendi, {len(secilen)} tanesi kullanilabilir.")
    return secilen
