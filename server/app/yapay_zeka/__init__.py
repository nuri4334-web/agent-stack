"""Yapay zekâ ortak arayüzü ve sahte sağlayıcı (S1-08).

Kapının bildiği tek şey buradaki `sor(talimat, veri)` fonksiyonudur.
Mimarideki 'kapı sabit, beyin değişir' ilkesi burada uygulanır.
"""
import time
from dataclasses import dataclass

from .. import ayarlar


@dataclass
class YapayZekaCevabi:
    """Ortak arayüz çıktısı: cevap, kullanılan model adı, süre, token sayıları."""

    cevap: str
    model: str
    sure_ms: float
    girdi_token: int = 0
    cikti_token: int = 0


class YapayZekaHatasi(Exception):
    """Sağlayıcı hata verdiğinde veya zaman aşımında fırlatılan güvenli hata.

    İçinde asla API anahtarı veya gizli URL bulunmaz.
    """

    def __init__(self, kod: str, mesaj: str):
        super().__init__(mesaj)
        self.kod = kod
        self.mesaj = mesaj


# --- İkinci sağlayıcı: sahte (Adım 3) ---
SAHTE_SABIT_CEVAP = "Bu sahte sağlayıcıdan dönen sabit test cevabıdır."
_sahte_cagri_sayaci: int = 0


def sahte_sayaci_sifirla() -> None:
    """Testlerde çağrı sayacını sıfırlamak için yardımcı fonksiyon."""
    global _sahte_cagri_sayaci
    _sahte_cagri_sayaci = 0


def sahte_cagri_sayisi() -> int:
    """Sahte sağlayıcının kaç kez çağrıldığını döner."""
    return _sahte_cagri_sayaci


def _sahte_sor(talimat: str, veri: str) -> YapayZekaCevabi:
    global _sahte_cagri_sayaci
    bas = time.perf_counter()
    _sahte_cagri_sayaci += 1
    sure_ms = round((time.perf_counter() - bas) * 1000, 2)
    return YapayZekaCevabi(
        cevap=SAHTE_SABIT_CEVAP,
        model="sahte-v1",
        sure_ms=sure_ms,
        girdi_token=len((talimat + " " + veri).split()),
        cikti_token=len(SAHTE_SABIT_CEVAP.split()),
    )


# --- Ortak Arayüz (Adım 1) ---
def sor(talimat: str, veri: str) -> YapayZekaCevabi:
    """Kapının çağırdığı tek ortak fonksiyon.

    Girdi: talimat metni ve veri metni, ayrı ayrı.
    Çıktı: YapayZekaCevabi (cevap, model, sure_ms, girdi_token, cikti_token).
    """
    saglayici = ayarlar.AI_SAGLAYICI

    if saglayici == "sahte":
        return _sahte_sor(talimat=talimat, veri=veri)

    if saglayici == "gemini":
        from . import gemini

        return gemini.sor(talimat=talimat, veri=veri)

    raise YapayZekaHatasi(
        kod="GECERSIZ_SAGLAYICI",
        mesaj=f"Bilinmeyen yapay zekâ sağlayıcısı: '{saglayici}'. ('sahte' veya 'gemini' olmalı)",
    )