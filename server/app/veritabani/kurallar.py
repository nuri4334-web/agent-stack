"""Kanal kuralı (S1-03): saf fonksiyon; veritabanı, ağ ya da saat kullanmaz."""
from collections.abc import Iterable
from typing import Literal

# Tablodaki durum değerleriyle birebir aynı.
IZINLI = "izinli"
HARIC = "hariç"

# İzin listesine yanlışlıkla yazılsa bile asla okunmayan kanallar.
YASAKLI_KANALLAR = frozenset({"ik"})


def kanal_adini_duzelt(ad: str) -> str:
    """Boşlukları ve baştaki '#' işaretini atar, küçük harfe çevirir (" #Dev " -> "dev")."""
    return ad.strip().lstrip("#").strip().lower()


def kanal_durumu(kanal_adi: str, izinli_kanallar: Iterable[str]) -> Literal["izinli", "hariç"]:
    """Kanal izin listesindeyse "izinli", değilse "hariç". Yasaklı ya da boş ad her zaman "hariç"."""
    ad = kanal_adini_duzelt(kanal_adi)
    if not ad or ad in YASAKLI_KANALLAR:
        return HARIC
    izinliler = {kanal_adini_duzelt(k) for k in izinli_kanallar}
    return IZINLI if ad in izinliler else HARIC
