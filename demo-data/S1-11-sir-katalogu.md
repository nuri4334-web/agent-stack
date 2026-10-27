# S1-11 · Sır ve kişisel veri biçimleri kataloğu

Hazırlayan: Musa · Onay: Nuri · Durum: taslak · 24 Ekim 2026

Aşama 3'teki giriş filtresinin (K4) temeli. Katalogda **15 sır türü ve 5 kişisel veri türü**, ayrıca **12 masum benzer** var. Bütün sahte örnekler [`S1-11-sahte-ornekler.json`](S1-11-sahte-ornekler.json) dosyasında. Bu dosyadaki her örneğin "beklenen" sonucu (maskele, maskele + alarm, dokunma) yazılı; detect-secrets ile tarandı.

> Bu dosyadaki her şey **sahtedir**. Anahtarlar `EXAMPLE` içerir ya da sıfırlarla doldurulmuştur; kişisel veriler uydurmadır.

## Özet: ne bulduk?

1. **detect-secrets sırların çoğunu tanıyor, kişisel verilerin hiçbirini tanımıyor.** 17 sır örneğinin 13'ünü yakaladı, 7 kişisel veri örneğinin hiçbirini yakalamadı.
2. **Bizim eklememiz gereken sır kuralları:**
   - Slack uygulama token'ı (`xapp-`)
   - GitHub ince ayarlı token'ı (`github_pat_`)
   - Google API anahtarı (`AIza`)
   - Anthropic anahtarı (`sk-ant-`)

   Google ve Anthropic anahtarları ancak satırda `..._API_KEY=` gibi bir ad varsa yakalandı; mesaja çıplak yapıştırılınca kaçtı.
3. **Bütün kişisel veri kuralları bizden:** e-posta, telefon, TC kimlik, IBAN ve kredi kartı.
4. **Yanlış alarmlar:** SHA-256 ve MD5 dosya özetleri ile etiketsiz rastgele diziler "yüksek entropi" diye işaretlendi. Commit kimliği, UUID, Slack kimlikleri ve linkler doğru şekilde bırakıldı.
5. **⚠️ Önemli:** detect-secrets varsayılan ayarla, yakaladığı Slack token'ını doğrulamak için **Slack'in sunucusuna gönderiyor**. Token geçersizse sonuçtan siliyor. Bu bizim "sır dışarı gitmez" kuralımızı (K7) çiğner ve sahte demo token'larının hiç yakalanmamasına yol açar. Filtre mutlaka **doğrulama kapalı** (`--no-verify`) çalışmalı.

## 1. Sır türleri

**Güven seviyeleri:**
- **Kesin:** bilinen önek ya da yapı. Karar: maskele ve alarm ver.
- **Şüpheli:** anahtar kelime ile rastgele dizinin birlikte görülmesi. Karar: maskele.
- **Zayıf:** yalnızca rastgele dizi. Karar: dokunma.

