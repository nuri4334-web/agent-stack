"""Olay kaydı yazma (S1-04): olay_kayitlari tablosuna tek satır. Yalnızca kod, sayı ve süre alır."""
import sqlite3

# olay_kayitlari tablosundaki sayı sütunları.
SAYI_SUTUNLARI = frozenset({
    "mesaj_sayisi", "kanal_sayisi", "kullanici_sayisi", "uyelik_sayisi",
    "engellenen_sayisi", "maskelenen_sayisi", "supheli_sayisi",
})


def olay_yaz(
    baglanti: sqlite3.Connection,
    *,
    zaman: str,
    istek_id: str,
    adim: str,
    karar: str,
    sure_ms: float,
    sebep_kodu: str | None = None,
    kanal_id: str | None = None,
    kisi_id: int | None = None,
    **sayilar: int,
) -> None:
    """Tek bir olay satırı ekler. Commit etmez: çağıranın işlemi içinde kullanılır."""
    bilinmeyen = set(sayilar) - SAYI_SUTUNLARI
    if bilinmeyen:
        raise ValueError(f"Bilinmeyen sayı alanı: {', '.join(sorted(bilinmeyen))}")
    satir = {
        "zaman": zaman, "istek_id": istek_id, "kisi_id": kisi_id, "adim": adim,
        "karar": karar, "sebep_kodu": sebep_kodu, "kanal_id": kanal_id, "sure_ms": sure_ms,
    } | sayilar
    sutunlar = ", ".join(satir)
    yerler = ", ".join("?" * len(satir))
    baglanti.execute(f"INSERT INTO olay_kayitlari ({sutunlar}) VALUES ({yerler})", tuple(satir.values()))
