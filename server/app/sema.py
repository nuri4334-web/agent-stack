"""Sohbet anlaşması: ekran ile sunucu arasında giden ve gelen verinin biçimi.

Ayrıntılı açıklama: docs/sohbet-anlasmasi.md
"""
from typing import Literal

from pydantic import BaseModel, Field


class SoruIstegi(BaseModel):
    soru: str = Field(min_length=1, max_length=2000, description="Kullanıcının sorusu")
    # GEÇİCİ: Aşama 2'de kaldırılacak; kimlik oturumdan okunacak.
    # Bu alan kalırsa en büyük yetki açığı olur: Ali bu alanı değiştirip Nuri olabilir.
    kullanici: str = Field(min_length=1, max_length=100, description="GEÇİCİ kullanıcı adı")


class KaynakMesaj(BaseModel):
    kanal: str
    yazan: str
    zaman: str  # ISO 8601, ör. 2026-10-22T14:05:00+03:00
    metin: str


class GuvenlikOzeti(BaseModel):
    engellenen: int = 0
    maskelenen: int = 0
    supheli: int = 0


class SoruCevabi(BaseModel):
    istek_id: str
    durum: Literal["tamam", "erisim_yok"] = "tamam"
    cevap: str
    kaynaklar: list[KaynakMesaj] = []
    guvenlik: GuvenlikOzeti = GuvenlikOzeti()


class HataDetayi(BaseModel):
    kod: str
    mesaj: str


class HataCevabi(BaseModel):
    hata: HataDetayi
