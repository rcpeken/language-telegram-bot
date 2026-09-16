"""lingo-radar - gun icine yayilmis kelime ogrenme botu.

Her calismada once bekleyen dugme cevaplarini isler, sonra vadesi gelen
tekrarlari ve yeni kelimeleri tek tek Telegram'a gonderir.

Kullanim:
    python main.py                  # cevaplari isle, kartlari gonder, arsivle
    python main.py --dry-run        # gondermeden ekrana bas (durumu degistirmez)
    python main.py --force          # slot araligi kontrolunu atla
    python main.py --feedback-only  # sadece cevaplari isle, kart gonderme
    python main.py --watch          # cevaplari aninda isle (bilgisayar acikken)
    python main.py --stats          # ilerleme ozeti
    python main.py --test-telegram  # kurulumu dogrula
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from lingo.bootstrap import check_dependencies, explain_missing_env, load_env

check_dependencies()

# config degerlerini import aninda hesapliyor - ortam once yuklenmeli.
HAS_ENV_FILE = load_env()

from lingo import config, deliver, feedback, generate, srs, store  # noqa: E402


def _split_quota(total: int, langs: list[str]) -> dict[str, int]:
    """Yeni kelime kotasini diller arasinda paylastirir.

    Tek dil acikken (varsayilan) hepsi ona gider. Iki dil acilirsa
    3 kelime 2/1 bolunur ve siradaki calismada sira degisir - boylece
    ikinci dil surekli az kelime alan taraf olmaz.
    """
    if not langs:
        return {}
    pay = {lang: total // len(langs) for lang in langs}
    artan = total - sum(pay.values())
    # Artani gunun sirasina gore dagit: gun degistikce oncelik doner.
    baslangic = config.today_tr().toordinal() % len(langs)
    for i in range(artan):
        pay[langs[(baslangic + i) % len(langs)]] += 1
    return pay


def _too_soon(state: dict, now: dt.datetime) -> float | None:
    """Son gonderimden bu yana yeterli sure gecti mi?

    GitHub cron'u gecikmeli tetikleyebiliyor ve workflow'da yedek deneme
    var; bu kontrol olmadan ayni slot icin iki kez kart gonderilebilir.
    Gecmediyse kalan saati dondurur.
    """
    son = state.get("last_sent_at")
    if not son:
        return None
    try:
        onceki = dt.datetime.fromisoformat(son)
    except ValueError:
        return None
    if onceki.tzinfo is None:
        onceki = onceki.replace(tzinfo=config.TR_TZ)
    gecen = (now - onceki).total_seconds() / 3600
    kalan = config.MIN_GAP_HOURS - gecen
    return kalan if kalan > 0 else None


def _bos_slot_bildir(state: dict, now: dt.datetime) -> None:
    """Gonderilecek kart kalmadiginda gunde en fazla bir kez haber verir.

    Her slotta mesaj atmak, saglayici bir gun boyunca kapaliysa kullaniciyi
    bes ayni bildirimle bogar. Gunde bir kez, okudugu yerden haber vermek
    yeterli - Actions gunlugune bakmasini beklemek gercekci degil.
    """
    bugun = now.date().isoformat()
    if state.get("last_notice_date") == bugun:
        return
    try:
        deliver.send_message(
            "<b>lingo-radar</b>\n\n"
            "Bu slotta yeni kelime uretilemedi - saglayici yanit vermedi "
            "veya gunluk kota doldu. Vadesi gelen tekrar da yoktu.\n\n"
            "<i>Sonraki slotta yeniden denenecek.</i>"
        )
    except Exception as exc:
        print(f"  Bilgi mesaji gonderilemedi: {exc}")
    state["last_notice_date"] = bugun


def _print_card(card: dict, kind: str) -> None:
    """--dry-run ciktisi: Telegram'a gidecek metnin duz hali."""
    import re
    metin = deliver.render_card(card, kind=kind)
    print(re.sub(r"</?(b|i|code|u|s)>", "", metin))
    print("-" * 50)