| # | Tür | Nasıl tanınır | Sahte örnek | Güven | Neyle karışabilir |
| --- | --- | --- | --- | --- | --- |
| S1 | Slack bot token'ı | `xoxb-` ile başlar. Ardından tirelerle ayrılmış iki sayı grubu (10–13 hane) ve harf-rakam karışık bir son parça gelir. | `xoxb-0000000000-0000000000000-EXAMPLEexampleEXAMPLEexa` | Kesin | Pek bir şeyle karışmaz; önek çok özgün. |
| S2 | Slack kullanıcı token'ı | `xoxp-` ile başlar; üç sayı grubu ve 28–34 karakterlik bir son parça. Kullanıcı adına iş yapar, bot token'ından daha tehlikelidir. | `xoxp-0000000000-0000000000-0000000000000-EXAMPLE0000…` | Kesin | — |
| S3 | Slack uygulama token'ı | `xapp-` (dönen sürümü `xoxe.xapp-`) ile başlar; `xapp-1-A…-sayı-uzun küçük harf/rakam`. | `xapp-1-A0000000000-0000000000000-0000…example` | Kesin | — |
| S4 | GitHub token'ı | `ghp_` (kişisel), `gho_` (OAuth), `ghu_`, `ghs_`, `ghr_` önekinden sonra 36 harf-rakam; toplam 40 karakter. Son 6 karakter CRC32 sağlamasıdır. | `ghp_EXAMPLE00000000000000000000000000000` | Kesin | — |
| S5 | GitHub ince ayarlı token'ı | `github_pat_` ile başlar, ardından 82 harf, rakam ya da alt çizgi. | `github_pat_EXAMPLE0000…` (93 karakter) | Kesin | — |
| S6 | AWS erişim anahtarı kimliği | `AKIA` (kalıcı) ya da `ASIA` (geçici) ile başlar; büyük harf ve rakamdan oluşan toplam 20 karakter. | `AKIAIOSFODNN7EXAMPLE` (AWS dokümanındaki örnek) | Kesin | Başka AWS kimlikleri: `AIDA` (kullanıcı), `AROA` (rol). Bunlar sır değildir. |
| S7 | AWS gizli erişim anahtarı | Öneki yok; 40 karakter, büyük ve küçük harf, rakam, `/` ve `+`. Yalnızca yanında `aws_secret_access_key` gibi bir ad varsa tanınır. | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` (AWS dokümanındaki örnek) | Şüpheli | Base64 metin parçaları. |
| S8 | Google API anahtarı (Gemini dahil) | `AIza` ile başlar, ardından 35 karakter (harf, rakam, `-`, `_`); toplam 39. | `AIzaSyEXAMPLE00000000000000000000000000` | Kesin | — |
| S9 | OpenAI API anahtarı | `sk-proj-`, `sk-svcacct-` ya da `sk-admin-` ile başlar; ortasında sabit `T3BlbkFJ` dizisi var. | `sk-proj-EXAMPLE0000…T3BlbkFJ0000…EXAMPLE` | Kesin | Başka `sk-` önekli anahtarlar, ör. Stripe `sk_live_` (alt çizgiyle). |
| S10 | Anthropic API anahtarı | `sk-ant-api03-` (yönetici için `sk-ant-admin01-`) ile başlar, 93 karakter sonra `AA` ile biter. | `sk-ant-api03-EXAMPLE0000…AA` | Kesin | — |
| S11 | Özel anahtar bloğu | `-----BEGIN … PRIVATE KEY-----` satırıyla başlayıp `-----END … PRIVATE KEY-----` ile biten çok satırlı blok (RSA, EC, OPENSSH). | `-----BEGIN OPENSSH PRIVATE KEY-----` / sahte gövde / `-----END …` | Kesin | `-----BEGIN PUBLIC KEY-----` ve `CERTIFICATE`. Bunlar sır değildir. |
| S12 | `.env` satırı | `AD=değer` biçimi; adda `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASS` ya da `PWD` geçer ve değer boş değildir. | `JWT_SECRET=ornek-jwt-gizli-anahtar-degistir`, `DB_PASSWORD=Ornek-Sifre-2026` | Şüpheli | `PASSWORD_MIN_LENGTH=8` gibi ayarlar ve `TOKEN_URL=https://…` gibi adresler. Değerin kendisine de bakılmalı. |
| S13 | Veritabanı adresindeki şifre | `şema://kullanıcı:şifre@sunucu` biçimi (postgres, mysql, mongodb, redis…). Yalnızca `:` ile `@` arasındaki şifre maskelenir. | `postgres://app_user:Ornek-Sifre-2026@db.staging.example:5432/shop` | Kesin | Şifresiz adresler, ör. `postgres://db:5432/app`. |
| S14 | Giriş token'ı (JWT / Bearer) | Noktayla ayrılmış üç parça; ilk iki parça `eyJ` ile başlar (base64 JSON). Ya da `Authorization: Bearer …` başlığı. | `Authorization: Bearer eyJhbGciOiJIUzI1NiIs…` | Kesin | — |
| S15 | Etiketsiz rastgele dizi | Uzun, harf ve rakam karışık, yanında anahtar kelime yok. | `Xy9Zk2Lm8Np4Qr7SaB3cD5eF6gH` | Zayıf | Masum benzerlerin hepsi (bölüm 3). **Dokunulmaz.** |

## 2. Kişisel veri türleri

