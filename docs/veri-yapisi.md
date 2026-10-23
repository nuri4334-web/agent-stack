# Veri yapısı — v1

Sunucunun SQLite tabloları. Sprint 1 · S1-03. Şemanın kendisi: `server/app/veritabani/tablolar.py`.

- Veritabanı Python'un kendi `sqlite3` modülüyle açılır; ek paket, ORM ya da migration aracı yoktur.
- Dosyanın yeri `.env` içindeki `VERITABANI_YOLU` ayarıdır (göreli yol repo köküne göre). Testler bellek içi (`:memory:`) veritabanı kullanır.
- Şema sürümü `PRAGMA user_version` içinde tutulur; şu anki sürüm **1**. Veritabanının sürümü koddakinden büyükse tablolar oluşturulmaz, hata verilir.
- Bütün tablolar `STRICT`'tir (yanlış türde değer reddedilir; en az SQLite 3.37.0 gerekir).
- Zaman alanları ISO 8601 metindir (ör. `2026-10-22T14:05:00+03:00`). Veritabanı zamanı kendisi doldurmaz; zamanı her zaman yazan kod verir.
- Kalıcı zincirleme silme (`ON DELETE CASCADE`) yoktur.

## Yetki zinciri

Bir kişinin hangi mesajları görebileceği şu zincirle bulunur:
`kisiler` → `bagli_hesaplar` (kaynak `slack`) → `slack_kullanicilari` → `kanal_uyelikleri` → `kanallar` (durum `izinli`).
Yani kişi, bağlı Slack hesabının üyesi olduğu ve durumu `izinli` olan kanalların mesajlarını görebilir; zincirin bir halkası eksikse hiçbir şey göremez.
Aşama 2'deki yetki kontrolü (`kapi.py` 2. adım) bu zinciri kullanacak. İstekteki geçici `kullanici` alanı bu zincirin parçası değildir.

## 1. `kisiler`

Sisteme giriş yapabilecek kişiler.

| Alan | Açıklama |
|---|---|
| `id` | Kişinin sistemdeki sayı kimliği. |
| `gorunen_ad` | Ekranda gösterilen ad; boş olamaz. |
| `rol` | `kullanici` ya da `admin`; verilmezse en az yetkili olan `kullanici` olur. |

## 2. `bagli_hesaplar`

Bir kişinin başka kaynaklardaki (Slack, Jira, GitHub) hesapları.

| Alan | Açıklama |
|---|---|
| `id` | Bağlantı satırının sayı kimliği. |
| `kisi_id` | Hesabın bağlı olduğu kişi (`kisiler.id`). |
| `kaynak` | Hesabın kaynağı: `slack`, `jira` ya da `github`. |
| `kaynak_kimligi` | Hesabın o kaynaktaki kimliği (ör. Slack kullanıcı kimliği `U123`). |
| `baglanma_sekli` | Hesabı kimin bağladığı: `yonetici` ya da `kendisi`. |
| `baglanma_zamani` | Hesabın bağlandığı zaman. |

Aynı kaynak hesabı (`kaynak` + `kaynak_kimligi`) iki kişiye bağlanamaz; bir kişi aynı kaynakta en fazla bir hesaba bağlanabilir.

## 3. `slack_kullanicilari`

Slack'teki herkes: sisteme hiç giriş yapmayanlar ve botlar dahil.

| Alan | Açıklama |
|---|---|
| `slack_id` | Slack kullanıcı kimliği (ör. `U123`). |
| `gorunen_ad` | Slack'teki görünen ad; bilinmiyorsa boş (NULL). |
| `gercek_ad` | Slack'teki gerçek ad; bilinmiyorsa boş (NULL). |
| `bot_mu` | Bot ise 1, insan ise 0; varsayılan 0. |

## 4. `kanallar`

Slack kanalları ve asistanın onları okuyup okuyamayacağı.

| Alan | Açıklama |
|---|---|
| `slack_id` | Slack kanal kimliği (ör. `C123`). |
| `ad` | Kanalın adı, `#` olmadan (ör. `dev`). |
| `ozel_mi` | Slack'te private kanal ise 1, değilse 0. |
| `durum` | `izinli` ya da `hariç`; yeni kanal her zaman `hariç` başlar, private olup olmaması bunu değiştirmez. |

