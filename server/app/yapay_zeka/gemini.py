"""İlk sağlayıcı: Gemini (S1-08 Adım 2, 4, 5, 6).

Gemini'ye özgü tüm detaylar yalnızca bu dosyada bulunur.
- Talimat -> system_instruction alanına
- Veri -> contents alanına
- Kafes: Araç (tools) yok, geçmiş yok, yalnızca düz metin döner.
- Güvenlik: Anahtar loglara veya hata mesajlarına asla yazılmaz.
"""
import time
import httpx

from .. import ayarlar
from . import YapayZekaCevabi, YapayZekaHatasi

GEMINI_API_TABAN = "https://generativelanguage.googleapis.com/v1beta/models"


def sor(talimat: str, veri: str) -> YapayZekaCevabi:
    """Gemini REST API'sine tek seferlik (kafesli) istek gönderir."""
    api_key = ayarlar.GEMINI_API_KEY
    if not api_key:
        raise YapayZekaHatasi(
            kod="ANAHTAR_EKSIK",
            mesaj="Gemini API anahtarı tanımlı değil. Sunucu ayarlarını kontrol edin.",
        )

    model_adi = ayarlar.GEMINI_MODEL.strip().removeprefix("models/")
    url = f"{GEMINI_API_TABAN}/{model_adi}:generateContent"

    # Adım 2 & 5: Sistem talimatı ve veri ayrı alanlarda; hiçbir araç (tools) verilmez
    govde = {
        "system_instruction": {
            "parts": [{"text": talimat}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": veri}],
            }
        ],
    }

    basliklar = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    bas = time.perf_counter()
    try:
        with httpx.Client(timeout=ayarlar.AI_ZAMAN_ASIMI_SN) as istemci:
            yanit = istemci.post(url, json=govde, headers=basliklar)
    except httpx.TimeoutException:
        raise YapayZekaHatasi(
            kod="ZAMAN_ASIMI",
            mesaj="Yapay zekâ servisi zamanında yanıt vermedi (zaman aşımı).",
        ) from None
    except httpx.RequestError:
        # Anahtar veya iç ağ bilgisi sızmaması için orijinal exception metni yazdırılmaz
        raise YapayZekaHatasi(
            kod="BAGLANTI_HATASI",
            mesaj="Yapay zekâ servisine şu anda ulaşılamıyor.",
        ) from None

    sure_ms = round((time.perf_counter() - bas) * 1000, 2)

    if yanit.status_code == 429:
        raise YapayZekaHatasi(
            kod="KOTA_ASILDI",
            mesaj="Yapay zekâ istek sınırı (kota) aşıldı. Lütfen biraz bekleyip tekrar deneyin.",
        )

    if yanit.status_code in (400, 401, 403):
        raise YapayZekaHatasi(
            kod="YETKI_VEYA_ISTEK_HATASI",
            mesaj="Yapay zekâ servisi isteği reddetti (yapılandırma veya yetki hatası).",
        )

    if yanit.status_code >= 500:
        raise YapayZekaHatasi(
            kod="SAGLAYICI_HATASI",
            mesaj="Yapay zekâ servisinde geçici bir sunucu hatası oluştu.",
        )

    if yanit.status_code != 200:
        raise YapayZekaHatasi(
            kod="BILINMEYEN_HATA",
            mesaj=f"Yapay zekâ servisi beklenmeyen bir durum döndürdü (HTTP {yanit.status_code}).",
        )

    try:
        veri_json = yanit.json()
        adaylar = veri_json.get("candidates") or []
        parcalar = adaylar[0]["content"]["parts"]
        cevap_metni = "".join(p.get("text", "") for p in parcalar).strip()
    except (KeyError, IndexError, TypeError, ValueError):
        raise YapayZekaHatasi(
            kod="CEVAP_COZULEMEDI",
            mesaj="Yapay zekâ servisinden geçerli bir metin yanıtı alınamadı.",
        ) from None

    kullanim = veri_json.get("usageMetadata") or {}
    girdi_token = int(kullanim.get("promptTokenCount", 0))
    cikti_token = int(kullanim.get("candidatesTokenCount", 0))

    return YapayZekaCevabi(
        cevap=cevap_metni,
        model=model_adi,
        sure_ms=sure_ms,
        girdi_token=girdi_token,
        cikti_token=cikti_token,
    )