| # | Tür | Nasıl tanınır | Sahte örnek | Güven | Neyle karışabilir |
| --- | --- | --- | --- | --- | --- |
| K1 | E-posta | `ad@alan.uzantı` biçimi. | `ornek.kisi@example.com` | Kesin | `@Ali` gibi Slack etiketleri (alan adı yok). `git@github.com:…` gibi adresler. |
| K2 | Telefon | `+90` ile başlayıp 5 ile devam eden 10 hane; boşluklu ya da boşluksuz. `0` ile başlayan 11 haneli `05xx` biçimi de olabilir. | `+90 500 000 00 00`, `0500 000 00 00` | `+90`: kesin, `05xx`: şüpheli | Sipariş ve fatura numaraları, tarihler. **`0` ile başlayan 11 hane TC olamaz.** |
| K3 | TC kimlik numarası | 11 hane, ilk hane 0 değil. 10. hane = ((1., 3., 5., 7., 9. hanelerin toplamı × 7) − (2., 4., 6., 8. hanelerin toplamı)) mod 10. 11. hane = ilk 10 hanenin toplamı mod 10. | `10000000146` (kuralı sağlıyor) | Yanında "TC" ya da "kimlik" geçiyorsa kesin; etiketsizse şüpheli | 11 haneli sipariş numaraları. Rastgele 11 haneli sayıların yaklaşık %1'i kuralı tesadüfen sağlar; bu yüzden etiketsiz eşleşme şüpheli sayılır. |
| K4 | TR IBAN | `TR` + 2 kontrol hanesi + 22 hane (5 banka kodu, 1 sıfır, 16 hesap numarası); toplam 26 karakter. Genelde 4'erli boşlukla yazılır. Mod-97 kontrolü geçmelidir. | `TR20 0000 0000 0000 0000 0000 01` | Kesin | Başka ülkelerin IBAN'ları (aynı kuralla yakalanabilir). |
| K5 | Kredi kartı numarası | 13–19 hane, genelde 4'erli gruplar. Luhn kontrolünü geçer. Visa 4, Mastercard 51–55 ya da 2221–2720, Amex 34/37 ile başlar. | `4111 1111 1111 1111` | Kesin | Uzun sipariş ve takip numaraları; Luhn kontrolü bunların çoğunu eler. |

**İsimler:** Bu katalogda değil. Presidio'nun hazır isim tanıyıcısı Türkçe isimlerde zayıf; Aşama 3'te isimler Slack kullanıcı listesinden sözlükle bulunup `KİŞİ_1` yapılacak (mimari özeti). Bu notu test etmedik, mimari özetinden aldık.

### Sahte kişisel verilerin neden güvenli olduğu

| Örnek | Neden gerçek birine ait değil |
| --- | --- |
| `ornek.kisi@example.com` | `example.com` alan adı örnekler için ayrılmış (RFC 2606); kimsenin e-postası olamaz. |
| `+90 500 000 00 00` | Uydurma. Gerçek birine ait olmadığını Nuri teyit etsin. |
| `10000000146` | Yazılım testlerinde sık kullanılan, kuralı sağlayan örnek numara. Gerçek birine ait olmadığını Nuri teyit etsin. |
| `TR20 0000 0000 0000 0000 0000 01` | Banka kodu `00000` hiçbir bankaya ait değil; yalnızca mod-97 kontrolünü geçiyor. |
| `4111 1111 1111 1111` | Ödeme sağlayıcılarının yayınladığı Visa test kartı; gerçek bir karta bağlı değil. |

## 3. Masum benzerler (yanlış alarmın ana kaynağı)

Bunların hepsi **dokunulmadan** bırakılmalı.

| # | Tür | Örnek | Nasıl ayırt edilir | detect-secrets |
| --- | --- | --- | --- | --- |
| M1 | Git commit kimliği | `a663950014a53b5bd5db54211e2fbc919bf98ff3` | 40 karakter, yalnızca 0–9 ve a–f; yakınında "commit" geçer. | ✅ dokunmadı |
| M2 | Kısa commit kimliği | `a663950` | 7–12 hex karakter. | ✅ dokunmadı |
| M3 | UUID | `3f2b8c1e-7a4d-4e9b-b1c2-9d8e7f6a5b4c` | 8-4-4-4-12 hex grupları. | ✅ dokunmadı |
| M4 | SHA-256 dosya özeti | `e3b0c442…7852b855` (64 hex) | 64 hex karakter; yakınında "sha256", "checksum", dosya adı geçer. | ❌ **yanlış alarm** |
| M5 | MD5 dosya özeti | `d41d8cd98f00b204e9800998ecf8427e` | 32 hex karakter; yakınında "md5" geçer. | ❌ **yanlış alarm** |
| M6 | Rastgele parametreli link | `https://tasarim.example/file/AbCd…?node-id=12-345&t=Xy9Z…` | Linkin içindeki parametre; sır önekiyle başlamıyor. | ✅ dokunmadı |
| M7 | Slack kişi ve kanal kimliği | `U0CA5HH3M1V`, `C07DEV1234` | `U`, `C` ya da `T` ile başlayan 9–11 karakterlik büyük harf ve rakam. | ✅ dokunmadı |
| M8 | Slack mesaj zaman damgası | `1792059120.000100` | 10 hane, nokta, 6 hane. | ✅ dokunmadı |
| M9 | 11 haneli sipariş numarası | `20261020001` | TC kuralını sağlamıyor. | ✅ dokunmadı |
| M10 | AWS hesap numarası ve ARN | `arn:aws:iam::123456789012:role/S3Access` | `arn:aws:` ile başlar; hesap numarası sır değildir. | ✅ dokunmadı |
| M11 | Sürüm numarası ve tarih | `v1.4.2`, `2026-10-20` | — | ✅ dokunmadı |
| M12 | Base64 resim parçası | `data:image/png;base64,iVBORw0KGgo…` | `data:` ile başlar. | ✅ dokunmadı |

