# lingo-radar

Sabah 9'dan akşam 9'a kadar üç saatte bir telefonuna düşen İngilizce kelime
kartları. Her seferinde **3 yeni kelime + 2 tekrar**. **Tamamen ücretsiz
çalışır.**

Telefonuna gelen kart şuna benziyor — sesli telaffuzuyla birlikte:

> 🆕 **resilient**  `/rɪˈzɪliənt/`
> _adjective · B2_ 🇬🇧
>
> **dirençli, esnek, güçlü**
> _Able to quickly return to a previous good condition after a difficult situation._
>
> “Local businesses proved to be highly resilient during the economic crisis.”
> _Yerel işletmeler ekonomik kriz sırasında son derece dirençli olduklarını kanıtladı._
>
> 🔗 resilient system · highly resilient
>
> `✅ Biliyordum`  `🔁 Bilmiyordum`

Düğmeye bastığın cevap, kelimenin **ne zaman tekrar karşına çıkacağını**
belirler. Amaç kelime biriktirmek değil, biriktirdiğini unutmamak.

---

## Neden günde 15 kelime, 25 değil?

Günde 25 yeni kelime kâğıt üzerinde hızlı görünür ama üç gün sonra ilk
günkülerin hiçbiri aklında kalmaz. Bu bot yeni kelimeyi günde 15'te tutuyor
(5 mesaj × 3 kelime) ve kalan yeri **aralıklı tekrara** ayırıyor.

Tekrar takvimi Leitner kutu sistemi:

| Kutu | Bir sonraki tekrar |
|------|--------------------|
| 1 | 1 gün sonra |
| 2 | 2 gün sonra |
| 3 | 4 gün sonra |
| 4 | 8 gün sonra |
| 5 | 16 gün sonra |
| 6 | 32 gün sonra |

**Biliyordum** → kelime bir üst kutuya çıkar, aralık uzar.
**Bilmiyordum** → 1. kutuya düşer, ertesi gün yine gelir.
**Hiç basmazsan** → kart yarına ötelenir; aynı kelime gün boyu tekrarlanmaz.

---

## Ücretsiz mi? Evet, dört parçanın da bedava katmanı var

| Parça | Nasıl ücretsiz |
|---|---|
| **Telegram bot** | Tamamen ücretsiz, limit yok |
| **GitHub Actions** (zamanlama) | Public repoda sınırsız |
| **Google Gemini** (kelime üretimi) | Ücretsiz katman, kredi kartı istemiyor |
| **gTTS** (telaffuz sesi) | Google Translate'in konuşma ucu, anahtar istemiyor |

Günde 5 LLM çağrısı yapılıyor; Gemini'nin ücretsiz katmanı günde 1500 isteğe
izin veriyor.

---

## Kurulum

**1. Paketler**

```
git clone <repo-adresi> && cd lingo-radar
python -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
```

**2. Telegram botu.** Telegram'da [@BotFather](https://t.me/BotFather)'a
`/newbot` yaz, bir isim ver, sana verdiği token'ı sakla. Sonra **oluşturduğun
bota bir mesaj at** — bot, kendisine hiç yazılmamış bir sohbete mesaj
gönderemez, bu adım şart.

