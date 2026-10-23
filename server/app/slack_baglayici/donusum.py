"""Slack verisini tablo satırlarına çeviren saf fonksiyonlar (S1-04): ağ, veritabanı ya da saat kullanmaz."""
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from ..veritabani.kurallar import kanal_durumu

# Slack mesaj kimliği: tam olarak "10 rakam . 6 rakam" (mesajlar tablosundaki CHECK ile aynı).
_TS_KALIBI = re.compile(r"[0-9]{10}\.[0-9]{6}")

# Slack hata kodları ve alt tür adları: küçük harf, rakam ve "_".
_KOD_KALIBI = re.compile(r"[a-z0-9_]{1,40}")


def ts_gecerli_mi(ts: object) -> bool:
    """ts metin mi ve tam "10 rakam . 6 rakam" biçiminde mi."""
    return isinstance(ts, str) and _TS_KALIBI.fullmatch(ts) is not None


def ts_zamani(ts: str) -> str:
    """ts'nin saniye kısmından ISO 8601 UTC zaman. ts ondalık sayıya çevrilmez."""
    saniye = int(ts.split(".", 1)[0])
    return datetime.fromtimestamp(saniye, tz=timezone.utc).isoformat()


def en_eski_ts(simdi: datetime, gun: int) -> str:
    """conversations.history "oldest" değeri: şimdiden gun gün önce, "1729500000.000000" biçiminde."""
    saniye = int((simdi - timedelta(days=gun)).timestamp())
    return f"{saniye}.000000"


def hata_kodunu_temizle(kod: object) -> str:
    """Kod yalnızca a-z, 0-9 ve "_" ise (en fazla 40 karakter) olduğu gibi, değilse "bilinmeyen_hata"."""
    if isinstance(kod, str) and _KOD_KALIBI.fullmatch(kod):
        return kod
    return "bilinmeyen_hata"


def _dolu_metin(deger: object) -> bool:
    return isinstance(deger, str) and len(deger.strip()) > 0


def atlama_nedeni(mesaj: object) -> str | None:
    """Mesaj yazılacaksa None; atlanacaksa nedeni (alt tür adı ya da sabit kod). Mesaj metni asla dönmez.

    Yalnızca kişilerin düz mesajları alınır: alt türü (subtype) olan her mesaj atlanır.
    """
    if not isinstance(mesaj, dict) or mesaj.get("type") != "message":
        return "mesaj_degil"
    if "subtype" in mesaj:
        alt_tur = mesaj["subtype"]
        if isinstance(alt_tur, str) and _KOD_KALIBI.fullmatch(alt_tur):
            return alt_tur
        return "bilinmeyen_alt_tur"
    if not ts_gecerli_mi(mesaj.get("ts")):
        return "gecersiz_ts"
    if not _dolu_metin(mesaj.get("user")):
        return "yazan_yok"
    if not _dolu_metin(mesaj.get("text")):
        return "bos_metin"
    return None


def mesaj_alinsin_mi(mesaj: object) -> bool:
    """Mesaj veritabanına yazılacak mı (atlama nedeni yoksa evet)."""
    return atlama_nedeni(mesaj) is None


def kanal_satiri(kanal: object, izinli_kanallar: Iterable[str]) -> dict:
    """conversations.list kaydını kanallar satırına çevirir; durum her seferinde izin listesinden hesaplanır."""
    if not isinstance(kanal, dict):
        raise ValueError("Kanal kaydı geçersiz.")
    slack_id, ad = kanal.get("id"), kanal.get("name")
    if not _dolu_metin(slack_id) or not _dolu_metin(ad):
        raise ValueError("Kanal kaydında kimlik ya da ad yok.")
    return {
        "slack_id": slack_id,
        "ad": ad,
        "ozel_mi": 1 if kanal.get("is_private") is True else 0,
        "durum": kanal_durumu(ad, izinli_kanallar),
    }


def kullanici_satiri(kullanici: object) -> dict:
    """users.list kaydını slack_kullanicilari satırına çevirir; boş ad None olur."""
    if not isinstance(kullanici, dict) or not _dolu_metin(kullanici.get("id")):
        raise ValueError("Kullanıcı kaydında kimlik yok.")
    slack_id = kullanici["id"]
    profil = kullanici.get("profile")
    if not isinstance(profil, dict):
        profil = {}
    gorunen = profil.get("display_name")
    gercek = profil.get("real_name") or kullanici.get("real_name")
    return {
        "slack_id": slack_id,
        "gorunen_ad": gorunen if _dolu_metin(gorunen) else None,
        "gercek_ad": gercek if _dolu_metin(gercek) else None,
        # Slackbot'un is_bot alanı false gelir; yine de bottur.
        "bot_mu": 1 if kullanici.get("is_bot") is True or slack_id == "USLACKBOT" else 0,
    }