## 4. detect-secrets karşılaştırması

detect-secrets 1.5.0, varsayılan eklentilerle, `scan --no-verify` ile tarandı; her örnek ayrı bir dosyadaydı. Örnek bazında sonuçlar JSON dosyasındaki `detect_secrets_sonuc` alanında.

| Durum | Türler |
| --- | --- |
| ✅ **Zaten tanıyor** | Slack bot ve kullanıcı token'ı (S1, S2), GitHub klasik token (S4), AWS erişim anahtarı kimliği (S6), OpenAI (S9), özel anahtar bloğu (S11), JWT (S14), veritabanı adresindeki şifre (S13, "Basic Auth" olarak) |
| 🟡 **Yalnızca adı varsa tanıyor** | AWS gizli anahtar (S7), Google (S8) ve Anthropic (S10) anahtarları, `.env` satırları (S12). Bunlar adlarındaki `KEY`, `SECRET` ve `PASSWORD` sayesinde "Secret Keyword" olarak yakalandı. Google ve Anthropic anahtarı mesaja çıplak yapıştırılınca **kaçtı**. |
| ❌ **Tanımıyor, bizim eklememiz gerek** | Slack uygulama token'ı `xapp-` (S3), GitHub ince ayarlı token'ı `github_pat_` (S5), Google `AIza` (S8, çıplak), Anthropic `sk-ant-` (S10, çıplak), **bütün kişisel veriler** (K1–K5) |
| ⚠️ **Yanlış alarm veriyor** | SHA-256 ve MD5 özetleri (M4, M5), etiketsiz rastgele dizi (S15). Hepsi "High Entropy String" eklentilerinden. |

### Aşama 3 için öneriler

1. **Doğrulamayı kapat.** detect-secrets kullanılırsa her zaman doğrulama kapalı çalışmalı: komut satırında `--no-verify`, kodda doğrulamayı kapatan ayar. Aksi halde bulunan token Slack'e gönderilir (K7 ihlali) ve geçersiz çıkınca sonuçtan silinir.
2. **Entropi tek başına "zayıf" sayılmalı.** Kademeli karara göre zayıf bulguya dokunulmaz. Böylece SHA-256 ve MD5 yanlış alarmları kendiliğinden düşer.
3. **Sağlama kontrolleri güveni artırsın ama şart olmasın.**
   - TC kuralı, IBAN mod-97 ve Luhn kontrolü yanlış alarmı çok azaltır.
   - GitHub token'ının CRC32 sağlaması gerçek token'ı kesinleştirir. Ama sahte demo token'ları bu sağlamadan geçmez; sağlama şart koşulursa Demo 2'deki `.env` mesajı yakalanmaz.
4. **Eksik kurallar:** `xapp-`, `github_pat_`, `AIza`, `sk-ant-` ve beş kişisel veri türü için kendi kurallarımız yazılmalı. Sahte örnekler JSON dosyasında hazır; her kural için kırmızı test bunlarla yazılabilir.

## Kaynaklar

- Slack token türleri ve önekleri: [docs.slack.dev/authentication/tokens](https://docs.slack.dev/authentication/tokens)
- GitHub token önekleri ve CRC32 sağlaması: [github.blog: Behind GitHub's new authentication token formats](https://github.blog/engineering/platform-security/behind-githubs-new-authentication-token-formats/)
- AWS kimlik önekleri (`AKIA`, `ASIA`…) ve örnek anahtarlar: [AWS IAM identifiers](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html)
- Google, OpenAI, Anthropic, JWT ve özel anahtar biçimleri: [gitleaks varsayılan kural dosyası](https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml)
- detect-secrets: [github.com/Yelp/detect-secrets](https://github.com/Yelp/detect-secrets) (1.5.0 ile test edildi)