**3. Gemini anahtarı.** [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
adresinden al. Kredi kartı istemiyor.

**4. `.env` dosyası**

```
copy .env.example .env
```

İçine token'ı ve API anahtarını yaz, sonra chat id'yi bul:

```
python get_chat_id.py
```

Çıkan `TELEGRAM_CHAT_ID=...` satırını `.env` içine yapıştır.

**5. Dene**

```
python main.py --test-telegram   # örnek bir kart gönderir
python main.py                   # gerçek çalışma
```

---

## Otomatik çalıştırma (GitHub Actions)

Bilgisayarın kapalıyken de kartların gelmesi için repoyu GitHub'a koy:

1. **Settings → Secrets and variables → Actions → Secrets**'a üç değer ekle:
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`
2. **Settings → Actions → General → Workflow permissions**'da
   **Read and write permissions**'ı seç. Bot öğrendiğin kelimeleri repoya
   commit ederek hatırlıyor; bu izin olmazsa hafıza her çalışmada sıfırlanır.

İki iş akışı var:

| Akış | Ne zaman | Ne yapar |
|---|---|---|
| `lingo-radar.yml` | 09:00 · 12:00 · 15:00 · 18:00 · 21:00 (TR) | Kartları gönderir |
| `lingo-feedback.yml` | Gündüz her 10 dakikada | Düğme cevaplarını işler |

Bundan sonra **elle hiçbir komut çalıştırmıyorsun.** Düğmeye bastıktan en geç
10 dakika sonra kartın altı `biliyordum — 4 gün sonra tekrar` diye güncellenir.
Anında görmek istersen, bilgisayarın açıkken `python main.py --watch`
çalıştırabilirsin.

> **Private repo kullanacaksan:** 10 dakikalık cevap akışı aylık 2000 dakikalık
> ücretsiz kotayı aşar. `lingo-feedback.yml` içindeki cron'u `"0 7-19 * * *"`
> yapıp saatliğe çek ya da dosyayı sil. Public repoda böyle bir sınır yok.

---

## Komutlar

| Komut | Ne yapar |
|---|---|
| `python main.py` | Cevapları işle, kartları gönder, arşivle |
| `python main.py --dry-run` | Göndermeden ekrana bas |
| `python main.py --stats` | Kaç kelime, hangi kutuda, kaçı oturmuş |
| `python main.py --watch` | Cevapları anında işle (Ctrl+C ile çık) |
| `python main.py --new 5 --review 3` | Bu çalışma için sayıları değiştir |
| `python main.py --test-telegram` | Kurulumu doğrula |
| `python test_offline.py` | Ağ gerektirmeyen testler |

---

## Ayarlar

Hepsi `.env` üzerinden, kod değiştirmeden:

| Ayar | Varsayılan | Ne işe yarar |
|---|---|---|
| `LINGO_EN_LEVEL` | `B2-C1` | Kelimelerin CEFR seviyesi |
| `LINGO_NEW_PER_RUN` | `3` | Mesaj başına yeni kelime |
| `LINGO_REVIEW_PER_RUN` | `2` | Mesaj başına tekrar |
| `LINGO_EN_ACCENT` | `co.uk` | Telaffuz aksanı (`com` = Amerikan) |
| `LINGO_AUDIO` | `1` | `0` yaparsan ses gönderilmez |
| `LINGO_LANGS` | `en` | Diller (aşağıya bak) |

**İspanyolca eklemek:** kod baştan çok dilli yazıldı, sadece kapalı duruyor.
`.env` içine `LINGO_LANGS=en,es` ve `LINGO_ES_LEVEL=A1-A2` yaz; yeni kelime
kotası iki dil arasında paylaştırılır, İngilizce hafızan olduğu gibi kalır.

---

## Dosya düzeni

```
main.py              Akış: cevapları işle → tekrarları seç → yeni üret → gönder
lingo/config.py      Diller, seviyeler, günlük yük, tekrar aralıkları
lingo/srs.py         Leitner kutu sistemi
lingo/store.py       data/state.json — kelime hafızası
lingo/generate.py    LLM istemi ve çıktı doğrulama
lingo/llm.py         Gemini / Groq / OpenRouter / Claude ortak katmanı
lingo/tts.py         gTTS ile mp3 telaffuz
lingo/deliver.py     Telegram mesajı, düğmeler, arşiv
lingo/feedback.py    Düğme cevaplarını tekrar takvimine işler
data/state.json      Öğrendiğin her kelime ve tekrar takvimi
archive/*.md         Günlük okunabilir kayıt
```

Hafızanın tek kaynağı `data/state.json` — yedeklemek istersen bu dosyayı
kopyalaman yeterli, silersen bot sıfırdan başlar.

---

## Bilinen sınırlar

- **Cron gecikmesi.** GitHub planlı çalışmaları yoğunlukta 5-30 dakika
  geciktirebiliyor. Her slot için yedek tetikleme var; ilki çalıştıysa yedek
  sessizce çıkar, mükerrer kart gelmez.
- **Düğme cevabı anında işlenmez.** Ücretsiz kalmanın bedeli: anında cevap 7/24
  ayakta duran bir sunucu ister.
- **gTTS resmi bir servis değil.** Geçici olarak yanıt vermeyebilir; o durumda
  kart sesli mesaj yerine düz metin olarak gelir, gönderim kaybolmaz.
- **LLM kotası dolarsa** o çalışmada yeni kelime üretilmez, sadece tekrarlar
  gönderilir — tekrarlar LLM gerektirmiyor.