def show_stats(state: dict) -> int:
    ozet = store.stats(state)
    bugun = config.today_tr()
    print("lingo-radar ilerleme")
    print("-" * 40)
    print(f"Toplam kelime     : {ozet['toplam']}")
    print(f"Oturmus (5+ kutu) : {ozet['oturmus']}")
    print(f"Bugun vadesi gelen: {ozet['bekleyen']}")
    print(f"Havuzda bekleyen  : {ozet['havuz']} kelime")
    for dil in config.LANGS:
        spec = config.lang_spec(dil)
        adet = len(store.known_words(state, dil))
        print(f"  {spec['label']:<12}: {adet} kelime (seviye {spec['level']})")
    kutular: dict[int, int] = {}
    for card in state["cards"].values():
        kutular[int(card.get("box", 1))] = kutular.get(int(card.get("box", 1)), 0) + 1
    if kutular:
        print("Kutu dagilimi     : " + ", ".join(
            f"{k}->{kutular[k]}" for k in sorted(kutular)
        ))
    print(f"Son gonderim      : {state.get('last_sent_at') or 'henuz yok'}")
    print(f"Bugun             : {bugun.isoformat()}")
    return 0


def watch(state: dict) -> int:
    """Dugme cevaplarini aninda isleyen dinleme modu.

    Telegram'in uzun yoklama (long polling) ozelligini kullanir: baglanti
    acik tutulur ve dugmeye bastigin anda cevap dusuyor. Bilgisayar acikken
    calistirmak icin - kapattiginda planli calismalar devrali, hicbir cevap
    kaybolmaz cunku Telegram bekleyen guncellemeleri 24 saat tutuyor.
    """
    import time

    print("Dinleme modu acik. Dugmelere bastikca cevaplar aninda islenecek.")
    print("Cikmak icin Ctrl+C.\n")
    while True:
        onceki_offset = state.get("update_offset", 0)
        try:
            feedback.poll(state, config.today_tr(), long_poll=25)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            # Ag kopmasi gecici; dongunun tumden olmesine izin verme.
            print(f"  Baglanti hatasi ({type(exc).__name__}: {exc}) - 10s sonra tekrar")
            time.sleep(10)
            continue
        if state.get("update_offset", 0) != onceki_offset:
            store.save_state(state)