Durum, `.env` içindeki izin listesinden (`IZINLI_KANALLAR`) `kanal_durumu()` kuralıyla hesaplanır (`server/app/veritabani/kurallar.py`).
`ik` kanalı izin listesine yazılsa bile `hariç` kalır: hem kuralda sabit yasak listesi vardır hem de tablo `ik` için `izinli` değerini kabul etmez.

## 5. `kanal_uyelikleri`

Hangi Slack kullanıcısının hangi kanalın üyesi olduğu.

| Alan | Açıklama |
|---|---|
| `kanal_id` | Kanal (`kanallar.slack_id`). |
| `slack_kullanici_id` | Üye olan Slack kullanıcısı (`slack_kullanicilari.slack_id`). |
| `guncelleme_zamani` | Bu üyeliğin Slack'ten en son doğrulandığı zaman; eski yetkiyi (bayat üyeliği) ölçmek için. |

Bir kullanıcı bir kanalda en fazla bir kez üye olarak yazılır.

## 6. `mesajlar`

Kanallardaki mesajlar; yalnızca temizlenmiş metin tutulur, ham metin alanı yoktur.

| Alan | Açıklama |
|---|---|
| `id` | Mesaj satırının sayı kimliği. |
| `kanal_id` | Mesajın kanalı (`kanallar.slack_id`). |
| `ts` | Slack mesaj kimliği; metin olarak ve tam olarak "10 rakam . 6 rakam" biçiminde (ör. `1729500000.000100`), ondalık sayı olarak yazılamaz. |
| `yazan_id` | Mesajı yazan Slack kullanıcısı ya da bot (`slack_kullanicilari.slack_id`). |
| `zaman` | Mesajın yazıldığı zaman. |
| `temiz_metin` | Temizlenmiş mesaj metni; mesaj metninin tutulduğu tek alan. |
| `supheli` | Mesaj şüpheli bulunduysa 1, bulunmadıysa 0; henüz kontrol edilmediyse boş (NULL). |

Aynı kanalda aynı `ts` ikinci kez yazılamaz.

## 7. `olay_kayitlari`

Kapı adımlarının ve Slack çekme çalışmalarının kararları. Mesaj metni, soru, cevap ya da serbest metin alanı yoktur; yalnızca kodlar, sayılar ve süreler tutulur.

| Alan | Açıklama |
|---|---|
| `id` | Kayıt satırının sayı kimliği. |
| `zaman` | Olayın zamanı. |
| `istek_id` | İsteğin kimliği (küçük onaltılık karakterler, en fazla 64); Slack çekmede o çalışmanın kimliğidir. |
| `kisi_id` | İsteği yapan kişi (`kisiler.id`); kimlik belirlenemediyse ya da Slack çekmeyse boş (NULL). |
| `adim` | Kapının 7 adımından biri (`kimlik` … `gosterim`) ya da `slack_cekme`. |
| `karar` | Kapı adımı için `gecti` / `durdu`, Slack çekme için `tamam` / `hata`. |
| `sebep_kodu` | Kararın sabit kodu (yalnızca büyük harf, rakam ve `_`, en fazla 40 karakter; ör. `KANAL_UYESI_DEGIL`); boş olabilir. |
| `kanal_id` | Olayın ilgili olduğu kanal (`kanallar.slack_id`); ör. çekilemeyen kanal; boş olabilir. |
| `mesaj_sayisi` | Adımda işlenen mesaj sayısı; Slack çekmede yeni mesaj sayısı. |
| `kanal_sayisi` | Slack çekmede işlenen kanal sayısı. |
| `kullanici_sayisi` | Slack çekmede işlenen kullanıcı sayısı. |
| `uyelik_sayisi` | Slack çekmede işlenen üyelik sayısı. |
| `engellenen_sayisi` | Bu adımda engellenen şey sayısı. |
| `maskelenen_sayisi` | Bu adımda maskelenen şey sayısı. |
| `supheli_sayisi` | Bu adımda şüpheli bulunan şey sayısı. |
| `sure_ms` | Adımın süresi, milisaniye. |

Bütün sayılar en az 0'dır ve verilmezse 0 olur.

**Slack çekme kaydı (S1-04):** Her çekme çalışması kendine yeni bir kimlik alır (kapıdaki `istek_id` ile aynı biçimde, küçük onaltılık) ve bu kimliği `istek_id` alanına yazar; `kisi_id` boş kalır.
Çalışmanın sonunda bir özet satırı yazılır (`adim = slack_cekme`, `karar = tamam`, `kanal_sayisi`, `kullanici_sayisi`, `uyelik_sayisi`, `mesaj_sayisi` dolu).
Çekilemeyen her kanal için ayrı bir satır yazılır (`karar = hata`, ör. `sebep_kodu = KANAL_CEKILEMEDI`, `kanal_id` dolu).

