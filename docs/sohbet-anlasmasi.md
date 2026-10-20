# Sohbet anlaşması (API contract) — v1

Ekranın (web) sunucuya ne gönderdiği ve ne aldığı. Sprint 1 · S1-02.
Değişiklik gerekirse önce bu dokümanı güncelleyen bir PR açılır; ekran ve sunucu ona uyar.

Sunucu adresi (geliştirme): `http://localhost:8000`. Arayüz bu adresi bir ayardan okur.

## 1. Sağlık kontrolü

`GET /saglik` → `200`
```json
{ "durum": "ayakta" }
```

## 2. Soru gönder

`POST /api/soru` · `Content-Type: application/json`

### İstek
```json
{
  "soru": "#dev'i özetle",
  "kullanici": "ali"
}
```

| Alan | Tür | Açıklama |
|---|---|---|
| `soru` | metin, 1–2000 karakter | Kullanıcının sorusu. |
| `kullanici` | metin | **GEÇİCİ.** Aşama 2'de kaldırılacak; kimlik sunucunun verdiği oturumdan okunacak. Bu alan kalırsa projenin en büyük yetki açığı olur: Ali bu alanı değiştirip Nuri olabilir. |

### Başarılı cevap — `200`
```json
{
  "istek_id": "3f9c2a1b7d4e",
  "durum": "tamam",
  "cevap": "#dev kanalında bu hafta login sayfası ve ...",
  "kaynaklar": [
    {
      "kanal": "dev",
      "yazan": "Deniz",
      "zaman": "2026-10-22T14:05:00+03:00",
      "metin": "@Ali login sayfasını sen al"
    }
  ],
  "guvenlik": { "engellenen": 0, "maskelenen": 0, "supheli": 0 }
}
```

| Alan | Açıklama |
|---|---|
| `istek_id` | İsteğin kimliği. Panelde olay kaydıyla eşleştirmek için. |
| `durum` | `"tamam"` ya da `"erisim_yok"`. `erisim_yok` olduğunda yapay zekâ hiç çağrılmamıştır; `cevap` "Bu bilgiye erişimin yok." olur, `kaynaklar` boştur. (Aşama 2'de devreye girer.) |
| `cevap` | Düz metin. **Ekran bunu düz metin olarak gösterir**; içindeki link ve resimler çalışır hale getirilmez (EchoLeak tipi sızıntıya karşı). |
| `kaynaklar` | Cevabın dayandığı mesajlar. Boş olabilir. Sprint 1'de boş. |
| `guvenlik` | Bu istekte kaç şey engellendi, maskelendi, şüpheli bulundu. Sprint 1'de hep sıfır. |

Cevap kelime kelime akıtılmaz (streaming yok): çıkış kontrolü cevabın tamamını görmelidir. Ekran beklerken "Yazıyor…" gösterir.

### Hata cevabı — her hata aynı biçimde
```json
{
  "hata": { "kod": "GECERSIZ_ISTEK", "mesaj": "İstek biçimi hatalı. Sohbet anlaşmasına bakın." }
}
```

| HTTP | `kod` | Ne zaman |
|---|---|---|
| 422 | `GECERSIZ_ISTEK` | Alan eksik, boş ya da çok uzun. |
| 502 | `SAGLAYICI_HATASI` | Yapay zekâ sağlayıcısı hata verdi ya da istek sınırı doldu (S1-08). |
| 504 | `ZAMAN_ASIMI` | Yapay zekâ zamanında cevap vermedi (S1-08). |
| 500 | `SUNUCU_HATASI` | Beklenmeyen hata. |

Ekran `hata.mesaj` metnini kullanıcıya gösterebilir; mesajlar hiçbir zaman anahtar, istek içeriği ya da teknik ayrıntı içermez.

## Sürüm notları
- **v1 (S1-02):** İlk sürüm.
- **Planlanan (Aşama 2):** `kullanici` alanı kalkar; giriş ve oturum eklenir. `durum: "erisim_yok"` devreye girer.
