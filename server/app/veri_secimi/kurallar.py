"""Veri seçimi kuralları (S1-05): saf fonksiyonlar; veritabanı, ağ ya da saat kullanmaz."""
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from ..veritabani.kurallar import IZINLI, kanal_adini_duzelt

# Yapay zekâya bir istekte gidebilecek en fazla mesaj sayısı (toplamda, kanal başına değil).
MESAJ_SINIRI = 50

# "#ad": ad harf, rakam, "_" ya da "-" ile sürer; kesme işaretinde durur ("#dev'i" -> "dev").
_KANAL_KALIBI = re.compile(r"#([\w-]+)")
_KULLANICI_ETIKETI = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
_KANAL_ETIKETI = re.compile(r"<#(C[A-Z0-9]+)(?:\|[^>]*)?>")

HedefSonucu = Literal["tamam", "slack_verisi_yok", "kanal_izinli_degil"]


def soruda_gecen_kanallar(soru: str) -> list[str]:
    """Soruda "#ad" biçiminde geçen kanal adları (küçük harf, "#"siz, ilk geçiş sırasıyla, tekrarsız).

    "#" olmadan geçen adlar tanınmaz. Yalnızca rakamlardan oluşan ifadeler ("PR #17", "#1") kanal adı sayılmaz.
    """
    adlar: list[str] = []
    for eslesme in _KANAL_KALIBI.finditer(soru):
        ad = kanal_adini_duzelt(eslesme.group(1))
        if ad.isdigit() or ad in adlar:
            continue
        adlar.append(ad)
    return adlar


def hedef_kanallari_bul(
    soru: str, kanallar: Sequence[tuple[str, str, str]]
) -> tuple[HedefSonucu, list[str]]:
    """Okunacak kanal kimlikleri. `kanallar`: (slack_id, ad, durum) satırları.

    Kanal tablosu boşsa "slack_verisi_yok". Soruda kanal adı geçiyorsa her biri var ve "izinli" olmalı;
    biri bile değilse "kanal_izinli_degil" ve boş liste. Ad geçmiyorsa bütün izinli kanallar.
    """
    if not kanallar:
        return "slack_verisi_yok", []
    adlar = soruda_gecen_kanallar(soru)
    if not adlar:
        return "tamam", [slack_id for slack_id, _, durum in kanallar if durum == IZINLI]
    ada_gore = {kanal_adini_duzelt(ad): (slack_id, durum) for slack_id, ad, durum in kanallar}
    hedefler = []
    for ad in adlar:
        kanal = ada_gore.get(ad)
        if kanal is None or kanal[1] != IZINLI:
            return "kanal_izinli_degil", []
        hedefler.append(kanal[0])
    return "tamam", hedefler


def yazan_adi(gercek_ad: str | None, gorunen_ad: str | None, slack_id: str) -> str:
    """Önce gerçek ad, yoksa görünen ad, o da yoksa Slack kimliği. Yalnızca boşluk boş sayılır."""
    for ad in (gercek_ad, gorunen_ad):
        if ad and ad.strip():
            return ad.strip()
    return slack_id


def slack_etiketlerini_coz(
    metin: str, kullanici_adlari: Mapping[str, str], kanal_adlari: Mapping[str, str]
) -> str:
    """<@U..> -> @ad, <#C..> -> #ad. Ad veritabanından gelir, etiketteki "|..." kısmından değil.

    Bilinmeyen kimlik ve diğer <...> biçimleri (<tel:..>, <https://..>, <!here>) olduğu gibi kalır.
    """
    def kullanici(e: re.Match) -> str:
        ad = kullanici_adlari.get(e.group(1))
        return f"@{ad}" if ad else e.group(0)

    def kanal(e: re.Match) -> str:
        ad = kanal_adlari.get(e.group(1))
        return f"#{ad}" if ad else e.group(0)

    return _KANAL_ETIKETI.sub(kanal, _KULLANICI_ETIKETI.sub(kullanici, metin))
