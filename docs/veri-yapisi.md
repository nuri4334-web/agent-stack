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

## Bilinen sınırlamalar

- Yabancı anahtar kontrolü yalnızca `baglan()` ile açılan bağlantıda çalışır; veritabanını başka yoldan (`sqlite3.connect`) açan kod bu kontrolü kaybeder.
- `olay_kayitlari.adim` değer listesi `kapi.ADIMLAR` ile elle eşleşir; kapıya adım eklenirse şema da güncellenmelidir (bir test farkı yakalar).
- Thread yanıtları, ekler ve dosyalar kapsam dışıdır.
- Maskeli metnin yapay zekâya giden hali için ayrı tablo Aşama 3'te eklenecek.