def test_telegram() -> int:
    """Kurulumu dogrular: kelime uretmeden tek bir test karti gonderir."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    print("Telegram kurulum kontrolu\n" + "-" * 40)
    print(f".env dosyasi       : {'var' if HAS_ENV_FILE else 'YOK'}")
    print(f"TELEGRAM_BOT_TOKEN : {'tanimli' if token else 'EKSIK'}")
    print(f"TELEGRAM_CHAT_ID   : {chat_id or 'EKSIK'}")
    if not token or not chat_id:
        if not HAS_ENV_FILE:
            explain_missing_env()
        else:
            print("\n.env dosyasi var ama eksik dolu. Adimlar icin README'ye bak.")
            print("Sirasiyla: @BotFather ile bot olustur -> bota mesaj at ->")
            print("python get_chat_id.py -> cikan degerleri .env'e yaz.")
        return 1

    ornek = {
        "id": "testcard00",
        "lang": config.LANGS[0] if config.LANGS else "en",
        "word": "resilient",
        "ipa": "/rɪˈzɪliənt/",
        "pos": "adjective",
        "level": "B2",
        "meaning_tr": "dayanikli, cabuk toparlanan",
        "definition_en": "able to recover quickly after something difficult",
        "example": "Small businesses proved surprisingly resilient during the crisis.",
        "example_tr": "Kucuk isletmeler kriz boyunca sasirtici olcude dayanikli cikti.",
        "collocations": ["resilient economy", "remarkably resilient"],
        "box": 1,
    }
    try:
        deliver.send_card(
            ornek, kind="new",
            with_audio=config.AUDIO_ENABLED,
            with_buttons=config.BUTTONS_ENABLED,
        )
    except Exception as exc:
        print(f"\nBASARISIZ: {exc}")
        print("\nSik sebepler:")
        print("  - Bota hic mesaj atmadin (bot once yazilmasi gereken taraftir)")
        print("  - chat_id yanlis: 'python get_chat_id.py' ile tekrar al")
        print("  - token eksik kopyalanmis: BotFather'daki satirin tamamini al")
        return 1

    print("\nBasarili. Telegram'da ornek karti gormus olmalisin.")
    print("Dugmeye basip 'python main.py --feedback-only' calistirirsan")
    print("cevabin nasil islendigini gorursun (test karti hafizada olmadigi")
    print("icin 'artik hafizada yok' cevabi normaldir).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Gun icine yayilmis kelime ogrenme botu")
    parser.add_argument("--dry-run", action="store_true",
                        help="Telegram'a gonderme, ekrana bas (durumu degistirmez)")
    parser.add_argument("--force", action="store_true",
                        help="Slot araligi kontrolunu atla")
    parser.add_argument("--new", type=int, default=None, help="Kac yeni kelime")
    parser.add_argument("--review", type=int, default=None, help="Kac tekrar karti")
    parser.add_argument("--no-llm", action="store_true",
                        help="Yeni kelime uretme, sadece tekrarlari gonder")
    parser.add_argument("--no-audio", action="store_true", help="Ses gonderme")
    parser.add_argument("--no-buttons", action="store_true", help="Dugmeleri ekleme")
    parser.add_argument("--no-archive", action="store_true", help="Markdown arsivi yazma")
    parser.add_argument("--feedback-only", action="store_true",
                        help="Sadece bekleyen cevaplari isle")
    parser.add_argument("--watch", action="store_true",
                        help="Dugme cevaplarini aninda isle (Ctrl+C ile cik)")
    parser.add_argument("--stats", action="store_true", help="Ilerleme ozetini goster")
    parser.add_argument("--test-telegram", action="store_true",
                        help="Sadece kurulumu dene")
    args = parser.parse_args()

    if args.test_telegram:
        return test_telegram()

    state = store.load_state()
    if args.stats:
        return show_stats(state)
    if args.watch:
        try:
            return watch(state)
        except KeyboardInterrupt:
            store.save_state(state)
            print("\nDinleme modu kapatildi.")
            return 0

    now = config.now_tr()
    today = now.date()
    yeni_adet = config.NEW_PER_RUN if args.new is None else args.new
    tekrar_adet = config.REVIEW_PER_RUN if args.review is None else args.review

    # 1) Bekleyen cevaplar. Kart gondermeden once isliyoruz ki bu calismanin
    #    tekrar secimi en guncel takvimi gorsun.
    if not args.dry_run:
        feedback.poll(state, today)
        # Cevaplari hemen kaydet: sonraki adimlarda (LLM kotasi, ag) bir sey
        # patlarsa kullanicinin bastigi dugmeler kaybolmasin.
        store.save_state(state)

    if args.feedback_only:
        print("Sadece cevaplar islendi.")
        return 0

    # 2) Slot araligi kontrolu.
    if not args.dry_run and not args.force:
        kalan = _too_soon(state, now)
        if kalan is not None:
            print(f"Son gonderimin uzerinden {config.MIN_GAP_HOURS} saat gecmedi "
                  f"({kalan:.1f} saat kaldi). Cikiliyor.")
            return 0

    # 3) Tekrarlar. Yeni kelimelerden once gonderiyoruz: hatirlamayi
    #    denemek, taze bilgiyle dolmadan once daha iyi calisiyor.
    tekrarlar = store.due_cards(state, today, tekrar_adet, langs=config.LANGS)
    print(f"Vadesi gelen tekrar: {len(tekrarlar)} kart")

    # 4) Yeni kelimeler havuzdan gelir. Havuz bu slotu karsilamiyorsa tek
    #    bir LLM cagrisiyla gunun tamami uretilip havuza konur - slot basina
    #    cagri yapmak ucretsiz katmanin gunluk istek hakkini bitiriyordu.
    #    Her dil icin ayri cagri: tek istemde iki dil karistirmak model
    #    ciktisinin kalitesini belirgin dusuruyor.
    yeniler: list[tuple[dict, str]] = []
    if yeni_adet > 0:
        for dil, adet in _split_quota(yeni_adet, config.LANGS).items():
            if adet <= 0:
                continue
            spec = config.lang_spec(dil)
            elde = store.pool_count(state, dil)

            if elde < adet and not args.no_llm:
                # Havuzu tepeye kadar dolduruyoruz: bugun bir daha cagri
                # yapmamak icin. En az bu slotun ihtiyaci kadar isteriz.
                istenen = max(config.POOL_TARGET - elde, adet)
                print(f"{spec['label']} havuzunda {elde} kelime var, "
                      f"{istenen} kelime uretiliyor (seviye {spec['level']})...")
                try:
                    kelimeler = generate.generate(
                        dil, istenen,
                        exclude=store.recent_words(state, dil, config.EXCLUDE_HINT_LIMIT),
                        known=store.known_words(state, dil),
                    )
                except Exception as exc:
                    # Kota dolmus ya da saglayici yanit vermiyor olabilir.
                    # Tekrarlar LLM gerektirmiyor; gonderim tumden iptal
                    # edilmez, havuzda ne varsa o gider.
                    print(f"  Kelime uretilemedi ({type(exc).__name__}: {exc})")
                else:
                    print(f"  Havuza {store.pool_add(state, kelimeler)} kelime eklendi.")
            elif elde >= adet:
                print(f"{spec['label']}: havuzdan {adet} kelime "
                      f"({elde} bekliyor, LLM cagrisi yok)")

            for kelime in store.pool_take(state, dil, adet):
                kelime["id"] = store.card_id(dil, kelime["word"])
                yeniler.append((kelime, dil))

    if not tekrarlar and not yeniler:
        # Bu bir cokme degil: saglayici gecici olarak yanit vermemis ya da
        # gunluk kota dolmus, ustelik vadesi gelen tekrar da yok. Hata
        # koduyla cikmak her seferinde kirmizi bir calisma ve bir ariza
        # e-postasi uretiyordu. Bunun yerine gunde bir kez Telegram'dan
        # haber verip sessizce cikiyoruz; sonraki slot yeniden deniyor.
        print("Gonderilecek kart yok. (Tekrar vadesi gelmemis ve yeni kelime uretilememis.)")
        if not args.dry_run:
            _bos_slot_bildir(state, now)
            store.save_state(state)
        return 0

    gonderilenler: list[tuple[dict, str]] = []
    sesli = config.AUDIO_ENABLED and not args.no_audio
    dugmeli = config.BUTTONS_ENABLED and not args.no_buttons

    if args.dry_run:
        print("\n" + "=" * 50)
        for card in tekrarlar:
            _print_card(card, "review")
        for kelime, _ in yeniler:
            _print_card(kelime, "new")
        print("=" * 50)
        print("\n--dry-run: hicbir sey gonderilmedi, durum dosyasi degismedi.")
        return 0

    deliver.send_header(
        new_count=len(yeniler), review_count=len(tekrarlar),
        stats=store.stats(state), now=now,
    )

    for card in tekrarlar:
        deliver.send_card(card, kind="review", with_audio=sesli, with_buttons=dugmeli)
        # Cevap gelmezse yarina otele - yoksa ayni kart her uc saatte tekrar cikar.
        srs.on_shown_unanswered(card, today)
        gonderilenler.append((card, "review"))

    for kelime, dil in yeniler:
        deliver.send_card(kelime, kind="new", with_audio=sesli, with_buttons=dugmeli)
        # Hafizaya gonderimden SONRA ekliyoruz: gonderim patlarsa kelime
        # "gorulmus" sayilip bir daha hic karsina cikmamis olmasin.
        _, card = store.add_card(state, kelime, dil, today, now.isoformat())
        gonderilenler.append((card, "new"))

    if not args.no_archive:
        deliver.append_archive(gonderilenler, now)

    state["last_sent_at"] = now.isoformat()
    store.save_state(state)

    ozet = store.stats(state)
    print(f"Bitti: {len(yeniler)} yeni + {len(tekrarlar)} tekrar gonderildi. "
          f"Toplam {ozet['toplam']} kelime.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
