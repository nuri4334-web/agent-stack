"""Veri seçimi sorgusu (S1-05): S1-04 tablolarından yalnızca izinli kanalların mesajlarını okur."""
import sqlite3
from dataclasses import dataclass, field

from ..sema import KaynakMesaj
from ..veritabani.kurallar import IZINLI
from .kurallar import MESAJ_SINIRI, HedefSonucu, hedef_kanallari_bul, slack_etiketlerini_coz, yazan_adi


@dataclass
class Secim:
    sonuc: HedefSonucu
    mesajlar: list[KaynakMesaj] = field(default_factory=list)  # eskiden yeniye


def mesajlari_sec(baglanti: sqlite3.Connection, soru: str, *, sinir: int = MESAJ_SINIRI) -> Secim:
    """Soruya göre en yeni `sinir` mesajı seçer. Bağlantıyı açmaz, kapatmaz; yalnızca okur."""
    kanallar = baglanti.execute("SELECT slack_id, ad, durum FROM kanallar ORDER BY slack_id").fetchall()
    sonuc, hedefler = hedef_kanallari_bul(soru, kanallar)
    return Secim(sonuc, _mesajlar(baglanti, hedefler, kanallar, sinir) if sonuc == "tamam" else [])


def _mesajlar(baglanti, hedefler: list[str], kanallar, sinir: int) -> list[KaynakMesaj]:
    if not hedefler:
        return []
    yerler = ", ".join("?" * len(hedefler))
    # durum koşulu hedef listesinden bağımsız olarak da uygulanır: hariç kanal hiçbir yoldan okunmaz.
    satirlar = baglanti.execute(
        "SELECT m.ts, m.zaman, m.temiz_metin, k.ad, u.slack_id, u.gercek_ad, u.gorunen_ad "
        "FROM mesajlar m "
        "JOIN kanallar k ON k.slack_id = m.kanal_id "
        "JOIN slack_kullanicilari u ON u.slack_id = m.yazan_id "
        f"WHERE k.durum = ? AND m.kanal_id IN ({yerler}) "
        "ORDER BY m.ts DESC, m.kanal_id DESC "
        "LIMIT ?",
        (IZINLI, *hedefler, sinir),
    ).fetchall()
    kullanici_adlari = {
        slack_id: yazan_adi(gercek_ad, gorunen_ad, slack_id)
        for slack_id, gercek_ad, gorunen_ad in baglanti.execute(
            "SELECT slack_id, gercek_ad, gorunen_ad FROM slack_kullanicilari"
        )
    }
    kanal_adlari = {slack_id: ad for slack_id, ad, _ in kanallar}
    return [
        KaynakMesaj(
            kanal=kanal_adi,
            yazan=yazan_adi(gercek_ad, gorunen_ad, yazan_id),
            zaman=zaman,
            metin=slack_etiketlerini_coz(temiz_metin, kullanici_adlari, kanal_adlari),
        )
        for _, zaman, temiz_metin, kanal_adi, yazan_id, gercek_ad, gorunen_ad in reversed(satirlar)
    ]
