"""Ag ve API anahtari gerektirmeyen testler.

Riskli olan kisimlar burada: modelin JSON'unu ayristirma, tekrar
takviminin dogru ilerlemesi, HTML kacisi, aciklama siniri ve dugme
cevaplarinin karta islenmesi.

    python test_offline.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

from lingo import config, deliver, feedback, generate, srs, store

FAILURES: list[str] = []
TODAY = dt.date(2026, 9, 16)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  gecti  {name}")
    else:
        FAILURES.append(name)
        print(f"  KALDI  {name} {detail}")


def make_card(word: str = "ubiquitous", **kw) -> dict:
    card = {
        "id": store.card_id("en", word),
        "lang": "en",
        "word": word,
        "ipa": "/juːˈbɪkwɪtəs/",
        "pos": "adjective",
        "level": "C1",
        "meaning_tr": "her yerde bulunan",
        "definition_en": "present or found everywhere",
        "example": "Smartphones have become ubiquitous in modern life.",
        "example_tr": "Akilli telefonlar modern hayatta her yerde.",
        "collocations": ["ubiquitous presence"],
        "box": 1,
        "due": TODAY.isoformat(),
    }
    card.update(kw)
    return card


# --- Aralikli tekrar -------------------------------------------------------

def test_srs():
    print("\nAralikli tekrar")
    card = make_card()
    srs.on_known(card, TODAY)
    check("dogru cevap kutuyu yukseltir", card["box"] == 2, f"box={card['box']}")
    check("vade 2 gun sonraya gider",
          card["due"] == (TODAY + dt.timedelta(days=2)).isoformat(), card["due"])

    for _ in range(10):
        srs.on_known(card, TODAY)
    check("kutu ust sinirda durur", card["box"] == config.MAX_BOX, f"box={card['box']}")

    srs.on_unknown(card, TODAY)
    check("yanlis cevap 1. kutuya dusurur", card["box"] == 1)
    check("yanlis cevap yarina planlar",
          card["due"] == (TODAY + dt.timedelta(days=1)).isoformat(), card["due"])
    check("sayaclar tutuluyor",
          card["known_count"] == 11 and card["unknown_count"] == 1,
          f"{card['known_count']}/{card['unknown_count']}")

    # Cevapsiz kart: bugun vadesi gelmisken gosterildi, yarina otelenmeli.
    cevapsiz = make_card("laconic", box=3, due=TODAY.isoformat())
    srs.on_shown_unanswered(cevapsiz, TODAY)
    check("cevapsiz kart yarina otelenir",
          cevapsiz["due"] == (TODAY + dt.timedelta(days=1)).isoformat(), cevapsiz["due"])
    check("cevapsiz kart kutusunu korur", cevapsiz["box"] == 3)

    ileri = make_card("prolific", box=4, due=(TODAY + dt.timedelta(days=5)).isoformat())
    srs.on_shown_unanswered(ileri, TODAY)
    check("ileri vadeli kart geri cekilmez",
          ileri["due"] == (TODAY + dt.timedelta(days=5)).isoformat(), ileri["due"])

    check("yeni kart 1. kutuda baslar", srs.new_card_fields(TODAY)["box"] == 1)
    check("vadesi gelen kart tespit ediliyor",
          srs.is_due(make_card(due="2026-09-01"), TODAY))
    check("vadesi gelmeyen kart elenir",
          not srs.is_due(make_card(due="2026-12-01"), TODAY))


# --- Hafiza ----------------------------------------------------------------

def test_store():
    print("\nKelime hafizasi")
    check("kart kimligi kararli",
          store.card_id("en", "Ubiquitous") == store.card_id("en", " ubiquitous "))
    check("dil kimligi ayirir",
          store.card_id("en", "casa") != store.card_id("es", "casa"))
    check("kimlik callback_data'ya sigar",
          len(f"k:{store.card_id('en', 'a very long multi word phrase here')}") <= 64)

    with tempfile.TemporaryDirectory() as tmp:
        eski = store.STATE_PATH
        store.STATE_PATH = Path(tmp) / "state.json"
        try:
            state = store.empty_state()
            _, card = store.add_card(state, make_card(), "en", TODAY, "2026-09-16T09:00:00")
            check("kart eklendi", len(state["cards"]) == 1)
            check("yeni kart tekrar alanlarini aliyor", card["due"] and card["box"] == 1)

            store.save_state(state)
            geri = store.load_state()
            check("durum diske yazilip geri okunuyor", len(geri["cards"]) == 1)
            check("turkce karakterler korunuyor",
                  list(geri["cards"].values())[0]["meaning_tr"] == "her yerde bulunan")

            store.STATE_PATH.write_text("{bozuk json", encoding="utf-8")
            kurtarilan = store.load_state()
            check("bozuk dosya cokmeye yol acmiyor", kurtarilan["cards"] == {})
            check("bozuk dosya yedeklenmis",
                  (Path(tmp) / "state.json.bozuk").exists())
        finally:
            store.STATE_PATH = eski

    state = store.empty_state()
    for kelime, kutu, vade in (
        ("alpha", 3, "2026-09-10"), ("beta", 1, "2026-09-10"),
        ("gamma", 2, "2026-09-16"), ("delta", 1, "2026-12-01"),
    ):
        cid = store.card_id("en", kelime)
        state["cards"][cid] = make_card(kelime, id=cid, box=kutu, due=vade)

    vadesi = store.due_cards(state, TODAY, 5, langs=["en"])
    check("gelecek vadeli kart secilmiyor",
          all(c["word"] != "delta" for c in vadesi), str([c["word"] for c in vadesi]))
    check("en eski vade once geliyor", vadesi[0]["due"] == "2026-09-10")
    check("ayni vadede zor kelime once", vadesi[0]["word"] == "beta", vadesi[0]["word"])
    check("limit uygulaniyor", len(store.due_cards(state, TODAY, 2, langs=["en"])) == 2)
    check("bilinen kelimeler toplaniyor",
          store.known_words(state, "en") == {"alpha", "beta", "gamma", "delta"})
    check("ispanyolca filtresi bos donuyor", store.known_words(state, "es") == set())


# --- Kelime havuzu ---------------------------------------------------------

def test_pool():
    print("\nKelime havuzu")
    state = store.empty_state()
    eklendi = store.pool_add(state, [
        {"word": "alpha", "lang": "en"},
        {"word": "beta", "lang": "en"},
        {"word": "Alpha", "lang": "en"},        # ayni kelime, farkli yazim
        {"word": "casa", "lang": "es"},
    ])
    check("mukerrer kelime havuza girmiyor", eklendi == 3, str(eklendi))
    check("dil basina sayim dogru", store.pool_count(state, "en") == 2)
    check("toplam sayim dogru", store.pool_count(state) == 3)
    check("havuzdaki kelime 'bilinen' sayiliyor",
          "alpha" in store.known_words(state, "en"))
    check("havuz dil filtresine uyuyor", "casa" not in store.known_words(state, "en"))

    alinan = store.pool_take(state, "en", 1)
    check("istenen sayida alindi",
          len(alinan) == 1 and alinan[0]["word"] == "alpha", str(alinan))
    check("alinan havuzdan cikarildi", store.pool_count(state, "en") == 1)
    check("diger dile dokunulmadi", store.pool_count(state, "es") == 1)
    check("sira korunuyor", store.pool_take(state, "en", 1)[0]["word"] == "beta")
    check("bos havuz bos liste donuyor", store.pool_take(state, "en", 3) == [])

    # Havuz durumu diske yazilip geri okunabilmeli - slotlar arasinda
    # yasayacagi tek yer orasi.
    with tempfile.TemporaryDirectory() as tmp:
        eski = store.STATE_PATH
        store.STATE_PATH = Path(tmp) / "state.json"
        try:
            s2 = store.empty_state()
            store.pool_add(s2, [{"word": "gamma", "lang": "en", "ipa": "/g/"}])
            store.save_state(s2)
            geri = store.load_state()
            check("havuz diskte kalici", store.pool_count(geri, "en") == 1)
            check("havuz alanlari korunuyor", geri["pool"][0]["ipa"] == "/g/")
        finally:
            store.STATE_PATH = eski

    # Eski surumden gelen, havuz alani olmayan durum dosyasi cokmemeli.
    eski_bicim = {"version": 1, "cards": {}, "update_offset": 0}
    check("havuzsuz eski durum cokmuyor", store.pool_count(eski_bicim) == 0)

    # Haric listesi: havuzdakiler basta olmali ki model onlari tekrar
    # onerip parti icindeki yerleri bosa harcamasin.
    state3 = store.empty_state()
    cid = store.card_id("en", "gonderilmis")
    state3["cards"][cid] = make_card("gonderilmis", id=cid)
    store.pool_add(state3, [{"word": "bekleyen", "lang": "en"}])
    haric = store.recent_words(state3, "en", 10)
    check("havuzdaki kelime haric listesinde", "bekleyen" in haric, str(haric))
    check("havuzdaki kelime basta", haric[0] == "bekleyen", str(haric))
    check("gonderilmis kelime de listede", "gonderilmis" in haric, str(haric))
    check("haric listesi limitleniyor", len(store.recent_words(state3, "en", 1)) == 1)


# --- LLM ciktisi -----------------------------------------------------------

GECERLI = {
    "word": "resilient", "pos": "adjective", "ipa": "rɪˈzɪliənt", "level": "b2",
    "meaning_tr": "dayanikli", "definition_en": "able to recover quickly",
    "example": "Small firms proved surprisingly resilient during the crisis.",
    "example_tr": "Kucuk firmalar kriz boyunca dayanikli cikti.",
    "collocations": ["resilient economy", "remarkably resilient"],
}


def test_parsing():
    print("\nModel ciktisini ayristirma")
    duz = json.dumps({"words": [GECERLI]})
    check("duz JSON ayristiriliyor", len(generate.parse_words(duz)) == 1)

    fenced = f"```json\n{duz}\n```"
    check("kod bloku soyuluyor", len(generate.parse_words(fenced)) == 1)

    gevezelik = f"Iste kartlariniz:\n{duz}\nUmarim ise yarar!"
    check("metin arasindan JSON cikariliyor", len(generate.parse_words(gevezelik)) == 1)

    check("ciplak liste kabul ediliyor",
          len(generate.parse_words(json.dumps([GECERLI]))) == 1)

    try:
        generate.parse_words("bugun kelime uretmek istemiyorum")
        check("JSON yoksa hata veriyor", False)
    except generate.GenerateError:
        check("JSON yoksa hata veriyor", True)


def test_validation():
    print("\nKart dogrulama")
    kart = generate.clean_word(dict(GECERLI), "en")
    check("gecerli kart geciyor", kart is not None)
    check("IPA egik cizgiyle sarmalaniyor", kart["ipa"] == "/rɪˈzɪliənt/", kart["ipa"])
    check("seviye buyuk harfe ceviriliyor", kart["level"] == "B2")
    check("dil etiketleniyor", kart["lang"] == "en")

    for alan in ("word", "ipa", "meaning_tr", "example", "example_tr", "definition_en"):
        eksik = dict(GECERLI)
        eksik.pop(alan)
        check(f"eksik '{alan}' eleniyor", generate.clean_word(eksik, "en") is None)

    kisa = dict(GECERLI, example="Very resilient.")
    check("cok kisa ornek cumle eleniyor", generate.clean_word(kisa, "en") is None)

    bos = dict(GECERLI, meaning_tr="   ")
    check("bos alan eleniyor", generate.clean_word(bos, "en") is None)

    metin_esles = dict(GECERLI, collocations="resilient economy")
    check("metin eslesme listeye ceviriliyor",
          generate.clean_word(metin_esles, "en")["collocations"] == ["resilient economy"])

    esles_yok = dict(GECERLI)
    esles_yok.pop("collocations")
    check("eslesme yoksa bos liste",
          generate.clean_word(esles_yok, "en")["collocations"] == [])

    seviye_yok = dict(GECERLI)
    seviye_yok.pop("level")
    check("seviye yoksa kart yine de geciyor",
          generate.clean_word(seviye_yok, "en")["level"] == "?")


def test_generate_filters():
    print("\nKelime uretimi (sahte LLM)")
    kelimeler = [
        dict(GECERLI, word="alpha"), dict(GECERLI, word="beta"),
        dict(GECERLI, word="Alpha"),          # ayni kelime, farkli yazim
        dict(GECERLI, word="gamma"),
        {"word": "bozuk"},                     # dogrulamayi gecemez
        dict(GECERLI, word="delta"),
    ]
    cagrilar: list[tuple[str, str]] = []

    def sahte(system: str, user: str) -> str:
        cagrilar.append((system, user))
        return json.dumps({"words": kelimeler})

    gercek = generate.llm.complete
    generate.llm.complete = sahte
    try:
        sonuc = generate.generate("en", 3, exclude=["beta"], known={"beta"})
        check("istenen sayida kelime donuyor", len(sonuc) == 3, str(len(sonuc)))
        secilen = [k["word"] for k in sonuc]
        check("bilinen kelime elenir", "beta" not in secilen, str(secilen))
        check("buyuk/kucuk harf mukerreri elenir",
              len({w.lower() for w in secilen}) == len(secilen), str(secilen))
        check("bozuk kart elenir", "bozuk" not in secilen)
        check("haric listesi isteme giriyor", "beta" in cagrilar[0][1])
        check("seviye isteme giriyor", config.lang_spec("en")["level"] in cagrilar[0][1])
        check("fazladan kelime isteniyor", "6" in cagrilar[0][1].split("Istenen kelime sayisi:")[1][:6])

        # Hepsi zaten biliniyorsa sessizce bos donmek yerine hata versin:
        # sessiz bos donus, gonderim adiminda fark edilmeden kaybolurdu.
        try:
            generate.generate("en", 3, exclude=[],
                              known={"alpha", "beta", "gamma", "delta"})
            check("hepsi bilinen kelimeyse hata veriyor", False)
        except generate.GenerateError:
            check("hepsi bilinen kelimeyse hata veriyor", True)

        check("sifir istenirse LLM cagrilmiyor",
              generate.generate("en", 0, exclude=[]) == [] and len(cagrilar) == 2)
    finally:
        generate.llm.complete = gercek


# --- Mesaj bicimi ----------------------------------------------------------

def test_rendering():
    print("\nKart gorunumu")
    kart = make_card()
    metin = deliver.render_card(kart, kind="new")
    check("kelime kalin yazilmis", "<b>ubiquitous</b>" in metin)
    check("IPA kod bloku icinde", "<code>/juːˈbɪkwɪtəs/</code>" in metin)
    check("yeni kart rozeti var", deliver.NEW_EMOJI in metin)
    check("yeni kartta kutu bilgisi yok", "kutu" not in metin)
    check("ornek cumle var", "Smartphones" in metin)
    check("turkce ceviri var", "Akilli telefonlar" in metin)

    tekrar = deliver.render_card(make_card(box=3), kind="review")
    check("tekrar kartinda kutu gosteriliyor", "kutu 3" in tekrar, tekrar[:80])
    check("tekrar rozeti var", deliver.REVIEW_EMOJI in tekrar)

    tehlikeli = make_card(meaning_tr="a < b & c > d", example_tr="<script>alert(1)</script>")
    kacisli = deliver.render_card(tehlikeli, kind="new")
    check("HTML ozel karakterleri kaciriliyor",
          "&lt;script&gt;" in kacisli and "&amp;" in kacisli)
    check("kesme isareti bozulmuyor",
          "&#x27;" not in deliver.render_card(
              make_card(example="It doesn't matter at all here."), kind="new"))

    uzun = make_card(
        definition_en="cok uzun bir tanim " * 80,
        example_tr="cok uzun bir ceviri " * 80,
    )
    kirpilmis = deliver.render_card(uzun, kind="new")
    check("aciklama siniri asilmiyor",
          len(kirpilmis) <= config.CAPTION_LIMIT, str(len(kirpilmis)))

    klavye = deliver.card_keyboard(kart["id"])
    dugmeler = klavye["inline_keyboard"][0]
    check("iki dugme var", len(dugmeler) == 2)
    check("callback_data 64 bayt siniri icinde",
          all(len(d["callback_data"].encode()) <= 64 for d in dugmeler))
    check("dugme verisi kart kimligini tasiyor",
          dugmeler[0]["callback_data"] == f"k:{kart['id']}")

    cevaplanmis = deliver.answered_keyboard(make_card(box=3, last_answer="known"))
    check("cevaplanmis klavye tek dugme", len(cevaplanmis["inline_keyboard"][0]) == 1)
    check("cevaplanmis klavye araligi gosteriyor",
          "4 gun" in cevaplanmis["inline_keyboard"][0][0]["text"],
          cevaplanmis["inline_keyboard"][0][0]["text"])


def test_archive(tmpdir: Path):
    print("\nArsiv")
    eski = deliver.ARCHIVE_DIR
    deliver.ARCHIVE_DIR = tmpdir / "archive"
    try:
        simdi = dt.datetime(2026, 9, 16, 9, 17, tzinfo=config.TR_TZ)
        yol = deliver.append_archive([(make_card(), "new")], simdi)
        icerik = yol.read_text(encoding="utf-8")
        check("arsiv basligi yaziliyor", "# lingo-radar - 2026-09-16" in icerik)
        check("slot saati yaziliyor", "## 09:17" in icerik)
        check("kelime yaziliyor", "ubiquitous" in icerik)

        deliver.append_archive([(make_card("laconic", box=2), "review")],
                               simdi.replace(hour=12, minute=17))
        icerik = yol.read_text(encoding="utf-8")
        check("ayni gune ekleniyor, ustune yazilmiyor",
              "ubiquitous" in icerik and "laconic" in icerik)
        check("baslik bir kez yaziliyor", icerik.count("# lingo-radar") == 1)
        check("tekrar kartinin kutusu yaziliyor", "kutu 2" in icerik)
    finally:
        deliver.ARCHIVE_DIR = eski


# --- Dugme cevaplari -------------------------------------------------------

def test_feedback():
    print("\nDugme cevaplari")
    state = store.empty_state()
    bilinen = make_card("alpha", box=2)
    bilinmeyen = make_card("beta", box=4)
    state["cards"][bilinen["id"]] = bilinen
    state["cards"][bilinmeyen["id"]] = bilinmeyen

    cagrilar: list[str] = []

    def sahte_call(method: str, *, data: dict, files=None, raise_on_error=True,
                   timeout=None) -> dict:
        cagrilar.append(method)
        if method != "getUpdates":
            return {"ok": True, "result": True}
        mesaj = {"message_id": 1, "chat": {"id": 42}}
        return {"ok": True, "result": [
            {"update_id": 100, "callback_query": {
                "id": "q1", "data": f"k:{bilinen['id']}", "message": mesaj}},
            {"update_id": 101, "callback_query": {
                "id": "q2", "data": f"u:{bilinmeyen['id']}", "message": mesaj}},
            {"update_id": 102, "callback_query": {
                "id": "q3", "data": "k:olmayan123", "message": mesaj}},
            {"update_id": 103, "callback_query": {"id": "q4", "data": "noop",
                                                  "message": mesaj}},
            {"update_id": 104, "message": {"text": "merhaba"}},
        ]}

    gercek = deliver.call
    deliver.call = sahte_call
    try:
        ozet = feedback.poll(state, TODAY)
    finally:
        deliver.call = gercek

    check("biliyordum sayildi", ozet["biliyordum"] == 1, str(ozet))
    check("bilmiyordum sayildi", ozet["bilmiyordum"] == 1, str(ozet))
    check("eslesmeyen kart sayildi", ozet["eslesmeyen"] == 1, str(ozet))
    check("dogru cevap kutuyu yukseltti", bilinen["box"] == 3, str(bilinen["box"]))
    check("yanlis cevap kutuyu dusurdu", bilinmeyen["box"] == 1,
          str(bilinmeyen["box"]))
    check("offset duz mesaji da onayliyor", state["update_offset"] == 105,
          str(state["update_offset"]))
    check("her sorgu yanitlandi", cagrilar.count("answerCallbackQuery") == 4,
          str(cagrilar))
    check("cevaplanan kartlarin klavyesi guncellendi",
          cagrilar.count("editMessageReplyMarkup") == 2, str(cagrilar))

    # Cevap gelmezse offset ilerlemez ve kart dokunulmadan kalir.
    state2 = store.empty_state()
    deliver.call = lambda method, *, data, files=None, raise_on_error=True, timeout=None: {
        "ok": True, "result": []}
    try:
        bos = feedback.poll(state2, TODAY)
    finally:
        deliver.call = gercek
    check("cevap yoksa sessizce geciyor", bos["biliyordum"] == 0)
    check("cevap yoksa offset degismiyor", state2["update_offset"] == 0)

    # Uzun yoklama suresi Telegram'a gecmeli ve kendi HTTP zaman asimimizin
    # altinda kalmali - ustunde olursa istek cevap gelmeden kopar.
    istekler = []

    def kaydeden(method, *, data, files=None, raise_on_error=True, timeout=None):
        istekler.append({"data": data, "timeout": timeout})
        return {"ok": True, "result": []}

    deliver.call = kaydeden
    try:
        feedback.poll(store.empty_state(), TODAY)
        feedback.poll(store.empty_state(), TODAY, long_poll=25)
    finally:
        deliver.call = gercek
    check("planli calisma beklemeden cikiyor", istekler[0]["data"]["timeout"] == 0)
    check("watch modu uzun yoklama yapiyor", istekler[1]["data"]["timeout"] == 25)
    check("HTTP siniri bekleme suresini kapsiyor",
          istekler[1]["timeout"] > istekler[1]["data"]["timeout"] + 5,
          f"HTTP {istekler[1]['timeout']} vs bekleme {istekler[1]['data']['timeout']}")


def test_watch_loop():
    print("\nDinleme modu")
    import main as main_mod

    cagri = {"sayi": 0}

    def sahte_poll(state, today, *, edit_messages=True, long_poll=0):
        cagri["sayi"] += 1
        state["update_offset"] = cagri["sayi"]      # her turda ilerlesin
        if cagri["sayi"] >= 3:
            raise KeyboardInterrupt
        return {"biliyordum": 0, "bilmiyordum": 0, "eslesmeyen": 0}

    kayitlar = []
    gercek_poll, gercek_save = main_mod.feedback.poll, main_mod.store.save_state
    main_mod.feedback.poll = sahte_poll
    main_mod.store.save_state = lambda state: kayitlar.append(dict(state))
    try:
        state = store.empty_state()
        try:
            main_mod.watch(state)
            check("Ctrl+C dongudan cikariyor", False)
        except KeyboardInterrupt:
            check("Ctrl+C dongudan cikariyor", True)
        check("dongu tekrar tekrar yokluyor", cagri["sayi"] == 3, str(cagri["sayi"]))
        check("offset ilerledikce kaydediliyor", len(kayitlar) == 2, str(len(kayitlar)))
    finally:
        main_mod.feedback.poll = gercek_poll
        main_mod.store.save_state = gercek_save


# --- Ana akis --------------------------------------------------------------

def test_main_helpers():
    print("\nAna akis yardimcilari")
    import main as main_mod

    check("tek dilde kotanin tamami ona gidiyor",
          main_mod._split_quota(3, ["en"]) == {"en": 3})
    iki = main_mod._split_quota(3, ["en", "es"])
    check("iki dilde kota bolunuyor", sum(iki.values()) == 3, str(iki))
    check("iki dilde de kelime var", all(v >= 1 for v in iki.values()), str(iki))
    check("dilsiz kota bos", main_mod._split_quota(3, []) == {})
    check("cift sayi esit bolunuyor",
          main_mod._split_quota(4, ["en", "es"]) == {"en": 2, "es": 2})

    simdi = dt.datetime(2026, 9, 16, 12, 17, tzinfo=config.TR_TZ)
    check("ilk calismada engel yok", main_mod._too_soon({"last_sent_at": None}, simdi) is None)
    yakin = {"last_sent_at": (simdi - dt.timedelta(minutes=30)).isoformat()}
    check("30 dakika once gonderildiyse engelleniyor",
          main_mod._too_soon(yakin, simdi) is not None)
    uzak = {"last_sent_at": (simdi - dt.timedelta(hours=3)).isoformat()}
    check("3 saat once gonderildiyse gecis serbest",
          main_mod._too_soon(uzak, simdi) is None)
    check("bozuk tarih engel olmuyor",
          main_mod._too_soon({"last_sent_at": "dun aksam"}, simdi) is None)
    # Saat dilimsiz kayit eski surumlerden kalabilir - TR kabul edilmeli.
    naif = {"last_sent_at": (simdi - dt.timedelta(hours=3)).replace(tzinfo=None).isoformat()}
    check("saat dilimsiz kayit cokmeye yol acmiyor",
          main_mod._too_soon(naif, simdi) is None)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        test_srs()
        test_store()
        test_pool()
        test_parsing()
        test_validation()
        test_generate_filters()
        test_rendering()
        test_archive(Path(tmp))
        test_feedback()
        test_watch_loop()
        test_main_helpers()

    print("\n" + "=" * 50)
    if FAILURES:
        print(f"{len(FAILURES)} test KALDI:")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("Tum testler gecti.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