Slack çekmenin sebep kodları:

| Kod | Karar | Anlamı |
|---|---|---|
| `KANAL_LISTESI_CEKILEMEDI` | `hata` | Kanal listesi alınamadı; hiçbir şey yazılmadı. |
| `KULLANICI_LISTESI_CEKILEMEDI` | `hata` | Kullanıcı listesi alınamadı; hiçbir şey yazılmadı. |
| `VERITABANI_YAZILAMADI` | `hata` | Kullanıcı ve kanal listesi yazılamadı; hiçbir şey yazılmadı. |
| `BOT_KANALDA_DEGIL` | `hata` | Kanal izinli ama bot kanalda değil; o kanal için Slack'e istek yapılmadı. |
| `KANAL_CEKILEMEDI` | `hata` | Kanalın üyeleri ya da mesajları alınamadı (ör. Slack `not_in_channel`, çok fazla istek); kanalın eski satırlarına dokunulmadı. |
| `KANAL_YAZILAMADI` | `hata` | Kanalın verisi veritabanına yazılamadı; o kanalın işlemi geri alındı. |
| `BAZI_KANALLAR_CEKILEMEDI` | `tamam` | Özet satırı: en az bir kanal hata verdi. Hata yoksa `sebep_kodu` boştur. |

Slack'in kendi hata kodu (ör. `not_in_channel`) olay kaydına yazılmaz; yalnızca ekranda görünür.

## 8. `yapay_zeka_cagrilari`

Yapay zekâya yapılan her çağrının ölçüleri. İstem ve cevap metni tutulmaz.

| Alan | Açıklama |
|---|---|
| `id` | Çağrı satırının sayı kimliği. |
| `zaman` | Çağrının yapıldığı zaman. |
| `istek_id` | Çağrının ait olduğu istek (`olay_kayitlari.istek_id` ile aynı değer). |
| `model` | Kullanılan modelin adı (yalnızca harf, rakam, `.`, `_`, `-`; en fazla 100 karakter). |
| `sonuc` | `tamam`, `saglayici_hatasi` ya da `zaman_asimi`; sohbet anlaşmasındaki `SAGLAYICI_HATASI` ve `ZAMAN_ASIMI` hatalarıyla eşleşir. |
| `gonderilen_mesaj_sayisi` | Yapay zekâya gönderilen mesaj sayısı. |
| `sure_ms` | Çağrının süresi, milisaniye. |
| `girdi_token` | Gönderilen token sayısı; bilinmiyorsa (ör. hata durumunda) boş (NULL). |
| `cikti_token` | Gelen token sayısı; bilinmiyorsa (ör. hata durumunda) boş (NULL). |

## Slack çekme ve başlangıç verisi (S1-04)

Kod: `server/app/slack_baglayici/`. Komutlar `server/` içinde çalışır:

```powershell
.venv/Scripts/python -m app.slack_baglayici.cek [--gun 30] [--sifirdan]
.venv/Scripts/python -m app.slack_baglayici.seed disa-aktar [--dosya YOL] [--uzerine-yaz]
.venv/Scripts/python -m app.slack_baglayici.seed yukle [--dosya YOL]
```

Çekme kuralları:

- Token yalnızca `.env` içindeki `SLACK_BOT_TOKEN`'dan okunur; ekrana, olay kaydına, hata mesajına ve seed dosyasına yazılmaz.
- Kanalların durumu her çalıştırmada Slack'teki güncel ad ve `IZINLI_KANALLAR` ile yeniden hesaplanır. Bir kanal için üye ya da mesaj isteği yapılmadan hemen önce durum bir kez daha hesaplanır; `hariç` kanal için Slack'e hiç istek yapılmaz.
- Slack kanal listesinde artık görünmeyen kanal (arşivlendi, silindi, bot private kanaldan çıkarıldı) `hariç` olur.
- Durumu `hariç` olan her kanalın mesajları ve üyelikleri silinir; kanal satırı kalır (olay kaydı ona bağlı olabilir).
- Bot izinli bir kanalda değilse o kanal için istek yapılmaz, `BOT_KANALDA_DEGIL` kaydı yazılır.
- Her izinli kanalın üye listesi tek işlemde yenilenir: Slack'te artık olmayan üyelik satırı silinir, kalanların `guncelleme_zamani` yenilenir.
- Yalnızca kişilerin düz mesajları yazılır: alt türü (`subtype`) olan her mesaj (kanala katıldı, bot mesajı, kanal adı değişti, thread'den kanala gönderilen yanıt vb.), yazanı olmayan ya da metni boş olan mesaj atlanır. Ekranda kanal başına atlanan sayısı ve nedenlerin dağılımı görünür (ör. `3 atlandı: channel_join 3`); bu dağılım olay kaydına yazılmaz.
- Mesaj veritabanına yazılmadan hemen önce `temizlik.temizle()` çağrılır (şimdilik metni değiştirmez; Aşama 3'te filtre bağlanacak).
- Aynı mesaj (`kanal_id` + `ts`) ikinci kez yazılmaz; komutu tekrar çalıştırmak mesajları çoğaltmaz.
- Slack "çok fazla istek" (HTTP 429) derse `Retry-After` kadar beklenir (tek bekleme en fazla 120 saniye) ve en fazla 5 kez denenir.
- `--gun` varsayılanı 30 (en az 1, en fazla 365). Demo mesajları 22 Ekim 2026'da yazıldı; yaklaşık 21 Kasım'dan sonra gerçek çekmede gelmesi için `--gun` büyütülmeli ya da seed kullanılmalı.
- `--sifirdan`: çekmeden önce bütün `mesajlar` ve `kanal_uyelikleri` satırları silinir; olay kaydı ve diğer tablolar kalır. Veritabanı dosyası silinirse komut boş dosyada da çalışır.

Başlangıç verisi (seed), varsayılan dosya `demo-verisi/slack-baslangic-verisi.json`:

- JSON, UTF-8, LF. Alanlar: `bicim` (`agentstack-slack-seed`), `surum` (1), `kanallar` (`slack_id`, `ad`, `ozel_mi`), `slack_kullanicilari` (`slack_id`, `gorunen_ad`, `gercek_ad`, `bot_mu`), `kanal_uyelikleri` (`kanal_id`, `slack_kullanici_id`), `mesajlar` (`kanal_id`, `ts`, `yazan_id`, `zaman`, `temiz_metin`).
- Yalnızca izinli kanallar, onların üyelikleri ve mesajları, bu satırların andığı kullanıcılar girer. Olay kaydı, yapay zekâ çağrıları, kişiler, bağlı hesaplar, `durum`, `guncelleme_zamani` ve `supheli` girmez.
- Gizli bilgi kontrolü (yazarken ve okurken): çekmede kullanılan token dosyada geçemez; `xox?-`, `ghp_`, `AIza`, `AKIA` kalıplarına uyan her metin `EXAMPLE` içermelidir. Kontrolden geçmeyen dosya yazılmaz ya da yüklenmez; hata mesajında yalnızca kalıbın adı görünür.
- `yukle` yalnızca Slack tabloları boş bir veritabanına yükler. Kanal durumu yükleyenin `IZINLI_KANALLAR` listesiyle yeniden hesaplanır; `hariç` çıkan kanalın üyelik ve mesajları yüklenmez.

## Bilinen sınırlamalar

- Slack'te düzenlenen mesaj veritabanında güncellenmez; silinen mesaj veritabanında kalır (`--sifirdan` ile düzelir).
- Bir kanalın üye listesi çekilemezse o kanalın eski üyelikleri kalır; ne kadar eski oldukları `guncelleme_zamani`'ndan görülür.
- `temizle()` şimdilik metni değiştirmez: Aşama 3'e kadar `temiz_metin` aslında Slack'teki metindir.
- Yabancı anahtar kontrolü yalnızca `baglan()` ile açılan bağlantıda çalışır; veritabanını başka yoldan (`sqlite3.connect`) açan kod bu kontrolü kaybeder.
- `olay_kayitlari.adim` değer listesi `kapi.ADIMLAR` ile elle eşleşir; kapıya adım eklenirse şema da güncellenmelidir (bir test farkı yakalar).
- Thread yanıtları, ekler ve dosyalar kapsam dışıdır.
- Maskeli metnin yapay zekâya giden hali için ayrı tablo Aşama 3'te eklenecek.
